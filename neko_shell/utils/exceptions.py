#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义异常模块

定义了 Neko_Shell 中使用的所有自定义异常类。
"""


class NekoShellError(Exception):
    """
    Neko_Shell 基础异常类
    
    所有 Neko_Shell 自定义异常的基类。
    
    Attributes:
        message: 错误消息
        details: 额外的错误详情
    """
    
    def __init__(self, message: str, details: str = None):
        super().__init__(message)
        self.message = message
        self.details = details
    
    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (详情: {self.details})"
        return self.message


# ============ 连接相关异常 ============

class ConnectionError(NekoShellError):
    """
    连接错误
    
    当无法建立或维持连接时抛出。
    
    Examples:
        >>> raise ConnectionError("无法连接到服务器")
        >>> raise ConnectionError("连接被拒绝", details="端口未开放")
    """
    pass


class AuthenticationError(ConnectionError):
    """
    认证错误
    
    当认证失败时抛出。
    
    Examples:
        >>> raise AuthenticationError("用户名或密码错误")
        >>> raise AuthenticationError("私钥认证失败", details="私钥文件不存在")
    """
    pass


class TimeoutError(ConnectionError):
    """
    超时错误
    
    当操作超时时抛出。
    
    Examples:
        >>> raise TimeoutError("连接超时")
        >>> raise TimeoutError("读取超时", details="超过 30 秒未收到响应")
    """
    pass


class ConnectionLostError(ConnectionError):
    """
    连接丢失错误
    
    当已建立的连接意外断开时抛出。
    
    Examples:
        >>> raise ConnectionLostError("连接已断开")
        >>> raise ConnectionLostError("服务器关闭了连接", details="EOF received")
    """
    pass


# ============ 配置相关异常 ============

class ConfigurationError(NekoShellError):
    """
    配置错误
    
    当配置无效或缺失时抛出。
    
    Examples:
        >>> raise ConfigurationError("配置文件不存在")
        >>> raise ConfigurationError("无效的端口号", details="端口必须在 1-65535 范围内")
    """
    pass


class ValidationError(ConfigurationError):
    """
    验证错误
    
    当配置验证失败时抛出。
    
    Examples:
        >>> raise ValidationError("无效的 IP 地址")
        >>> raise ValidationError("密码不能为空")
    """
    pass


# ============ 文件传输相关异常 ============

class FileTransferError(NekoShellError):
    """
    文件传输错误
    
    当文件传输操作失败时抛出。
    
    Examples:
        >>> raise FileTransferError("上传失败")
        >>> raise FileTransferError("下载中断", details="网络连接断开")
    """
    pass


class FileNotFoundError(FileTransferError):
    """
    文件未找到错误
    
    当请求的文件不存在时抛出。
    
    Examples:
        >>> raise FileNotFoundError("远程文件不存在", details="/path/to/file")
    """
    pass


class PermissionDeniedError(FileTransferError):
    """
    权限拒绝错误
    
    当没有足够的权限执行文件操作时抛出。
    
    Examples:
        >>> raise PermissionDeniedError("没有写入权限", details="/path/to/file")
    """
    pass


# ============ 协议相关异常 ============

class ProtocolError(NekoShellError):
    """
    协议错误
    
    当协议通信出现问题时抛出。
    
    Examples:
        >>> raise ProtocolError("无效的协议响应")
        >>> raise ProtocolError("协议版本不兼容", details="服务器版本: 1.0, 客户端版本: 2.0")
    """
    pass


class UnsupportedFeatureError(ProtocolError):
    """
    不支持的功能错误
    
    当服务器不支持请求的功能时抛出。
    
    Examples:
        >>> raise UnsupportedFeatureError("服务器不支持 FTPS")
        >>> raise UnsupportedFeatureError("不支持被动模式", details="服务器仅支持主动模式")
    """
    pass


# ============ 操作相关异常 ============

class OperationError(NekoShellError):
    """
    操作错误
    
    当操作执行失败时抛出。
    
    Examples:
        >>> raise OperationError("命令执行失败")
        >>> raise OperationError("目录创建失败", details="父目录不存在")
    """
    pass


class OperationCancelledError(OperationError):
    """
    操作取消错误
    
    当操作被用户取消时抛出。
    
    Examples:
        >>> raise OperationCancelledError("用户取消了操作")
    """
    pass


class OperationTimeoutError(OperationError):
    """
    操作超时错误
    
    当操作执行超时时抛出。
    
    Examples:
        >>> raise OperationTimeoutError("命令执行超时", details="超过 60 秒")
    """
    pass
