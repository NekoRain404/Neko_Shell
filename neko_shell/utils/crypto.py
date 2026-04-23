#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
加密工具模块

提供密码安全存储和加密功能。
"""

import os
import base64
import hashlib
from typing import Optional
from pathlib import Path

from neko_shell.utils import get_logger

logger = get_logger("crypto")

# 尝试导入可选依赖
try:
    import keyring

    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False
    logger.warning("keyring 未安装，密码存储功能受限")

try:
    from cryptography.fernet import Fernet
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    logger.warning("cryptography 未安装，加密功能受限")


class SecureStorage:
    """
    安全存储管理器

    提供密码的安全存储和检索功能。

    Example:
        >>> storage = SecureStorage()
        >>> storage.store_password("conn_001", "secret123")
        >>> password = storage.retrieve_password("conn_001")
        >>> storage.delete_password("conn_001")
    """

    SERVICE_NAME = "Neko_Shell"

    @classmethod
    def store_password(cls, connection_id: str, password: str) -> bool:
        """
        安全存储密码

        Args:
            connection_id: 连接标识符
            password: 密码

        Returns:
            bool: 是否成功
        """
        if not HAS_KEYRING:
            logger.warning("keyring 不可用，无法安全存储密码")
            return False

        try:
            keyring.set_password(cls.SERVICE_NAME, connection_id, password)
            logger.debug(f"密码已存储: {connection_id}")
            return True
        except Exception as e:
            logger.error(f"存储密码失败: {e}")
            return False

    @classmethod
    def retrieve_password(cls, connection_id: str) -> Optional[str]:
        """
        检索存储的密码

        Args:
            connection_id: 连接标识符

        Returns:
            Optional[str]: 密码，如果不存在返回 None
        """
        if not HAS_KEYRING:
            return None

        try:
            return keyring.get_password(cls.SERVICE_NAME, connection_id)
        except Exception as e:
            logger.error(f"检索密码失败: {e}")
            return None

    @classmethod
    def delete_password(cls, connection_id: str) -> bool:
        """
        删除存储的密码

        Args:
            connection_id: 连接标识符

        Returns:
            bool: 是否成功
        """
        if not HAS_KEYRING:
            return False

        try:
            keyring.delete_password(cls.SERVICE_NAME, connection_id)
            logger.debug(f"密码已删除: {connection_id}")
            return True
        except Exception as e:
            logger.error(f"删除密码失败: {e}")
            return False


class ConfigEncryptor:
    """
    配置文件加密器

    使用密码加密配置文件。

    Example:
        >>> encryptor = ConfigEncryptor("my_master_password")
        >>> encryptor.encrypt_file(config_path)
        >>> encryptor.decrypt_file(config_path)
    """

    MAGIC = b"NEKO_SHELL_ENC_V1\n"
    SALT_SIZE = 16
    PBKDF2_ITERATIONS = 390_000

    def __init__(self, password: str, salt: Optional[bytes] = None):
        """
        初始化加密器

        Args:
            password: 主密码
            salt: 可选盐值。未传入时为每次加密生成随机盐。
        """
        if not HAS_CRYPTOGRAPHY:
            raise RuntimeError("cryptography 库未安装")

        self._password = password
        self._salt = salt or os.urandom(self.SALT_SIZE)
        self._key = self._derive_key(password, self._salt)
        self._fernet = Fernet(self._key)
        self._legacy_fernet = Fernet(self._derive_key(password))

    @staticmethod
    def _derive_key(password: str, salt: Optional[bytes] = None) -> bytes:
        """从密码派生加密密钥"""
        if salt is None:
            key = hashlib.sha256(password.encode()).digest()
        else:
            key = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode(),
                salt,
                ConfigEncryptor.PBKDF2_ITERATIONS,
            )
        return base64.urlsafe_b64encode(key)

    @classmethod
    def is_encrypted_data(cls, data: bytes) -> bool:
        """判断字节数据是否为新版加密格式。"""
        return data.startswith(cls.MAGIC)

    @classmethod
    def is_encrypted_file(cls, file_path: Path) -> bool:
        """判断文件是否为新版加密格式。"""
        if not file_path.exists() or not file_path.is_file():
            return False
        with open(file_path, "rb") as f:
            return f.read(len(cls.MAGIC)) == cls.MAGIC

    def encrypt_data(self, data: bytes) -> bytes:
        """
        加密数据

        Args:
            data: 原始数据

        Returns:
            bytes: 加密后的数据
        """
        encrypted = self._fernet.encrypt(data)
        return self.MAGIC + self._salt + encrypted

    def decrypt_data(self, data: bytes) -> bytes:
        """
        解密数据

        Args:
            data: 加密数据

        Returns:
            bytes: 解密后的数据
        """
        if self.is_encrypted_data(data):
            offset = len(self.MAGIC)
            salt = data[offset : offset + self.SALT_SIZE]
            payload = data[offset + self.SALT_SIZE :]
            fernet = Fernet(self._derive_key(self._password, salt))
            return fernet.decrypt(payload)

        # 兼容旧版无头部、无 salt 的 Fernet 数据。
        return self._legacy_fernet.decrypt(data)

    def encrypt_file(self, file_path: Path) -> None:
        """
        加密文件

        Args:
            file_path: 文件路径
        """
        with open(file_path, "rb") as f:
            data = f.read()

        if self.is_encrypted_data(data):
            logger.debug(f"文件已加密，跳过: {file_path}")
            return

        encrypted = self.encrypt_data(data)

        with open(file_path, "wb") as f:
            f.write(encrypted)

        logger.info(f"文件已加密: {file_path}")

    def decrypt_file(self, file_path: Path) -> None:
        """
        解密文件

        Args:
            file_path: 文件路径
        """
        with open(file_path, "rb") as f:
            data = f.read()

        if not data:
            return

        if not self.is_encrypted_data(data):
            logger.debug(f"文件未加密，跳过: {file_path}")
            return

        decrypted = self.decrypt_data(data)

        with open(file_path, "wb") as f:
            f.write(decrypted)

        logger.info(f"文件已解密: {file_path}")


class PackageSigner:
    """共享包签名工具。"""

    SIGNATURE_ALGORITHM = "ed25519"

    @staticmethod
    def _require_crypto() -> None:
        if not HAS_CRYPTOGRAPHY:
            raise RuntimeError("cryptography 库未安装")

    @classmethod
    def generate_private_key_pem(cls) -> str:
        """生成 PEM 编码的 Ed25519 私钥。"""
        cls._require_crypto()
        private_key = Ed25519PrivateKey.generate()
        return private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

    @classmethod
    def public_key_from_private_key_pem(cls, private_key_pem: str) -> str:
        """根据私钥生成 Base64 编码的公钥。"""
        cls._require_crypto()
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None,
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("共享包签名私钥类型无效")
        public_key = private_key.public_key()
        return base64.b64encode(
            public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")

    @staticmethod
    def fingerprint_from_public_key(public_key_b64: str) -> str:
        """根据公钥生成稳定指纹。"""
        public_key_raw = base64.b64decode(public_key_b64.encode("ascii"))
        return hashlib.sha256(public_key_raw).hexdigest()

    @classmethod
    def sign_text(cls, private_key_pem: str, text: str) -> str:
        """对文本进行签名并返回 Base64 编码。"""
        cls._require_crypto()
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None,
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("共享包签名私钥类型无效")
        signature = private_key.sign(text.encode("utf-8"))
        return base64.b64encode(signature).decode("ascii")

    @classmethod
    def verify_text(cls, public_key_b64: str, text: str, signature_b64: str) -> bool:
        """验证文本签名。"""
        cls._require_crypto()
        public_key_raw = base64.b64decode(public_key_b64.encode("ascii"))
        signature = base64.b64decode(signature_b64.encode("ascii"))
        public_key = Ed25519PublicKey.from_public_bytes(public_key_raw)
        try:
            public_key.verify(signature, text.encode("utf-8"))
        except InvalidSignature:
            return False
        return True


def generate_random_password(length: int = 16) -> str:
    """
    生成随机密码

    Args:
        length: 密码长度

    Returns:
        str: 随机密码
    """
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_password(password: str, salt: Optional[bytes] = None) -> tuple:
    """
    哈希密码

    Args:
        password: 密码
        salt: 盐值，如果为 None 则生成新盐值

    Returns:
        tuple: (哈希值, 盐值)
    """
    if salt is None:
        salt = os.urandom(32)

    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)

    return key, salt


def verify_password(password: str, key: bytes, salt: bytes) -> bool:
    """
    验证密码

    Args:
        password: 密码
        key: 存储的哈希值
        salt: 盐值

    Returns:
        bool: 是否匹配
    """
    new_key, _ = hash_password(password, salt)
    return new_key == key
