#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Neko_Shell 主包

一个功能强大的远程连接管理工具，支持多种协议。

支持的连接类型:
    - SSH: 安全外壳远程登录
    - SFTP: 安全文件传输
    - FTP/FTPS: 文件传输协议
    - Serial: 串口通信
    - TCP: TCP 套接字连接
    - UDP: UDP 数据报通信
    - VNC: 远程桌面协议

快速开始:
    >>> from neko_shell import create_connection, TCPConfig
    >>> 
    >>> config = TCPConfig(name="test", host="192.168.1.100", port=8080)
    >>> conn = create_connection(config)
    >>> conn.connect()
    >>> conn.write(b"hello")
    >>> conn.disconnect()

命令行启动:
    python -m neko_shell
    
    或:
    
    neko-shell --theme dark
"""

from .release import APP_AUTHOR, APP_VERSION


__version__ = APP_VERSION
__author__ = APP_AUTHOR

# 导入常用组件
from .core.connection import (
    # 工厂函数
    create_connection,
    create_connection_from_dict,
    ConnectionFactory,
    # 连接类型
    ConnectionType,
    ConnectionStatus,
    # 连接类
    SSHConnection,
    SFTPConnection,
    FTPConnection,
    SerialConnection,
    TCPConnection,
    UDPConnection,
    VNCConnection,
)

from .models.connection import (
    # 配置类
    SSHConfig,
    SFTPConfig,
    FTPConfig,
    SerialConfig,
    TCPConfig,
    UDPConfig,
    VNCConfig,
)

from .utils import (
    # 异常
    ConnectionError,
    AuthenticationError,
    TimeoutError,
    # 日志
    get_logger,
    setup_logging,
    # 配置
    ConfigManager,
)

from .app import Application, get_app

__all__ = [
    # 版本
    '__version__',
    '__author__',
    # 应用
    'Application',
    'get_app',
    # 工厂函数
    'create_connection',
    'create_connection_from_dict',
    'ConnectionFactory',
    # 连接类型和状态
    'ConnectionType',
    'ConnectionStatus',
    # 连接类
    'SSHConnection',
    'SFTPConnection',
    'FTPConnection',
    'SerialConnection',
    'TCPConnection',
    'UDPConnection',
    'VNCConnection',
    # 配置类
    'SSHConfig',
    'SFTPConfig',
    'FTPConfig',
    'SerialConfig',
    'TCPConfig',
    'UDPConfig',
    'VNCConfig',
    # 异常
    'ConnectionError',
    'AuthenticationError',
    'TimeoutError',
    # 工具
    'get_logger',
    'setup_logging',
    'ConfigManager',
]
