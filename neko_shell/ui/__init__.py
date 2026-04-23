#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI 模块

提供 Neko_Shell 的用户界面组件。
"""

from .main_window import MainWindow
from .widgets.connection_tree import ConnectionTreeWidget
from .widgets.terminal_widget import (
    TerminalWidget,
    QTermTerminalWidget,
    QTermExternalTerminalWidget,
    QTermLocalTerminalWidget,
)
from .widgets.file_browser import FileBrowserWidget
from .widgets.system_monitor import SystemMonitorWidget
from .widgets.vnc_widget import VNCWidget
from .widgets.tunnel_manager import TunnelManagerWidget
from .widgets.docker_manager import DockerManagerWidget
from .widgets.frp_widget import FRPWidget
from .dialogs.connection_dialog import ConnectionDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.about_dialog import AboutDialog
from .dialogs.help_dialog import HelpDialog
from .dialogs.tunnel_dialog import TunnelDialog

__all__ = [
    # 主窗口
    'MainWindow',
    # 组件
    'ConnectionTreeWidget',
    'TerminalWidget',
    'QTermTerminalWidget',
    'QTermExternalTerminalWidget',
    'QTermLocalTerminalWidget',
    'FileBrowserWidget',
    'SystemMonitorWidget',
    'VNCWidget',
    'TunnelManagerWidget',
    'DockerManagerWidget',
    'FRPWidget',
    # 对话框
    'ConnectionDialog',
    'SettingsDialog',
    'AboutDialog',
    'HelpDialog',
    'TunnelDialog',
]
