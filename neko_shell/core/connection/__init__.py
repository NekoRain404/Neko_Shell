# 连接管理模块
"""
连接管理模块提供了统一的连接接口和多种协议的实现。

支持的连接类型：
- SSH: 安全外壳远程登录
- SFTP: 安全文件传输
- FTP/FTPS: 文件传输协议
- Serial: 串口通信
- TCP: TCP 套接字连接
- UDP: UDP 数据报通信
- VNC: 远程桌面协议

使用示例:
    >>> from neko_shell.core.connection import ConnectionFactory, TCPConfig
    >>> 
    >>> # 方式1: 使用工厂创建
    >>> config = TCPConfig(name="test", host="192.168.1.100", port=8080)
    >>> conn = ConnectionFactory.create(config)
    >>> 
    >>> # 方式2: 直接创建
    >>> from neko_shell.core.connection import TCPConnection
    >>> conn = TCPConnection(config)
"""

from .base import (
    BaseConnection,
    ConnectionStatus,
    ConnectionType,
    ConnectionInfo,
)

from .factory import (
    ConnectionFactory,
    create_connection,
    create_connection_from_dict,
)

# 连接实现
from .ftp import FTPConnection
from .sftp import SFTPConnection
from .serial import SerialConnection
from .ssh import SSHConnection
from .tcp import TCPConnection
from .udp import UDPConnection
from .vnc import VNCConnection

# 配置类
from neko_shell.models.connection import (
    # FTP
    SSHConfig,
    SFTPConfig,
    FTPConfig, 
    FTPMode, 
    FTPSType, 
    FTPFileItem,
    # Serial
    SerialConfig,
    SerialParity,
    SerialStopBits,
    SerialByteSize,
    SerialFlowControl,
    SerialPortInfo,
    # TCP
    TCPConfig,
    # UDP
    UDPConfig,
    UDPMode,
    # VNC
    VNCConfig,
    VNCSecurityType,
    VNCColorDepth,
)

__all__ = [
    # 基类
    'BaseConnection',
    'ConnectionStatus',
    'ConnectionType',
    'ConnectionInfo',
    # 工厂
    'ConnectionFactory',
    'create_connection',
    'create_connection_from_dict',
    # FTP
    'SSHConnection',
    'SSHConfig',
    'SFTPConnection',
    'SFTPConfig',
    'FTPConnection',
    'FTPConfig',
    'FTPMode',
    'FTPSType',
    'FTPFileItem',
    # Serial
    'SerialConnection',
    'SerialConfig',
    'SerialParity',
    'SerialStopBits',
    'SerialByteSize',
    'SerialFlowControl',
    'SerialPortInfo',
    # TCP
    'TCPConnection',
    'TCPConfig',
    # UDP
    'UDPConnection',
    'UDPConfig',
    'UDPMode',
    # VNC
    'VNCConnection',
    'VNCConfig',
    'VNCSecurityType',
    'VNCColorDepth',
]
