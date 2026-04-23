#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组件模块

提供 Neko_Shell 的自定义 UI 组件。
"""

from .connection_tree import ConnectionTreeWidget
from .terminal_widget import (
    TerminalWidget,
    TerminalSplitWidget,
    QTermDockerExecTerminalWidget,
    QTermTerminalWidget,
    QTermExternalTerminalWidget,
    QTermLocalTerminalWidget,
)
from .file_browser import FileBrowserWidget
from .system_monitor import SystemMonitorWidget
from .vnc_widget import VNCWidget
from .tunnel_manager import TunnelManagerWidget
from .docker_manager import DockerManagerWidget
from .frp_widget import FRPWidget

__all__ = [
    'ConnectionTreeWidget',
    'TerminalWidget',
    'TerminalSplitWidget',
    'QTermDockerExecTerminalWidget',
    'QTermTerminalWidget',
    'QTermExternalTerminalWidget',
    'QTermLocalTerminalWidget',
    'FileBrowserWidget',
    'SystemMonitorWidget',
    'VNCWidget',
    'TunnelManagerWidget',
    'DockerManagerWidget',
    'FRPWidget',
]
