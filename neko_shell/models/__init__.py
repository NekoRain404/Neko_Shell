# 数据模型模块
"""
Neko_Shell 数据模型
"""

from .connection import (
    # 基类
    BaseConnectionConfig,
    # SSH/SFTP
    SSHConfig,
    SFTPConfig,
    # FTP
    FTPConfig,
    FTPMode,
    FTPSType,
    FTPFileItem,
    # 串口
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
from .tunnel import TunnelConfig

__all__ = [
    # 基类
    'BaseConnectionConfig',
    # SSH/SFTP
    'SSHConfig',
    'SFTPConfig',
    # FTP
    'FTPConfig',
    'FTPMode',
    'FTPSType',
    'FTPFileItem',
    # 串口
    'SerialConfig',
    'SerialParity',
    'SerialStopBits',
    'SerialByteSize',
    'SerialFlowControl',
    'SerialPortInfo',
    # TCP
    'TCPConfig',
    # UDP
    'UDPConfig',
    'UDPMode',
    # VNC
    'VNCConfig',
    'VNCSecurityType',
    'VNCColorDepth',
    'TunnelConfig',
]
