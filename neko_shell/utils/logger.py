#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志工具模块

提供统一的日志配置和管理功能。
"""

import logging
import sys
import re
from pathlib import Path
from typing import Optional
from datetime import datetime


class SensitiveDataFilter(logging.Filter):
    """
    敏感数据过滤器
    
    自动脱敏日志中的敏感信息（密码、密钥等）。
    """
    
    SENSITIVE_PATTERNS = [
        'password',
        'passwd',
        'secret',
        'token',
        'key',
        'credential',
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """过滤日志记录"""
        message = record.getMessage()
        for pattern in self.SENSITIVE_PATTERNS:
            if pattern in message.lower():
                record.msg = self._mask_sensitive(message, pattern)
        return True
    
    def _mask_sensitive(self, message: str, pattern: str) -> str:
        """脱敏处理"""
        return re.sub(
            rf'({pattern}\s*[=:]\s*)[^\s,]+',
            r'\1***MASKED***',
            message,
            flags=re.IGNORECASE
        )


def get_logger(
    name: str,
    level: int = logging.DEBUG,
    log_dir: Optional[Path] = None,
    console: bool = True
) -> logging.Logger:
    """
    获取配置好的日志器
    
    Args:
        name: 日志器名称
        level: 日志级别
        log_dir: 日志文件目录
        console: 是否输出到控制台
        
    Returns:
        logging.Logger: 配置好的日志器
        
    Example:
        >>> logger = get_logger('MyModule')
        >>> logger.info("这是一条日志")
    """
    logger = logging.getLogger(name)
    
    # 避免重复配置
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 添加敏感数据过滤器
    logger.addFilter(SensitiveDataFilter())
    
    # 日志格式
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '%(levelname)s: %(message)s'
    )
    
    # 文件处理器
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    # 控制台处理器
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    return logger


def setup_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.DEBUG,
    console: bool = True
) -> None:
    """
    配置全局日志
    
    Args:
        log_dir: 日志文件目录
        level: 日志级别
        console: 是否输出到控制台
    """
    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 清除现有处理器
    root_logger.handlers.clear()
    
    # 添加敏感数据过滤器
    root_logger.addFilter(SensitiveDataFilter())
    
    # 格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 文件处理器
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # 控制台处理器
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
