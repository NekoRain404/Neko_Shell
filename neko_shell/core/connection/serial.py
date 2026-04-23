#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
串口连接模块

实现了串口通信连接功能。
"""

import threading
import time
import platform
from typing import Optional, List, Callable, Tuple
from datetime import datetime

from .base import BaseConnection, ConnectionStatus, ConnectionInfo, ConnectionType
from neko_shell.models.connection import (
    SerialConfig,
    SerialParity,
    SerialStopBits,
    SerialByteSize,
    SerialFlowControl,
    SerialPortInfo,
)
from neko_shell.utils.exceptions import (
    ConnectionError,
    ConnectionLostError,
    TimeoutError,
    OperationError,
    OperationCancelledError,
)

# 延迟导入 serial 模块
_serial = None


def _get_serial_module():
    """延迟加载 serial 模块"""
    global _serial
    if _serial is None:
        try:
            import serial
            import serial.tools.list_ports
            _serial = serial
        except ImportError:
            raise ImportError(
                "pyserial 未安装，请运行: pip install pyserial"
            )
    return _serial


# pyserial 常量映射
PARITY_MAP = {
    SerialParity.NONE: 'N',
    SerialParity.EVEN: 'E',
    SerialParity.ODD: 'O',
    SerialParity.MARK: 'M',
    SerialParity.SPACE: 'S',
}

STOPBITS_MAP = {
    SerialStopBits.ONE: 1,
    SerialStopBits.ONE_POINT_FIVE: 1.5,
    SerialStopBits.TWO: 2,
}

BYTESIZE_MAP = {
    SerialByteSize.FIVE: 5,
    SerialByteSize.SIX: 6,
    SerialByteSize.SEVEN: 7,
    SerialByteSize.EIGHT: 8,
}


class SerialConnection(BaseConnection):
    """
    串口连接实现
    
    提供串口通信功能，支持多种波特率、数据位、校验位、停止位配置。
    
    Features:
        - 可配置波特率、数据位、校验位、停止位
        - 支持多种流控制方式
        - 异步数据接收（通过回调）
        - 发送文本/二进制数据
        - 自动检测可用串口
        - RTS/DTR 信号控制
        - 断线检测
    
    Example:
        >>> from neko_shell.core.connection import SerialConnection
        >>> from neko_shell.models.connection import SerialConfig
        >>> 
        >>> # 创建配置
        >>> config = SerialConfig(
        ...     name="调试串口",
        ...     port="/dev/ttyUSB0",
        ...     baud_rate=115200
        ... )
        >>> 
        >>> # 创建连接
        >>> serial = SerialConnection(config)
        >>> serial.connect()
        >>> 
        >>> # 发送数据
        >>> serial.write_line("AT")
        >>> 
        >>> # 设置接收回调
        >>> serial.on('data_received', lambda data: print(data))
        >>> 
        >>> # 断开连接
        >>> serial.disconnect()
    """
    
    def __init__(self, config: SerialConfig):
        """
        初始化串口连接
        
        Args:
            config: 串口配置对象
        """
        super().__init__(config)
        self._serial = None
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        self._receive_buffer = bytearray()
    
    @staticmethod
    def list_available_ports() -> List[SerialPortInfo]:
        """
        列出系统所有可用的串口设备
        
        Returns:
            List[SerialPortInfo]: 串口信息列表
            
        Example:
            >>> ports = SerialConnection.list_available_ports()
            >>> for port in ports:
            ...     print(f"{port.port}: {port.description}")
        """
        serial = _get_serial_module()
        ports = []
        
        for port in serial.tools.list_ports.comports():
            ports.append(SerialPortInfo(
                port=port.device,
                description=port.description,
                hwid=port.hwid,
                vid=port.vid,
                pid=port.pid,
                manufacturer=getattr(port, 'manufacturer', None),
                product=getattr(port, 'product', None),
                serial_number=getattr(port, 'serial_number', None),
            ))
        
        return ports
    
    @staticmethod
    def get_port_names() -> List[str]:
        """
        获取所有可用串口的设备名称
        
        Returns:
            List[str]: 串口名称列表（如 ['/dev/ttyUSB0', '/dev/ttyACM0']）
        """
        return [p.port for p in SerialConnection.list_available_ports()]
    
    @property
    def port(self) -> str:
        """获取当前串口名称"""
        return self._config.port
    
    @property
    def baud_rate(self) -> int:
        """获取当前波特率"""
        return self._config.baud_rate
    
    def connect(self) -> None:
        """
        打开串口连接
        
        Raises:
            ConnectionError: 无法打开串口
            TimeoutError: 连接超时
        """
        self._set_status(ConnectionStatus.CONNECTING)
        self._logger.info(f"正在打开串口: {self._config.port}")
        
        try:
            serial = _get_serial_module()
            
            # 创建串口实例
            self._serial = serial.Serial(
                port=self._config.port,
                baudrate=self._config.baud_rate,
                bytesize=BYTESIZE_MAP[self._config.byte_size],
                parity=PARITY_MAP[self._config.parity],
                stopbits=STOPBITS_MAP[self._config.stop_bits],
                timeout=self._config.timeout,
                write_timeout=self._config.write_timeout,
            )
            
            # 设置流控制
            if self._config.flow_control == SerialFlowControl.XON_XOFF:
                self._serial.xonxoff = True
            elif self._config.flow_control == SerialFlowControl.RTS_CTS:
                self._serial.rtscts = True
            elif self._config.flow_control == SerialFlowControl.DSR_DTR:
                self._serial.dsrdtr = True
            
            # 等待串口就绪
            time.sleep(0.1)
            
            if not self._serial.is_open:
                raise ConnectionError(f"无法打开串口: {self._config.port}")
            
            # 仅在缓冲区中确实有残留数据时才清空，避免无意义副作用
            in_waiting = getattr(self._serial, 'in_waiting', 0)
            out_waiting = getattr(self._serial, 'out_waiting', 0)
            if isinstance(in_waiting, int) and in_waiting > 0:
                self._serial.reset_input_buffer()
            if isinstance(out_waiting, int) and out_waiting > 0:
                self._serial.reset_output_buffer()
            
            self._running = True
            self._start_read_thread()
            
            self._set_status(ConnectionStatus.CONNECTED)
            self._logger.info(
                f"串口已打开: {self._config.port} @ {self._config.baud_rate} baud"
            )
            
        except ConnectionError:
            raise
        except Exception as e:
            self._set_status(ConnectionStatus.ERROR, str(e))
            raise ConnectionError(f"串口连接失败: {e}") from e
    
    def disconnect(self) -> None:
        """
        关闭串口连接
        """
        self._running = False
        
        # 等待读取线程结束
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)
        
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
                self._logger.info(f"串口已关闭: {self._config.port}")
            except Exception as e:
                self._logger.warning(f"关闭串口时出错: {e}")
        
        self._serial = None
        self._set_status(ConnectionStatus.DISCONNECTED)
    
    def is_connected(self) -> bool:
        """
        检查连接状态
        
        Returns:
            bool: True 表示已连接
        """
        return self._serial is not None and self._serial.is_open
    
    def get_info(self) -> ConnectionInfo:
        """
        获取连接信息
        
        Returns:
            ConnectionInfo: 连接信息对象
        """
        return ConnectionInfo(
            id=self._id,
            name=self._config.name,
            connection_type=ConnectionType.SERIAL,
            host=self._config.port,  # 使用 host 字段存储端口名
            status=self._status,
            error_message=self._last_error
        )
    
    # ==================== 数据发送 ====================
    
    def write(self, data: bytes) -> int:
        """
        发送原始字节数据
        
        Args:
            data: 要发送的字节数据
            
        Returns:
            int: 实际发送的字节数
            
        Raises:
            ConnectionError: 串口未连接
            OperationError: 发送失败
        """
        self._check_connection()
        
        try:
            written = self._serial.write(data)
            self._logger.debug(f"发送 {written} 字节: {data!r}")
            return written
        except Exception as e:
            self._logger.error(f"发送数据失败: {e}")
            raise OperationError(f"发送数据失败: {e}") from e
    
    def write_line(
        self, 
        text: str, 
        encoding: Optional[str] = None,
        line_ending: Optional[str] = None
    ) -> int:
        """
        发送一行文本（自动添加行结束符）
        
        Args:
            text: 要发送的文本
            encoding: 字符编码，默认使用配置中的编码
            line_ending: 行结束符，默认使用配置中的行结束符
            
        Returns:
            int: 实际发送的字节数
            
        Example:
            >>> serial.write_line("AT")  # 发送 "AT\\r\\n"
        """
        encoding = encoding or self._config.encoding
        line_ending = line_ending or self._config.line_ending
        
        data = (text + line_ending).encode(encoding)
        return self.write(data)
    
    def write_bytes(self, data: List[int]) -> int:
        """
        发送字节列表
        
        Args:
            data: 字节值列表（0-255）
            
        Returns:
            int: 实际发送的字节数
        """
        return self.write(bytes(data))
    
    # ==================== 数据接收 ====================
    
    def read(self, size: int = -1) -> bytes:
        """
        读取数据
        
        Args:
            size: 要读取的字节数，-1 表示读取所有可用数据
            
        Returns:
            bytes: 读取到的数据
            
        Raises:
            ConnectionError: 串口未连接
            TimeoutError: 读取超时
        """
        self._check_connection()
        
        try:
            if size == -1:
                # 读取所有可用数据
                waiting = self._serial.in_waiting
                if waiting > 0:
                    return self._serial.read(waiting)
                return b''
            else:
                return self._serial.read(size)
        except Exception as e:
            if "timeout" in str(e).lower():
                raise TimeoutError(f"读取超时: {e}") from e
            raise OperationError(f"读取失败: {e}") from e
    
    def read_line(
        self, 
        encoding: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> Optional[str]:
        """
        读取一行文本（阻塞直到收到行结束符或超时）
        
        Args:
            encoding: 字符编码
            timeout: 超时时间（秒）
            
        Returns:
            Optional[str]: 读取到的文本行，超时返回 None
        """
        encoding = encoding or self._config.encoding
        timeout = timeout or self._config.timeout
        
        self._check_connection()
        
        try:
            line = self._serial.readline()
            if line:
                return line.decode(encoding).rstrip()
            return None
        except Exception as e:
            self._logger.error(f"读取行失败: {e}")
            return None
    
    def read_until(
        self, 
        expected: bytes, 
        timeout: Optional[float] = None
    ) -> bytes:
        """
        读取数据直到遇到指定字节序列
        
        Args:
            expected: 期望的字节序列
            timeout: 超时时间（秒）
            
        Returns:
            bytes: 读取到的数据（包含结束符）
            
        Raises:
            TimeoutError: 超时未找到结束符
        """
        timeout = timeout or self._config.timeout
        start_time = time.time()
        buffer = bytearray()
        
        self._check_connection()
        
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"读取超时，未找到结束符: {expected!r}")
            
            if self._serial.in_waiting > 0:
                byte = self._serial.read(1)
                buffer.extend(byte)
                
                if buffer.endswith(expected):
                    return bytes(buffer)
            
            time.sleep(0.001)
    
    @property
    def in_waiting(self) -> int:
        """获取输入缓冲区中的字节数"""
        if self._serial:
            return self._serial.in_waiting
        return 0
    
    @property
    def out_waiting(self) -> int:
        """获取输出缓冲区中的字节数"""
        if self._serial:
            return self._serial.out_waiting
        return 0
    
    def flush_input(self) -> None:
        """清空输入缓冲区"""
        if self._serial:
            self._serial.reset_input_buffer()
            self._logger.debug("输入缓冲区已清空")
    
    def flush_output(self) -> None:
        """清空输出缓冲区"""
        if self._serial:
            self._serial.reset_output_buffer()
            self._logger.debug("输出缓冲区已清空")
    
    def flush(self) -> None:
        """清空所有缓冲区"""
        self.flush_input()
        self.flush_output()
    
    # ==================== 信号控制 ====================
    
    def set_rts(self, state: bool) -> None:
        """
        设置 RTS (Request To Send) 信号
        
        Args:
            state: True 表示高电平，False 表示低电平
        """
        if self._serial:
            self._serial.rts = state
            self._logger.debug(f"RTS 设置为: {state}")
    
    def set_dtr(self, state: bool) -> None:
        """
        设置 DTR (Data Terminal Ready) 信号
        
        Args:
            state: True 表示高电平，False 表示低电平
        """
        if self._serial:
            self._serial.dtr = state
            self._logger.debug(f"DTR 设置为: {state}")
    
    @property
    def rts(self) -> bool:
        """获取 RTS 信号状态"""
        return self._serial.rts if self._serial else False
    
    @property
    def dtr(self) -> bool:
        """获取 DTR 信号状态"""
        return self._serial.dtr if self._serial else False
    
    @property
    def cts(self) -> bool:
        """获取 CTS (Clear To Send) 信号状态"""
        return self._serial.cts if self._serial else False
    
    @property
    def dsr(self) -> bool:
        """获取 DSR (Data Set Ready) 信号状态"""
        return self._serial.dsr if self._serial else False
    
    @property
    def cd(self) -> bool:
        """获取 CD (Carrier Detect) 信号状态"""
        return self._serial.cd if self._serial else False
    
    @property
    def ri(self) -> bool:
        """获取 RI (Ring Indicator) 信号状态"""
        return self._serial.ri if self._serial else False
    
    # ==================== 特殊功能 ====================
    
    def send_break(self, duration: float = 0.25) -> None:
        """
        发送 Break 信号
        
        Args:
            duration: Break 信号持续时间（秒）
        """
        if self._serial:
            self._serial.send_break(duration)
            self._logger.debug(f"发送 Break 信号: {duration}s")
    
    def set_baud_rate(self, baud_rate: int) -> None:
        """
        动态更改波特率
        
        Args:
            baud_rate: 新的波特率
        """
        if self._serial:
            self._serial.baudrate = baud_rate
            self._config.baud_rate = baud_rate
            self._logger.info(f"波特率已更改为: {baud_rate}")
    
    # ==================== 内部方法 ====================
    
    def _check_connection(self) -> None:
        """检查连接状态"""
        if not self.is_connected():
            raise ConnectionLostError("串口连接已断开")
    
    def _start_read_thread(self) -> None:
        """启动读取线程"""
        def read_loop():
            while self._running and self._serial:
                try:
                    if self._serial.in_waiting > 0:
                        data = self._serial.read(self._serial.in_waiting)
                        if data:
                            # 将数据添加到缓冲区
                            self._receive_buffer.extend(data)
                            
                            # 触发数据接收事件
                            self.emit('data_received', data)
                            
                            # 检查是否有完整行
                            self._check_lines()
                    else:
                        time.sleep(0.001)  # 避免忙等待
                        
                except Exception as e:
                    if self._running:
                        self._logger.error(f"读取数据失败: {e}")
                        # 检测连接是否断开
                        if not self.is_connected():
                            self._set_status(ConnectionStatus.DISCONNECTED)
                            self.emit('disconnected')
                            break
        
        self._read_thread = threading.Thread(target=read_loop, daemon=True)
        self._read_thread.start()
    
    def _check_lines(self) -> None:
        """检查缓冲区中是否有完整行"""
        while True:
            # 查找行结束符
            for ending in ['\r\n', '\n', '\r']:
                ending_bytes = ending.encode(self._config.encoding)
                idx = self._receive_buffer.find(ending_bytes)
                if idx != -1:
                    # 提取一行
                    line_bytes = bytes(self._receive_buffer[:idx])
                    del self._receive_buffer[:idx + len(ending_bytes)]
                    
                    try:
                        line = line_bytes.decode(self._config.encoding)
                        self.emit('line_received', line)
                    except Exception as e:
                        self._logger.warning(f"解码行失败: {e}")
                    break
            else:
                break
    
    def __repr__(self) -> str:
        return f"<SerialConnection {self._config.port}@{self._config.baud_rate} status={self._status.value}>"
