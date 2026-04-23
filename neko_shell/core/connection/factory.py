#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接工厂模块

提供统一的连接创建接口。
"""

from typing import Dict, Type, Any, Optional
from .base import BaseConnection, ConnectionType
from .ftp import FTPConnection
from .sftp import SFTPConnection
from .serial import SerialConnection
from .ssh import SSHConnection
from .tcp import TCPConnection
from .udp import UDPConnection
from .vnc import VNCConnection

# 配置类导入
from neko_shell.models.connection import (
    BaseConnectionConfig,
    FTPConfig,
    SFTPConfig,
    SerialConfig,
    SSHConfig,
    TCPConfig,
    UDPConfig,
    VNCConfig,
)


class ConnectionFactory:
    """
    连接工厂
    
    根据配置创建对应的连接实例。
    
    Example:
        >>> from neko_shell.core.connection import ConnectionFactory
        >>> from neko_shell.models.connection import TCPConfig
        >>> 
        >>> config = TCPConfig(name="test", host="192.168.1.100", port=8080)
        >>> conn = ConnectionFactory.create(config)
        >>> conn.connect()
    """
    
    # 连接类型映射
    _connection_classes: Dict[ConnectionType, Type[BaseConnection]] = {
        ConnectionType.SSH: SSHConnection,
        ConnectionType.SFTP: SFTPConnection,
        ConnectionType.FTP: FTPConnection,
        ConnectionType.SERIAL: SerialConnection,
        ConnectionType.TCP: TCPConnection,
        ConnectionType.UDP: UDPConnection,
        ConnectionType.VNC: VNCConnection,
    }
    
    # 配置类型映射
    _config_classes: Dict[ConnectionType, Type[BaseConnectionConfig]] = {
        ConnectionType.SSH: SSHConfig,
        ConnectionType.SFTP: SFTPConfig,
        ConnectionType.FTP: FTPConfig,
        ConnectionType.SERIAL: SerialConfig,
        ConnectionType.TCP: TCPConfig,
        ConnectionType.UDP: UDPConfig,
        ConnectionType.VNC: VNCConfig,
    }
    
    @classmethod
    def create(cls, config: BaseConnectionConfig) -> BaseConnection:
        """
        根据配置创建连接实例
        
        Args:
            config: 连接配置对象
            
        Returns:
            BaseConnection: 连接实例
            
        Raises:
            ValueError: 不支持的连接类型
        """
        connection_type = config.connection_type
        
        if connection_type not in cls._connection_classes:
            raise ValueError(f"不支持的连接类型: {connection_type}")
        
        connection_class = cls._connection_classes[connection_type]
        return connection_class(config)
    
    @classmethod
    def create_from_dict(cls, data: Dict[str, Any]) -> BaseConnection:
        """
        从字典创建连接实例
        
        Args:
            data: 配置字典（必须包含 connection_type 字段）
            
        Returns:
            BaseConnection: 连接实例
        """
        connection_type_str = data.get('connection_type')
        if not connection_type_str:
            raise ValueError("配置中缺少 connection_type 字段")
        
        connection_type = ConnectionType(connection_type_str)
        
        if connection_type not in cls._config_classes:
            raise ValueError(f"不支持的连接类型: {connection_type}")
        
        config_class = cls._config_classes[connection_type]
        config = config_class.from_dict(data)
        
        return cls.create(config)
    
    @classmethod
    def get_supported_types(cls) -> list:
        """
        获取支持的连接类型列表
        
        Returns:
            list: 连接类型列表
        """
        return list(cls._connection_classes.keys())
    
    @classmethod
    def register(
        cls,
        connection_type: ConnectionType,
        connection_class: Type[BaseConnection],
        config_class: Type[BaseConnectionConfig]
    ) -> None:
        """
        注册新的连接类型
        
        Args:
            connection_type: 连接类型
            connection_class: 连接类
            config_class: 配置类
        """
        cls._connection_classes[connection_type] = connection_class
        cls._config_classes[connection_type] = config_class
    
    @classmethod
    def is_type_supported(cls, connection_type: ConnectionType) -> bool:
        """
        检查连接类型是否支持
        
        Args:
            connection_type: 连接类型
            
        Returns:
            bool: 是否支持
        """
        return connection_type in cls._connection_classes


def create_connection(config: BaseConnectionConfig) -> BaseConnection:
    """
    快捷函数：创建连接
    
    Args:
        config: 连接配置
        
    Returns:
        BaseConnection: 连接实例
        
    Example:
        >>> from neko_shell.core.connection import create_connection
        >>> from neko_shell.models.connection import TCPConfig
        >>> 
        >>> conn = create_connection(TCPConfig(
        ...     name="test",
        ...     host="192.168.1.100",
        ...     port=8080
        ... ))
    """
    return ConnectionFactory.create(config)


def create_connection_from_dict(data: Dict[str, Any]) -> BaseConnection:
    """
    快捷函数：从字典创建连接
    
    Args:
        data: 配置字典
        
    Returns:
        BaseConnection: 连接实例
    """
    return ConnectionFactory.create_from_dict(data)
