#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FTP 连接模块

实现了 FTP 和 FTPS (FTP over SSL/TLS) 连接功能。
"""

import ftplib
import io
import os
import posixpath
import socket
import re
from typing import Optional, List, Callable, BinaryIO, Tuple
from datetime import datetime
import threading
import time

from .base import BaseConnection, ConnectionStatus, ConnectionInfo, ConnectionType
from neko_shell.models.connection import FTPConfig, FTPMode, FTPSType, FTPFileItem
from neko_shell.utils.exceptions import (
    ConnectionError,
    AuthenticationError,
    TimeoutError,
    ConnectionLostError,
    FileTransferError,
    PermissionDeniedError,
    ProtocolError,
    UnsupportedFeatureError,
    OperationError,
    OperationCancelledError,
)


class FTPConnection(BaseConnection):
    """
    FTP/FTPS 连接实现

    支持 FTP 和 FTPS (隐式/显式 SSL/TLS) 连接，提供文件传输和目录管理功能。

    Features:
        - 标准 FTP 连接
        - FTPS 隐式加密 (端口 990)
        - FTPS 显式加密 (AUTH TLS/SSL)
        - 主动/被动模式
        - 文件上传/下载（支持进度回调）
        - 目录管理
        - 文件操作（删除、重命名）

    Example:
        >>> from neko_shell.core.connection import FTPConnection
        >>> from neko_shell.models.connection import FTPConfig, FTPSType

        >>> # 创建配置
        >>> config = FTPConfig(
        ...     name="我的 FTP",
        ...     host="ftp.example.com",
        ...     username="user",
        ...     password="pass",
        ...     ftps_type=FTPSType.EXPLICIT
        ... )

        >>> # 创建连接
        >>> ftp = FTPConnection(config)
        >>> ftp.connect()

        >>> # 列出目录
        >>> files = ftp.list_dir()
        >>> for f in files:
        ...     print(f.name, f.size, f.is_dir)

        >>> # 上传文件
        >>> with open("local.txt", "rb") as f:
        ...     ftp.upload_file("remote.txt", f)

        >>> # 断开连接
        >>> ftp.disconnect()
    """

    def __init__(self, config: FTPConfig):
        """
        初始化 FTP 连接

        Args:
            config: FTP 配置对象
        """
        super().__init__(config)
        self._ftp: Optional[ftplib.FTP] = None
        self._current_dir: str = "/"
        self._transfer_cancelled: bool = False

    @property
    def current_dir(self) -> str:
        """获取当前目录"""
        return self._current_dir

    def connect(self) -> None:
        """
        建立 FTP 连接

        Raises:
            ConnectionError: 连接失败
            AuthenticationError: 认证失败
            TimeoutError: 连接超时
        """
        self._set_status(ConnectionStatus.CONNECTING)
        self._logger.info(f"正在连接 FTP 服务器: {self._config.host}:{self._config.port}")

        try:
            # 创建 FTP 客户端
            self._ftp = self._create_ftp_client()

            # 连接服务器
            self._ftp.connect(self._config.host, self._config.port, timeout=self._config.timeout)

            # FTPS 显式加密
            if self._config.ftps_type == FTPSType.EXPLICIT:
                self._ftp.auth()
                self._ftp.prot_p()  # 启用数据连接加密

            # 登录
            self._ftp.login(self._config.username, self._config.password or "")

            # FTPS 隐式加密 - 登录后启用数据连接加密
            if self._config.ftps_type == FTPSType.IMPLICIT:
                self._ftp.prot_p()

            # 设置传输模式
            self._ftp.set_pasv(self._config.mode == FTPMode.PASSIVE)

            # 获取当前目录
            self._current_dir = self._ftp.pwd()

            self._set_status(ConnectionStatus.CONNECTED)
            self._logger.info(f"FTP 连接成功: {self._config.host}")

        except ftplib.error_perm as e:
            self._ftp = None
            self._set_status(ConnectionStatus.ERROR, str(e))
            error_msg = str(e).lower()
            if "login" in error_msg or "password" in error_msg or "530" in error_msg:
                raise AuthenticationError(f"FTP 认证失败: {e}") from e
            raise ConnectionError(f"FTP 权限错误: {e}") from e

        except socket.timeout as e:
            self._ftp = None
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise TimeoutError(f"FTP 连接超时: {e}") from e

        except socket.gaierror as e:
            self._ftp = None
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"无法解析主机名: {self._config.host}") from e

        except ConnectionRefusedError as e:
            self._ftp = None
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"连接被拒绝，请检查端口是否正确: {self._config.port}") from e

        except Exception as e:
            self._ftp = None
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"FTP 连接失败: {e}") from e

    def disconnect(self) -> None:
        """
        断开 FTP 连接
        """
        if self._ftp is None:
            return

        try:
            # 尝试正常退出
            self._ftp.quit()
            self._logger.info("FTP 连接已正常关闭")
        except Exception:
            # 如果 quit 失败，强制关闭
            try:
                self._ftp.close()
            except Exception:
                pass
        finally:
            self._ftp = None
            self._set_status(ConnectionStatus.DISCONNECTED)

    def is_connected(self) -> bool:
        """
        检查连接状态

        Returns:
            bool: True 表示已连接
        """
        if self._ftp is None:
            return False

        try:
            # 发送 NOOP 命令检查连接
            self._ftp.voidcmd("NOOP")
            return True
        except Exception:
            self._set_status(ConnectionStatus.DISCONNECTED)
            return False

    def get_info(self) -> ConnectionInfo:
        """
        获取连接信息

        Returns:
            ConnectionInfo: 连接信息对象
        """
        return ConnectionInfo(
            id=self._id,
            name=self._config.name,
            connection_type=ConnectionType.FTP,
            host=self._config.host,
            port=self._config.port,
            status=self._status,
            error_message=self._last_error,
        )

    def _create_ftp_client(self) -> ftplib.FTP:
        """
        创建 FTP 客户端实例

        根据配置创建标准 FTP 或 FTPS 客户端。

        Returns:
            ftplib.FTP: FTP 客户端
        """
        if self._config.ftps_type == FTPSType.IMPLICIT:
            return ftplib.FTP_TLS()
        elif self._config.ftps_type == FTPSType.EXPLICIT:
            return ftplib.FTP_TLS()
        else:
            return ftplib.FTP()

    # ==================== 目录操作 ====================

    def pwd(self) -> str:
        """
        获取当前工作目录

        Returns:
            str: 当前目录路径
        """
        self._check_connection()
        return self._ftp.pwd()

    def cwd(self, path: str) -> None:
        """
        切换工作目录

        Args:
            path: 目标目录路径

        Raises:
            FileTransferError: 目录不存在或无权限
        """
        self._check_connection()
        try:
            self._ftp.cwd(path)
            self._current_dir = self._ftp.pwd()
            self._logger.debug(f"切换目录: {self._current_dir}")
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法切换到目录: {path}") from e

    def list_dir(self, path: str = "") -> List[FTPFileItem]:
        """
        列出目录内容

        Args:
            path: 目录路径，空字符串表示当前目录

        Returns:
            List[FTPFileItem]: 文件项列表

        Raises:
            FileTransferError: 目录不存在或无权限
        """
        self._check_connection()

        items = []
        target_path = path or self._current_dir

        try:
            # 尝试使用 MLSD 命令（更详细的列表）
            try:
                for name, facts in self._ftp.mlsd(target_path):
                    item = self._parse_mlsd(name, facts)
                    items.append(item)
                return items
            except ftplib.error_perm:
                # MLSD 不支持，使用 LIST
                pass

            # 使用 LIST 命令
            lines = []
            self._ftp.retrlines(f"LIST {target_path}", lines.append)

            for line in lines:
                if line.strip():
                    item = self._parse_list_line(line)
                    if item:
                        items.append(item)

            return items

        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法列出目录: {target_path}") from e
        except Exception as e:
            raise FileTransferError(f"列出目录失败: {e}") from e

    def list_names(self, path: str = "") -> List[str]:
        """
        列出目录下的文件名

        Args:
            path: 目录路径

        Returns:
            List[str]: 文件名列表
        """
        self._check_connection()
        try:
            return self._ftp.nlst(path or "")
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法列出目录: {path}") from e

    def get_file_info(self, path: str) -> FTPFileItem:
        """
        获取单个文件或目录的属性信息。

        Args:
            path: 目标路径

        Returns:
            FTPFileItem: 文件属性
        """
        self._check_connection()

        normalized_path = path.rstrip("/") or path
        parent_dir = posixpath.dirname(normalized_path) or self._current_dir
        target_name = posixpath.basename(normalized_path) or normalized_path

        if normalized_path in {".", "/"}:
            target_name = self._current_dir.rstrip("/") or "/"
            parent_dir = self._current_dir

        try:
            for item in self.list_dir(parent_dir):
                if item.name == target_name:
                    return item
        except Exception as exc:
            raise FileTransferError(f"读取属性失败: {exc}") from exc

        raise FileTransferError(f"未找到目标路径: {path}")

    def mkdir(self, path: str) -> None:
        """
        创建目录

        Args:
            path: 目录路径

        Raises:
            FileTransferError: 创建失败
        """
        self._check_connection()
        try:
            self._ftp.mkd(path)
            self._logger.info(f"创建目录: {path}")
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法创建目录: {path}") from e

    def rmdir(self, path: str) -> None:
        """
        删除空目录

        Args:
            path: 目录路径

        Raises:
            FileTransferError: 删除失败（目录非空或无权限）
        """
        self._check_connection()
        try:
            self._ftp.rmd(path)
            self._logger.info(f"删除目录: {path}")
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法删除目录: {path}") from e

    # ==================== 文件操作 ====================

    def download_file(
        self,
        remote_path: str,
        local_file: BinaryIO,
        progress_callback: Optional[Callable[[int, int], bool]] = None,
        block_size: int = 8192,
    ) -> None:
        """
        下载文件

        Args:
            remote_path: 远程文件路径
            local_file: 本地文件对象（二进制写入模式）
            progress_callback: 进度回调函数 (已传输字节, 总字节) -> 是否继续
            block_size: 传输块大小

        Raises:
            FileTransferError: 下载失败
            OperationCancelledError: 用户取消
        """
        self._check_connection()
        self._transfer_cancelled = False

        try:
            # 获取文件大小
            file_size = self.size(remote_path)
            transferred = [0]  # 使用列表以便在闭包中修改

            def callback(data: bytes) -> None:
                """传输回调"""
                if self._transfer_cancelled:
                    raise OperationCancelledError("下载已取消")

                local_file.write(data)
                transferred[0] += len(data)

                if progress_callback:
                    if not progress_callback(transferred[0], file_size):
                        self._transfer_cancelled = True
                        raise OperationCancelledError("下载已取消")

            self._ftp.retrbinary(f"RETR {remote_path}", callback, block_size)
            self._logger.info(f"下载文件: {remote_path} ({transferred[0]} 字节)")

        except OperationCancelledError:
            raise
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法下载文件: {remote_path}") from e
        except Exception as e:
            raise FileTransferError(f"下载文件失败: {remote_path} - {e}") from e

    def upload_file(
        self,
        remote_path: str,
        local_file: BinaryIO,
        progress_callback: Optional[Callable[[int, int], bool]] = None,
        block_size: int = 8192,
    ) -> None:
        """
        上传文件

        Args:
            remote_path: 远程文件路径
            local_file: 本地文件对象（二进制读取模式）
            progress_callback: 进度回调函数 (已传输字节, 总字节) -> 是否继续
            block_size: 传输块大小

        Raises:
            FileTransferError: 上传失败
            OperationCancelledError: 用户取消
        """
        self._check_connection()
        self._transfer_cancelled = False

        try:
            # 获取本地文件大小
            local_file.seek(0, 2)  # 移动到文件末尾
            file_size = local_file.tell()
            local_file.seek(0)  # 移动到文件开头

            transferred = [0]

            if progress_callback:
                if not progress_callback(0, file_size):
                    self._transfer_cancelled = True
                    raise OperationCancelledError("上传已取消")

            # 使用回调函数跟踪进度
            def callback(data: bytes) -> None:
                """传输回调 - 在每个块发送后调用"""
                if self._transfer_cancelled:
                    raise OperationCancelledError("上传已取消")

                transferred[0] += len(data)

                if progress_callback:
                    if not progress_callback(transferred[0], file_size):
                        self._transfer_cancelled = True
                        raise OperationCancelledError("上传已取消")

            # storbinary 会读取文件并发送，callback 用于进度跟踪
            self._ftp.storbinary(
                f"STOR {remote_path}", local_file, blocksize=block_size, callback=callback
            )

            self._logger.info(f"上传文件: {remote_path} ({transferred[0]} 字节)")

        except OperationCancelledError:
            raise
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法上传文件: {remote_path}") from e
        except Exception as e:
            raise FileTransferError(f"上传文件失败: {remote_path} - {e}") from e

    def delete_file(self, path: str) -> None:
        """
        删除文件

        Args:
            path: 文件路径

        Raises:
            FileTransferError: 删除失败
        """
        self._check_connection()
        try:
            self._ftp.delete(path)
            self._logger.info(f"删除文件: {path}")
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法删除文件: {path}") from e

    def rename(self, old_name: str, new_name: str) -> None:
        """
        重命名文件或目录

        Args:
            old_name: 原名称
            new_name: 新名称

        Raises:
            FileTransferError: 重命名失败
        """
        self._check_connection()
        try:
            self._ftp.rename(old_name, new_name)
            self._logger.info(f"重命名: {old_name} -> {new_name}")
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法重命名: {old_name}") from e

    def size(self, path: str) -> int:
        """
        获取文件大小

        Args:
            path: 文件路径

        Returns:
            int: 文件大小（字节），-1 表示无法获取

        Raises:
            FileTransferError: 文件不存在
        """
        self._check_connection()
        try:
            size = self._ftp.size(path)
            return size if size is not None else -1
        except ftplib.error_perm:
            return -1

    def modify_time(self, path: str) -> Optional[datetime]:
        """
        获取文件修改时间

        Args:
            path: 文件路径

        Returns:
            Optional[datetime]: 修改时间，None 表示无法获取
        """
        self._check_connection()
        try:
            mtime = self._ftp.sendcmd(f"MDTM {path}")
            if mtime.startswith("213 "):
                # 格式: YYYYMMDDHHMMSS
                mtime = mtime[4:].strip()
                return datetime.strptime(mtime, "%Y%m%d%H%M%S")
        except Exception:
            pass
        return None

    def cancel_transfer(self) -> None:
        """取消当前的文件传输"""
        self._transfer_cancelled = True

    # ==================== 高级功能 ====================

    def download_to_path(
        self,
        remote_path: str,
        local_path: str,
        progress_callback: Optional[Callable[[int, int], bool]] = None,
        resume: bool = True,
    ) -> None:
        """
        下载文件到本地路径

        Args:
            remote_path: 远程文件路径
            local_path: 本地文件路径
            progress_callback: 进度回调
        """
        self._check_connection()
        self._transfer_cancelled = False

        remote_size = self.size(remote_path)
        offset = 0
        mode = "wb"
        if resume and os.path.exists(local_path) and remote_size > 0:
            try:
                local_size = os.path.getsize(local_path)
            except OSError:
                local_size = 0

            if local_size >= remote_size:
                if progress_callback:
                    progress_callback(remote_size, remote_size)
                return

            if 0 < local_size < remote_size:
                offset = local_size
                mode = "ab"

        if offset == 0:
            with open(local_path, mode) as f:
                self.download_file(remote_path, f, progress_callback)
            return

        transferred = [offset]

        def callback(data: bytes) -> None:
            if self._transfer_cancelled:
                raise OperationCancelledError("下载已取消")
            file_handle.write(data)
            transferred[0] += len(data)
            if progress_callback and not progress_callback(transferred[0], remote_size):
                self._transfer_cancelled = True
                raise OperationCancelledError("下载已取消")

        try:
            with open(local_path, mode) as file_handle:
                self._ftp.retrbinary(f"RETR {remote_path}", callback, 8192, rest=offset)
        except OperationCancelledError:
            raise
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法下载文件: {remote_path}") from e
        except Exception as e:
            raise FileTransferError(f"下载文件失败: {remote_path} - {e}") from e

    def upload_from_path(
        self,
        local_path: str,
        remote_path: str,
        progress_callback: Optional[Callable[[int, int], bool]] = None,
        resume: bool = True,
    ) -> None:
        """
        从本地路径上传文件

        Args:
            local_path: 本地文件路径
            remote_path: 远程文件路径
            progress_callback: 进度回调
        """
        self._check_connection()
        self._transfer_cancelled = False

        try:
            total_size = os.path.getsize(local_path)
        except OSError as exc:
            raise FileTransferError(f"读取本地文件失败: {exc}") from exc

        offset = 0
        if resume:
            remote_size = self.size(remote_path)
            if remote_size > 0 and total_size > 0 and remote_size >= total_size:
                if progress_callback:
                    progress_callback(total_size, total_size)
                return
            if 0 < remote_size < total_size:
                offset = remote_size

        transferred = [offset]

        def callback(data: bytes) -> None:
            if self._transfer_cancelled:
                raise OperationCancelledError("上传已取消")
            transferred[0] += len(data)
            if progress_callback and not progress_callback(transferred[0], total_size):
                self._transfer_cancelled = True
                raise OperationCancelledError("上传已取消")

        try:
            with open(local_path, "rb") as file_handle:
                if offset:
                    file_handle.seek(offset)
                if progress_callback and not progress_callback(offset, total_size):
                    self._transfer_cancelled = True
                    raise OperationCancelledError("上传已取消")
                self._ftp.storbinary(
                    f"STOR {remote_path}",
                    file_handle,
                    blocksize=8192,
                    callback=callback,
                    rest=offset or None,
                )
        except OperationCancelledError:
            raise
        except ftplib.error_perm as e:
            raise PermissionDeniedError(f"无法上传文件: {remote_path}") from e
        except Exception as e:
            raise FileTransferError(f"上传文件失败: {remote_path} - {e}") from e

    def read_text(self, remote_path: str, encoding: str = "utf-8") -> str:
        """读取远程文本文件。"""
        buffer = io.BytesIO()
        self.download_file(remote_path, buffer)
        return buffer.getvalue().decode(encoding, errors="replace")

    def write_text(self, remote_path: str, content: str, encoding: str = "utf-8") -> None:
        """写入远程文本文件。"""
        payload = io.BytesIO(content.encode(encoding))
        self.upload_file(remote_path, payload)

    def create_file(self, remote_path: str) -> None:
        """创建空文件。"""
        self.write_text(remote_path, "")

    def exists(self, path: str) -> bool:
        """
        检查文件或目录是否存在

        Args:
            path: 路径

        Returns:
            bool: True 表示存在
        """
        self._check_connection()
        try:
            # 尝试获取文件大小（适用于文件）
            self._ftp.size(path)
            return True
        except Exception:
            pass

        try:
            # 尝试切换到该路径（适用于目录）
            current = self._ftp.pwd()
            self._ftp.cwd(path)
            self._ftp.cwd(current)
            return True
        except Exception:
            pass

        return False

    def is_dir(self, path: str) -> bool:
        """
        检查是否为目录

        Args:
            path: 路径

        Returns:
            bool: True 表示是目录
        """
        self._check_connection()
        try:
            current = self._ftp.pwd()
            self._ftp.cwd(path)
            self._ftp.cwd(current)
            return True
        except Exception:
            return False

    def get_welcome_message(self) -> Optional[str]:
        """
        获取服务器欢迎消息

        Returns:
            Optional[str]: 欢迎消息
        """
        if self._ftp:
            return self._ftp.getwelcome()
        return None

    # ==================== 辅助方法 ====================

    def _check_connection(self) -> None:
        """检查连接状态"""
        if not self.is_connected():
            raise ConnectionLostError("FTP 连接已断开")

    def _parse_mlsd(self, name: str, facts: dict) -> FTPFileItem:
        """
        解析 MLSD 输出

        Args:
            name: 文件名
            facts: 文件属性

        Returns:
            FTPFileItem: 文件项
        """
        return FTPFileItem(
            name=name,
            is_dir=facts.get("type", "") == "dir",
            size=int(facts.get("size", 0)),
            modify_time=facts.get("modify"),
            permissions=facts.get("unix.mode"),
            owner=facts.get("unix.owner"),
            group=facts.get("unix.group"),
        )

    def _parse_list_line(self, line: str) -> Optional[FTPFileItem]:
        """
        解析 LIST 命令输出行

        Args:
            line: LIST 输出行

        Returns:
            Optional[FTPFileItem]: 文件项，解析失败返回 None
        """
        # Unix 风格: drwxr-xr-x  2 user group 4096 Jan  1 12:00 dirname
        # 或: -rw-r--r--  1 user group 1234 Jan  1 12:00 filename

        parts = line.split(None, 8)
        if len(parts) < 9:
            return None

        perms = parts[0]
        is_dir = perms.startswith("d")
        size = int(parts[4]) if parts[4].isdigit() else 0
        name = parts[8]

        # 跳过 . 和 ..
        if name in (".", ".."):
            return None

        return FTPFileItem(
            name=name,
            is_dir=is_dir,
            size=size,
            permissions=perms,
            owner=parts[2],
            group=parts[3],
            modify_time=f"{parts[5]} {parts[6]} {parts[7]}",
        )

    def __repr__(self) -> str:
        return (
            f"<FTPConnection {self._config.host}:{self._config.port} status={self._status.value}>"
        )
