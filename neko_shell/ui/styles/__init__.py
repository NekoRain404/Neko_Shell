#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
样式模块

提供 Neko_Shell 的 UI 样式。
"""

from .themes import ThemeManager, dark_theme, eye_care_theme, light_theme

__all__ = [
    'ThemeManager',
    'dark_theme',
    'eye_care_theme',
    'light_theme',
]
