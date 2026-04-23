#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对话框模块

提供 Neko_Shell 的对话框组件。
"""

from .connection_dialog import ConnectionDialog
from .settings_dialog import SettingsDialog
from .about_dialog import AboutDialog
from .compose_dialog import ComposeCommandDialog
from .command_center_dialog import CommandCenterDialog
from .help_dialog import HelpDialog
from .quick_open_dialog import QuickOpenDialog
from .shared_library_approval_dialog import SharedLibraryApprovalDialog
from .shared_library_integrity_dialog import SharedLibraryIntegrityDialog
from .sync_history_dialog import SyncHistoryDialog
from .text_file_dialog import TextFileDialog
from .tunnel_dialog import TunnelDialog

__all__ = [
    "ConnectionDialog",
    "SettingsDialog",
    "AboutDialog",
    "ComposeCommandDialog",
    "CommandCenterDialog",
    "HelpDialog",
    "QuickOpenDialog",
    "SharedLibraryApprovalDialog",
    "SharedLibraryIntegrityDialog",
    "SyncHistoryDialog",
    "TextFileDialog",
    "TunnelDialog",
]
