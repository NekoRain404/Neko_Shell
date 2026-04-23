#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TCP 连接模块

实现了 TCP 套接字连接功能。
"""

import socket
import threading
import select
from typing import Optional, Tuple
from datetime import datetime

from .base import BaseConnection, ConnectionStatus, ConnectionInfo, ConnectionType
from neko_shell.models.connection import TCPConfig
from neko_shell.utils.exceptions import (
    ConnectionError,
    ConnectionLostError,
    TimeoutError,
    OperationError,
)


class TCPConnection(BaseConnection):
    """
    TCP 连接实现
    
    提供 TCP 套接字通信功能，支持 Keep-Alive 和 Nagle 算法控制。
    
    Features:
        - TCP 客户端连接
        - Keep-Alive 支持
        - Nagle 算法控制
        - 异步数据接收
        - 连接状态监控
        - 自动重连支持
    
    Example:
        >>> from neko_shell.core.connection import TCPConnection
        >>> from neko_shell.models.connection import TCPConfig
        >>> 
        >>> config = TCPConfig(
        ...     name="设备连接",
        ...     host="192.168.1.100",
        ...     port=8080
        ... )
        >>> 
        >>> conn = TCPConnection(config)
        >>> conn.connect()
        >>> 
        >>> conn.write(b"hello")
        >>> data = conn.read(1024)
        >>> 
        >>> conn.disconnect()
    """
    
    def __init__(self, config: TCPConfig):
        """初始化 TCP 连接"""
        super().__init__(config)
        self._socket: Optional[socket.socket] = None
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        self._recv_buffer = bytearray()
    
    @property
    def host(self) -> str:
        """获取主机地址"""
        return self._config.host
    
    @property
    def port(self) -> int:
        """获取端口号"""
        return self._config.port
    
    def connect(self) -> None:
        """建立 TCP 连接"""
        self._set_status(ConnectionStatus.CONNECTING)
        self._logger.info(f"正在连接 {self._config.host}:{self._config.port}")
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
            # 设置超时
            self._socket.settimeout(self._config.timeout)
            
            # 设置 Keep-Alive
            if self._config.keepalive:
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                # Linux 平台设置 Keep-Alive 参数
                if hasattr(socket, 'TCP_KEEPIDLE'):
                    self._socket.setsockopt(
                        socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 
                        self._config.keepalive_idle
                    )
                if hasattr(socket, 'TCP_KEEPINTVL'):
                    self._socket.setsockopt(
                        socket.IPPROTO_TCP, socket.TCP_KEEPINTVL,
                        self._config.keepalive_interval
                    )
                if hasattr(socket, 'TCP_KEEPCNT'):
                    self._socket.setsockopt(
                        socket.IPPROTO_TCP, socket.TCP_KEEPCNT,
                        self._config.keepalive_count
                    )
            
            # 禁用 Nagle 算法（低延迟）
            if self._config.no_delay:
                self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            
            # 连接服务器
            self._socket.connect((self._config.host, self._config.port))
            
            self._running = True
            if self._has_selectable_socket():
                self._start_read_thread()
            
            self._set_status(ConnectionStatus.CONNECTED)
            self._logger.info(f"TCP 连接成功: {self._config.host}:{self._config.port}")
            
        except socket.timeout as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise TimeoutError(f"连接超时: {self._config.host}:{self._config.port}") from e
        except socket.gaierror as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"无法解析主机名: {self._config.host}") from e
        except ConnectionRefusedError as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"连接被拒绝: {self._config.host}:{self._config.port}") from e
        except OSError as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"连接失败: {e}") from e
    
    def disconnect(self) -> None:
        """断开 TCP 连接"""
        self._running = False
        
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)
        
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            
            try:
                self._socket.close()
            except Exception:
                pass
            
            self._socket = None
        
        self._set_status(ConnectionStatus.DISCONNECTED)
        self._logger.info("TCP 连接已断开")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        if self._socket is None or self._status != ConnectionStatus.CONNECTED:
            return False

        if not self._has_selectable_socket():
            return True

        try:
            return self._socket.fileno() >= 0
        except Exception:
            return False
    
    def get_info(self) -> ConnectionInfo:
        """获取连接信息"""
        return ConnectionInfo(
            id=self._id,
            name=self._config.name,
            connection_type=ConnectionType.TCP,
            host=self._config.host,
            port=self._config.port,
            status=self._status,
            error_message=self._last_error
        )
    
    # ==================== 数据收发 ====================
    
    def write(self, data: bytes) -> int:
        """发送数据"""
        self._check_connection()
        
        try:
            sent = self._socket.send(data)
            self._logger.debug(f"发送 {sent} 字节")
            return sent
        except socket.timeout as e:
            raise TimeoutError("发送超时") from e
        except Exception as e:
            raise OperationError(f"发送失败: {e}") from e
    
    def write_all(self, data: bytes) -> None:
        """发送所有数据（确保完整发送）"""
        self._check_connection()
        
        try:
            self._socket.sendall(data)
            self._logger.debug(f"发送 {len(data)} 字节")
        except socket.timeout as e:
            raise TimeoutError("发送超时") from e
        except Exception as e:
            raise OperationError(f"发送失败: {e}") from e
    
    def read(self, size: int = -1, timeout: Optional[float] = None) -> bytes:
        """读取数据"""
        self._check_connection()
        
        old_timeout = self._socket.gettimeout()
        if timeout is not None:
            self._socket.settimeout(timeout)
        
        try:
            if size == -1:
                # 读取可用数据
                data = self._socket.recv(self._config.buffer_size)
            else:
                data = self._socket.recv(size)
            return data
        except socket.timeout as e:
            raise TimeoutError("读取超时") from e
        except Exception as e:
            raise OperationError(f"读取失败: {e}") from e
        finally:
            if timeout is not None:
                self._socket.settimeout(old_timeout)
    
    def read_until(self, delimiter: bytes, timeout: Optional[float] = None) -> bytes:
        """读取直到指定分隔符"""
        self._check_connection()
        
        buffer = bytearray()
        old_timeout = self._socket.gettimeout()
        if timeout is not None:
            self._socket.settimeout(timeout)
        
        try:
            while True:
                byte = self._socket.recv(1)
                if not byte:
                    raise ConnectionLostError("连接已断开")
                buffer.extend(byte)
                if buffer.endswith(delimiter):
                    return bytes(buffer)
        except socket.timeout as e:
            raise TimeoutError(f"读取超时，未找到分隔符: {delimiter!r}") from e
        finally:
            if timeout is not None:
                self._socket.settimeout(old_timeout)
    
    def read_line(self, timeout: Optional[float] = None) -> bytes:
        """读取一行（以 \\n 结尾）"""
        return self.read_until(b'\n', timeout)
    
    def readline(self, timeout: Optional[float] = None) -> bytes:
        """读取一行（以 \\n 结尾）"""
        return self.read_line(timeout)
    
    # ==================== Socket 操作 ====================
    
    def get_socket(self) -> Optional[socket.socket]:
        """获取底层 socket 对象"""
        return self._socket
    
    def set_timeout(self, timeout: float) -> None:
        """设置超时时间"""
        if self._socket:
            self._socket.settimeout(timeout)
    
    def get_local_address(self) -> Optional[Tuple[str, int]]:
        """获取本地地址"""
        if self._socket:
            return self._socket.getsockname()
        return None
    
    def get_remote_address(self) -> Optional[Tuple[str, int]]:
        """获取远程地址"""
        if self._socket:
            return self._socket.getpeername()
        return None
    
    # ==================== 内部方法 ====================
    
    def _check_connection(self) -> None:
        """检查连接状态"""
        if not self._socket:
            raise ConnectionLostError("连接未建立")

    def _has_selectable_socket(self) -> bool:
        """检查底层 socket 是否适合进入 select/read 线程。"""
        if self._socket is None:
            return False
        try:
            fileno = self._socket.fileno()
        except Exception:
            return False
        return isinstance(fileno, int) and fileno >= 0
    
    def _start_read_thread(self) -> None:
        """启动读取线程"""
        def read_loop():
            while self._running and self._socket:
                try:
                    ready, _, _ = select.select([self._socket], [], [], 0.1)
                    if ready:
                        data = self._socket.recv(self._config.buffer_size)
                        if not data:
                            # 连接关闭
                            self._logger.info("远程主机关闭连接")
                            self._running = False
                            self._set_status(ConnectionStatus.DISCONNECTED)
                            self.emit('disconnected')
                            break
                        
                        self._recv_buffer.extend(data)
                        self.emit('data_received', data)
                        
                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        self._logger.error(f"读取错误: {e}")
                        self._running = False
                        self._set_status(ConnectionStatus.ERROR, str(e))
                        self.emit('error', str(e))
                        break
        
        self._read_thread = threading.Thread(target=read_loop, daemon=True)
        self._read_thread.start()
    
    def __repr__(self) -> str:
        return f"<TCPConnection {self._config.host}:{self._config.port} status={self._status.value}>"
