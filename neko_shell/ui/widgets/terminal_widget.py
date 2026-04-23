#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端组件

提供终端显示和交互功能。
"""

import os
import platform
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QSpinBox,
    QWidget,
    QVBoxLayout,
)
from PySide6.QtCore import Qt, Signal, QStringListModel
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut, QTextCursor, QTextDocument

from neko_shell.ui.styles import ThemeManager
from neko_shell.core.connection import BaseConnection, ConnectionStatus, ConnectionType
from neko_shell.models.connection import SSHConfig
from neko_shell.release import APP_NAME, format_version_display
from neko_shell.utils import (
    AppConfig,
    flatten_terminal_snippet_groups,
    get_logger,
    load_command_index,
    normalize_terminal_macros,
    normalize_terminal_favorite_snippets,
    normalize_terminal_snippet_groups,
    normalize_terminal_snippets,
)

try:
    from qtermwidget.qtermwidget import QTermWidget
    HAS_QTERMWIDGET = True
except ImportError:
    QTermWidget = None  # type: ignore
    HAS_QTERMWIDGET = False


DEFAULT_TERMINAL_THEMES = [
    "Ubuntu",
    "Linux",
    "Tango",
    "Solarized",
    "WhiteOnBlack",
    "BlackOnWhite",
    "GreenOnBlack",
]

CLASSIC_TERMINAL_SCHEMES: dict[str, dict[str, str]] = {
    "Ubuntu": {
        "background": "#300a24",
        "text": "#f2f2f2",
        "prompt": "#f6c177",
        "border": "#5b2f4f",
    },
    "Linux": {
        "background": "#111111",
        "text": "#e4e4e4",
        "prompt": "#4ec9b0",
        "border": "#2f2f2f",
    },
    "Tango": {
        "background": "#1f1f1f",
        "text": "#f8f8f2",
        "prompt": "#8be9fd",
        "border": "#3b3b3b",
    },
    "Solarized": {
        "background": "#002b36",
        "text": "#93a1a1",
        "prompt": "#b58900",
        "border": "#18434c",
    },
    "WhiteOnBlack": {
        "background": "#111111",
        "text": "#fafafa",
        "prompt": "#6ab5ff",
        "border": "#2d2d2d",
    },
    "BlackOnWhite": {
        "background": "#fbfbfb",
        "text": "#1f252d",
        "prompt": "#1664c0",
        "border": "#d7dde5",
    },
    "GreenOnBlack": {
        "background": "#08140a",
        "text": "#88d46b",
        "prompt": "#c2ff97",
        "border": "#17301b",
    },
}


def is_qtermwidget_available() -> bool:
    """检查 qtermwidget 是否可用。"""
    return HAS_QTERMWIDGET


def get_terminal_theme_choices() -> list[str]:
    """返回终端主题候选。"""
    return list(DEFAULT_TERMINAL_THEMES)


def normalize_terminal_theme(theme_name: Optional[str]) -> str:
    """将终端主题名归一化为受支持值。"""
    normalized = (theme_name or "").strip()
    if normalized in DEFAULT_TERMINAL_THEMES:
        return normalized
    return DEFAULT_TERMINAL_THEMES[0]


def should_use_qtermwidget(backend: str, connection: BaseConnection) -> bool:
    """根据设置和连接类型判断是否启用 qtermwidget。"""
    if not HAS_QTERMWIDGET:
        return False
    if connection.config.connection_type not in {ConnectionType.SSH, ConnectionType.SERIAL}:
        return False
    return backend in {"auto", "qtermwidget"}


def build_ssh_terminal_command(config: SSHConfig) -> tuple[str, list[str]]:
    """构造供 qtermwidget 启动的 SSH 命令。"""
    ssh_program = shutil.which("ssh") or "ssh"
    args = [
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "TCPKeepAlive=yes",
        "-t",
    ]

    if config.port != 22:
        args.extend(["-p", str(config.port)])

    if config.private_key_path:
        key_path = str(Path(config.private_key_path).expanduser())
        if os.name != "nt" and os.path.exists(key_path):
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        args.extend(["-i", key_path])
    elif not config.look_for_keys:
        args.extend(["-o", "PubkeyAuthentication=no"])

    if not config.allow_agent:
        args.extend(["-o", "IdentityAgent=none"])

    if config.proxy_command:
        args.extend(["-o", f"ProxyCommand={config.proxy_command}"])

    if config.password and not config.private_key_path:
        if os.name == "nt":
            null_device = "NUL"
        else:
            null_device = "/dev/null"
        args.extend([
            "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={null_device}",
        ])

    args.append(f"{config.username}@{config.host}")
    return ssh_program, args


def build_docker_exec_terminal_command(
    config: SSHConfig,
    container_id: str,
    shell: str = "sh",
) -> tuple[str, list[str]]:
    """构造通过 SSH 打开 Docker 容器交互终端的命令。"""
    program, args = build_ssh_terminal_command(config)
    remote_command = build_docker_exec_shell_command(container_id, shell=shell)
    args.append(f"sh -lc {shlex.quote(remote_command)}")
    return program, args


def build_docker_exec_shell_command(container_id: str, shell: str = "sh") -> str:
    """构造远端 shell 中执行的 docker exec 命令。"""
    safe_container = shlex.quote(container_id)
    safe_shell = shlex.quote(shell or "sh")
    return (
        f"docker exec -it {safe_container} {safe_shell} -l "
        f"|| docker exec -it {safe_container} /bin/sh "
        f"|| sudo docker exec -it {safe_container} {safe_shell} -l "
        f"|| sudo docker exec -it {safe_container} /bin/sh"
    )


def build_local_terminal_command() -> tuple[str, list[str]]:
    """构造跨平台本地终端启动命令。"""
    system_name = platform.system()

    if os.name == "nt":
        for candidate in ("pwsh", "powershell", "cmd"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved, []
        return "cmd", []

    shell_program = os.environ.get("SHELL")
    if not shell_program:
        shell_program = "/bin/zsh" if system_name == "Darwin" else "/bin/bash"

    args: list[str] = []
    shell_name = os.path.basename(shell_program)
    if shell_name in {"bash", "zsh", "fish", "sh"}:
        args.append("-l")

    return shell_program, args


def _font_family() -> str:
    return "Consolas" if os.name == "nt" else "Monospace"


def _normalized_snippet_lines(lines: object) -> list[str]:
    """统一归一化快捷命令配置。"""
    return normalize_terminal_snippets(lines if isinstance(lines, list) else None)


def _default_snippet_group_name() -> str:
    return "常用"


def _favorite_group_label() -> str:
    return "收藏"


def _config_snippet_groups(app_config: AppConfig) -> dict[str, list[str]]:
    groups_source = getattr(app_config, "terminal_snippet_groups", None) or app_config.terminal_snippets
    return normalize_terminal_snippet_groups(groups_source)


def _config_favorite_snippets(app_config: AppConfig, groups: dict[str, list[str]]) -> list[str]:
    favorites = getattr(app_config, "terminal_favorite_snippets", None)
    return normalize_terminal_favorite_snippets(favorites, groups)


def _snippet_payload(groups: dict[str, list[str]], favorites: list[str]) -> dict[str, object]:
    normalized_groups = normalize_terminal_snippet_groups(groups)
    normalized_favorites = normalize_terminal_favorite_snippets(favorites, normalized_groups)
    return {
        "terminal_snippet_groups": normalized_groups,
        "terminal_snippets": flatten_terminal_snippet_groups(normalized_groups),
        "terminal_favorite_snippets": normalized_favorites,
    }


def _config_macros(app_config: AppConfig) -> dict[str, list[str]]:
    return normalize_terminal_macros(getattr(app_config, "terminal_macros", None), allow_empty=True)


def _session_payload(
    groups: dict[str, list[str]],
    favorites: list[str],
    macros: dict[str, list[str]],
) -> dict[str, object]:
    normalized_groups = normalize_terminal_snippet_groups(groups, allow_empty=True)
    return {
        "session_snippet_groups": normalized_groups,
        "session_favorite_snippets": normalize_terminal_favorite_snippets(
            favorites,
            normalized_groups,
            allow_empty=True,
        ),
        "session_macros": normalize_terminal_macros(macros, allow_empty=True),
    }


def _tr(controller: object, text: str) -> str:
    translator = getattr(controller, "tr", None)
    return translator(text) if callable(translator) else text


def _emit_optional_signal(controller: object, signal_name: str) -> None:
    signal = getattr(controller, signal_name, None)
    if signal is not None and hasattr(signal, "emit"):
        signal.emit()


def _current_scope_index(controller: object) -> int:
    scope_combo = getattr(controller, "scope_combo", None)
    if scope_combo is None:
        return 0
    return max(0, int(scope_combo.currentIndex()))


def _current_scope_label(controller: object) -> str:
    scope_combo = getattr(controller, "scope_combo", None)
    if scope_combo is None:
        return _tr(controller, "全局")
    return str(scope_combo.currentText() or _tr(controller, "全局")).strip() or _tr(
        controller, "全局"
    )


def _set_scope_index(controller: object, index: int) -> None:
    scope_combo = getattr(controller, "scope_combo", None)
    if scope_combo is not None:
        scope_combo.setCurrentIndex(index)


def _enclosing_terminal_split_widget(controller: object) -> Optional[QWidget]:
    """向上查找所属的双终端分屏容器。"""
    parent_getter = getattr(controller, "parentWidget", None)
    parent = parent_getter() if callable(parent_getter) else None
    while parent is not None:
        if type(parent).__name__ == "TerminalSplitWidget":
            return parent
        next_getter = getattr(parent, "parentWidget", None)
        parent = next_getter() if callable(next_getter) else None
    return None


def _default_snippet_command_seed(controller: object) -> str:
    command_input = getattr(controller, "command_input", None)
    if command_input is not None:
        text = str(command_input.text() or "").strip()
        if text:
            return text
    if hasattr(controller, "_current_snippet_text"):
        return str(controller._current_snippet_text() or "").strip()
    return ""


def _save_context_snippet_with_prompt(controller: object) -> None:
    """通过弹窗保存快捷命令，适配精简 UI。"""
    suggested = _default_snippet_command_seed(controller)
    command, accepted = QInputDialog.getText(
        controller,
        _tr(controller, "保存快捷命令"),
        _tr(controller, "命令内容:"),
        text=suggested,
    )
    if not accepted:
        return
    normalized = str(command or "").strip()
    if not normalized:
        return
    if hasattr(controller, "snippet_combo"):
        controller.snippet_combo.setCurrentText(normalized)
    if hasattr(controller, "_save_current_snippet"):
        controller._save_current_snippet()


def _add_terminal_scope_menu(controller: object, menu: QMenu) -> None:
    """向菜单中添加全局/会话作用域切换。"""
    scope_menu = menu.addMenu(_tr(controller, "作用域"))
    current_index = _current_scope_index(controller)
    scope_texts = (
        [_tr(controller, "全局"), _tr(controller, "会话")]
        if getattr(controller, "scope_combo", None) is None
        else [str(controller.scope_combo.itemText(0)), str(controller.scope_combo.itemText(1))]
    )
    tool_tip = ""
    scope_combo = getattr(controller, "scope_combo", None)
    if scope_combo is not None:
        tool_tip = str(scope_combo.toolTip() or "").strip()

    for index, label in enumerate(scope_texts):
        action = scope_menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(index == current_index)
        if tool_tip and index == current_index:
            action.setToolTip(tool_tip)
        action.triggered.connect(
            lambda checked=False, current_index=index: _set_scope_index(
                controller, current_index
            )
        )


def _terminal_context_supports_file_browser(controller: object) -> bool:
    connection = getattr(controller, "connection", None)
    connection_type = getattr(getattr(connection, "config", None), "connection_type", None)
    return connection_type in {ConnectionType.SSH, ConnectionType.SFTP, ConnectionType.FTP}


def _terminal_context_supports_split(controller: object) -> bool:
    connection_id = str(getattr(controller, "connection_id", "") or "").strip()
    if connection_id.startswith("__local_terminal__"):
        return True
    if type(controller).__name__ == "QTermLocalTerminalWidget":
        return True
    connection = getattr(controller, "connection", None)
    connection_type = getattr(getattr(connection, "config", None), "connection_type", None)
    return connection_type in {
        ConnectionType.SSH,
        ConnectionType.SERIAL,
        ConnectionType.TCP,
        ConnectionType.UDP,
    }


def _run_context_snippet(controller: object, command: str, group_name: Optional[str] = None) -> None:
    if not command:
        return
    if group_name and hasattr(controller, "group_combo"):
        controller.group_combo.setCurrentText(group_name)
    if hasattr(controller, "snippet_combo"):
        controller.snippet_combo.setCurrentText(command)
    if hasattr(controller, "_run_selected_snippet"):
        controller._run_selected_snippet()


def _run_context_macro(controller: object, macro_name: str) -> None:
    if not macro_name:
        return
    if hasattr(controller, "macro_combo"):
        controller.macro_combo.setCurrentText(macro_name)
    if hasattr(controller, "_run_selected_macro"):
        controller._run_selected_macro()


def _add_terminal_display_menu(
    controller: object,
    menu: QMenu,
    *,
    current_theme_name: str,
    current_font_size: int,
    set_theme: Callable[[str], None],
    set_font_size: Callable[[int], None],
    default_font_size: int = 10,
) -> None:
    """向菜单中添加显示相关动作。"""
    display_menu = menu.addMenu(_tr(controller, "显示"))

    font_menu = display_menu.addMenu(_tr(controller, "字号"))
    decrease_action = font_menu.addAction(_tr(controller, "减小字号"))
    decrease_action.setEnabled(current_font_size > 6)
    decrease_action.triggered.connect(
        lambda checked=False, size=max(6, current_font_size - 1): set_font_size(size)
    )

    increase_action = font_menu.addAction(_tr(controller, "增大字号"))
    increase_action.setEnabled(current_font_size < 36)
    increase_action.triggered.connect(
        lambda checked=False, size=min(36, current_font_size + 1): set_font_size(size)
    )

    reset_action = font_menu.addAction(_tr(controller, "恢复默认字号"))
    reset_action.triggered.connect(
        lambda checked=False, size=max(6, default_font_size): set_font_size(size)
    )

    font_menu.addSeparator()
    for size in (9, 10, 11, 12, 14, 16, 18):
        action = font_menu.addAction(f"{size} pt")
        action.setCheckable(True)
        action.setChecked(size == current_font_size)
        action.triggered.connect(lambda checked=False, value=size: set_font_size(value))

    theme_menu = display_menu.addMenu(_tr(controller, "终端主题"))
    for theme_name in get_terminal_theme_choices():
        action = theme_menu.addAction(theme_name)
        action.setCheckable(True)
        action.setChecked(theme_name == current_theme_name)
        action.triggered.connect(
            lambda checked=False, name=theme_name: set_theme(name)
        )


def _add_terminal_workspace_menu(controller: object, menu: QMenu) -> None:
    """向菜单中添加工作区联动动作。"""
    workspace_menu = menu.addMenu(_tr(controller, "工作区"))
    split_container = _enclosing_terminal_split_widget(controller)

    if _terminal_context_supports_file_browser(controller):
        file_browser_action = workspace_menu.addAction(_tr(controller, "打开文件浏览器"))
        file_browser_action.triggered.connect(
            lambda checked=False: _emit_optional_signal(controller, "file_browser_requested")
        )

    if split_container is not None and hasattr(split_container, "toggle_orientation"):
        orientation_action = workspace_menu.addAction(_tr(controller, "切换分屏方向"))
        orientation_action.triggered.connect(
            lambda checked=False: split_container.toggle_orientation()
        )

    if _terminal_context_supports_split(controller):
        split_action = workspace_menu.addAction(_tr(controller, "终端分屏"))
        split_action.triggered.connect(
            lambda checked=False: _emit_optional_signal(controller, "split_requested")
        )

    sync_action = workspace_menu.addAction(_tr(controller, "同步输入"))
    sync_action.triggered.connect(
        lambda checked=False: _emit_optional_signal(controller, "sync_toggle_requested")
    )

    workspace_menu.addSeparator()

    command_center_action = workspace_menu.addAction(_tr(controller, "快捷命令中心"))
    command_center_action.triggered.connect(
        lambda checked=False: _emit_optional_signal(controller, "command_center_requested")
    )

    compose_action = workspace_menu.addAction(_tr(controller, "编排发送"))
    compose_action.triggered.connect(
        lambda checked=False: _emit_optional_signal(controller, "compose_requested")
    )

    quick_inspection_action = workspace_menu.addAction(_tr(controller, "快速巡检"))
    quick_inspection_action.triggered.connect(
        lambda checked=False: _emit_optional_signal(controller, "quick_inspection_requested")
    )


def _add_terminal_snippet_menu(controller: object, menu: QMenu) -> None:
    """向菜单中添加快捷命令动作。"""
    snippet_menu = menu.addMenu(
        _tr(controller, f"快捷命令（{_current_scope_label(controller)}）")
    )
    current_command = ""
    if hasattr(controller, "_current_snippet_text"):
        current_command = str(controller._current_snippet_text() or "").strip()
    favorites = (
        list(controller._current_scope_favorites())
        if hasattr(controller, "_current_scope_favorites")
        else []
    )
    groups = (
        {
            str(group_name): list(commands)
            for group_name, commands in controller._current_scope_groups().items()
        }
        if hasattr(controller, "_current_scope_groups")
        else {}
    )
    is_favorite = bool(current_command and current_command in favorites)

    run_current_action = snippet_menu.addAction(_tr(controller, "运行当前命令"))
    run_current_action.setEnabled(bool(current_command))
    run_current_action.triggered.connect(
        lambda checked=False, command=current_command: _run_context_snippet(controller, command)
    )

    save_snippet_action = snippet_menu.addAction(_tr(controller, "新增快捷命令"))
    save_snippet_action.triggered.connect(
        lambda checked=False: _save_context_snippet_with_prompt(controller)
    )

    favorite_action = snippet_menu.addAction(
        _tr(controller, "取消收藏当前命令") if is_favorite else _tr(controller, "收藏当前命令")
    )
    favorite_action.setEnabled(bool(current_command))
    favorite_action.triggered.connect(getattr(controller, "_toggle_favorite_current_snippet"))

    delete_action = snippet_menu.addAction(_tr(controller, "删除当前命令"))
    delete_action.setEnabled(bool(current_command))
    delete_action.triggered.connect(getattr(controller, "_delete_current_snippet"))

    if favorites:
        snippet_menu.addSeparator()
        favorites_menu = snippet_menu.addMenu(_tr(controller, "收藏命令"))
        for command in favorites:
            action = favorites_menu.addAction(command)
            action.triggered.connect(
                lambda checked=False, current_command=command: _run_context_snippet(
                    controller, current_command
                )
            )
    else:
        placeholder = snippet_menu.addAction(_tr(controller, "暂无收藏命令"))
        placeholder.setEnabled(False)

    if groups:
        groups_menu = snippet_menu.addMenu(_tr(controller, "命令组"))
        for group_name, commands in groups.items():
            if not commands:
                continue
            group_menu = groups_menu.addMenu(group_name)
            for command in commands:
                action = group_menu.addAction(command)
                action.triggered.connect(
                    lambda checked=False, current_command=command, current_group=group_name: (
                        _run_context_snippet(controller, current_command, current_group)
                    )
                )
    else:
        placeholder = snippet_menu.addAction(_tr(controller, "暂无命令组"))
        placeholder.setEnabled(False)


def _add_terminal_macro_menu(controller: object, menu: QMenu) -> None:
    """向菜单中添加命令宏动作。"""
    macro_menu = menu.addMenu(_tr(controller, f"命令宏（{_current_scope_label(controller)}）"))
    current_macro_name = ""
    if hasattr(controller, "_selected_macro_name"):
        current_macro_name = str(controller._selected_macro_name() or "").strip()
    macros = (
        {
            str(name): list(commands)
            for name, commands in controller._current_scope_macros().items()
        }
        if hasattr(controller, "_current_scope_macros")
        else {}
    )

    run_macro_action = macro_menu.addAction(_tr(controller, "执行当前命令宏"))
    run_macro_action.setEnabled(bool(current_macro_name))
    run_macro_action.triggered.connect(
        lambda checked=False, name=current_macro_name: _run_context_macro(controller, name)
    )

    save_macro_action = macro_menu.addAction(
        getattr(getattr(controller, "save_macro_btn", None), "text", lambda: _tr(controller, "保存宏"))()
    )
    save_macro_action.triggered.connect(getattr(controller, "_save_current_macro"))

    delete_macro_action = macro_menu.addAction(_tr(controller, "删除当前命令宏"))
    delete_macro_action.setEnabled(bool(current_macro_name))
    delete_macro_action.triggered.connect(getattr(controller, "_delete_current_macro"))

    if macros:
        macro_menu.addSeparator()
        saved_macro_menu = macro_menu.addMenu(_tr(controller, "已保存命令宏"))
        for macro_name in macros:
            action = saved_macro_menu.addAction(macro_name)
            action.triggered.connect(
                lambda checked=False, current_name=macro_name: _run_context_macro(
                    controller, current_name
                )
            )
    else:
        placeholder = macro_menu.addAction(_tr(controller, "暂无命令宏"))
        placeholder.setEnabled(False)


class EnhancedQTermWidget(QTermWidget):  # type: ignore[misc]
    """带右键菜单和快捷键增强的 QTermWidget。"""

    font_size_changed = Signal(int)
    theme_changed = Signal(str)

    def __init__(self, theme_name: str = "Ubuntu", font_size: int = 10, parent: Optional[QWidget] = None):
        super().__init__(0, parent)
        self._logger = get_logger("EnhancedQTermWidget")
        self.current_theme_name = normalize_terminal_theme(theme_name)
        self.current_font_size = font_size
        self._clipboard = QApplication.clipboard()
        self._extra_context_menu_builder: Optional[Callable[[QMenu], None]] = None
        self._install_shortcuts()
        self._apply_theme(self.current_theme_name)
        self._apply_font_size(self.current_font_size)
        if hasattr(self, "setSuppressProgramBackgroundColors"):
            self.setSuppressProgramBackgroundColors(True)

    def _install_shortcuts(self) -> None:
        if platform.system() == "Darwin":
            copy_shortcut = QKeySequence.Copy
            paste_shortcut = QKeySequence.Paste
        else:
            copy_shortcut = QKeySequence("Ctrl+Shift+C")
            paste_shortcut = QKeySequence("Ctrl+Shift+V")

        self._shortcut_copy = QShortcut(copy_shortcut, self)
        self._shortcut_copy.setContext(Qt.WidgetWithChildrenShortcut)
        self._shortcut_copy.activated.connect(self._copy_selection)

        self._shortcut_paste = QShortcut(paste_shortcut, self)
        self._shortcut_paste.setContext(Qt.WidgetWithChildrenShortcut)
        self._shortcut_paste.activated.connect(self._paste_clipboard)

    def _copy_selection(self) -> None:
        try:
            if hasattr(self, "selectedText") and self.selectedText(True):
                self.copyClipboard()
        except Exception as exc:
            self._logger.debug("复制终端内容失败: %s", exc)

    def _has_selection(self) -> bool:
        try:
            return bool(hasattr(self, "selectedText") and self.selectedText(True))
        except Exception:
            return False

    def _paste_clipboard(self) -> None:
        try:
            self.pasteClipboard()
        except Exception as exc:
            self._logger.debug("粘贴终端内容失败: %s", exc)

    def _apply_theme(self, theme_name: str) -> None:
        try:
            self.current_theme_name = normalize_terminal_theme(theme_name)
            self.setColorScheme(self.current_theme_name)
            self.theme_changed.emit(self.current_theme_name)
        except Exception as exc:
            self._logger.debug("应用终端主题失败 [%s]: %s", theme_name, exc)

    def _apply_font_size(self, font_size: int) -> None:
        try:
            normalized = max(6, min(int(font_size), 36))
        except (TypeError, ValueError):
            normalized = 10
        font = QFont(_font_family(), normalized)
        font.setStyleHint(QFont.Monospace)
        if hasattr(self, "setTerminalFont"):
            self.setTerminalFont(font)
        self.current_font_size = normalized
        self.font_size_changed.emit(normalized)

    def set_terminal_preferences(self, theme_name: Optional[str] = None, font_size: Optional[int] = None) -> None:
        """统一更新终端主题和字号。"""
        if theme_name is not None:
            self._apply_theme(theme_name)
        if font_size is not None:
            self._apply_font_size(font_size)

    def build_context_menu(self) -> QMenu:
        """构建 qtermwidget 的右键菜单。"""
        menu = QMenu(self)

        copy_action = QAction(self.tr("复制"), self)
        copy_action.setEnabled(self._has_selection())
        copy_action.triggered.connect(self._copy_selection)
        menu.addAction(copy_action)

        paste_action = QAction(self.tr("粘贴"), self)
        paste_action.setEnabled(bool(self._clipboard.text()))
        paste_action.triggered.connect(self._paste_clipboard)
        menu.addAction(paste_action)

        clear_action = QAction(self.tr("清屏"), self)
        clear_action.triggered.connect(self.clear)
        menu.addAction(clear_action)

        menu.addSeparator()
        _add_terminal_scope_menu(self, menu)

        if callable(self._extra_context_menu_builder):
            self._extra_context_menu_builder(menu)

        menu.addSeparator()
        _add_terminal_display_menu(
            self,
            menu,
            current_theme_name=self.current_theme_name,
            current_font_size=self.current_font_size,
            set_theme=lambda theme_name: self.set_terminal_preferences(theme_name=theme_name),
            set_font_size=lambda font_size: self.set_terminal_preferences(font_size=font_size),
        )
        return menu

    def contextMenuEvent(self, event) -> None:
        self.build_context_menu().exec(event.globalPos())

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                step = 1 if delta > 0 else -1
                self._apply_font_size(self.current_font_size + step)
            event.accept()
            return
        super().wheelEvent(event)


class _BaseQTermContainer(QWidget):
    """统一封装 qtermwidget 终端容器公共逻辑。"""

    closed = Signal()
    command_executed = Signal(str)
    output_appended = Signal(str)
    execution_reported = Signal(object)
    snippets_changed = Signal(object)
    session_state_changed = Signal(object)
    file_browser_requested = Signal()
    split_requested = Signal()
    sync_toggle_requested = Signal()
    command_center_requested = Signal()
    compose_requested = Signal()
    quick_inspection_requested = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        app_config: Optional[AppConfig] = None,
    ):
        super().__init__(parent)
        if not HAS_QTERMWIDGET or QTermWidget is None:
            raise RuntimeError("qtermwidget 不可用")

        self._logger = get_logger(type(self).__name__)
        self._connection: Optional[BaseConnection] = None
        self._app_config = app_config or AppConfig()
        self._snippet_groups = _config_snippet_groups(self._app_config)
        self._favorite_snippets = _config_favorite_snippets(self._app_config, self._snippet_groups)
        self._macros = _config_macros(self._app_config)
        self._session_snippet_groups: dict[str, list[str]] = {}
        self._session_favorite_snippets: list[str] = []
        self._session_macros: dict[str, list[str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.terminal = EnhancedQTermWidget(
            theme_name=self._app_config.terminal_theme,
            font_size=self._app_config.terminal_font_size,
            parent=self,
        )
        self.terminal._extra_context_menu_builder = self._populate_terminal_context_menu
        if hasattr(self.terminal, "receivedData"):
            self.terminal.receivedData.connect(self._forward_terminal_output)
        layout.addWidget(self.terminal)

        self.context_hint_label = QLabel(
            self.tr("右键终端可用：工作区、快捷命令、命令宏、显示。"),
            self,
        )
        self.context_hint_label.setObjectName("panelMeta")
        self.context_hint_label.setWordWrap(True)
        self.context_hint_label.hide()

        self._control_panel = QWidget(self)
        self._control_panel.hide()
        control_layout = QVBoxLayout(self._control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        self.copy_btn = QPushButton(self.tr("复制"))
        self.copy_btn.clicked.connect(self.terminal._copy_selection)
        toolbar.addWidget(self.copy_btn)

        self.paste_btn = QPushButton(self.tr("粘贴"))
        self.paste_btn.clicked.connect(self.terminal._paste_clipboard)
        toolbar.addWidget(self.paste_btn)

        self.clear_btn = QPushButton(self.tr("清屏"))
        self.clear_btn.clicked.connect(self._clear_terminal)
        toolbar.addWidget(self.clear_btn)

        toolbar.addWidget(QLabel(self.tr("范围:")))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems([self.tr("全局"), self.tr("会话")])
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        toolbar.addWidget(self.scope_combo)

        toolbar.addWidget(QLabel(self.tr("主题:")))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(get_terminal_theme_choices())
        self.theme_combo.setCurrentText(normalize_terminal_theme(self._app_config.terminal_theme))
        self.theme_combo.currentTextChanged.connect(self._apply_toolbar_theme)
        self.theme_combo.setMaximumWidth(150)
        toolbar.addWidget(self.theme_combo)

        toolbar.addWidget(QLabel(self.tr("字体:")))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 24)
        self.font_size_spin.setValue(self._app_config.terminal_font_size)
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        toolbar.addWidget(self.font_size_spin)

        toolbar.addStretch()
        control_layout.addLayout(toolbar)

        commands_toolbar = QHBoxLayout()
        commands_toolbar.setSpacing(4)
        commands_toolbar.addWidget(QLabel(self.tr("命令组:")))
        self.group_combo = QComboBox()
        self.group_combo.setMaximumWidth(120)
        self.group_combo.currentTextChanged.connect(self._on_group_changed)
        commands_toolbar.addWidget(self.group_combo)

        commands_toolbar.addWidget(QLabel(self.tr("快捷命令:")))
        self.snippet_combo = QComboBox()
        self.snippet_combo.setEditable(True)
        self.snippet_combo.setInsertPolicy(QComboBox.NoInsert)
        self.snippet_combo.setMaximumWidth(260)
        line_edit = self.snippet_combo.lineEdit()
        if line_edit is not None:
            line_edit.returnPressed.connect(self._run_selected_snippet)
        commands_toolbar.addWidget(self.snippet_combo)

        self.favorite_snippet_btn = QPushButton(self.tr("收藏"))
        self.favorite_snippet_btn.clicked.connect(self._toggle_favorite_current_snippet)
        commands_toolbar.addWidget(self.favorite_snippet_btn)

        self.run_snippet_btn = QPushButton(self.tr("运行"))
        self.run_snippet_btn.clicked.connect(self._run_selected_snippet)
        commands_toolbar.addWidget(self.run_snippet_btn)

        self.save_snippet_btn = QPushButton(self.tr("保存"))
        self.save_snippet_btn.clicked.connect(self._save_current_snippet)
        commands_toolbar.addWidget(self.save_snippet_btn)

        self.delete_snippet_btn = QPushButton(self.tr("删除"))
        self.delete_snippet_btn.clicked.connect(self._delete_current_snippet)
        commands_toolbar.addWidget(self.delete_snippet_btn)
        commands_toolbar.addStretch()
        control_layout.addLayout(commands_toolbar)

        macro_toolbar = QHBoxLayout()
        macro_toolbar.setSpacing(4)
        macro_toolbar.addWidget(QLabel(self.tr("命令宏:")))
        self.macro_combo = QComboBox()
        self.macro_combo.setEditable(False)
        self.macro_combo.setMaximumWidth(220)
        macro_toolbar.addWidget(self.macro_combo)

        self.run_macro_btn = QPushButton(self.tr("执行宏"))
        self.run_macro_btn.clicked.connect(self._run_selected_macro)
        macro_toolbar.addWidget(self.run_macro_btn)

        self.save_macro_btn = QPushButton(self.tr("保存宏"))
        self.save_macro_btn.clicked.connect(self._save_current_macro)
        macro_toolbar.addWidget(self.save_macro_btn)

        self.delete_macro_btn = QPushButton(self.tr("删除宏"))
        self.delete_macro_btn.clicked.connect(self._delete_current_macro)
        macro_toolbar.addWidget(self.delete_macro_btn)
        macro_toolbar.addStretch()
        control_layout.addLayout(macro_toolbar)
        self._refresh_group_combo()
        self._refresh_snippet_combo()
        self._refresh_macro_combo()
        self._sync_favorite_button()
        self._sync_scope_enabled_state()

        self.terminal.font_size_changed.connect(self._sync_font_size)
        self.terminal.theme_changed.connect(self._sync_theme)

    @property
    def connection(self) -> Optional[BaseConnection]:
        """获取当前绑定的连接。"""
        return self._connection

    def apply_preferences(self, app_config: AppConfig) -> None:
        """应用外部配置变更。"""
        self._app_config = app_config
        self._set_snippet_state(
            _config_snippet_groups(app_config),
            _config_favorite_snippets(app_config, _config_snippet_groups(app_config)),
        )
        self._set_macro_state(_config_macros(app_config))
        normalized_theme = normalize_terminal_theme(app_config.terminal_theme)
        self._sync_theme(normalized_theme)
        self._sync_font_size(app_config.terminal_font_size)
        self.terminal.set_terminal_preferences(
            theme_name=normalized_theme,
            font_size=app_config.terminal_font_size,
        )

    def apply_session_state(self, session_data: Optional[dict[str, object]]) -> None:
        """应用会话级快捷命令与宏。"""
        payload = session_data or {}
        self._set_session_state(
            payload.get("session_snippet_groups"),
            payload.get("session_favorite_snippets"),
            payload.get("session_macros"),
        )

    def export_session_state(self) -> dict[str, object]:
        """导出当前会话级终端数据。"""
        return _session_payload(
            self._session_snippet_groups,
            self._session_favorite_snippets,
            self._session_macros,
        )

    def _current_scope(self) -> str:
        return "session" if self.scope_combo.currentIndex() == 1 else "global"

    def _current_scope_groups(self) -> dict[str, list[str]]:
        return self._session_snippet_groups if self._current_scope() == "session" else self._snippet_groups

    def _current_scope_favorites(self) -> list[str]:
        return self._session_favorite_snippets if self._current_scope() == "session" else self._favorite_snippets

    def _current_scope_macros(self) -> dict[str, list[str]]:
        return self._session_macros if self._current_scope() == "session" else self._macros

    def _set_macro_state(
        self,
        macros: object,
        *,
        emit_signal: bool = False,
        preferred_name: Optional[str] = None,
    ) -> None:
        normalized_macros = normalize_terminal_macros(macros, allow_empty=True)
        if normalized_macros == self._macros:
            return
        self._macros = normalized_macros
        self._refresh_macro_combo()
        if preferred_name and preferred_name in self._macros:
            self.macro_combo.setCurrentText(preferred_name)
        if emit_signal:
            payload = _snippet_payload(self._snippet_groups, self._favorite_snippets)
            payload["terminal_macros"] = dict(self._macros)
            self.snippets_changed.emit(payload)

    def _set_session_state(
        self,
        groups: object,
        favorites: object,
        macros: object,
        *,
        emit_signal: bool = False,
        preferred_group: Optional[str] = None,
        preferred_command: Optional[str] = None,
        preferred_macro: Optional[str] = None,
    ) -> None:
        normalized_groups = normalize_terminal_snippet_groups(groups, allow_empty=True)
        normalized_favorites = normalize_terminal_favorite_snippets(
            favorites,
            normalized_groups,
            allow_empty=True,
        )
        normalized_macros = normalize_terminal_macros(macros, allow_empty=True)
        if (
            normalized_groups == self._session_snippet_groups
            and normalized_favorites == self._session_favorite_snippets
            and normalized_macros == self._session_macros
        ):
            return
        self._session_snippet_groups = normalized_groups
        self._session_favorite_snippets = normalized_favorites
        self._session_macros = normalized_macros
        self._refresh_group_combo()
        self._refresh_snippet_combo()
        self._refresh_macro_combo()
        if preferred_group:
            self.group_combo.setCurrentText(preferred_group)
        if preferred_command:
            self.snippet_combo.setCurrentText(preferred_command)
        if preferred_macro:
            self.macro_combo.setCurrentText(preferred_macro)
        self._sync_favorite_button()
        self._sync_scope_enabled_state()
        if emit_signal:
            self.session_state_changed.emit(self.export_session_state())

    def _refresh_macro_combo(self) -> None:
        current_name = self.macro_combo.currentText().strip() if hasattr(self, "macro_combo") else ""
        macros = list(self._current_scope_macros().keys())
        self.macro_combo.blockSignals(True)
        self.macro_combo.clear()
        self.macro_combo.addItems(macros)
        if current_name and current_name in macros:
            self.macro_combo.setCurrentText(current_name)
        self.macro_combo.blockSignals(False)
        self.run_macro_btn.setEnabled(bool(macros))
        self.delete_macro_btn.setEnabled(bool(macros))

    def _sync_scope_enabled_state(self) -> None:
        is_session = self._current_scope() == "session"
        has_connection = self._connection is not None
        self.scope_combo.setToolTip(
            self.tr("会话范围会跟随当前连接保存") if has_connection else self.tr("本地终端仅保留当前窗口会话范围")
        )
        self.save_macro_btn.setText(self.tr("保存会话宏") if is_session else self.tr("保存宏"))
        self.save_snippet_btn.setText(self.tr("保存到会话") if is_session else self.tr("保存"))

    def _refresh_group_combo(self) -> None:
        current_group = self._current_group_name()
        group_names = [_favorite_group_label(), *self._current_scope_groups().keys()]
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItems(group_names)
        self.group_combo.setCurrentText(current_group or group_names[0])
        self.group_combo.blockSignals(False)

    def _commands_for_current_group(self) -> list[str]:
        group_name = self._current_group_name()
        if group_name == _favorite_group_label():
            return list(self._current_scope_favorites())
        return list(self._current_scope_groups().get(group_name, []))

    def _refresh_snippet_combo(self) -> None:
        current_text = self._current_snippet_text()
        commands = self._commands_for_current_group()
        self.snippet_combo.blockSignals(True)
        self.snippet_combo.clear()
        self.snippet_combo.addItems(commands)
        self.snippet_combo.setCurrentText(current_text or (commands[0] if commands else ""))
        self.snippet_combo.blockSignals(False)
        self._sync_favorite_button()

    def _current_snippet_text(self) -> str:
        return self.snippet_combo.currentText().strip()

    def _current_group_name(self) -> str:
        current = self.group_combo.currentText().strip() if hasattr(self, "group_combo") else ""
        if current:
            return current
        return _favorite_group_label()

    def _selected_group_for_save(self) -> str:
        group_name = self._current_group_name()
        if group_name == _favorite_group_label():
            return _default_snippet_group_name()
        return group_name or _default_snippet_group_name()

    def _set_snippet_state(
        self,
        groups: object,
        favorites: object,
        emit_signal: bool = False,
        preferred_group: Optional[str] = None,
        preferred_command: Optional[str] = None,
    ) -> None:
        normalized_groups = normalize_terminal_snippet_groups(groups)
        normalized_favorites = normalize_terminal_favorite_snippets(favorites, normalized_groups)
        if (
            normalized_groups == self._snippet_groups
            and normalized_favorites == self._favorite_snippets
        ):
            return
        self._snippet_groups = normalized_groups
        self._favorite_snippets = normalized_favorites
        current_group = preferred_group or self._current_group_name()
        current_command = preferred_command or self._current_snippet_text()
        self._refresh_group_combo()
        if current_group in {_favorite_group_label(), *self._snippet_groups.keys()}:
            self.group_combo.setCurrentText(current_group)
        self._refresh_snippet_combo()
        if current_command:
            self.snippet_combo.setCurrentText(current_command)
        self._sync_favorite_button()
        if emit_signal:
            payload = _snippet_payload(self._snippet_groups, self._favorite_snippets)
            payload["terminal_macros"] = dict(self._macros)
            self.snippets_changed.emit(payload)

    def _save_current_snippet(self) -> None:
        command = self._current_snippet_text()
        if not command:
            return
        group_name = self._selected_group_for_save()
        groups = {name: list(commands) for name, commands in self._current_scope_groups().items()}
        groups.setdefault(group_name, [])
        groups[group_name].append(command)
        if self._current_scope() == "session":
            self._set_session_state(
                groups,
                self._current_scope_favorites(),
                self._current_scope_macros(),
                emit_signal=True,
                preferred_group=group_name,
                preferred_command=command,
            )
        else:
            self._set_snippet_state(
                groups,
                self._favorite_snippets,
                emit_signal=True,
                preferred_group=group_name,
                preferred_command=command,
            )
        self.snippet_combo.setCurrentText(command)

    def _delete_current_snippet(self) -> None:
        command = self._current_snippet_text()
        if not command:
            return
        groups = {
            name: [item for item in commands if item != command]
            for name, commands in self._current_scope_groups().items()
        }
        groups = {name: commands for name, commands in groups.items() if commands}
        favorites = [item for item in self._current_scope_favorites() if item != command]
        if self._current_scope() == "session":
            self._set_session_state(
                groups,
                favorites,
                self._current_scope_macros(),
                emit_signal=True,
            )
        else:
            self._set_snippet_state(groups, favorites, emit_signal=True)

    def _run_selected_snippet(self) -> None:
        command = self._current_snippet_text()
        if not command:
            return
        try:
            self.command_executed.emit(command)
            self._send_terminal_text(command)
        except Exception as exc:
            self._logger.debug("运行快捷命令失败: %s", exc)

    def _send_terminal_text(self, command: str) -> None:
        if hasattr(self.terminal, "sendText"):
            self.terminal.sendText(f"{command}\n")
            return
        if self._connection and hasattr(self._connection, "write"):
            self._connection.write(command.encode("utf-8") + b"\n")

    def execute_broadcast_command(self, command: str) -> None:
        """执行来自主窗口同步输入栏的广播命令。"""
        normalized = (command or "").strip()
        if not normalized:
            return
        self._send_terminal_text(normalized)

    def _toggle_favorite_current_snippet(self) -> None:
        command = self._current_snippet_text()
        if not command:
            return
        favorites = list(self._current_scope_favorites())
        if command in favorites:
            favorites = [item for item in favorites if item != command]
        else:
            favorites.append(command)
        if self._current_scope() == "session":
            self._set_session_state(
                self._current_scope_groups(),
                favorites,
                self._current_scope_macros(),
                emit_signal=True,
                preferred_group=self._current_group_name(),
                preferred_command=command,
            )
        else:
            self._set_snippet_state(
                self._snippet_groups,
                favorites,
                emit_signal=True,
                preferred_group=self._current_group_name(),
                preferred_command=command,
            )

    def _sync_favorite_button(self) -> None:
        command = self._current_snippet_text()
        is_favorite = bool(command and command in self._current_scope_favorites())
        self.favorite_snippet_btn.setText(self.tr("取消收藏") if is_favorite else self.tr("收藏"))

    def _on_group_changed(self, _group_name: str) -> None:
        self._refresh_snippet_combo()

    def _on_scope_changed(self, _index: int) -> None:
        self._refresh_group_combo()
        self._refresh_snippet_combo()
        self._refresh_macro_combo()
        self._sync_scope_enabled_state()

    def _selected_macro_name(self) -> str:
        return self.macro_combo.currentText().strip()

    def _run_selected_macro(self) -> None:
        macro_name = self._selected_macro_name()
        if not macro_name:
            return
        commands = self._current_scope_macros().get(macro_name, [])
        if not commands:
            return
        for command in commands:
            try:
                self.command_executed.emit(command)
                self._send_terminal_text(command)
            except Exception as exc:
                self._logger.debug("执行命令宏失败 [%s]: %s", macro_name, exc)
                break

    def _save_current_macro(self) -> None:
        suggested_name = self._selected_macro_name() or self._current_snippet_text() or self.tr("新宏")
        macro_name, accepted = QInputDialog.getText(
            self,
            self.tr("保存命令宏"),
            self.tr("宏名称:"),
            text=suggested_name,
        )
        if not accepted:
            return
        macro_name = macro_name.strip()
        if not macro_name:
            return
        content, accepted = QInputDialog.getMultiLineText(
            self,
            self.tr("编辑命令宏"),
            self.tr("每行一条命令:"),
            self._current_snippet_text(),
        )
        if not accepted:
            return
        commands = [line.strip() for line in content.splitlines() if line.strip()]
        if not commands:
            return
        macros = {name: list(items) for name, items in self._current_scope_macros().items()}
        macros[macro_name] = commands
        if self._current_scope() == "session":
            self._set_session_state(
                self._current_scope_groups(),
                self._current_scope_favorites(),
                macros,
                emit_signal=True,
                preferred_macro=macro_name,
            )
        else:
            self._set_macro_state(macros, emit_signal=True, preferred_name=macro_name)

    def _delete_current_macro(self) -> None:
        macro_name = self._selected_macro_name()
        if not macro_name:
            return
        macros = {
            name: list(commands)
            for name, commands in self._current_scope_macros().items()
            if name != macro_name
        }
        if self._current_scope() == "session":
            self._set_session_state(
                self._current_scope_groups(),
                self._current_scope_favorites(),
                macros,
                emit_signal=True,
            )
        else:
            self._set_macro_state(macros, emit_signal=True)

    def _sync_font_size(self, size: int) -> None:
        if self.font_size_spin.value() == size:
            return
        self.font_size_spin.blockSignals(True)
        self.font_size_spin.setValue(size)
        self.font_size_spin.blockSignals(False)

    def _sync_theme(self, theme_name: str) -> None:
        normalized_theme = normalize_terminal_theme(theme_name)
        if self.theme_combo.currentText() == normalized_theme:
            return
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentText(normalized_theme)
        self.theme_combo.blockSignals(False)

    def _apply_toolbar_theme(self, theme_name: Optional[str] = None) -> None:
        self.terminal.set_terminal_preferences(
            theme_name=normalize_terminal_theme(theme_name or self.theme_combo.currentText())
        )

    def _populate_terminal_context_menu(self, menu: QMenu) -> None:
        """扩展 qtermwidget 右键菜单。"""
        _add_terminal_workspace_menu(self, menu)
        _add_terminal_snippet_menu(self, menu)
        _add_terminal_macro_menu(self, menu)

    def _clear_terminal(self) -> None:
        if hasattr(self.terminal, "clear"):
            self.terminal.clear()

    def _forward_terminal_output(self, chunk: object) -> None:
        """转发 qtermwidget 输出内容。"""
        if chunk is None:
            return
        if isinstance(chunk, bytes):
            text = chunk.decode("utf-8", errors="replace")
        else:
            text = str(chunk)
        if text:
            self.output_appended.emit(text)

    def _on_font_size_changed(self, size: int) -> None:
        self.terminal.set_terminal_preferences(font_size=size)

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.disconnect()
            except Exception as exc:
                self._logger.debug("关闭 qtermwidget 终端连接失败: %s", exc)
        self.closed.emit()
        super().close()


class QTermTerminalWidget(_BaseQTermContainer):
    """基于 qtermwidget 的 SSH 终端组件。"""

    def __init__(self, parent: Optional[QWidget] = None, app_config: Optional[AppConfig] = None):
        super().__init__(parent=parent, app_config=app_config)
        self._auth_state = {
            "yes": False,
            "password": False,
            "passphrase": False,
        }

    def set_connection(self, connection: BaseConnection) -> None:
        """绑定 SSH 连接并启动 qtermwidget 会话。"""
        self._connection = connection
        self._sync_scope_enabled_state()
        if connection.config.connection_type != ConnectionType.SSH:
            raise RuntimeError("QTermTerminalWidget 仅支持 SSH 连接")

        config = connection.config
        if not isinstance(config, SSHConfig):
            raise RuntimeError("SSH 配置无效")

        program, args = build_ssh_terminal_command(config)
        if hasattr(self.terminal, "receivedData"):
            self.terminal.receivedData.connect(self._on_terminal_data)
        self.terminal.setShellProgram(program)
        self.terminal.setArgs(args)
        self.terminal.startShellProgram()

    def _on_terminal_data(self, chunk: str) -> None:
        """处理 SSH 首次连接时的交互提示。"""
        if not self._connection or not isinstance(self._connection.config, SSHConfig):
            return

        text = (chunk or "").lower()
        config = self._connection.config

        if (not self._auth_state["yes"]) and "are you sure you want to continue connecting" in text:
            self._auth_state["yes"] = True
            self.terminal.sendText("yes\n")
            return

        if (
            config.passphrase
            and not self._auth_state["passphrase"]
            and re.search(r"passphrase[^\n]{0,80}:", text)
        ):
            self._auth_state["passphrase"] = True
            self.terminal.sendText(config.passphrase + "\n")
            return

        if (
            config.password
            and not self._auth_state["password"]
            and re.search(r"password[^\n]{0,80}:", text)
        ):
            self._auth_state["password"] = True
            self.terminal.sendText(config.password + "\n")


class QTermDockerExecTerminalWidget(QTermTerminalWidget):
    """基于 qtermwidget 的 Docker 容器交互终端。"""

    def __init__(
        self,
        container_id: str,
        parent: Optional[QWidget] = None,
        app_config: Optional[AppConfig] = None,
        shell: str = "sh",
    ):
        super().__init__(parent=parent, app_config=app_config)
        self._container_id = container_id
        self._shell = shell

    def set_connection(self, connection: BaseConnection) -> None:
        """绑定 SSH 连接配置并启动 docker exec 会话。"""
        self._connection = connection
        self._sync_scope_enabled_state()
        if connection.config.connection_type != ConnectionType.SSH:
            raise RuntimeError("Docker 容器终端仅支持 SSH 连接")

        config = connection.config
        if not isinstance(config, SSHConfig):
            raise RuntimeError("SSH 配置无效")

        program, args = build_docker_exec_terminal_command(config, self._container_id, self._shell)
        if hasattr(self.terminal, "receivedData"):
            self.terminal.receivedData.connect(self._on_terminal_data)
        self.terminal.setShellProgram(program)
        self.terminal.setArgs(args)
        self.terminal.startShellProgram()


class QTermExternalTerminalWidget(_BaseQTermContainer):
    """基于 qtermwidget 的外部终端组件，适用于串口等字节流连接。"""

    def __init__(self, parent: Optional[QWidget] = None, app_config: Optional[AppConfig] = None):
        super().__init__(parent=parent, app_config=app_config)

    def set_connection(self, connection: BaseConnection) -> None:
        """绑定串口等外部连接。"""
        self._connection = connection
        self._sync_scope_enabled_state()
        if hasattr(connection, "on"):
            connection.on("data_received", self._on_data_received)

        if hasattr(self.terminal, "sendData"):
            self.terminal.sendData.connect(self._send_terminal_data)
        if hasattr(self.terminal, "startTerminalTeletype"):
            self.terminal.startTerminalTeletype()

    def _send_terminal_data(self, payload: bytes, length: int) -> None:
        """将 qtermwidget 输入写回底层连接。"""
        if not self._connection or not hasattr(self._connection, "write"):
            return
        try:
            data = payload[:length]
            self._connection.write(data)
        except Exception as exc:
            self._logger.debug("外部终端写入失败: %s", exc)

    def _on_data_received(self, data: bytes, *_args) -> None:
        """将连接收到的字节流渲染到 qtermwidget。"""
        try:
            payload = data if isinstance(data, bytes) else bytes(data)
            session = self.terminal.m_impl.m_session
            session.onReceiveBlock(payload, len(payload))
            self.output_appended.emit(payload.decode("utf-8", errors="replace"))
        except Exception as exc:
            self._logger.debug("外部终端渲染失败: %s", exc)

 
class QTermLocalTerminalWidget(_BaseQTermContainer):
    """本地终端组件。"""

    def __init__(self, parent: Optional[QWidget] = None, app_config: Optional[AppConfig] = None):
        super().__init__(parent=parent, app_config=app_config)
        self._start_local_shell()

    def _start_local_shell(self) -> None:
        program, args = build_local_terminal_command()
        self.terminal.setShellProgram(program)
        self.terminal.setArgs(args)
        self.terminal.startShellProgram()


class TerminalSplitWidget(QWidget):
    """双终端分屏容器。"""

    closed = Signal()
    command_executed = Signal(str)
    output_appended = Signal(str)
    execution_reported = Signal(object)
    snippets_changed = Signal(object)
    session_state_changed = Signal(object)

    def __init__(
        self,
        primary_terminal: QWidget,
        secondary_terminal: QWidget,
        parent: Optional[QWidget] = None,
        orientation: Qt.Orientation = Qt.Horizontal,
    ):
        super().__init__(parent)
        self._primary_terminal = primary_terminal
        self._secondary_terminal = secondary_terminal
        self._orientation = orientation
        self._logger = get_logger("TerminalSplitWidget")
        self._last_command_source: Optional[QWidget] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter(self._orientation, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._primary_terminal)
        self.splitter.addWidget(self._secondary_terminal)
        self.splitter.setSizes([1, 1])
        layout.addWidget(self.splitter, 1)

        self._bind_child_terminal(self._primary_terminal)
        self._bind_child_terminal(self._secondary_terminal)

    @property
    def primary_terminal(self) -> QWidget:
        """返回主终端组件。"""
        return self._primary_terminal

    @property
    def secondary_terminal(self) -> QWidget:
        """返回副终端组件。"""
        return self._secondary_terminal

    @property
    def connection(self):
        """优先返回主终端连接，用于系统监控等上层逻辑。"""
        primary = getattr(self._primary_terminal, "connection", None)
        if primary is not None:
            return primary
        return getattr(self._secondary_terminal, "connection", None)

    def _bind_child_terminal(self, widget: QWidget) -> None:
        if hasattr(widget, "command_executed"):
            widget.command_executed.connect(
                lambda command, source_widget=widget: self._forward_child_command(
                    source_widget,
                    command,
                )
            )
        if hasattr(widget, "output_appended"):
            widget.output_appended.connect(self.output_appended.emit)
        if hasattr(widget, "execution_reported"):
            widget.execution_reported.connect(self.execution_reported.emit)
        if hasattr(widget, "snippets_changed"):
            widget.snippets_changed.connect(self.snippets_changed.emit)
        if hasattr(widget, "session_state_changed"):
            widget.session_state_changed.connect(self.session_state_changed.emit)

    def _forward_child_command(self, source_widget: QWidget, command: str) -> None:
        """转发子终端命令，并记录最近的来源子终端。"""
        self._last_command_source = source_widget
        self.command_executed.emit(command)

    def _refresh_summary(self) -> None:
        """保留兼容接口，避免旧调用失效。"""
        return None

    def toggle_orientation(self) -> None:
        """切换分屏方向。"""
        self._orientation = Qt.Vertical if self._orientation == Qt.Horizontal else Qt.Horizontal
        self.splitter.setOrientation(self._orientation)
        self._refresh_summary()

    def apply_preferences(self, app_config: AppConfig) -> None:
        """把终端设置同步给分屏中的两个终端。"""
        for widget in (self._primary_terminal, self._secondary_terminal):
            if hasattr(widget, "apply_preferences"):
                widget.apply_preferences(app_config)

    def apply_session_state(self, session_data: Optional[dict[str, object]]) -> None:
        """把会话级终端数据同步给分屏中的两个终端。"""
        for widget in (self._primary_terminal, self._secondary_terminal):
            if hasattr(widget, "apply_session_state"):
                widget.apply_session_state(session_data)

    def export_session_state(self) -> dict[str, object]:
        """优先导出主终端的会话级数据。"""
        if hasattr(self._primary_terminal, "export_session_state"):
            return self._primary_terminal.export_session_state()
        if hasattr(self._secondary_terminal, "export_session_state"):
            return self._secondary_terminal.export_session_state()
        return {}

    def execute_broadcast_command(self, command: str) -> None:
        """将同步输入广播到分屏中的两个终端。"""
        for widget in (self._primary_terminal, self._secondary_terminal):
            if hasattr(widget, "execute_broadcast_command"):
                widget.execute_broadcast_command(command)

    def execute_broadcast_command_to_peer(self, command: str) -> int:
        """仅广播到最近命令来源之外的分屏子终端。"""
        delivered = 0
        for widget in (self._primary_terminal, self._secondary_terminal):
            if widget is self._last_command_source:
                continue
            if hasattr(widget, "execute_broadcast_command"):
                widget.execute_broadcast_command(command)
                delivered += 1
        return delivered

    def close_terminals(self) -> None:
        """关闭分屏中的全部终端组件。"""
        for widget in (self._primary_terminal, self._secondary_terminal):
            try:
                widget.close()
            except Exception as exc:
                self._logger.debug("关闭分屏终端失败 [%s]: %s", type(widget).__name__, exc)

    def close(self) -> None:
        self.close_terminals()
        self.closed.emit()
        super().close()


class TerminalWidget(QWidget):
    """
    终端组件
    
    提供：
    - 终端显示
    - 命令输入
    - 历史命令
    - 字体和颜色配置
    
    Signals:
        command_executed: 命令执行时发出
        closed: 终端关闭时发出
    """
    
    # 信号
    command_executed = Signal(str)  # command
    output_appended = Signal(str)
    execution_reported = Signal(object)
    closed = Signal()
    snippets_changed = Signal(object)
    session_state_changed = Signal(object)
    file_browser_requested = Signal()
    split_requested = Signal()
    sync_toggle_requested = Signal()
    command_center_requested = Signal()
    compose_requested = Signal()
    quick_inspection_requested = Signal()
    
    def __init__(self, parent: Optional[QWidget] = None, app_config: Optional[AppConfig] = None):
        super().__init__(parent)
        
        self._logger = get_logger('TerminalWidget')
        self._connection: Optional[BaseConnection] = None
        self._app_config = app_config or AppConfig()
        self._status_handler = None
        self._snippet_groups = _config_snippet_groups(self._app_config)
        self._favorite_snippets = _config_favorite_snippets(self._app_config, self._snippet_groups)
        self._macros = _config_macros(self._app_config)
        self._session_snippet_groups: dict[str, list[str]] = {}
        self._session_favorite_snippets: list[str] = []
        self._session_macros: dict[str, list[str]] = {}
        self._command_history: list = []
        self._history_index = -1
        self._command_index = load_command_index()
        self._completion_model = QStringListModel(self)
        self._completer = QCompleter(self._completion_model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        
        self._setup_ui()
        self._setup_terminal()

    @property
    def connection(self) -> Optional[BaseConnection]:
        """获取当前绑定的连接。"""
        return self._connection
        
    def _setup_ui(self) -> None:
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 终端显示区
        self.terminal_display = QPlainTextEdit()
        self.terminal_display.setReadOnly(True)
        self.terminal_display.setFont(QFont("Monospace", 10))
        self.terminal_display.setContextMenuPolicy(Qt.CustomContextMenu)
        self.terminal_display.customContextMenuRequested.connect(
            self._show_terminal_display_context_menu
        )
        layout.addWidget(self.terminal_display)
        
        # 命令输入区
        input_layout = QHBoxLayout()
        input_layout.setSpacing(4)
        
        self.prompt_label = QLabel("$")
        self.prompt_label.setFont(QFont("Monospace", 10))
        input_layout.addWidget(self.prompt_label)
        
        self.command_input = QLineEdit()
        self.command_input.setFont(QFont("Monospace", 10))
        self.command_input.setCompleter(self._completer)
        self.command_input.setPlaceholderText(
            self.tr("输入命令后回车，右键查看更多操作")
        )
        self.command_input.returnPressed.connect(self._execute_command)
        self.command_input.textEdited.connect(self._update_completions)
        input_layout.addWidget(self.command_input)
        
        layout.addLayout(input_layout)

        self.context_hint_label = QLabel(
            self.tr("右键终端可用：搜索、工作区、快捷命令、命令宏、显示。"),
            self,
        )
        self.context_hint_label.setObjectName("panelMeta")
        self.context_hint_label.setWordWrap(True)
        self.context_hint_label.hide()

        self._control_panel = QWidget(self)
        self._control_panel.hide()
        control_layout = QVBoxLayout(self._control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(8)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        
        self.clear_btn = QPushButton(self.tr("清屏"))
        self.clear_btn.setProperty("secondary", True)
        self.clear_btn.clicked.connect(self.clear_terminal)
        toolbar.addWidget(self.clear_btn)
        self.search_toggle_btn = QPushButton(self.tr("搜索"))
        self.search_toggle_btn.clicked.connect(self._toggle_search_bar)
        toolbar.addWidget(self.search_toggle_btn)

        self.scroll_top_btn = QPushButton(self.tr("顶部"))
        self.scroll_top_btn.clicked.connect(self._scroll_to_output_top)
        toolbar.addWidget(self.scroll_top_btn)

        self.scroll_bottom_btn = QPushButton(self.tr("底部"))
        self.scroll_bottom_btn.clicked.connect(self._scroll_to_output_bottom)
        toolbar.addWidget(self.scroll_bottom_btn)

        toolbar.addWidget(QLabel(self.tr("范围:")))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems([self.tr("全局"), self.tr("会话")])
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        toolbar.addWidget(self.scope_combo)

        toolbar.addSpacing(6)
        toolbar.addWidget(QLabel(self.tr("主题:")))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(get_terminal_theme_choices())
        self.theme_combo.setCurrentText(normalize_terminal_theme(self._app_config.terminal_theme))
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self.theme_combo.setMaximumWidth(150)
        toolbar.addWidget(self.theme_combo)
        
        toolbar.addStretch()
        
        # 字体大小
        toolbar.addWidget(QLabel(self.tr("字体:")))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 24)
        self.font_size_spin.setValue(self._app_config.terminal_font_size)
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        toolbar.addWidget(self.font_size_spin)
        
        control_layout.addLayout(toolbar)

        self.search_bar = QWidget()
        search_layout = QHBoxLayout(self.search_bar)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)
        search_layout.addWidget(QLabel(self.tr("查找:")))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self.tr("输入关键字后回车定位"))
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.returnPressed.connect(self._find_next_match)
        search_layout.addWidget(self.search_edit, 1)
        self.search_prev_btn = QPushButton(self.tr("上一个"))
        self.search_prev_btn.clicked.connect(self._find_previous_match)
        search_layout.addWidget(self.search_prev_btn)
        self.search_next_btn = QPushButton(self.tr("下一个"))
        self.search_next_btn.clicked.connect(self._find_next_match)
        search_layout.addWidget(self.search_next_btn)
        self.search_status_label = QLabel(self.tr("未搜索"))
        search_layout.addWidget(self.search_status_label)
        self.search_close_btn = QPushButton(self.tr("关闭"))
        self.search_close_btn.clicked.connect(lambda: self._toggle_search_bar(False))
        search_layout.addWidget(self.search_close_btn)
        self.search_bar.hide()
        layout.addWidget(self.search_bar)
        self._search_shortcut = QShortcut(QKeySequence.Find, self)
        self._search_shortcut.activated.connect(lambda: self._toggle_search_bar(True))

        commands_toolbar = QHBoxLayout()
        commands_toolbar.setSpacing(4)
        commands_toolbar.addWidget(QLabel(self.tr("命令组:")))
        self.group_combo = QComboBox()
        self.group_combo.setMaximumWidth(120)
        self.group_combo.currentTextChanged.connect(self._on_group_changed)
        commands_toolbar.addWidget(self.group_combo)

        commands_toolbar.addWidget(QLabel(self.tr("快捷命令:")))
        self.snippet_combo = QComboBox()
        self.snippet_combo.setEditable(True)
        self.snippet_combo.setInsertPolicy(QComboBox.NoInsert)
        self.snippet_combo.setMaximumWidth(260)
        line_edit = self.snippet_combo.lineEdit()
        if line_edit is not None:
            line_edit.returnPressed.connect(self._run_selected_snippet)
        commands_toolbar.addWidget(self.snippet_combo)

        self.favorite_snippet_btn = QPushButton(self.tr("收藏"))
        self.favorite_snippet_btn.clicked.connect(self._toggle_favorite_current_snippet)
        commands_toolbar.addWidget(self.favorite_snippet_btn)

        self.run_snippet_btn = QPushButton(self.tr("运行"))
        self.run_snippet_btn.clicked.connect(self._run_selected_snippet)
        commands_toolbar.addWidget(self.run_snippet_btn)

        self.save_snippet_btn = QPushButton(self.tr("保存"))
        self.save_snippet_btn.clicked.connect(self._save_current_snippet)
        commands_toolbar.addWidget(self.save_snippet_btn)

        self.delete_snippet_btn = QPushButton(self.tr("删除"))
        self.delete_snippet_btn.clicked.connect(self._delete_current_snippet)
        commands_toolbar.addWidget(self.delete_snippet_btn)
        commands_toolbar.addStretch()
        control_layout.addLayout(commands_toolbar)

        macro_toolbar = QHBoxLayout()
        macro_toolbar.setSpacing(4)
        macro_toolbar.addWidget(QLabel(self.tr("命令宏:")))
        self.macro_combo = QComboBox()
        self.macro_combo.setEditable(False)
        self.macro_combo.setMaximumWidth(220)
        macro_toolbar.addWidget(self.macro_combo)

        self.run_macro_btn = QPushButton(self.tr("执行宏"))
        self.run_macro_btn.clicked.connect(self._run_selected_macro)
        macro_toolbar.addWidget(self.run_macro_btn)

        self.save_macro_btn = QPushButton(self.tr("保存宏"))
        self.save_macro_btn.clicked.connect(self._save_current_macro)
        macro_toolbar.addWidget(self.save_macro_btn)

        self.delete_macro_btn = QPushButton(self.tr("删除宏"))
        self.delete_macro_btn.clicked.connect(self._delete_current_macro)
        macro_toolbar.addWidget(self.delete_macro_btn)
        macro_toolbar.addStretch()
        control_layout.addLayout(macro_toolbar)

        self._refresh_group_combo()
        self._refresh_snippet_combo()
        self._refresh_macro_combo()
        self._sync_favorite_button()
        self._sync_scope_enabled_state()
        self._apply_visual_theme()
        
    def _setup_terminal(self) -> None:
        """设置终端"""
        self.append_output(f"{APP_NAME} 终端 v{format_version_display()}\n")
        self.append_output("输入 'help' 查看可用命令\n\n")
        
    def set_connection(self, connection: BaseConnection) -> None:
        """
        设置关联的连接
        
        Args:
            connection: 连接实例
        """
        # 解绑旧连接的状态监听，避免重复提示。
        if self._connection is not None and self._status_handler is not None and hasattr(self._connection, "off"):
            try:
                self._connection.off("status_changed", self._status_handler)
            except Exception:
                pass
        self._connection = connection
        self._sync_scope_enabled_state()
        
        # 连接数据接收信号
        if hasattr(connection, 'on'):
            connection.on('data_received', self._on_data_received)

        if hasattr(connection, "on"):
            def _on_status_changed(new_status: ConnectionStatus, old_status: ConnectionStatus) -> None:
                if new_status == ConnectionStatus.RECONNECTING:
                    self.append_output(self.tr("\n[连接] 断线，正在重连...\n"))
                elif new_status == ConnectionStatus.CONNECTED and old_status == ConnectionStatus.RECONNECTING:
                    self.append_output(self.tr("[连接] 重连成功。\n"))
                elif new_status == ConnectionStatus.DISCONNECTED:
                    self.append_output(self.tr("\n[连接] 已断开。\n"))
                elif new_status == ConnectionStatus.ERROR:
                    error_text = getattr(connection, "last_error", None) or self.tr("未知错误")
                    self.append_output(self.tr(f"\n[连接] 错误: {error_text}\n"))

            self._status_handler = _on_status_changed
            connection.on("status_changed", _on_status_changed)

        if getattr(connection, 'prefers_shell_commands', False) and hasattr(connection, 'open_shell'):
            try:
                connection.open_shell()
                self.append_output(self.tr("已开启交互式会话\n"))
            except Exception as exc:
                self.append_output(self.tr(f"开启交互式会话失败: {exc}\n"))

    def apply_preferences(self, app_config: AppConfig) -> None:
        """应用终端配置。"""
        self._app_config = app_config
        groups = _config_snippet_groups(app_config)
        favorites = _config_favorite_snippets(app_config, groups)
        self._set_snippet_state(groups, favorites)
        self._set_macro_state(_config_macros(app_config))
        self.theme_combo.setCurrentText(normalize_terminal_theme(app_config.terminal_theme))
        self.font_size_spin.setValue(app_config.terminal_font_size)
        self._apply_visual_theme()

    def apply_session_state(self, session_data: Optional[dict[str, object]]) -> None:
        """应用会话级快捷命令与宏。"""
        payload = session_data or {}
        self._set_session_state(
            payload.get("session_snippet_groups"),
            payload.get("session_favorite_snippets"),
            payload.get("session_macros"),
        )

    def export_session_state(self) -> dict[str, object]:
        """导出当前会话级终端数据。"""
        return _session_payload(
            self._session_snippet_groups,
            self._session_favorite_snippets,
            self._session_macros,
        )

    def _current_scope(self) -> str:
        return "session" if self.scope_combo.currentIndex() == 1 else "global"

    def _current_scope_groups(self) -> dict[str, list[str]]:
        return self._session_snippet_groups if self._current_scope() == "session" else self._snippet_groups

    def _current_scope_favorites(self) -> list[str]:
        return self._session_favorite_snippets if self._current_scope() == "session" else self._favorite_snippets

    def _current_scope_macros(self) -> dict[str, list[str]]:
        return self._session_macros if self._current_scope() == "session" else self._macros

    def _set_macro_state(
        self,
        macros: object,
        *,
        emit_signal: bool = False,
        preferred_name: Optional[str] = None,
    ) -> None:
        normalized_macros = normalize_terminal_macros(macros, allow_empty=True)
        if normalized_macros == self._macros:
            return
        self._macros = normalized_macros
        self._refresh_macro_combo()
        if preferred_name and preferred_name in self._macros:
            self.macro_combo.setCurrentText(preferred_name)
        if emit_signal:
            payload = _snippet_payload(self._snippet_groups, self._favorite_snippets)
            payload["terminal_macros"] = dict(self._macros)
            self.snippets_changed.emit(payload)

    def _set_session_state(
        self,
        groups: object,
        favorites: object,
        macros: object,
        *,
        emit_signal: bool = False,
        preferred_group: Optional[str] = None,
        preferred_command: Optional[str] = None,
        preferred_macro: Optional[str] = None,
    ) -> None:
        normalized_groups = normalize_terminal_snippet_groups(groups, allow_empty=True)
        normalized_favorites = normalize_terminal_favorite_snippets(
            favorites,
            normalized_groups,
            allow_empty=True,
        )
        normalized_macros = normalize_terminal_macros(macros, allow_empty=True)
        if (
            normalized_groups == self._session_snippet_groups
            and normalized_favorites == self._session_favorite_snippets
            and normalized_macros == self._session_macros
        ):
            return
        self._session_snippet_groups = normalized_groups
        self._session_favorite_snippets = normalized_favorites
        self._session_macros = normalized_macros
        self._refresh_group_combo()
        self._refresh_snippet_combo()
        self._refresh_macro_combo()
        if preferred_group:
            self.group_combo.setCurrentText(preferred_group)
        if preferred_command:
            self.snippet_combo.setCurrentText(preferred_command)
        if preferred_macro:
            self.macro_combo.setCurrentText(preferred_macro)
        self._sync_favorite_button()
        self._sync_scope_enabled_state()
        if emit_signal:
            self.session_state_changed.emit(self.export_session_state())

    def _refresh_macro_combo(self) -> None:
        current_name = self.macro_combo.currentText().strip() if hasattr(self, "macro_combo") else ""
        macros = list(self._current_scope_macros().keys())
        self.macro_combo.blockSignals(True)
        self.macro_combo.clear()
        self.macro_combo.addItems(macros)
        if current_name and current_name in macros:
            self.macro_combo.setCurrentText(current_name)
        self.macro_combo.blockSignals(False)
        self.run_macro_btn.setEnabled(bool(macros))
        self.delete_macro_btn.setEnabled(bool(macros))

    def _sync_scope_enabled_state(self) -> None:
        is_session = self._current_scope() == "session"
        has_connection = self._connection is not None
        self.scope_combo.setToolTip(
            self.tr("会话范围会跟随当前连接保存") if has_connection else self.tr("本地终端仅保留当前窗口会话范围")
        )
        self.save_macro_btn.setText(self.tr("保存会话宏") if is_session else self.tr("保存宏"))
        self.save_snippet_btn.setText(self.tr("保存到会话") if is_session else self.tr("保存"))

    def _refresh_group_combo(self) -> None:
        current_group = self._current_group_name()
        group_names = [_favorite_group_label(), *self._current_scope_groups().keys()]
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItems(group_names)
        self.group_combo.setCurrentText(current_group or group_names[0])
        self.group_combo.blockSignals(False)

    def _commands_for_current_group(self) -> list[str]:
        group_name = self._current_group_name()
        if group_name == _favorite_group_label():
            return list(self._current_scope_favorites())
        return list(self._current_scope_groups().get(group_name, []))

    def _refresh_snippet_combo(self) -> None:
        current_text = self._current_snippet_text()
        commands = self._commands_for_current_group()
        self.snippet_combo.blockSignals(True)
        self.snippet_combo.clear()
        self.snippet_combo.addItems(commands)
        self.snippet_combo.setCurrentText(current_text or (commands[0] if commands else ""))
        self.snippet_combo.blockSignals(False)
        self._sync_favorite_button()

    def _current_snippet_text(self) -> str:
        return self.snippet_combo.currentText().strip()

    def _current_group_name(self) -> str:
        current = self.group_combo.currentText().strip() if hasattr(self, "group_combo") else ""
        if current:
            return current
        return _favorite_group_label()

    def _selected_group_for_save(self) -> str:
        group_name = self._current_group_name()
        if group_name == _favorite_group_label():
            return _default_snippet_group_name()
        return group_name or _default_snippet_group_name()

    def _set_snippet_state(
        self,
        groups: object,
        favorites: object,
        emit_signal: bool = False,
        preferred_group: Optional[str] = None,
        preferred_command: Optional[str] = None,
    ) -> None:
        normalized_groups = normalize_terminal_snippet_groups(groups)
        normalized_favorites = normalize_terminal_favorite_snippets(favorites, normalized_groups)
        if (
            normalized_groups == self._snippet_groups
            and normalized_favorites == self._favorite_snippets
        ):
            return
        self._snippet_groups = normalized_groups
        self._favorite_snippets = normalized_favorites
        current_group = preferred_group or self._current_group_name()
        current_command = preferred_command or self._current_snippet_text()
        self._refresh_group_combo()
        if current_group in {_favorite_group_label(), *self._snippet_groups.keys()}:
            self.group_combo.setCurrentText(current_group)
        self._refresh_snippet_combo()
        if current_command:
            self.snippet_combo.setCurrentText(current_command)
        self._sync_favorite_button()
        if emit_signal:
            payload = _snippet_payload(self._snippet_groups, self._favorite_snippets)
            payload["terminal_macros"] = dict(self._macros)
            self.snippets_changed.emit(payload)

    def _run_selected_snippet(self) -> None:
        command = self._current_snippet_text()
        if not command:
            return
        self.command_input.setText(command)
        self._execute_command()

    def _save_current_snippet(self) -> None:
        command = self._current_snippet_text()
        if not command:
            return
        group_name = self._selected_group_for_save()
        groups = {name: list(commands) for name, commands in self._current_scope_groups().items()}
        groups.setdefault(group_name, [])
        groups[group_name].append(command)
        if self._current_scope() == "session":
            self._set_session_state(
                groups,
                self._current_scope_favorites(),
                self._current_scope_macros(),
                emit_signal=True,
                preferred_group=group_name,
                preferred_command=command,
            )
        else:
            self._set_snippet_state(
                groups,
                self._favorite_snippets,
                emit_signal=True,
                preferred_group=group_name,
                preferred_command=command,
            )
        self.snippet_combo.setCurrentText(command)

    def _delete_current_snippet(self) -> None:
        command = self._current_snippet_text()
        if not command:
            return
        groups = {
            name: [item for item in commands if item != command]
            for name, commands in self._current_scope_groups().items()
        }
        groups = {name: commands for name, commands in groups.items() if commands}
        favorites = [item for item in self._current_scope_favorites() if item != command]
        if self._current_scope() == "session":
            self._set_session_state(
                groups,
                favorites,
                self._current_scope_macros(),
                emit_signal=True,
            )
        else:
            self._set_snippet_state(groups, favorites, emit_signal=True)

    def _toggle_favorite_current_snippet(self) -> None:
        command = self._current_snippet_text()
        if not command:
            return
        favorites = list(self._current_scope_favorites())
        if command in favorites:
            favorites = [item for item in favorites if item != command]
        else:
            favorites.append(command)
        if self._current_scope() == "session":
            self._set_session_state(
                self._current_scope_groups(),
                favorites,
                self._current_scope_macros(),
                emit_signal=True,
                preferred_group=self._current_group_name(),
                preferred_command=command,
            )
        else:
            self._set_snippet_state(
                self._snippet_groups,
                favorites,
                emit_signal=True,
                preferred_group=self._current_group_name(),
                preferred_command=command,
            )

    def _sync_favorite_button(self) -> None:
        command = self._current_snippet_text()
        is_favorite = bool(command and command in self._current_scope_favorites())
        self.favorite_snippet_btn.setText(self.tr("取消收藏") if is_favorite else self.tr("收藏"))

    def _on_group_changed(self, _group_name: str) -> None:
        self._refresh_snippet_combo()

    def _on_scope_changed(self, _index: int) -> None:
        self._refresh_group_combo()
        self._refresh_snippet_combo()
        self._refresh_macro_combo()
        self._sync_scope_enabled_state()

    def _selected_macro_name(self) -> str:
        return self.macro_combo.currentText().strip()

    def _run_selected_macro(self) -> None:
        macro_name = self._selected_macro_name()
        if not macro_name:
            return
        commands = self._current_scope_macros().get(macro_name, [])
        if not commands:
            return
        self.append_output(f"[宏] {macro_name}\n")
        for command in commands:
            self.append_output(f"$ {command}\n")
            self._perform_command_execution(command)

    def _save_current_macro(self) -> None:
        suggested_name = self._selected_macro_name() or self._current_snippet_text() or self.tr("新宏")
        macro_name, accepted = QInputDialog.getText(
            self,
            self.tr("保存命令宏"),
            self.tr("宏名称:"),
            text=suggested_name,
        )
        if not accepted:
            return
        macro_name = macro_name.strip()
        if not macro_name:
            return
        content, accepted = QInputDialog.getMultiLineText(
            self,
            self.tr("编辑命令宏"),
            self.tr("每行一条命令:"),
            self._current_snippet_text(),
        )
        if not accepted:
            return
        commands = [line.strip() for line in content.splitlines() if line.strip()]
        if not commands:
            return
        macros = {name: list(items) for name, items in self._current_scope_macros().items()}
        macros[macro_name] = commands
        if self._current_scope() == "session":
            self._set_session_state(
                self._current_scope_groups(),
                self._current_scope_favorites(),
                macros,
                emit_signal=True,
                preferred_macro=macro_name,
            )
        else:
            self._set_macro_state(macros, emit_signal=True, preferred_name=macro_name)

    def _delete_current_macro(self) -> None:
        macro_name = self._selected_macro_name()
        if not macro_name:
            return
        macros = {
            name: list(commands)
            for name, commands in self._current_scope_macros().items()
            if name != macro_name
        }
        if self._current_scope() == "session":
            self._set_session_state(
                self._current_scope_groups(),
                self._current_scope_favorites(),
                macros,
                emit_signal=True,
            )
        else:
            self._set_macro_state(macros, emit_signal=True)

    def _toggle_search_bar(self, visible: Optional[bool] = None) -> None:
        target = not self.search_bar.isVisible() if visible is None else bool(visible)
        self.search_bar.setVisible(target)
        if target:
            self.search_edit.setFocus(Qt.OtherFocusReason)
            self.search_edit.selectAll()

    def _copy_output_selection(self) -> None:
        """复制终端输出中的选中文本。"""
        self.terminal_display.copy()

    def _copy_all_output(self) -> None:
        """复制全部终端输出。"""
        QApplication.clipboard().setText(self.terminal_display.toPlainText())

    def _paste_clipboard_to_input(self) -> None:
        """将剪贴板内容粘贴到命令输入框。"""
        text = QApplication.clipboard().text()
        if not text:
            return
        self.command_input.setFocus(Qt.OtherFocusReason)
        self.command_input.insert(text)

    def _build_terminal_context_menu(self) -> QMenu:
        """构建经典终端的右键菜单。"""
        menu = QMenu(self)

        copy_action = menu.addAction(self.tr("复制"))
        copy_action.setEnabled(self.terminal_display.textCursor().hasSelection())
        copy_action.triggered.connect(self._copy_output_selection)

        paste_action = menu.addAction(self.tr("粘贴到输入框"))
        paste_action.setEnabled(bool(QApplication.clipboard().text()))
        paste_action.triggered.connect(self._paste_clipboard_to_input)

        clear_action = menu.addAction(self.tr("清屏"))
        clear_action.triggered.connect(self.clear_terminal)

        output_menu = menu.addMenu(self.tr("输出"))
        copy_all_action = output_menu.addAction(self.tr("复制全部输出"))
        copy_all_action.setEnabled(bool(self.terminal_display.toPlainText()))
        copy_all_action.triggered.connect(self._copy_all_output)

        search_action = output_menu.addAction(self.tr("搜索输出"))
        search_action.triggered.connect(lambda checked=False: self._toggle_search_bar(True))

        output_menu.addSeparator()

        scroll_top_action = output_menu.addAction(self.tr("跳到顶部"))
        scroll_top_action.triggered.connect(self._scroll_to_output_top)

        scroll_bottom_action = output_menu.addAction(self.tr("跳到底部"))
        scroll_bottom_action.triggered.connect(self._scroll_to_output_bottom)

        menu.addSeparator()
        _add_terminal_scope_menu(self, menu)
        _add_terminal_workspace_menu(self, menu)
        _add_terminal_snippet_menu(self, menu)
        _add_terminal_macro_menu(self, menu)
        menu.addSeparator()
        _add_terminal_display_menu(
            self,
            menu,
            current_theme_name=normalize_terminal_theme(self.theme_combo.currentText()),
            current_font_size=self.font_size_spin.value(),
            set_theme=lambda theme_name: self.theme_combo.setCurrentText(
                normalize_terminal_theme(theme_name)
            ),
            set_font_size=lambda font_size: self.font_size_spin.setValue(font_size),
        )
        return menu

    def _show_terminal_display_context_menu(self, pos) -> None:
        """显示经典终端输出区的右键菜单。"""
        menu = self._build_terminal_context_menu()
        menu.exec(self.terminal_display.viewport().mapToGlobal(pos))

    def _on_search_text_changed(self, text: str) -> None:
        query = text.strip()
        if not query:
            self.search_status_label.setText(self.tr("未搜索"))
            return
        source = self.terminal_display.toPlainText()
        count = source.lower().count(query.lower())
        self.search_status_label.setText(self.tr(f"{count} 个匹配"))

    def _find_in_output(self, backward: bool = False) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        found = (
            self.terminal_display.find(query, QTextDocument.FindBackward)
            if backward
            else self.terminal_display.find(query)
        )
        if found:
            return
        cursor = self.terminal_display.textCursor()
        cursor.movePosition(QTextCursor.End if backward else QTextCursor.Start)
        self.terminal_display.setTextCursor(cursor)
        wrapped_found = (
            self.terminal_display.find(query, QTextDocument.FindBackward)
            if backward
            else self.terminal_display.find(query)
        )
        if not wrapped_found:
            self.search_status_label.setText(self.tr("无匹配"))

    def _find_next_match(self) -> None:
        self._find_in_output(backward=False)

    def _find_previous_match(self) -> None:
        self._find_in_output(backward=True)

    def _scroll_to_output_top(self) -> None:
        cursor = self.terminal_display.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.terminal_display.setTextCursor(cursor)
        self.terminal_display.centerCursor()

    def _scroll_to_output_bottom(self) -> None:
        cursor = self.terminal_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.terminal_display.setTextCursor(cursor)
        self.terminal_display.centerCursor()

    def _apply_visual_theme(self) -> None:
        """让经典终端跟随当前应用主题。"""
        theme_name = normalize_terminal_theme(self.theme_combo.currentText())
        theme = ThemeManager.get_active_theme()
        terminal_theme = CLASSIC_TERMINAL_SCHEMES.get(theme_name, theme["terminal"])
        input_theme = theme["input"]
        widget_theme = theme["widget"]
        background = terminal_theme.get("background", theme["terminal"]["background"])
        foreground = terminal_theme.get("text", theme["terminal"]["text"])
        prompt = terminal_theme.get("prompt", theme["terminal"]["prompt"])
        border = terminal_theme.get("border", widget_theme["border"])

        self.terminal_display.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {background};
                color: {foreground};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 10px;
            }}
            """
        )
        self.prompt_label.setStyleSheet(f"color: {prompt}; font-weight: 700;")
        self.command_input.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: {input_theme['background']};
                color: {input_theme['text']};
                border: 1px solid {input_theme['border']};
                border-radius: 10px;
                padding: 7px 10px;
            }}
            QLineEdit:focus {{
                border-color: {input_theme['focus_border']};
            }}
            """
        )

    def _on_theme_changed(self, _theme_name: str) -> None:
        """切换经典终端主题。"""
        normalized_theme = normalize_terminal_theme(self.theme_combo.currentText())
        if self.theme_combo.currentText() != normalized_theme:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentText(normalized_theme)
            self.theme_combo.blockSignals(False)
        self._apply_visual_theme()

    def _build_command_bytes(self, command: str) -> bytes:
        """根据连接类型构造要发送的命令字节流。"""
        line_ending = getattr(getattr(self._connection, 'config', None), 'line_ending', "\n")
        return f"{command}{line_ending}".encode('utf-8')

    def send_command(self, command: str) -> None:
        """向当前连接发送一条命令。"""
        if not self._connection:
            raise RuntimeError("未连接到远程主机")
        payload = self._build_command_bytes(command)
        if hasattr(self._connection, 'write'):
            self._connection.write(payload)
            return
        if hasattr(self._connection, 'send'):
            self._connection.send(payload)
            return
        raise RuntimeError("当前连接不支持终端写入")

    def _perform_command_execution(
        self,
        command: str,
        *,
        emit_signal: bool = True,
        allow_builtin: bool = True,
    ) -> None:
        """执行命令发送逻辑，供常规输入和同步输入复用。"""
        if allow_builtin and self._handle_builtin_command(command):
            return

        if emit_signal:
            self.command_executed.emit(command)

        if (
            self._connection
            and getattr(self._connection, 'prefers_shell_commands', False)
            and hasattr(self._connection, 'write')
        ):
            try:
                self.send_command(command)
            except Exception as e:
                self.append_output(f"发送失败: {e}\n")
        elif self._connection and hasattr(self._connection, 'exec_command'):
            try:
                exit_code, stdout, stderr = self._connection.exec_command(command)
                if stdout:
                    self.append_output(stdout)
                if stderr:
                    self.append_output(f"错误: {stderr}")
                self.execution_reported.emit(
                    {
                        "command": command,
                        "exit_code": exit_code,
                        "stdout": stdout,
                        "stderr": stderr,
                        "completed_at": datetime.now().strftime("%H:%M:%S"),
                        "source": "exec_command",
                    }
                )
                self.append_output("\n")
            except Exception as e:
                self.append_output(f"执行失败: {e}\n")
                self.execution_reported.emit(
                    {
                        "command": command,
                        "exit_code": None,
                        "stdout": "",
                        "stderr": str(e),
                        "completed_at": datetime.now().strftime("%H:%M:%S"),
                        "source": "exec_command",
                    }
                )
        elif self._connection and hasattr(self._connection, 'write'):
            try:
                self.send_command(command)
            except Exception as e:
                self.append_output(f"发送失败: {e}\n")
        elif self._connection and hasattr(self._connection, 'send'):
            try:
                self.send_command(command)
            except Exception as e:
                self.append_output(f"发送失败: {e}\n")
        else:
            self.append_output("未连接到远程主机\n")

    def execute_broadcast_command(self, command: str) -> None:
        """执行来自主窗口同步输入栏的广播命令。"""
        normalized = (command or "").strip()
        if not normalized:
            return
        self.append_output(f"[同步] $ {normalized}\n")
        self._perform_command_execution(normalized, emit_signal=False, allow_builtin=False)

    def _update_completions(self, text: str) -> None:
        """根据当前输入更新补全候选。"""
        stripped = text.lstrip()
        commands = self._command_index.get("commands", [])
        options = self._command_index.get("options", {})

        if not stripped:
            self._completion_model.setStringList(list(commands))
            self._completer.setCompletionPrefix("")
            return

        parts = stripped.split()
        if len(parts) <= 1 and " " not in stripped:
            prefix = parts[0]
            candidates = [command for command in commands if command.startswith(prefix)]
            self._completion_model.setStringList(candidates)
            self._completer.setCompletionPrefix(prefix)
            return

        command = parts[0]
        last_token = parts[-1]
        if last_token.startswith("-"):
            candidates = [
                option
                for option in options.get(command, [])
                if option.startswith(last_token)
            ]
            self._completion_model.setStringList(candidates)
            self._completer.setCompletionPrefix(last_token)
            return

        self._completion_model.setStringList([])
        self._completer.setCompletionPrefix("")
            
    def append_output(self, text: str) -> None:
        """
        追加输出文本
        
        Args:
            text: 要追加的文本
        """
        self.terminal_display.moveCursor(QTextCursor.End)
        self.terminal_display.insertPlainText(text)
        self.terminal_display.ensureCursorVisible()
        if text:
            self.output_appended.emit(text)
        
    def clear_terminal(self) -> None:
        """清空终端"""
        self.terminal_display.clear()
        
    def _execute_command(self) -> None:
        """执行命令"""
        command = self.command_input.text().strip()
        if not command:
            return
            
        # 显示命令
        self.append_output(f"$ {command}\n")
        
        # 添加到历史
        self._command_history.append(command)
        self._history_index = len(self._command_history)
        
        # 清空输入
        self.command_input.clear()
        self._perform_command_execution(command)
            
    def _handle_builtin_command(self, command: str) -> bool:
        """
        处理内置命令
        
        Args:
            command: 命令字符串
            
        Returns:
            bool: 是否是内置命令
        """
        parts = command.split()
        if not parts:
            return False
            
        cmd = parts[0].lower()
        
        if cmd == 'help':
            self._show_help()
            return True
        elif cmd == 'clear':
            self.clear_terminal()
            return True
        elif cmd == 'exit':
            self.close()
            return True
            
        return False
        
    def _show_help(self) -> None:
        """显示帮助信息"""
        help_text = """
可用命令:
  help    - 显示帮助信息
  clear   - 清空终端
  exit    - 关闭终端

终端效率:
  搜索    - 点击“搜索”或按 Ctrl+F 查找输出
  作用域  - 可切换全局 / 会话快捷命令与命令宏
  命令宏  - 可保存并执行多条命令组成的宏

导航:
  Up      - 上一条历史命令
  Down    - 下一条历史命令
  顶部    - 跳到输出顶部
  底部    - 跳到输出底部

"""
        self.append_output(help_text)
        
    def _on_data_received(self, data: bytes, *_args) -> None:
        """
        数据接收回调
        
        Args:
            data: 接收到的数据
        """
        try:
            text = data.decode('utf-8', errors='replace')
            self.append_output(text)
        except Exception as e:
            self._logger.error(f"解码数据失败: {e}")
            
    def _on_font_size_changed(self, size: int) -> None:
        """字体大小改变"""
        font = self.terminal_display.font()
        font.setPointSize(size)
        self.terminal_display.setFont(font)
        self.command_input.setFont(font)
        self.prompt_label.setFont(font)
        
    def keyPressEvent(self, event) -> None:
        """键盘事件处理"""
        # 历史命令导航
        if event.key() == Qt.Key_Up:
            if self._history_index > 0:
                self._history_index -= 1
                self.command_input.setText(self._command_history[self._history_index])
        elif event.key() == Qt.Key_Down:
            if self._history_index < len(self._command_history) - 1:
                self._history_index += 1
                self.command_input.setText(self._command_history[self._history_index])
            else:
                self._history_index = len(self._command_history)
                self.command_input.clear()
        else:
            super().keyPressEvent(event)
            
    def close(self) -> None:
        """关闭终端"""
        if self._connection:
            if self._status_handler is not None and hasattr(self._connection, "off"):
                try:
                    self._connection.off("status_changed", self._status_handler)
                except Exception:
                    pass
            try:
                self._connection.disconnect()
            except Exception as e:
                self._logger.error(f"断开连接失败: {e}")
                
        self.closed.emit()
        super().close()
