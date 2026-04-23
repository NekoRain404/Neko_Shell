#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证器模块

提供各种数据验证功能。
"""

import re
from typing import Optional, Tuple
from pathlib import Path


def validate_host(host: str) -> Tuple[bool, Optional[str]]:
    """
    验证主机地址
    
    Args:
        host: 主机地址（IP 或域名）
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
        
    Example:
        >>> validate_host("192.168.1.1")
        (True, None)
        >>> validate_host("invalid..host")
        (False, "无效的主机地址")
    """
    if not host:
        return False, "主机地址不能为空"
    
    # IP 地址验证
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, host):
        parts = host.split('.')
        if all(0 <= int(part) <= 255 for part in parts):
            return True, None
        return False, "IP 地址范围无效"
    
    # 域名验证
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$'
    if re.match(domain_pattern, host):
        return True, None
    
    # localhost
    if host == 'localhost':
        return True, None
    
    return False, "无效的主机地址"


def validate_port(port: int) -> Tuple[bool, Optional[str]]:
    """
    验证端口号
    
    Args:
        port: 端口号
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    if not isinstance(port, int):
        return False, "端口必须是整数"
    
    if port < 0 or port > 65535:
        return False, "端口范围必须在 0-65535 之间"
    
    return True, None


def validate_timeout(timeout: float) -> Tuple[bool, Optional[str]]:
    """
    验证超时时间
    
    Args:
        timeout: 超时时间（秒）
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    if not isinstance(timeout, (int, float)):
        return False, "超时时间必须是数字"
    
    if timeout <= 0:
        return False, "超时时间必须大于 0"
    
    return True, None


def validate_baud_rate(baud_rate: int) -> Tuple[bool, Optional[str]]:
    """
    验证波特率
    
    Args:
        baud_rate: 波特率
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    valid_rates = [
        110, 300, 600, 1200, 2400, 4800, 9600, 
        14400, 19200, 38400, 57600, 115200, 
        128000, 256000, 460800, 921600
    ]
    
    if baud_rate not in valid_rates:
        return False, f"无效的波特率，常见值: {', '.join(map(str, valid_rates[:8]))}..."
    
    return True, None


def validate_serial_port(port: str) -> Tuple[bool, Optional[str]]:
    """
    验证串口名称
    
    Args:
        port: 串口名称
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    if not port:
        return False, "串口名称不能为空"
    
    # Linux 串口模式
    if port.startswith('/dev/tty'):
        return True, None
    
    # Windows 串口模式
    if re.match(r'^COM\d+$', port, re.IGNORECASE):
        return True, None
    
    # macOS 串口模式
    if port.startswith('/dev/cu.'):
        return True, None
    
    return False, "无效的串口名称格式"


def validate_file_path(path: str, must_exist: bool = False) -> Tuple[bool, Optional[str]]:
    """
    验证文件路径
    
    Args:
        path: 文件路径
        must_exist: 文件是否必须存在
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    if not path:
        return False, "文件路径不能为空"
    
    try:
        p = Path(path)
        
        if must_exist and not p.exists():
            return False, f"文件不存在: {path}"
        
        return True, None
    except Exception as e:
        return False, f"无效的文件路径: {e}"


def validate_key_file(key_path: str) -> Tuple[bool, Optional[str]]:
    """
    验证 SSH 私钥文件
    
    Args:
        key_path: 私钥文件路径
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    valid, error = validate_file_path(key_path, must_exist=True)
    if not valid:
        return valid, error
    
    try:
        path = Path(key_path)
        content = path.read_text()
        
        # 检查是否是有效的私钥格式
        if '-----BEGIN' not in content or 'PRIVATE KEY' not in content:
            return False, "不是有效的私钥文件"
        
        return True, None
    except Exception as e:
        return False, f"读取私钥文件失败: {e}"


def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """
    验证密码强度
    
    Args:
        password: 密码
        
    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    if len(password) < 6:
        return False, "密码长度至少 6 位"
    
    if len(password) > 64:
        return False, "密码长度不能超过 64 位"
    
    return True, None


class Validator:
    """
    验证器类
    
    提供链式调用的验证方法。
    
    Example:
        >>> validator = Validator()
        >>> validator.validate_host("192.168.1.1").validate_port(8080)
        >>> if validator.is_valid():
        ...     print("验证通过")
    """
    
    def __init__(self):
        self._errors: list = []
    
    def is_valid(self) -> bool:
        """检查是否所有验证都通过"""
        return len(self._errors) == 0
    
    def get_errors(self) -> list:
        """获取所有错误"""
        return self._errors
    
    def validate_host(self, host: str) -> 'Validator':
        """验证主机地址"""
        valid, error = validate_host(host)
        if not valid:
            self._errors.append(f"主机地址: {error}")
        return self
    
    def validate_port(self, port: int) -> 'Validator':
        """验证端口"""
        valid, error = validate_port(port)
        if not valid:
            self._errors.append(f"端口: {error}")
        return self
    
    def validate_timeout(self, timeout: float) -> 'Validator':
        """验证超时时间"""
        valid, error = validate_timeout(timeout)
        if not valid:
            self._errors.append(f"超时时间: {error}")
        return self
    
    def clear(self) -> 'Validator':
        """清除所有错误"""
        self._errors.clear()
        return self
