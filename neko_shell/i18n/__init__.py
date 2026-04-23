#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国际化模块

提供多语言支持。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional

__all__ = [
    "tr",
    "get_available_languages",
    "get_available_language_options",
    "get_language_display_name",
    "get_language_resource_files",
    "get_qt_translations_dir",
    "get_translations_dir",
    "normalize_language_code",
    "resolve_language_code",
]


BUILTIN_LANGUAGE = "zh_CN"
_LANGUAGE_DISPLAY_NAMES = {
    "zh_CN": "简体中文",
    "en": "English",
}


# 翻译缓存
_translations: Dict[str, Dict[str, str]] = {}

# 当前语言
_current_language: str = BUILTIN_LANGUAGE


def normalize_language_code(language: Optional[str]) -> str:
    """规整语言代码。"""
    normalized = str(language or BUILTIN_LANGUAGE).strip()
    return normalized or BUILTIN_LANGUAGE


def get_translations_dir() -> Path:
    """获取翻译文件目录"""
    return Path(__file__).parent / "translations"


def get_qt_translations_dir() -> Path:
    """获取 Qt 语言包目录。"""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            runtime_root = Path(bundle_root)
        else:
            runtime_root = Path(sys.executable).resolve().parent
    else:
        runtime_root = Path(__file__).resolve().parents[2]
    return runtime_root / "neko_shell" / "i18n" / "translations"


def get_language_resource_files(language: Optional[str]) -> list[Path]:
    """返回指定语言存在的资源文件。"""
    normalized = normalize_language_code(language)
    resource_files: list[Path] = []

    json_file = get_translations_dir() / f"{normalized}.json"
    if json_file.exists():
        resource_files.append(json_file)

    qt_file = get_qt_translations_dir() / f"neko_shell_{normalized}.qm"
    if qt_file.exists():
        resource_files.append(qt_file)

    return resource_files


def get_available_languages() -> list[str]:
    """按当前运行时真实资源返回可用语言列表。"""
    available_languages = [BUILTIN_LANGUAGE]
    seen_languages = {BUILTIN_LANGUAGE}
    discovered_languages: set[str] = set()

    for path in get_translations_dir().glob("*.json"):
        discovered_languages.add(normalize_language_code(path.stem))

    for path in get_qt_translations_dir().glob("neko_shell_*.qm"):
        discovered_languages.add(normalize_language_code(path.stem.removeprefix("neko_shell_")))

    for language in sorted(discovered_languages):
        if language in seen_languages:
            continue
        seen_languages.add(language)
        available_languages.append(language)

    return available_languages


def get_language_display_name(language: Optional[str]) -> str:
    """返回语言代码对应的展示名称。"""
    normalized = normalize_language_code(language)
    return _LANGUAGE_DISPLAY_NAMES.get(normalized, normalized)


def get_available_language_options() -> list[tuple[str, str]]:
    """返回可直接用于 UI 的语言选项。"""
    return [
        (language, get_language_display_name(language))
        for language in get_available_languages()
    ]


def resolve_language_code(language: Optional[str]) -> str:
    """将任意语言配置解析为当前运行时实际可用的语言。"""
    normalized = normalize_language_code(language)
    return normalized if normalized in get_available_languages() else BUILTIN_LANGUAGE


def set_language(language: str) -> None:
    """
    设置当前语言
    
    Args:
        language: 语言代码
    """
    global _current_language, _translations

    resolved_language = resolve_language_code(language)
    _current_language = resolved_language
    _load_translations(resolved_language)


def _load_translations(language: str) -> None:
    """加载翻译文件"""
    global _translations

    trans_file = get_translations_dir() / f"{language}.json"

    if trans_file.exists():
        import json

        with open(trans_file, "r", encoding="utf-8") as f:
            _translations[language] = json.load(f)
    else:
        _translations[language] = {}


def tr(text: str, context: Optional[str] = None) -> str:
    """
    翻译文本
    
    Args:
        text: 要翻译的文本
        context: 翻译上下文
        
    Returns:
        str: 翻译后的文本
    """
    if _current_language in _translations:
        trans_dict = _translations[_current_language]

        if context:
            key = f"{context}.{text}"
            if key in trans_dict:
                return trans_dict[key]

        if text in trans_dict:
            return trans_dict[text]

    return text
