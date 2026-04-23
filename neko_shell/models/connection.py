#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接配置模型

定义了各种连接类型的配置数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from enum import Enum
import uuid

if TYPE_CHECKING:
    from neko_shell.core.connection.base import ConnectionType


class FTPMode(Enum):
    """
    FTP 模式枚举
    
    - PASSIVE: 被动模式（默认），客户端连接服务器打开的数据端口
    - ACTIVE: 主动模式，服务器连接客户端打开的数据端口
    
    大多数现代网络环境（特别是防火墙/NAT 后）推荐使用被动模式。
    """
    PASSIVE = "passive"
    ACTIVE = "active"


class FTPSType(Enum):
    """
    FTPS 类型枚举
    
    - NONE: 不加密，标准 FTP
    - IMPLICIT: 隐式 FTPS，连接时即启用 SSL/TLS（端口通常为 990）
    - EXPLICIT: 显式 FTPS，连接后通过 AUTH 命令升级为加密（端口通常为 21）
    """
    NONE = "none"
    IMPLICIT = "implicit"
    EXPLICIT = "explicit"


@dataclass
class BaseConnectionConfig:
    """
    连接配置基类
    
    所有连接配置都应继承此类。
    
    Attributes:
        name: 连接名称
        connection_type: 连接类型（子类会自动设置）
        group: 分组名称
        environment: 环境名称
        project: 项目名称
        business_domain: 业务域名称
        description: 连接描述
        tags: 标签列表
    """
    name: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    connection_type: 'ConnectionType' = None  # type: ignore
    group: str = "default"
    environment: str = ""
    project: str = ""
    business_domain: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'connection_type': self.connection_type.value,
            'group': self.group,
            'environment': self.environment,
            'project': self.project,
            'business_domain': self.business_domain,
            'description': self.description,
            'tags': self.tags,
        }
    
    @classmethod
    def _filter_init_kwargs(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """过滤掉 dataclass 未声明的附加字段。"""
        allowed = {item.name for item in fields(cls)}
        return {key: value for key, value in data.items() if key in allowed}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseConnectionConfig':
        """从字典创建"""
        from neko_shell.core.connection.base import ConnectionType
        converted = dict(data)
        if 'connection_type' in converted and isinstance(converted['connection_type'], str):
            converted['connection_type'] = ConnectionType(converted['connection_type'])
        return cls(**cls._filter_init_kwargs(converted))


@dataclass
class FTPConfig(BaseConnectionConfig):
    """
    FTP/FTPS 连接配置
    
    用于配置 FTP 或 FTPS (FTP over SSL/TLS) 连接。
    
    Attributes:
        host: FTP 服务器地址
        port: FTP 服务器端口，默认 21
        username: 用户名，默认 "anonymous"
        password: 密码
        mode: FTP 模式 (主动/被动)
        ftps_type: FTPS 类型 (无/隐式/显式)
        timeout: 连接超时时间（秒）
        encoding: 字符编码
        auto_reconnect: 是否自动重连
        max_reconnect_attempts: 最大重连次数
    
    Examples:
        >>> # 基本 FTP 连接
        >>> config = FTPConfig(
        ...     name="我的 FTP",
        ...     host="ftp.example.com",
        ...     username="user",
        ...     password="pass"
        ... )
        
        >>> # FTPS 隐式加密
        >>> config = FTPConfig(
        ...     name="安全 FTP",
        ...     host="ftps.example.com",
        ...     port=990,
        ...     username="user",
        ...     password="pass",
        ...     ftps_type=FTPSType.IMPLICIT
        ... )
    """
    host: str = ""
    port: int = 21
    username: str = "anonymous"
    password: str = ""
    mode: FTPMode = FTPMode.PASSIVE  # type: ignore
    ftps_type: FTPSType = FTPSType.NONE  # type: ignore
    timeout: float = 30.0
    encoding: str = "utf-8"
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 3
    
    def __post_init__(self):
        """初始化后处理"""
        from neko_shell.core.connection.base import ConnectionType
        self.connection_type = ConnectionType.FTP
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = super().to_dict()
        data.update({
            'host': self.host,
            'port': self.port,
            'username': self.username,
            # 不保存密码到配置文件
            'mode': self.mode.value,
            'ftps_type': self.ftps_type.value,
            'timeout': self.timeout,
            'encoding': self.encoding,
            'auto_reconnect': self.auto_reconnect,
            'max_reconnect_attempts': self.max_reconnect_attempts,
        })
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FTPConfig':
        """从字典创建"""
        from neko_shell.core.connection.base import ConnectionType
        converted = dict(data)
        if 'connection_type' in converted:
            converted['connection_type'] = ConnectionType(converted['connection_type'])
        if 'mode' in converted and isinstance(converted['mode'], str):
            converted['mode'] = FTPMode(converted['mode'])
        if 'ftps_type' in converted and isinstance(converted['ftps_type'], str):
            converted['ftps_type'] = FTPSType(converted['ftps_type'])
        return cls(**cls._filter_init_kwargs(converted))
    
    def is_ftps(self) -> bool:
        """是否为 FTPS 连接"""
        return self.ftps_type != FTPSType.NONE
    
    def __repr__(self) -> str:
        return f"<FTPConfig name={self.name} host={self.host}:{self.port}>"


@dataclass
class FTPFileItem:
    """
    FTP 文件项
    
    表示 FTP 服务器上的文件或目录信息。
    
    Attributes:
        name: 文件名
        is_dir: 是否为目录
        size: 文件大小（字节）
        modify_time: 修改时间
        permissions: 权限字符串
        owner: 所有者
        group: 所属组
    """
    name: str
    is_dir: bool = False
    size: int = 0
    modify_time: Optional[str] = None
    permissions: Optional[str] = None
    owner: Optional[str] = None
    group: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'is_dir': self.is_dir,
            'size': self.size,
            'modify_time': self.modify_time,
            'permissions': self.permissions,
            'owner': self.owner,
            'group': self.group,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FTPFileItem':
        """从字典创建"""
        return cls(**data)


# ==================== 串口配置 ====================

class SerialParity(Enum):
    """
    串口校验位枚举
    
    - NONE: 无校验（默认）
    - EVEN: 偶校验
    - ODD: 奇校验
    - MARK: 标记校验
    - SPACE: 空格校验
    """
    NONE = "none"
    EVEN = "even"
    ODD = "odd"
    MARK = "mark"
    SPACE = "space"


class SerialStopBits(Enum):
    """
    串口停止位枚举
    
    - ONE: 1 位停止位（默认）
    - ONE_POINT_FIVE: 1.5 位停止位
    - TWO: 2 位停止位
    """
    ONE = "1"
    ONE_POINT_FIVE = "1.5"
    TWO = "2"


class SerialByteSize(Enum):
    """
    串口数据位枚举
    
    - FIVE: 5 位数据位
    - SIX: 6 位数据位
    - SEVEN: 7 位数据位
    - EIGHT: 8 位数据位（默认）
    """
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"


class SerialFlowControl(Enum):
    """
    串口流控制枚举
    
    - NONE: 无流控制（默认）
    - XON_XOFF: 软件流控制（XON/XOFF）
    - RTS_CTS: 硬件流控制（RTS/CTS）
    - DSR_DTR: 硬件流控制（DSR/DTR）
    """
    NONE = "none"
    XON_XOFF = "xon_xoff"
    RTS_CTS = "rts_cts"
    DSR_DTR = "dsr_dtr"


@dataclass
class SerialConfig(BaseConnectionConfig):
    """
    串口连接配置
    
    用于配置串口通信参数。
    
    Attributes:
        port: 串口设备路径（如 /dev/ttyUSB0 或 COM3）
        baud_rate: 波特率，默认 9600
        byte_size: 数据位，默认 8 位
        parity: 校验位，默认无校验
        stop_bits: 停止位，默认 1 位
        flow_control: 流控制，默认无
        timeout: 读取超时时间（秒），默认 1.0
        write_timeout: 写入超时时间（秒），默认 1.0
        encoding: 字符编码，默认 UTF-8
        line_ending: 行结束符，默认 \\r\\n
        auto_reconnect: 是否自动重连
        max_reconnect_attempts: 最大重连次数
    
    Examples:
        >>> # 基本串口配置
        >>> config = SerialConfig(
        ...     name="串口1",
        ...     port="/dev/ttyUSB0",
        ...     baud_rate=115200
        ... )
        
        >>> # 完整配置
        >>> config = SerialConfig(
        ...     name="调试串口",
        ...     port="COM3",
        ...     baud_rate=9600,
        ...     byte_size=SerialByteSize.EIGHT,
        ...     parity=SerialParity.NONE,
        ...     stop_bits=SerialStopBits.ONE,
        ...     flow_control=SerialFlowControl.NONE
        ... )
    """
    port: str = ""
    baud_rate: int = 9600
    byte_size: SerialByteSize = SerialByteSize.EIGHT  # type: ignore
    parity: SerialParity = SerialParity.NONE  # type: ignore
    stop_bits: SerialStopBits = SerialStopBits.ONE  # type: ignore
    flow_control: SerialFlowControl = SerialFlowControl.NONE  # type: ignore
    timeout: float = 1.0
    write_timeout: float = 1.0
    encoding: str = "utf-8"
    line_ending: str = "\r\n"
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 3
    
    def __post_init__(self):
        """初始化后处理"""
        from neko_shell.core.connection.base import ConnectionType
        self.connection_type = ConnectionType.SERIAL
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = super().to_dict()
        data.update({
            'port': self.port,
            'baud_rate': self.baud_rate,
            'byte_size': self.byte_size.value,
            'parity': self.parity.value,
            'stop_bits': self.stop_bits.value,
            'flow_control': self.flow_control.value,
            'timeout': self.timeout,
            'write_timeout': self.write_timeout,
            'encoding': self.encoding,
            'line_ending': self.line_ending,
            'auto_reconnect': self.auto_reconnect,
            'max_reconnect_attempts': self.max_reconnect_attempts,
        })
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SerialConfig':
        """从字典创建"""
        from neko_shell.core.connection.base import ConnectionType
        converted = dict(data)
        if 'connection_type' in converted:
            converted['connection_type'] = ConnectionType(converted['connection_type'])
        if 'byte_size' in converted and isinstance(converted['byte_size'], str):
            converted['byte_size'] = SerialByteSize(converted['byte_size'])
        if 'parity' in converted and isinstance(converted['parity'], str):
            converted['parity'] = SerialParity(converted['parity'])
        if 'stop_bits' in converted and isinstance(converted['stop_bits'], str):
            converted['stop_bits'] = SerialStopBits(converted['stop_bits'])
        if 'flow_control' in converted and isinstance(converted['flow_control'], str):
            converted['flow_control'] = SerialFlowControl(converted['flow_control'])
        return cls(**cls._filter_init_kwargs(converted))
    
    def __repr__(self) -> str:
        return f"<SerialConfig name={self.name} port={self.port} baud={self.baud_rate}>"


@dataclass
class SerialPortInfo:
    """
    串口信息
    
    表示系统中可用的串口设备信息。
    
    Attributes:
        port: 设备路径
        description: 设备描述
        hwid: 硬件 ID
        vid: 厂商 ID
        pid: 产品 ID
        manufacturer: 制造商
        product: 产品名称
        serial_number: 序列号
    """
    port: str
    description: str = ""
    hwid: Optional[str] = None
    vid: Optional[int] = None
    pid: Optional[int] = None
    manufacturer: Optional[str] = None
    product: Optional[str] = None
    serial_number: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'port': self.port,
            'description': self.description,
            'hwid': self.hwid,
            'vid': self.vid,
            'pid': self.pid,
            'manufacturer': self.manufacturer,
            'product': self.product,
            'serial_number': self.serial_number,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SerialPortInfo':
        """从字典创建"""
        return cls(**data)
    
    @property
    def display_name(self) -> str:
        """获取显示名称"""
        if self.description:
            return f"{self.port} - {self.description}"
        return self.port


# ==================== TCP 配置 ====================

@dataclass
class TCPConfig(BaseConnectionConfig):
    """
    TCP 连接配置
    
    用于配置 TCP 套接字连接。
    
    Attributes:
        host: 远程主机地址
        port: 远程端口号
        timeout: 连接/读写超时时间（秒）
        buffer_size: 接收缓冲区大小
        keepalive: 是否启用 TCP Keep-Alive
        keepalive_idle: Keep-Idle 空闲时间（秒）
        keepalive_interval: Keep-Alive 探测间隔（秒）
        keepalive_count: Keep-Alive 探测次数
        no_delay: 是否禁用 Nagle 算法
        auto_reconnect: 是否自动重连
        max_reconnect_attempts: 最大重连次数
    
    Examples:
        >>> # 基本 TCP 配置
        >>> config = TCPConfig(
        ...     name="设备连接",
        ...     host="192.168.1.100",
        ...     port=8080
        ... )
        
        >>> # 启用 Keep-Alive
        >>> config = TCPConfig(
        ...     name="长连接",
        ...     host="192.168.1.100",
        ...     port=8080,
        ...     keepalive=True,
        ...     keepalive_idle=60
        ... )
    """
    host: str = ""
    port: int = 0
    timeout: float = 10.0
    buffer_size: int = 4096
    keepalive: bool = True
    keepalive_idle: int = 60
    keepalive_interval: int = 10
    keepalive_count: int = 5
    no_delay: bool = True
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 3
    
    def __post_init__(self):
        """初始化后处理"""
        from neko_shell.core.connection.base import ConnectionType
        self.connection_type = ConnectionType.TCP
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = super().to_dict()
        data.update({
            'host': self.host,
            'port': self.port,
            'timeout': self.timeout,
            'buffer_size': self.buffer_size,
            'keepalive': self.keepalive,
            'keepalive_idle': self.keepalive_idle,
            'keepalive_interval': self.keepalive_interval,
            'keepalive_count': self.keepalive_count,
            'no_delay': self.no_delay,
            'auto_reconnect': self.auto_reconnect,
            'max_reconnect_attempts': self.max_reconnect_attempts,
        })
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TCPConfig':
        """从字典创建"""
        from neko_shell.core.connection.base import ConnectionType
        converted = dict(data)
        if 'connection_type' in converted:
            converted['connection_type'] = ConnectionType(converted['connection_type'])
        return cls(**cls._filter_init_kwargs(converted))
    
    def __repr__(self) -> str:
        return f"<TCPConfig name={self.name} {self.host}:{self.port}>"


# ==================== UDP 配置 ====================

class UDPMode(Enum):
    """
    UDP 工作模式枚举
    
    - CLIENT: 客户端模式（发送数据到指定服务器）
    - SERVER: 服务器模式（绑定本地端口接收数据）
    - BIDIRECTIONAL: 双向模式（同时发送和接收）
    """
    CLIENT = "client"
    SERVER = "server"
    BIDIRECTIONAL = "bidirectional"


@dataclass
class UDPConfig(BaseConnectionConfig):
    """
    UDP 连接配置
    
    用于配置 UDP 数据报通信。
    
    Attributes:
        local_host: 本地绑定地址，默认 0.0.0.0
        local_port: 本地绑定端口，0 表示随机端口
        remote_host: 远程主机地址（客户端模式）
        remote_port: 远程端口（客户端模式）
        mode: 工作模式（客户端/服务器/双向）
        buffer_size: 接收缓冲区大小
        timeout: 接收超时时间（秒）
        broadcast: 是否启用广播
        multicast_group: 组播地址（可选）
        multicast_ttl: 组播 TTL
        auto_reconnect: 是否自动重连
    
    Examples:
        >>> # UDP 客户端
        >>> config = UDPConfig(
        ...     name="UDP客户端",
        ...     mode=UDPMode.CLIENT,
        ...     remote_host="192.168.1.100",
        ...     remote_port=5000
        ... )
        
        >>> # UDP 服务器
        >>> config = UDPConfig(
        ...     name="UDP服务器",
        ...     mode=UDPMode.SERVER,
        ...     local_port=5000
        ... )
        
        >>> # 广播
        >>> config = UDPConfig(
        ...     name="广播",
        ...     mode=UDPMode.CLIENT,
        ...     remote_port=5000,
        ...     broadcast=True
        ... )
    """
    local_host: str = "0.0.0.0"
    local_port: int = 0
    remote_host: str = ""
    remote_port: int = 0
    mode: UDPMode = UDPMode.CLIENT  # type: ignore
    buffer_size: int = 4096
    timeout: float = 5.0
    broadcast: bool = False
    multicast_group: Optional[str] = None
    multicast_ttl: int = 1
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 3
    
    def __post_init__(self):
        """初始化后处理"""
        from neko_shell.core.connection.base import ConnectionType
        self.connection_type = ConnectionType.UDP
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = super().to_dict()
        data.update({
            'local_host': self.local_host,
            'local_port': self.local_port,
            'remote_host': self.remote_host,
            'remote_port': self.remote_port,
            'mode': self.mode.value,
            'buffer_size': self.buffer_size,
            'timeout': self.timeout,
            'broadcast': self.broadcast,
            'multicast_group': self.multicast_group,
            'multicast_ttl': self.multicast_ttl,
            'auto_reconnect': self.auto_reconnect,
            'max_reconnect_attempts': self.max_reconnect_attempts,
        })
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UDPConfig':
        """从字典创建"""
        from neko_shell.core.connection.base import ConnectionType
        converted = dict(data)
        if 'connection_type' in converted:
            converted['connection_type'] = ConnectionType(converted['connection_type'])
        if 'mode' in converted and isinstance(converted['mode'], str):
            converted['mode'] = UDPMode(converted['mode'])
        return cls(**cls._filter_init_kwargs(converted))
    
    def __repr__(self) -> str:
        if self.mode == UDPMode.SERVER:
            return f"<UDPConfig name={self.name} server:{self.local_port}>"
        elif self.remote_host:
            return f"<UDPConfig name={self.name} {self.remote_host}:{self.remote_port}>"
        return f"<UDPConfig name={self.name} {self.mode.value}>"


# ==================== VNC 配置 ====================

class VNCSecurityType(Enum):
    """
    VNC 安全类型枚举
    
    - NONE: 无认证
    - VNC: 标准 VNC 密码认证
    - RA2: RA2 加密
    - TLS: TLS 加密
    - VENCRYPT: VeNCrypt 加密
    """
    NONE = "none"
    VNC = "vnc"
    RA2 = "ra2"
    TLS = "tls"
    VENCRYPT = "vencrypt"


class VNCColorDepth(Enum):
    """
    VNC 色深枚举
    
    - COLOR_8: 8 位色 (256色)
    - COLOR_16: 16 位色 (65536色)
    - COLOR_24: 24 位色 (真彩色)
    - COLOR_32: 32 位色
    """
    COLOR_8 = 8
    COLOR_16 = 16
    COLOR_24 = 24
    COLOR_32 = 32


@dataclass
class VNCConfig(BaseConnectionConfig):
    """
    VNC 连接配置
    
    用于配置 VNC 远程桌面连接。
    
    Attributes:
        host: VNC 服务器地址
        port: VNC 服务器端口，默认 5900
        password: VNC 密码
        username: 用户名（某些 VNC 服务器需要）
        security_type: 安全类型
        color_depth: 色深
        shared: 是否共享连接（允许多个客户端）
        view_only: 只读模式
        compress_level: 压缩级别 0-9
        quality: 图像质量 0-9
        timeout: 连接超时时间（秒）
        encoding: 编码方式列表
        auto_reconnect: 是否自动重连
    
    Examples:
        >>> # 基本 VNC 连接
        >>> config = VNCConfig(
        ...     name="远程桌面",
        ...     host="192.168.1.100",
        ...     port=5900,
        ...     password="secret"
        ... )
        
        >>> # 高质量连接
        >>> config = VNCConfig(
        ...     name="高清桌面",
        ...     host="192.168.1.100",
        ...     color_depth=VNCColorDepth.COLOR_32,
        ...     quality=9
        ... )
    """
    host: str = ""
    port: int = 5900
    password: str = ""
    username: Optional[str] = None
    security_type: VNCSecurityType = VNCSecurityType.VNC  # type: ignore
    color_depth: VNCColorDepth = VNCColorDepth.COLOR_24  # type: ignore
    shared: bool = True
    view_only: bool = False
    compress_level: int = 6
    quality: int = 6
    timeout: float = 10.0
    encoding: List[str] = field(default_factory=lambda: ['raw', 'copyrect', 'rre', 'hextile', 'zrle', 'tight'])
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 3
    
    def __post_init__(self):
        """初始化后处理"""
        from neko_shell.core.connection.base import ConnectionType
        self.connection_type = ConnectionType.VNC
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = super().to_dict()
        data.update({
            'host': self.host,
            'port': self.port,
            # 不保存密码
            'username': self.username,
            'security_type': self.security_type.value,
            'color_depth': self.color_depth.value,
            'shared': self.shared,
            'view_only': self.view_only,
            'compress_level': self.compress_level,
            'quality': self.quality,
            'timeout': self.timeout,
            'encoding': self.encoding,
            'auto_reconnect': self.auto_reconnect,
            'max_reconnect_attempts': self.max_reconnect_attempts,
        })
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VNCConfig':
        """从字典创建"""
        from neko_shell.core.connection.base import ConnectionType
        converted = dict(data)
        if 'connection_type' in converted:
            converted['connection_type'] = ConnectionType(converted['connection_type'])
        if 'security_type' in converted and isinstance(converted['security_type'], str):
            converted['security_type'] = VNCSecurityType(converted['security_type'])
        if 'color_depth' in converted and isinstance(converted['color_depth'], int):
            converted['color_depth'] = VNCColorDepth(converted['color_depth'])
        return cls(**cls._filter_init_kwargs(converted))
    
    def __repr__(self) -> str:
        return f"<VNCConfig name={self.name} {self.host}:{self.port}>"


# ==================== SSH/SFTP 配置 ====================

@dataclass
class SSHConfig(BaseConnectionConfig):
    """
    SSH 连接配置。

    用于配置 SSH 远程登录和命令执行。
    """

    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    private_key_path: str = ""
    passphrase: str = ""
    timeout: float = 10.0
    allow_agent: bool = False
    look_for_keys: bool = False
    proxy_command: str = ""
    request_pty: bool = True
    term_type: str = "xterm-256color"
    term_width: int = 120
    term_height: int = 40
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 3

    def __post_init__(self):
        """初始化后处理。"""
        from neko_shell.core.connection.base import ConnectionType

        self.connection_type = ConnectionType.SSH

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        data = super().to_dict()
        data.update(
            {
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "private_key_path": self.private_key_path,
                "timeout": self.timeout,
                "allow_agent": self.allow_agent,
                "look_for_keys": self.look_for_keys,
                "proxy_command": self.proxy_command,
                "request_pty": self.request_pty,
                "term_type": self.term_type,
                "term_width": self.term_width,
                "term_height": self.term_height,
                "auto_reconnect": self.auto_reconnect,
                "max_reconnect_attempts": self.max_reconnect_attempts,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SSHConfig":
        """从字典创建。"""
        from neko_shell.core.connection.base import ConnectionType

        converted = dict(data)
        if "connection_type" in converted:
            converted["connection_type"] = ConnectionType(converted["connection_type"])
        return cls(**cls._filter_init_kwargs(converted))


@dataclass
class SFTPConfig(SSHConfig):
    """
    SFTP 连接配置。

    继承 SSH 配置并增加初始路径。
    """

    initial_path: str = "."

    def __post_init__(self):
        """初始化后处理。"""
        from neko_shell.core.connection.base import ConnectionType

        self.connection_type = ConnectionType.SFTP

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        data = super().to_dict()
        data["connection_type"] = "sftp"
        data["initial_path"] = self.initial_path
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SFTPConfig":
        """从字典创建。"""
        from neko_shell.core.connection.base import ConnectionType

        converted = dict(data)
        if "connection_type" in converted:
            converted["connection_type"] = ConnectionType(converted["connection_type"])
        return cls(**cls._filter_init_kwargs(converted))
