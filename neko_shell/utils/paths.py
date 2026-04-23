#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路径工具模块

提供跨平台的配置目录和资源路径解析。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths

APP_DIR_NAME = "Neko_Shell"


def get_default_config_dir() -> Path:
    """
    获取默认配置目录。

    - Linux: ~/.config/Neko_Shell
    - macOS: ~/Library/Application Support/Neko_Shell
    - Windows: %APPDATA%/Neko_Shell
    """
    base_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if base_dir:
        base_path = Path(base_dir)
        if base_path.name.lower() == APP_DIR_NAME.lower():
            return base_path
        return base_path / APP_DIR_NAME

    return Path.home() / ".config" / APP_DIR_NAME


def get_runtime_root() -> Path:
    """获取当前运行时根目录。

    - 源码运行时返回仓库根目录
    - PyInstaller 冻结运行时返回 bundle 根目录
    """
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            return Path(bundle_root)
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parents[2]


def get_repo_root() -> Path:
    """获取仓库或 bundle 根目录。"""
    return get_runtime_root()


def get_linux_commands_json_path() -> Path:
    """获取 Linux 命令索引文件路径。"""
    return get_runtime_root() / "conf" / "linux_commands.json"


def get_app_translations_dir() -> Path:
    """获取应用语言资源目录。"""
    return get_runtime_root() / "neko_shell" / "i18n" / "translations"


def get_app_translation_file(language: str) -> Path:
    """获取指定语言对应的 Qt 语言包路径。"""
    normalized_language = str(language or "zh_CN").strip() or "zh_CN"
    return get_app_translations_dir() / f"neko_shell_{normalized_language}.qm"
