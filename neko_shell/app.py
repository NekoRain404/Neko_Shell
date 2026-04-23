#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用程序管理模块

提供 QApplication 的单例管理和全局配置。
"""

from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox
from PySide6.QtCore import QTranslator
from typing import Optional
from pathlib import Path
import sys

from neko_shell.i18n import resolve_language_code
from neko_shell.utils import (
    AppConfig,
    ConfigEncryptor,
    ConfigManager,
    ConfigurationError,
    get_app_translation_file,
    setup_logging,
    get_logger,
    get_default_config_dir,
)
from neko_shell.release import APP_NAME, APP_VERSION
from neko_shell.ui.icons import app_icon
from neko_shell.ui.styles import ThemeManager


class Application(QApplication):
    """
    Neko_Shell 应用程序类

    扩展 QApplication，提供：
    - 配置管理
    - 主题管理
    - 国际化支持
    - 全局状态管理

    Example:
        >>> from neko_shell.app import Application
        >>>
        >>> app = Application.instance()
        >>> app.initialize()
        >>> app.run()
    """

    _instance: Optional["Application"] = None

    def __init__(self, argv: list = None):
        """
        初始化应用程序

        Args:
            argv: 命令行参数
        """
        super().__init__(argv or sys.argv)

        # 设置单例
        Application._instance = self

        # 属性
        self._config_manager: Optional[ConfigManager] = None
        self._translator: Optional[QTranslator] = None
        self._logger = get_logger("Application")
        self._config_master_password: Optional[str] = None
        self._reencrypt_config_on_exit = False
        self.aboutToQuit.connect(self._restore_config_encryption)

        # 应用信息
        self.setApplicationName(APP_NAME)
        self.setApplicationVersion(APP_VERSION)
        self.setOrganizationName(APP_NAME)
        self.setWindowIcon(app_icon())

    @classmethod
    def instance(cls) -> "Application":
        """获取应用程序单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self, config_dir: Optional[Path] = None) -> None:
        """
        初始化应用程序

        Args:
            config_dir: 配置目录路径
        """
        # 设置配置目录
        if config_dir is None:
            config_dir = get_default_config_dir()

        self._config_manager = ConfigManager(config_dir)

        # 设置日志
        log_dir = config_dir / "logs"
        setup_logging(log_dir=log_dir)
        self._logger.info("应用程序初始化开始")

        self._unlock_encrypted_config_files_if_needed()

        # 加载配置
        app_config = self._config_manager.app_config

        # 应用主题
        ThemeManager.apply_theme(self, app_config.theme)

        # 设置语言
        self._setup_language(app_config.language)

        self._logger.info("应用程序初始化完成")

    def _setup_language(self, language: str) -> None:
        """
        设置界面语言

        Args:
            language: 语言代码 (如 'zh_CN', 'en')
        """
        if self._translator is not None:
            self.removeTranslator(self._translator)

        self._translator = QTranslator(self)
        requested_language = str(language or "zh_CN").strip() or "zh_CN"
        effective_language = resolve_language_code(requested_language)

        if effective_language != requested_language:
            self._logger.info(
                "界面语言 %s 当前不可用，已回退到 %s",
                requested_language,
                effective_language,
            )

        translation_file = get_app_translation_file(effective_language)

        if translation_file.exists():
            if self._translator.load(str(translation_file)):
                self.installTranslator(self._translator)
                self._logger.info("加载界面语言包: %s", effective_language)
                return

            self._logger.warning("界面语言包加载失败: %s", translation_file)
            return

        if effective_language == "zh_CN":
            self._logger.info("使用内置中文源字符串，无需额外语言包")
        else:
            self._logger.info(
                "未找到界面语言包 %s，保留源字符串: %s",
                effective_language,
                translation_file,
            )

    def _encrypted_config_paths(self) -> list[Path]:
        """返回当前已加密的配置文件列表。"""
        if self._config_manager is None:
            return []
        return [
            path
            for path in self._config_manager.config_file_paths()
            if ConfigEncryptor.is_encrypted_file(path)
        ]

    def _unlock_encrypted_config_files_if_needed(self) -> None:
        """启动时检测并解锁加密配置。"""
        if self._config_manager is None:
            return

        encrypted_paths = self._encrypted_config_paths()
        if not encrypted_paths:
            return

        path_names = ", ".join(path.name for path in encrypted_paths)
        while True:
            password, accepted = QInputDialog.getText(
                None,
                self.tr("解锁配置"),
                self.tr(f"检测到已加密配置文件: {path_names}\n请输入主密码以继续启动:"),
                QLineEdit.Password,
            )
            if not accepted:
                raise ConfigurationError("已取消解锁加密配置")
            if not password:
                QMessageBox.warning(None, self.tr("错误"), self.tr("主密码不能为空"))
                continue
            try:
                self._config_manager.decrypt_config_files(password)
            except Exception as exc:
                self._logger.warning("解锁加密配置失败: %s", exc)
                QMessageBox.warning(None, self.tr("解锁失败"), str(exc))
                continue

            self._config_master_password = password
            self._reencrypt_config_on_exit = True
            self._logger.info("已解锁加密配置文件，将在退出时恢复加密")
            return

    @property
    def master_password_enabled(self) -> bool:
        """当前会话是否启用了主密码保护。"""
        return self._reencrypt_config_on_exit and bool(self._config_master_password)

    def enable_master_password(self, password: str) -> None:
        """启用主密码保护，并在退出时自动重新加密配置。"""
        if not password:
            raise ConfigurationError("主密码不能为空")
        if self._config_manager is None:
            raise RuntimeError("应用程序未初始化，请先调用 initialize()")
        self._config_master_password = password
        self._reencrypt_config_on_exit = True
        self._logger.info("主密码保护已启用，应用退出时将自动加密配置")

    def disable_master_password(self, password: Optional[str] = None) -> None:
        """关闭主密码保护，退出时不再自动加密配置。"""
        if (
            self._config_master_password
            and password is not None
            and password != self._config_master_password
        ):
            raise ConfigurationError("主密码不正确")
        self._config_master_password = None
        self._reencrypt_config_on_exit = False
        self._logger.info("主密码保护已关闭")

    def _restore_config_encryption(self) -> None:
        """应用退出时恢复配置文件加密。"""
        if (
            not self._reencrypt_config_on_exit
            or not self._config_master_password
            or self._config_manager is None
        ):
            return
        try:
            encrypted_paths = self._config_manager.encrypt_config_files(
                self._config_master_password
            )
            self._logger.info("已恢复配置文件加密: %s", len(encrypted_paths))
        except Exception as exc:
            self._logger.error("恢复配置文件加密失败: %s", exc)

    @property
    def config_manager(self) -> ConfigManager:
        """获取配置管理器"""
        if self._config_manager is None:
            raise RuntimeError("应用程序未初始化，请先调用 initialize()")
        return self._config_manager

    @property
    def app_config(self) -> AppConfig:
        """获取应用配置"""
        return self.config_manager.app_config

    def run(self) -> int:
        """
        运行应用程序

        Returns:
            int: 退出代码
        """
        self._logger.info("应用程序启动")
        return self.exec()

    def quit(self) -> None:
        """退出应用程序"""
        self._logger.info("应用程序退出")
        super().quit()


def get_app() -> Application:
    """
    获取应用程序实例

    Returns:
        Application: 应用程序实例
    """
    return Application.instance()
