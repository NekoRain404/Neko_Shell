#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UDP 连接模块

实现了 UDP 数据报通信功能。
"""

import socket
import struct
import threading
import select
from typing import Optional, Tuple
from datetime import datetime

from .base import BaseConnection, ConnectionStatus, ConnectionInfo, ConnectionType
from neko_shell.models.connection import UDPConfig, UDPMode
from neko_shell.utils.exceptions import (
    ConnectionError,
    TimeoutError,
    OperationError,
)


class UDPConnection(BaseConnection):
    """
    UDP 连接实现
    
    提供 UDP 数据报通信功能，支持客户端、服务器和广播模式。
    
    Features:
        - UDP 客户端模式（发送数据到服务器）
        - UDP 服务器模式（绑定端口接收数据）
        - 广播支持
        - 组播支持
        - 异步数据接收
    
    Example:
        >>> from neko_shell.core.connection import UDPConnection
        >>> from neko_shell.models.connection import UDPConfig, UDPMode
        >>> 
        >>> # UDP 客户端
        >>> config = UDPConfig(
        ...     name="UDP客户端",
        ...     mode=UDPMode.CLIENT,
        ...     remote_host="192.168.1.100",
        ...     remote_port=5000
        ... )
        >>> conn = UDPConnection(config)
        >>> conn.connect()
        >>> conn.sendto(b"hello")
        >>> data, addr = conn.recvfrom()
        
        >>> # UDP 服务器
        >>> config = UDPConfig(
        ...     name="UDP服务器",
        ...     mode=UDPMode.SERVER,
        ...     local_port=5000
        ... )
        >>> conn = UDPConnection(config)
        >>> conn.connect()
        >>> data, addr = conn.recvfrom()
        >>> conn.sendto(b"response", addr)
    """
    
    def __init__(self, config: UDPConfig):
        """初始化 UDP 连接"""
        super().__init__(config)
        self._socket: Optional[socket.socket] = None
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
    
    @property
    def mode(self) -> UDPMode:
        """获取工作模式"""
        return self._config.mode
    
    @property
    def local_address(self) -> Tuple[str, int]:
        """获取本地地址"""
        if self._socket:
            return self._socket.getsockname()
        return (self._config.local_host, self._config.local_port)
    
    def connect(self) -> None:
        """建立 UDP 连接（创建套接字）"""
        self._set_status(ConnectionStatus.CONNECTING)
        self._logger.info(f"正在创建 UDP 套接字 ({self._config.mode.value})")
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.settimeout(self._config.timeout)
            
            # 启用广播
            if self._config.broadcast:
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                self._logger.info("已启用广播模式")
            
            # 设置接收缓冲区大小
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 
                                   self._config.buffer_size * 4)
            
            if self._config.mode == UDPMode.SERVER:
                # 服务器模式：绑定本地端口
                self._socket.bind((self._config.local_host, self._config.local_port))
                self._logger.info(f"UDP 服务器绑定: {self._config.local_host}:{self._config.local_port}")
            
            elif self._config.mode == UDPMode.CLIENT:
                # 客户端模式：可选绑定本地端口
                if self._config.local_port > 0:
                    self._socket.bind((self._config.local_host, self._config.local_port))
                self._logger.info(f"UDP 客户端就绪")
            
            elif self._config.mode == UDPMode.BIDIRECTIONAL:
                # 双向模式：绑定本地端口
                self._socket.bind((self._config.local_host, self._config.local_port))
                self._logger.info(f"UDP 双向模式绑定: {self._config.local_host}:{self._config.local_port}")
            
            # 加入组播组
            if self._config.multicast_group:
                self._join_multicast_group()
            
            self._running = True
            if self._has_selectable_socket():
                self._start_read_thread()
            
            self._set_status(ConnectionStatus.CONNECTED)
            
        except socket.gaierror as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"地址解析失败: {e}") from e
        except OSError as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"创建套接字失败: {e}") from e
    
    def disconnect(self) -> None:
        """断开 UDP 连接"""
        self._running = False
        
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)
        
        # 退出组播组
        if self._config.multicast_group and self._socket:
            try:
                self._leave_multicast_group()
            except Exception:
                pass
        
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        
        self._set_status(ConnectionStatus.DISCONNECTED)
        self._logger.info("UDP 连接已断开")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self._socket is not None
    
    def get_info(self) -> ConnectionInfo:
        """获取连接信息"""
        local_addr = self.local_address
        return ConnectionInfo(
            id=self._id,
            name=self._config.name,
            connection_type=ConnectionType.UDP,
            host=local_addr[0],
            port=local_addr[1],
            status=self._status,
            error_message=self._last_error
        )
    
    # ==================== 数据收发 ====================
    
    def sendto(self, data: bytes, address: Optional[Tuple[str, int]] = None) -> int:
        """
        发送数据报到指定地址
        
        Args:
            data: 要发送的数据
            address: 目标地址 (host, port)，默认使用配置的远程地址
            
        Returns:
            int: 发送的字节数
        """
        self._check_connection()
        
        if address is None:
            if self._config.remote_host and self._config.remote_port:
                address = (self._config.remote_host, self._config.remote_port)
            else:
                raise OperationError("未指定目标地址")
        
        try:
            sent = self._socket.sendto(data, address)
            self._logger.debug(f"发送 {sent} 字节到 {address}")
            return sent
        except socket.timeout as e:
            raise TimeoutError("发送超时") from e
        except Exception as e:
            raise OperationError(f"发送失败: {e}") from e
    
    def send(self, data: bytes) -> int:
        """发送数据（使用默认远程地址）"""
        return self.sendto(data)
    
    def recvfrom(self, size: int = -1, timeout: Optional[float] = None) -> Tuple[bytes, Tuple[str, int]]:
        """
        接收数据报
        
        Args:
            size: 接收缓冲区大小，默认使用配置值
            timeout: 超时时间
            
        Returns:
            Tuple[bytes, Tuple[str, int]]: (数据, 源地址)
        """
        self._check_connection()
        
        buffer_size = size if size > 0 else self._config.buffer_size
        
        old_timeout = self._socket.gettimeout()
        if timeout is not None:
            self._socket.settimeout(timeout)
        
        try:
            data, addr = self._socket.recvfrom(buffer_size)
            self._logger.debug(f"从 {addr} 接收 {len(data)} 字节")
            return data, addr
        except socket.timeout as e:
            raise TimeoutError("接收超时") from e
        except Exception as e:
            raise OperationError(f"接收失败: {e}") from e
        finally:
            if timeout is not None:
                self._socket.settimeout(old_timeout)
    
    def recv(self, size: int = -1, timeout: Optional[float] = None) -> bytes:
        """接收数据报（不返回源地址）"""
        data, _ = self.recvfrom(size, timeout)
        return data
    
    # ==================== 组播支持 ====================
    
    def _join_multicast_group(self) -> None:
        """加入组播组"""
        if not self._socket:
            return
        
        try:
            # 设置组播 TTL
            self._socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL,
                struct.pack('b', self._config.multicast_ttl)
            )
            
            # 加入组播组
            group = socket.inet_aton(self._config.multicast_group)
            mreq = struct.pack('4sL', group, socket.INADDR_ANY)
            self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            self._logger.info(f"已加入组播组: {self._config.multicast_group}")
            
        except Exception as e:
            self._logger.error(f"加入组播组失败: {e}")
            raise ConnectionError(f"加入组播组失败: {e}") from e
    
    def _leave_multicast_group(self) -> None:
        """退出组播组"""
        if not self._socket or not self._config.multicast_group:
            return
        
        try:
            group = socket.inet_aton(self._config.multicast_group)
            mreq = struct.pack('4sL', group, socket.INADDR_ANY)
            self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            self._logger.info(f"已退出组播组: {self._config.multicast_group}")
        except Exception as e:
            self._logger.warning(f"退出组播组失败: {e}")
    
    def set_multicast_ttl(self, ttl: int) -> None:
        """设置组播 TTL"""
        if self._socket:
            self._socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL,
                struct.pack('b', ttl)
            )
            self._config.multicast_ttl = ttl
    
    # ==================== 广播支持 ====================
    
    def broadcast(self, data: bytes, port: Optional[int] = None) -> int:
        """
        发送广播数据
        
        Args:
            data: 要发送的数据
            port: 目标端口，默认使用配置的远程端口
        """
        if not self._config.broadcast:
            raise OperationError("未启用广播模式，请在配置中设置 broadcast=True")
        
        port = port or self._config.remote_port
        if not port:
            raise OperationError("未指定广播端口")
        
        return self.sendto(data, ('<broadcast>', port))
    
    # ==================== 内部方法 ====================
    
    def _check_connection(self) -> None:
        """检查连接状态"""
        if not self._socket:
            raise OperationError("连接未建立")

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
                        data, addr = self._socket.recvfrom(self._config.buffer_size)
                        self._logger.debug(f"从 {addr} 接收 {len(data)} 字节")
                        self.emit('data_received', data, addr)
                        
                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        self._logger.error(f"接收错误: {e}")
        
        self._read_thread = threading.Thread(target=read_loop, daemon=True)
        self._read_thread.start()
    
    def __repr__(self) -> str:
        mode = self._config.mode.value
        if self._config.mode == UDPMode.SERVER:
            return f"<UDPConnection {mode} :{self._config.local_port}>"
        elif self._config.remote_host:
            return f"<UDPConnection {mode} {self._config.remote_host}:{self._config.remote_port}>"
        return f"<UDPConnection {mode}>"
