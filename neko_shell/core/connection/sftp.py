#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFTP 连接模块

实现了基于 Paramiko 的 SFTP 文件操作。
"""

from __future__ import annotations

import os
import posixpath
import shlex
import stat
from datetime import datetime
from typing import BinaryIO, Callable, Optional, Union

from .base import ConnectionInfo, ConnectionStatus, ConnectionType
from .ssh import SSHConnection
from neko_shell.models.connection import FTPFileItem, SFTPConfig
from neko_shell.utils.exceptions import (
    FileTransferError,
    OperationError,
    PermissionDeniedError,
)


class SFTPConnection(SSHConnection):
    """SFTP 连接实现。"""

    def __init__(self, config: SFTPConfig):
        super().__init__(config)
        self._sftp = None
        self._current_dir = "."
        self._transfer_cancelled = False

    @property
    def current_dir(self) -> str:
        """获取当前目录。"""
        return self._current_dir

    def connect(self) -> None:
        """建立 SFTP 连接。"""
        super().connect()
        self._sftp = self._client.open_sftp()
        self._current_dir = self._normalize_path(self._config.initial_path or ".")
        self._set_status(ConnectionStatus.CONNECTED)

    def disconnect(self) -> None:
        """断开 SFTP 连接。"""
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        super().disconnect()

    def get_info(self) -> ConnectionInfo:
        """获取连接信息。"""
        return ConnectionInfo(
            id=self._id,
            name=self._config.name,
            connection_type=ConnectionType.SFTP,
            host=self._config.host,
            port=self._config.port,
            status=self._status,
            error_message=self._last_error,
        )

    def _check_sftp(self) -> None:
        """检查 SFTP 会话状态。"""
        self._check_connection()
        if self._sftp is None:
            raise FileTransferError("SFTP 会话未建立")

    def _normalize_path(self, path: str) -> str:
        """标准化远程路径。"""
        self._check_sftp()
        return self._sftp.normalize(path)

    def cwd(self, path: str) -> None:
        """切换远程目录。"""
        self._check_sftp()
        self._sftp.chdir(path)
        self._current_dir = self._normalize_path(path)

    def pwd(self) -> str:
        """获取当前目录。"""
        self._check_sftp()
        return self._current_dir

    def list_dir(self, path: str = "") -> list[FTPFileItem]:
        """列出目录内容。"""
        self._check_sftp()
        target_path = path or self._current_dir
        items = []
        try:
            for attr in self._sftp.listdir_attr(target_path):
                items.append(
                    FTPFileItem(
                        name=attr.filename,
                        is_dir=stat.S_ISDIR(attr.st_mode),
                        size=attr.st_size,
                        modify_time=datetime.fromtimestamp(attr.st_mtime).isoformat(),
                        permissions=stat.filemode(attr.st_mode),
                        owner=str(attr.st_uid) if attr.st_uid is not None else None,
                        group=str(attr.st_gid) if attr.st_gid is not None else None,
                    )
                )
            return items
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法列出目录: {target_path}") from exc
        except OSError as exc:
            raise FileTransferError(f"列出目录失败: {exc}") from exc

    def mkdir(self, path: str) -> None:
        """创建目录。"""
        self._check_sftp()
        try:
            self._sftp.mkdir(path)
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法创建目录: {path}") from exc
        except OSError as exc:
            raise FileTransferError(f"创建目录失败: {exc}") from exc

    def rmdir(self, path: str) -> None:
        """删除空目录。"""
        self._check_sftp()
        try:
            self._sftp.rmdir(path)
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法删除目录: {path}") from exc
        except OSError as exc:
            raise FileTransferError(f"删除目录失败: {exc}") from exc

    def rename(self, old_name: str, new_name: str) -> None:
        """重命名文件或目录。"""
        self._check_sftp()
        try:
            self._sftp.rename(old_name, new_name)
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法重命名: {old_name}") from exc
        except OSError as exc:
            raise FileTransferError(f"重命名失败: {exc}") from exc

    def delete_file(self, path: str) -> None:
        """删除文件。"""
        self._check_sftp()
        try:
            self._sftp.remove(path)
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法删除文件: {path}") from exc
        except OSError as exc:
            raise FileTransferError(f"删除文件失败: {exc}") from exc

    @staticmethod
    def _parse_mode(mode: Union[int, str]) -> int:
        """解析 chmod 权限值。"""
        if isinstance(mode, int):
            if mode < 0:
                raise ValueError("权限值不能为负数")
            return mode

        normalized = str(mode).strip()
        if normalized.startswith("0o"):
            normalized = normalized[2:]
        if not normalized or not all(char in "01234567" for char in normalized):
            raise ValueError("权限格式无效，请使用八进制格式，例如 755")
        return int(normalized, 8)

    def chmod(self, path: str, mode: Union[int, str]) -> None:
        """修改远程文件或目录权限。"""
        self._check_sftp()
        try:
            self._sftp.chmod(path, self._parse_mode(mode))
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法修改权限: {path}") from exc
        except OSError as exc:
            raise FileTransferError(f"修改权限失败: {exc}") from exc

    def get_file_info(self, path: str) -> FTPFileItem:
        """获取单个远程文件或目录的详细属性。"""
        self._check_sftp()
        try:
            attr = self._sftp.stat(path)
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法读取属性: {path}") from exc
        except OSError as exc:
            raise FileTransferError(f"读取属性失败: {exc}") from exc

        normalized_path = path.rstrip("/") or path
        name = posixpath.basename(normalized_path) or normalized_path or path
        return FTPFileItem(
            name=name,
            is_dir=stat.S_ISDIR(attr.st_mode),
            size=attr.st_size,
            modify_time=datetime.fromtimestamp(attr.st_mtime).isoformat(),
            permissions=stat.filemode(attr.st_mode),
            owner=str(attr.st_uid) if attr.st_uid is not None else None,
            group=str(attr.st_gid) if attr.st_gid is not None else None,
        )

    def chown(
        self,
        path: str,
        owner: Optional[Union[int, str]] = None,
        group: Optional[Union[int, str]] = None,
    ) -> None:
        """修改远程文件或目录属主/属组。"""
        self._check_sftp()
        try:
            current = self._sftp.stat(path)
            uid = current.st_uid if owner in (None, "") else int(owner)
            gid = current.st_gid if group in (None, "") else int(group)
            self._sftp.chown(path, uid, gid)
        except ValueError as exc:
            raise OperationError("属主和属组必须是数字 ID") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法修改属主属组: {path}") from exc
        except OSError as exc:
            raise FileTransferError(f"修改属主属组失败: {exc}") from exc

    @staticmethod
    def _quote_path(path: str) -> str:
        """Shell 安全引用远程路径。"""
        return shlex.quote(path)

    @staticmethod
    def _archive_command(archive_name: str, item_names: list[str]) -> str:
        """按归档文件后缀生成压缩命令。"""
        quoted_archive = SFTPConnection._quote_path(archive_name)
        quoted_items = " ".join(SFTPConnection._quote_path(name) for name in item_names)
        lower_name = archive_name.lower()

        if lower_name.endswith(".zip"):
            return (
                "command -v zip >/dev/null 2>&1 "
                f"&& zip -r {quoted_archive} {quoted_items} "
                "|| { echo 'zip command not found' >&2; exit 127; }"
            )
        return f"tar -czf {quoted_archive} -- {quoted_items}"

    @staticmethod
    def _extract_command(archive_name: str) -> str:
        """按归档文件后缀生成解压命令。"""
        quoted_archive = SFTPConnection._quote_path(archive_name)
        lower_name = archive_name.lower()

        if lower_name.endswith(".zip"):
            return (
                "command -v unzip >/dev/null 2>&1 "
                f"&& unzip -o {quoted_archive} "
                "|| { echo 'unzip command not found' >&2; exit 127; }"
            )
        if lower_name.endswith((".tar.gz", ".tgz")):
            return f"tar -xzf {quoted_archive}"
        if lower_name.endswith((".tar.bz2", ".tbz2")):
            return f"tar -xjf {quoted_archive}"
        if lower_name.endswith((".tar.xz", ".txz")):
            return f"tar -xJf {quoted_archive}"
        if lower_name.endswith(".tar"):
            return f"tar -xf {quoted_archive}"
        if lower_name.endswith(".gz"):
            return f"gzip -dkf {quoted_archive}"
        raise ValueError(f"不支持的压缩包格式: {archive_name}")

    def _run_file_command(
        self, working_dir: str, command: str, timeout: Optional[float] = None
    ) -> None:
        """在指定目录执行远程文件命令并检查结果。"""
        shell_command = f"cd {self._quote_path(working_dir)} && {command}"
        exit_code, stdout, stderr = self.exec_command(shell_command, timeout=timeout)
        if exit_code != 0:
            detail = (stderr or stdout or "").strip()
            raise OperationError(f"远程文件命令执行失败({exit_code}): {detail}")

    @classmethod
    def _copy_command(cls, source_paths: list[str], target_dir: str) -> str:
        """生成批量复制命令。"""
        quoted_sources = " ".join(cls._quote_path(path) for path in source_paths)
        quoted_target = cls._quote_path(target_dir)
        return f"cp -a -- {quoted_sources} {quoted_target}"

    @classmethod
    def _move_command(cls, source_paths: list[str], target_dir: str) -> str:
        """生成批量移动命令。"""
        quoted_sources = " ".join(cls._quote_path(path) for path in source_paths)
        quoted_target = cls._quote_path(target_dir)
        return f"mv -- {quoted_sources} {quoted_target}"

    def create_archive(
        self,
        source_paths: list[str],
        archive_path: str,
        timeout: Optional[float] = None,
    ) -> None:
        """将多个远程文件或目录压缩为归档文件。"""
        self._check_sftp()
        if not source_paths:
            raise ValueError("至少需要选择一个文件或目录")

        archive_dir = posixpath.dirname(archive_path) or self._current_dir
        archive_name = posixpath.basename(archive_path)
        item_paths = []
        for path in source_paths:
            normalized_path = path.rstrip("/")
            source_dir = posixpath.dirname(normalized_path) or self._current_dir
            if source_dir == archive_dir:
                item_paths.append(posixpath.basename(normalized_path))
            else:
                item_paths.append(normalized_path)

        if not archive_name or any(not item for item in item_paths):
            raise ValueError("压缩路径无效")

        self._run_file_command(
            archive_dir,
            self._archive_command(archive_name, item_paths),
            timeout=timeout,
        )

    def extract_archive(
        self,
        archive_path: str,
        target_dir: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """解压远程归档文件到目标目录。"""
        self._check_sftp()
        working_dir = target_dir or posixpath.dirname(archive_path) or self._current_dir
        archive_name = posixpath.basename(archive_path)
        if not archive_name:
            raise ValueError("压缩包路径无效")

        self._run_file_command(
            working_dir,
            self._extract_command(archive_name),
            timeout=timeout,
        )

    def copy_paths(
        self,
        source_paths: list[str],
        target_dir: str,
        timeout: Optional[float] = None,
    ) -> None:
        """批量复制远程文件或目录到目标目录。"""
        self._check_sftp()
        if not source_paths:
            raise ValueError("至少需要选择一个文件或目录")
        if not target_dir:
            raise ValueError("目标目录不能为空")

        self._run_file_command(
            self._current_dir,
            self._copy_command(source_paths, target_dir),
            timeout=timeout,
        )

    def move_paths(
        self,
        source_paths: list[str],
        target_dir: str,
        timeout: Optional[float] = None,
    ) -> None:
        """批量移动远程文件或目录到目标目录。"""
        self._check_sftp()
        if not source_paths:
            raise ValueError("至少需要选择一个文件或目录")
        if not target_dir:
            raise ValueError("目标目录不能为空")

        self._run_file_command(
            self._current_dir,
            self._move_command(source_paths, target_dir),
            timeout=timeout,
        )

    def exists(self, path: str) -> bool:
        """检查路径是否存在。"""
        self._check_sftp()
        try:
            self._sftp.stat(path)
            return True
        except OSError:
            return False

    def is_dir(self, path: str) -> bool:
        """检查是否为目录。"""
        self._check_sftp()
        try:
            return stat.S_ISDIR(self._sftp.stat(path).st_mode)
        except OSError:
            return False

    def size(self, path: str) -> int:
        """获取文件大小。"""
        self._check_sftp()
        try:
            return self._sftp.stat(path).st_size
        except OSError as exc:
            raise FileTransferError(f"获取文件大小失败: {exc}") from exc

    def modify_time(self, path: str) -> Optional[datetime]:
        """获取文件修改时间。"""
        self._check_sftp()
        try:
            return datetime.fromtimestamp(self._sftp.stat(path).st_mtime)
        except OSError:
            return None

    def download_file(
        self,
        remote_path: str,
        local_file: BinaryIO,
        progress_callback: Optional[Callable[[int, int], bool]] = None,
        block_size: int = 32768,
    ) -> None:
        """下载文件到本地文件对象。"""
        self._check_sftp()
        self._transfer_cancelled = False
        file_size = self.size(remote_path)
        transferred = 0

        try:
            with self._sftp.open(remote_path, "rb") as remote_file:
                while True:
                    data = remote_file.read(block_size)
                    if not data:
                        break
                    local_file.write(data)
                    transferred += len(data)
                    if progress_callback and not progress_callback(transferred, file_size):
                        self._transfer_cancelled = True
                        raise FileTransferError("下载已取消")
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法下载文件: {remote_path}") from exc
        except OSError as exc:
            raise FileTransferError(f"下载文件失败: {exc}") from exc

    def upload_file(
        self,
        remote_path: str,
        local_file: BinaryIO,
        progress_callback: Optional[Callable[[int, int], bool]] = None,
        block_size: int = 32768,
    ) -> None:
        """上传本地文件对象到远程文件。"""
        self._check_sftp()
        self._transfer_cancelled = False
        local_file.seek(0, 2)
        total_size = local_file.tell()
        local_file.seek(0)
        transferred = 0

        try:
            with self._sftp.open(remote_path, "wb") as remote_file:
                while True:
                    data = local_file.read(block_size)
                    if not data:
                        break
                    remote_file.write(data)
                    transferred += len(data)
                    if progress_callback and not progress_callback(transferred, total_size):
                        self._transfer_cancelled = True
                        raise FileTransferError("上传已取消")
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法上传文件: {remote_path}") from exc
        except OSError as exc:
            raise FileTransferError(f"上传文件失败: {exc}") from exc

    def download_to_path(
        self,
        remote_path: str,
        local_path: str,
        progress_callback: Optional[Callable[[int, int], bool]] = None,
        resume: bool = True,
    ) -> None:
        """下载文件到本地路径。"""
        self._check_sftp()
        remote_size = self.size(remote_path)
        offset = 0
        mode = "wb"

        if resume and os.path.exists(local_path):
            try:
                local_size = os.path.getsize(local_path)
            except OSError:
                local_size = 0

            if remote_size > 0 and local_size >= remote_size:
                if progress_callback:
                    progress_callback(remote_size, remote_size)
                return

            if 0 < local_size < remote_size:
                offset = local_size
                mode = "ab"

        if offset == 0:
            with open(local_path, mode) as local_file:
                self.download_file(remote_path, local_file, progress_callback)
            return

        self._transfer_cancelled = False
        transferred = offset
        with open(local_path, mode) as local_file:
            try:
                with self._sftp.open(remote_path, "rb") as remote_file:
                    if hasattr(remote_file, "seek"):
                        remote_file.seek(offset)
                    while True:
                        data = remote_file.read(32768)
                        if not data:
                            break
                        local_file.write(data)
                        transferred += len(data)
                        if progress_callback and not progress_callback(transferred, remote_size):
                            self._transfer_cancelled = True
                            raise FileTransferError("下载已取消")
            except PermissionError as exc:
                raise PermissionDeniedError(f"无法下载文件: {remote_path}") from exc
            except OSError as exc:
                raise FileTransferError(f"下载文件失败: {exc}") from exc

    def upload_from_path(
        self,
        local_path: str,
        remote_path: str,
        progress_callback: Optional[Callable[[int, int], bool]] = None,
        resume: bool = True,
    ) -> None:
        """从本地路径上传文件。"""
        self._check_sftp()
        self._transfer_cancelled = False

        try:
            total_size = os.path.getsize(local_path)
        except OSError as exc:
            raise FileTransferError(f"读取本地文件失败: {exc}") from exc

        offset = 0
        remote_mode = "wb"
        if resume:
            try:
                remote_size = self._sftp.stat(remote_path).st_size
            except OSError:
                remote_size = 0

            if total_size > 0 and remote_size >= total_size:
                if progress_callback:
                    progress_callback(total_size, total_size)
                return

            if 0 < remote_size < total_size:
                offset = remote_size
                remote_mode = "ab"

        if offset == 0:
            with open(local_path, "rb") as local_file:
                self.upload_file(remote_path, local_file, progress_callback)
            return

        transferred = offset
        with open(local_path, "rb") as local_file:
            local_file.seek(offset)
            try:
                with self._sftp.open(remote_path, remote_mode) as remote_file:
                    while True:
                        data = local_file.read(32768)
                        if not data:
                            break
                        remote_file.write(data)
                        transferred += len(data)
                        if progress_callback and not progress_callback(transferred, total_size):
                            self._transfer_cancelled = True
                            raise FileTransferError("上传已取消")
            except PermissionError as exc:
                raise PermissionDeniedError(f"无法上传文件: {remote_path}") from exc
            except OSError as exc:
                raise FileTransferError(f"上传文件失败: {exc}") from exc

    def read_text(self, remote_path: str, encoding: str = "utf-8") -> str:
        """读取远程文本文件。"""
        self._check_sftp()
        try:
            with self._sftp.open(remote_path, "rb") as remote_file:
                return remote_file.read().decode(encoding, errors="replace")
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法读取文件: {remote_path}") from exc
        except OSError as exc:
            raise FileTransferError(f"读取文件失败: {exc}") from exc

    def write_text(self, remote_path: str, content: str, encoding: str = "utf-8") -> None:
        """写入远程文本文件。"""
        self._check_sftp()
        try:
            with self._sftp.open(remote_path, "wb") as remote_file:
                remote_file.write(content.encode(encoding))
        except PermissionError as exc:
            raise PermissionDeniedError(f"无法写入文件: {remote_path}") from exc
        except OSError as exc:
            raise FileTransferError(f"写入文件失败: {exc}") from exc

    def create_file(self, remote_path: str) -> None:
        """创建空文件。"""
        self.write_text(remote_path, "")

    def join_path(self, *parts: str) -> str:
        """拼接远程路径。"""
        return posixpath.join(*parts)
