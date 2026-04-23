#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接基类模块

定义了所有连接类型的通用接口和基础功能。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, Dict, Any
import threading
import uuid
import logging


class ConnectionStatus(Enum):
    """连接状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class ConnectionType(Enum):
    """连接类型枚举"""
    SSH = "ssh"
    SFTP = "sftp"
    FTP = "ftp"
    FTPS = "ftps"
    SERIAL = "serial"
    TCP = "tcp"
    UDP = "udp"
    VNC = "vnc"
    RDP = "rdp"


@dataclass
class ConnectionInfo:
    """连接信息"""
    id: str
    name: str
    connection_type: ConnectionType
    host: Optional[str] = None
    port: Optional[int] = None
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'connection_type': self.connection_type.value,
            'host': self.host,
            'port': self.port,
            'status': self.status.value,
            'error_message': self.error_message,
        }


class BaseConnection(ABC):
    """
    连接基类
    
    所有连接类型都必须继承此类并实现其抽象方法。
    
    Attributes:
        id: 连接唯一标识符
        status: 当前连接状态
        config: 连接配置
    
    Events:
        connected: 连接成功时触发
        disconnected: 断开连接时触发
        error: 发生错误时触发
        status_changed: 状态变化时触发
    
    Example:
        >>> class MyConnection(BaseConnection):
        ...     def connect(self):
        ...         # 实现连接逻辑
        ...         pass
        ...     def disconnect(self):
        ...         # 实现断开逻辑
        ...         pass
        ...     def is_connected(self) -> bool:
        ...         return self._connected
        ...     def get_info(self) -> ConnectionInfo:
        ...         return ConnectionInfo(...)
    """
    
    def __init__(self, config: Any):
        """
        初始化连接
        
        Args:
            config: 连接配置对象
        """
        self._id: str = getattr(config, 'id', str(uuid.uuid4()))
        self._config = config
        self._status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self._lock = threading.RLock()
        self._callbacks: Dict[str, list[Callable]] = {}
        self._logger = logging.getLogger(self.__class__.__name__)
        
        # 连接错误信息
        self._last_error: Optional[str] = None
    
    @property
    def id(self) -> str:
        """获取连接 ID"""
        return self._id
    
    @property
    def status(self) -> ConnectionStatus:
        """获取当前状态"""
        return self._status
    
    @property
    def config(self) -> Any:
        """获取配置"""
        return self._config
    
    @property
    def last_error(self) -> Optional[str]:
        """获取最后的错误信息"""
        return self._last_error
    
    def on(self, event: str, callback: Callable) -> None:
        """
        注册事件回调函数
        
        Args:
            event: 事件名称，支持: 'connected', 'disconnected', 'error', 'status_changed'
            callback: 回调函数
        """
        self._callbacks.setdefault(event, []).append(callback)
    
    def off(self, event: str, callback: Optional[Callable] = None) -> None:
        """
        移除事件回调函数
        
        Args:
            event: 事件名称
            callback: 指定回调；为空时移除该事件全部回调
        """
        if callback is None:
            self._callbacks.pop(event, None)
            return

        callbacks = self._callbacks.get(event, [])
        callbacks = [registered for registered in callbacks if registered is not callback]
        if callbacks:
            self._callbacks[event] = callbacks
        else:
            self._callbacks.pop(event, None)
    
    def emit(self, event: str, *args, **kwargs) -> None:
        """
        触发事件
        
        Args:
            event: 事件名称
            *args: 位置参数
            **kwargs: 关键字参数
        """
        callbacks = list(self._callbacks.get(event, []))
        for callback in callbacks:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                self._logger.error(f"事件回调执行失败 [{event}]: {e}")
    
    def _set_status(self, status: ConnectionStatus, error_message: Optional[str] = None) -> None:
        """
        设置连接状态
        
        Args:
            status: 新状态
            error_message: 错误信息（可选）
        """
        old_status = self._status
        self._status = status
        self._last_error = error_message
        
        if old_status != status:
            self.emit('status_changed', status, old_status)
        
        if status == ConnectionStatus.CONNECTED:
            self.emit('connected')
        elif status == ConnectionStatus.DISCONNECTED:
            self.emit('disconnected')
        elif status == ConnectionStatus.ERROR:
            self.emit('error', error_message)
    
    @abstractmethod
    def connect(self) -> None:
        """
        建立连接
        
        子类必须实现此方法来建立实际的连接。
        
        Raises:
            ConnectionError: 连接失败
            AuthenticationError: 认证失败
            TimeoutError: 连接超时
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """
        断开连接
        
        子类必须实现此方法来断开连接并清理资源。
        """
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """
        检查连接状态
        
        Returns:
            bool: True 表示已连接，False 表示未连接
        """
        pass
    
    @abstractmethod
    def get_info(self) -> ConnectionInfo:
        """
        获取连接信息
        
        Returns:
            ConnectionInfo: 连接信息对象
        """
        pass
    
    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()
        return False
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self._id} status={self._status.value}>"
