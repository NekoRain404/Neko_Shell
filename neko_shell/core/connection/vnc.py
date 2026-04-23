#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VNC 连接模块

实现了 VNC 远程桌面连接功能。

基于 RFB (Remote Framebuffer) 协议实现。
"""

import socket
import struct
import threading
import time
from typing import Optional, Tuple, Callable

from .base import BaseConnection, ConnectionStatus, ConnectionInfo, ConnectionType
from neko_shell.models.connection import VNCConfig
from neko_shell.utils.exceptions import (
    ConnectionError,
    ConnectionLostError,
    TimeoutError,
    AuthenticationError,
)


class VNCConnection(BaseConnection):
    """
    VNC 连接实现
    
    提供 VNC 远程桌面连接功能，基于 RFB 协议。
    
    Features:
        - RFB 协议握手
        - VNC 密码认证
        - 帧缓冲更新
        - 键盘/鼠标事件发送
        - 剪贴板支持
        - 多种编码支持
    
    Example:
        >>> from neko_shell.core.connection import VNCConnection
        >>> from neko_shell.models.connection import VNCConfig
        >>> 
        >>> config = VNCConfig(
        ...     name="远程桌面",
        ...     host="192.168.1.100",
        ...     port=5900,
        ...     password="secret"
        ... )
        >>> 
        >>> conn = VNCConnection(config)
        >>> conn.connect()
        >>> 
        >>> # 发送键盘事件
        >>> conn.send_key_event(ord('A'), pressed=True)
        >>> 
        >>> # 发送鼠标事件
        >>> conn.send_pointer_event(100, 100, button_mask=1)
        >>> 
        >>> conn.disconnect()
    """
    
    # RFB 协议版本
    RFB_VERSION = "RFB 003.008"
    
    # 服务器消息类型
    MSG_FRAMEBUFFER_UPDATE = 0
    MSG_SET_COLOR_MAP = 1
    MSG_BELL = 2
    MSG_SERVER_CUT_TEXT = 3
    
    # 客户端消息类型
    MSG_SET_PIXEL_FORMAT = 0
    MSG_SET_ENCODINGS = 2
    MSG_FRAMEBUFFER_UPDATE_REQUEST = 3
    MSG_KEY_EVENT = 4
    MSG_POINTER_EVENT = 5
    MSG_CLIENT_CUT_TEXT = 6
    
    def __init__(self, config: VNCConfig):
        """初始化 VNC 连接"""
        super().__init__(config)
        self._socket: Optional[socket.socket] = None
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        
        # VNC 协议相关
        self._protocol_version: str = ""
        self._framebuffer_width: int = 0
        self._framebuffer_height: int = 0
        self._framebuffer_name: str = ""
        self._pixel_format: dict = {}
        
        # 回调
        self._frame_callback: Optional[Callable] = None
    
    @property
    def host(self) -> str:
        """获取主机地址"""
        return self._config.host
    
    @property
    def port(self) -> int:
        """获取端口号"""
        return self._config.port
    
    @property
    def framebuffer_size(self) -> Tuple[int, int]:
        """获取帧缓冲尺寸"""
        return (self._framebuffer_width, self._framebuffer_height)
    
    @property
    def desktop_name(self) -> str:
        """获取桌面名称"""
        return self._framebuffer_name
    
    def connect(self) -> None:
        """建立 VNC 连接"""
        self._set_status(ConnectionStatus.CONNECTING)
        self._logger.info(f"正在连接 VNC: {self._config.host}:{self._config.port}")
        
        try:
            # 1. 建立 TCP 连接
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self._config.timeout)
            self._socket.connect((self._config.host, self._config.port))
            
            # 2. 协议握手
            self._handshake()
            
            # 3. 安全认证
            self._authenticate()
            
            # 4. 客户端初始化
            self._client_init()
            
            # 5. 获取服务器信息
            self._get_server_info()
            
            # 6. 设置编码
            self._set_encodings()
            
            self._running = True
            self._start_read_thread()
            
            self._set_status(ConnectionStatus.CONNECTED)
            self._logger.info(
                f"VNC 连接成功: {self._framebuffer_name} "
                f"({self._framebuffer_width}x{self._framebuffer_height})"
            )
            
        except socket.timeout as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise TimeoutError(f"VNC 连接超时: {e}") from e
        except AuthenticationError:
            raise
        except Exception as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"VNC 连接失败: {e}") from e
    
    def disconnect(self) -> None:
        """断开 VNC 连接"""
        self._running = False
        
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)
        
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        
        self._set_status(ConnectionStatus.DISCONNECTED)
        self._logger.info("VNC 连接已断开")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self._socket is not None and self._status == ConnectionStatus.CONNECTED
    
    def get_info(self) -> ConnectionInfo:
        """获取连接信息"""
        return ConnectionInfo(
            id=self._id,
            name=self._config.name,
            connection_type=ConnectionType.VNC,
            host=self._config.host,
            port=self._config.port,
            status=self._status,
            error_message=self._last_error
        )
    
    # ==================== 协议握手 ====================
    
    def _handshake(self) -> None:
        """RFB 协议握手"""
        # 接收服务器版本 (12 字节)
        version_data = self._recv_exact(12)
        server_version = version_data.decode('ascii').strip()
        
        if not server_version.startswith('RFB '):
            raise ConnectionError(f"无效的 VNC 服务器响应: {server_version}")
        
        self._protocol_version = server_version
        self._logger.debug(f"服务器版本: {server_version}")
        
        # 发送客户端版本 (RFB 003.008)
        self._socket.send((self.RFB_VERSION + "\n").encode('ascii'))
        self._logger.debug(f"客户端版本: {self.RFB_VERSION}")
    
    def _authenticate(self) -> None:
        """安全认证"""
        # 接收安全类型数量
        num_types = struct.unpack('!B', self._recv_exact(1))[0]
        
        if num_types == 0:
            # 连接失败，读取错误信息
            reason_len = struct.unpack('!I', self._recv_exact(4))[0]
            reason = self._recv_exact(reason_len).decode('utf-8')
            raise ConnectionError(f"VNC 服务器拒绝连接: {reason}")
        
        # 接收安全类型列表
        security_types = list(struct.unpack(f'!{num_types}B', self._recv_exact(num_types)))
        self._logger.debug(f"支持的安全类型: {security_types}")
        
        # 选择安全类型
        if self._config.password and 2 in security_types:
            # VNC 认证 (type 2)
            self._socket.send(struct.pack('!B', 2))
            self._vnc_auth()
        elif 1 in security_types:
            # 无认证 (type 1)
            self._socket.send(struct.pack('!B', 1))
            self._logger.info("VNC 无认证连接")
        else:
            raise AuthenticationError("VNC 服务器不支持可用的认证方式")
        
        # 接收安全结果
        result = struct.unpack('!I', self._recv_exact(4))[0]
        if result != 0:
            raise AuthenticationError("VNC 认证失败")
    
    def _vnc_auth(self) -> None:
        """VNC 密码认证 (DES 加密)"""
        # 接收 16 字节随机挑战
        challenge = self._recv_exact(16)
        
        # 使用密码加密挑战
        key = self._password_to_key(self._config.password)
        response = self._des_encrypt(challenge, key)
        
        # 发送响应
        self._socket.send(response)
        self._logger.debug("VNC 认证响应已发送")
    
    @staticmethod
    def _password_to_key(password: str) -> bytes:
        """将 VNC 密码转换为 DES 密钥"""
        key = password.encode('latin-1')[:8].ljust(8, b'\x00')
        # 反转每个字节的位
        return bytes([int('{:08b}'.format(b)[::-1], 2) for b in key])
    
    @staticmethod
    def _des_encrypt(data: bytes, key: bytes) -> bytes:
        """DES 加密 (VNC 使用 ECB 模式)"""
        des_module = None
        try:
            from Crypto.Cipher import DES as _DES  # type: ignore
            des_module = _DES
        except Exception:
            try:
                # 支持 pycryptodomex 的命名空间
                from Cryptodome.Cipher import DES as _DES  # type: ignore
                des_module = _DES
            except Exception:
                des_module = None

        if des_module is not None:
            cipher = des_module.new(key, des_module.MODE_ECB)
            return cipher.encrypt(data)

        try:
            import pyDes  # type: ignore
        except Exception as exc:
            raise AuthenticationError(
                "VNC 密码认证需要 DES 加密库。请安装 Neko_Shell[vnc] (pycryptodome) 或安装 pyDes。"
            ) from exc

        cipher = pyDes.des(key, pyDes.ECB)
        return cipher.encrypt(data)
    
    def _client_init(self) -> None:
        """客户端初始化"""
        # 发送共享标志 (1 字节)
        shared = 1 if self._config.shared else 0
        self._socket.send(struct.pack('!B', shared))
        self._logger.debug(f"共享模式: {self._config.shared}")
    
    def _get_server_info(self) -> None:
        """获取服务器信息"""
        # 接收帧缓冲信息 (24 字节固定部分)
        data = self._recv_exact(24)
        
        (
            width, height, 
            bpp, depth, big_endian, true_color,
            red_max, green_max, blue_max,
            red_shift, green_shift, blue_shift
        ) = struct.unpack('!HHBBBBHHHBBBxxx', data)
        
        self._framebuffer_width = width
        self._framebuffer_height = height
        
        self._pixel_format = {
            'bits_per_pixel': bpp,
            'depth': depth,
            'big_endian': big_endian,
            'true_color': true_color,
            'red_max': red_max,
            'green_max': green_max,
            'blue_max': blue_max,
            'red_shift': red_shift,
            'green_shift': green_shift,
            'blue_shift': blue_shift,
        }
        
        # 接收桌面名称
        name_len = struct.unpack('!I', self._recv_exact(4))[0]
        self._framebuffer_name = self._recv_exact(name_len).decode('utf-8')
        
        self._logger.info(f"VNC 桌面: {self._framebuffer_name} ({width}x{height})")
    
    # ==================== 编码设置 ====================
    
    def _set_encodings(self) -> None:
        """设置支持的编码"""
        # 编码类型
        encoding_map = {
            'raw': 0,
            'copyrect': 0,
            'rre': 2,
            'hextile': 5,
            'zrle': 16,
            'tight': 7,
            'zlib': 6,
        }
        
        encodings = []
        for enc_name in self._config.encoding:
            if enc_name in encoding_map:
                encodings.append(encoding_map[enc_name])
        
        if not encodings:
            encodings = [0]  # 至少支持 Raw
        
        # 发送编码设置消息
        msg = struct.pack(
            '!BBH',
            self.MSG_SET_ENCODINGS,
            0,  # padding
            len(encodings)
        )
        msg += struct.pack(f'!{len(encodings)}i', *encodings)
        self._socket.send(msg)
        self._logger.debug(f"设置编码: {encodings}")
    
    # ==================== 输入事件 ====================
    
    def send_key_event(self, key: int, pressed: bool = True) -> None:
        """
        发送键盘事件
        
        Args:
            key: 键码 (X11 keysym)
            pressed: True 表示按下，False 表示释放
        """
        self._check_connection()
        
        msg = struct.pack(
            '!BBHI',
            self.MSG_KEY_EVENT,
            1 if pressed else 0,
            0,  # padding
            key
        )
        self._socket.send(msg)
        self._logger.debug(f"键盘事件: key={key}, pressed={pressed}")
    
    def send_pointer_event(
        self, 
        x: int, 
        y: int, 
        button_mask: int = 0
    ) -> None:
        """
        发送鼠标事件
        
        Args:
            x: X 坐标
            y: Y 坐标
            button_mask: 按钮掩码
                - bit 0: 左键
                - bit 1: 中键
                - bit 2: 右键
                - bit 3: 滚轮上
                - bit 4: 滚轮下
        """
        self._check_connection()
        
        msg = struct.pack(
            '!BBHH',
            self.MSG_POINTER_EVENT,
            button_mask,
            x,
            y
        )
        self._socket.send(msg)
        self._logger.debug(f"鼠标事件: x={x}, y={y}, buttons={button_mask}")
    
    def send_text(self, text: str) -> None:
        """
        发送文本（模拟键盘输入）
        
        Args:
            text: 要输入的文本
        """
        for char in text:
            keysym = ord(char)
            self.send_key_event(keysym, pressed=True)
            time.sleep(0.01)
            self.send_key_event(keysym, pressed=False)
            time.sleep(0.01)
    
    def send_clipboard(self, text: str) -> None:
        """
        发送剪贴板文本
        
        Args:
            text: 剪贴板文本
        """
        self._check_connection()
        
        text_bytes = text.encode('utf-8')
        msg = struct.pack(
            '!BBI',
            self.MSG_CLIENT_CUT_TEXT,
            0,  # padding
            len(text_bytes)
        )
        msg += text_bytes
        self._socket.send(msg)
    
    # ==================== 帧缓冲 ====================
    
    def request_frame_update(self, incremental: bool = True) -> None:
        """
        请求帧缓冲更新
        
        Args:
            incremental: 是否增量更新
        """
        self._check_connection()
        
        msg = struct.pack(
            '!BBHHHH',
            self.MSG_FRAMEBUFFER_UPDATE_REQUEST,
            1 if incremental else 0,
            0, 0,  # x, y
            self._framebuffer_width,
            self._framebuffer_height
        )
        self._socket.send(msg)
    
    def set_frame_callback(self, callback: Callable[[int, int, int, int, bytes], None]) -> None:
        """
        设置帧更新回调
        
        Args:
            callback: 回调函数 (x, y, width, height, pixel_data)
        """
        self._frame_callback = callback
    
    # ==================== 内部方法 ====================
    
    def _check_connection(self) -> None:
        """检查连接状态"""
        if not self.is_connected():
            raise ConnectionLostError("VNC 连接已断开")
    
    def _recv_exact(self, size: int) -> bytes:
        """精确接收指定字节数"""
        data = bytearray()
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise ConnectionLostError("VNC 连接已断开")
            data.extend(chunk)
        return bytes(data)
    
    def _start_read_thread(self) -> None:
        """启动读取线程"""
        def read_loop():
            while self._running and self._socket:
                try:
                    # 读取消息类型
                    msg_type = self._recv_exact(1)
                    if not msg_type:
                        break
                    
                    self._handle_server_message(msg_type[0])
                    
                except ConnectionLostError:
                    if self._running:
                        self._set_status(ConnectionStatus.DISCONNECTED)
                        self.emit('disconnected')
                    break
                except Exception as e:
                    if self._running:
                        self._logger.error(f"VNC 读取错误: {e}")
        
        self._read_thread = threading.Thread(target=read_loop, daemon=True)
        self._read_thread.start()
    
    def _handle_server_message(self, msg_type: int) -> None:
        """处理服务器消息"""
        if msg_type == self.MSG_FRAMEBUFFER_UPDATE:
            self._handle_framebuffer_update()
        elif msg_type == self.MSG_SET_COLOR_MAP:
            self._handle_color_map()
        elif msg_type == self.MSG_BELL:
            self.emit('bell')
        elif msg_type == self.MSG_SERVER_CUT_TEXT:
            self._handle_clipboard()
        else:
            self._logger.warning(f"未知消息类型: {msg_type}")
    
    def _handle_framebuffer_update(self) -> None:
        """处理帧缓冲更新"""
        # 读取消息头
        self._recv_exact(1)  # padding
        num_rects = struct.unpack('!H', self._recv_exact(2))[0]
        
        for _ in range(num_rects):
            # 读取矩形信息
            x, y, w, h, encoding = struct.unpack('!HHHHi', self._recv_exact(12))
            
            # 根据 encoding 处理像素数据
            if encoding == 0:  # Raw
                bytes_per_pixel = self._pixel_format.get('bits_per_pixel', 24) // 8
                pixel_data = self._recv_exact(w * h * bytes_per_pixel)
                
                if self._frame_callback:
                    self._frame_callback(x, y, w, h, pixel_data)
                
                self.emit('frame_update', x, y, w, h, pixel_data)
            else:
                self._logger.debug(f"忽略编码类型: {encoding}")
    
    def _handle_color_map(self) -> None:
        """处理颜色映射"""
        # 读取并忽略颜色映射
        self._recv_exact(1)  # padding
        first_color, num_colors = struct.unpack('!HH', self._recv_exact(4))
        
        for _ in range(num_colors):
            self._recv_exact(6)  # RGB 值
    
    def _handle_clipboard(self) -> None:
        """处理剪贴板数据"""
        self._recv_exact(3)  # padding
        length = struct.unpack('!I', self._recv_exact(4))[0]
        text = self._recv_exact(length).decode('utf-8')
        
        self.emit('clipboard', text)
    
    def __repr__(self) -> str:
        return f"<VNCConnection {self._config.host}:{self._config.port} status={self._status.value}>"
