#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口模块

提供 Neko_Shell 的主界面。
"""

from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
import shlex
import time
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QFrame,
    QSplitter,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from neko_shell.core.connection import (
    BaseConnection,
    ConnectionFactory,
    ConnectionStatus,
    ConnectionType,
)
from neko_shell.models.connection import SFTPConfig, SSHConfig
from neko_shell.ui.styles import ThemeManager
from neko_shell.utils import (
    ConfigManager,
    flatten_terminal_snippet_groups,
    get_logger,
    normalize_terminal_macros,
    normalize_terminal_favorite_snippets,
    normalize_terminal_snippet_groups,
    normalize_terminal_snippets,
)
from neko_shell.utils.exceptions import ConfigurationError

from .dialogs.connection_dialog import ConnectionDialog
from .dialogs.compose_dialog import ComposeCommandDialog
from .dialogs.command_center_dialog import CommandCenterDialog
from .dialogs.help_dialog import HelpDialog
from .dialogs.quick_open_dialog import QuickOpenDialog
from .dialogs.shared_library_approval_dialog import SharedLibraryApprovalDialog
from .dialogs.shared_library_integrity_dialog import SharedLibraryIntegrityDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.sync_history_dialog import SyncHistoryDialog
from .icons import app_icon, connection_type_icon, icon
from .widgets.connection_tree import ConnectionTreeWidget
from .widgets.docker_manager import DockerManagerWidget
from .widgets.file_browser import FileBrowserWidget
from .widgets.frp_widget import FRPWidget
from .widgets.system_monitor import SystemMonitorWidget
from .widgets.terminal_widget import (
    QTermDockerExecTerminalWidget,
    QTermExternalTerminalWidget,
    QTermLocalTerminalWidget,
    QTermTerminalWidget,
    TerminalSplitWidget,
    TerminalWidget,
    build_docker_exec_shell_command,
    should_use_qtermwidget,
)
from .widgets.tunnel_manager import TunnelManagerWidget
from .widgets.vnc_widget import VNCWidget


@dataclass
class SyncDispatchRecord:
    """同步输入发送记录。"""

    batch_id: int
    timestamp: str
    source_label: str
    scope_label: str
    command_count: int
    delivery_count: int
    target_count: int
    target_names: list[str]
    commands: list[str]
    failed_targets: list[str]
    target_connection_ids: list[str] = field(default_factory=list)
    source_kind: str = "compose"
    origin_batch_id: Optional[int] = None
    retry_mode: Optional[str] = None
    scope_key: Optional[str] = None
    task_preset_key: Optional[str] = None
    task_preset_title: Optional[str] = None
    task_template_label: Optional[str] = None
    target_type_key: Optional[str] = None
    target_filter_label: Optional[str] = None
    target_group_key: Optional[str] = None
    target_group_label: Optional[str] = None
    archive_tags: list[str] = field(default_factory=list)
    result_excerpt: str = ""
    result_excerpt_updated_at: Optional[str] = None
    result_sample_count: int = 0
    target_result_entries: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class SharedLibraryShareMenuBindings:
    """共享与同步子菜单动作集合。"""

    menu: QMenu
    import_action: QAction
    publish_action: QAction
    remove_action: QAction
    push_action: QAction
    pull_action: QAction
    status_action: QAction
    history_action: QAction
    approval_action: QAction
    integrity_action: QAction
    governance_action: QAction
    report_action: QAction


@dataclass(frozen=True)
class TaskPresetDefinition:
    """终端任务预设定义。"""

    key: str
    title: str
    keywords: tuple[str, ...]
    default_commands: tuple[str, ...]


class MainWindow(QMainWindow):
    """
    Neko_Shell 主窗口

    主界面包含：
    - 连接管理面板（左侧）
    - 工作区（终端/文件浏览器等）
    - 系统监控面板（底部）
    - 工具栏和菜单

    Signals:
        connection_created: 连接创建时发出
        connection_closed: 连接关闭时发出
    """

    # 信号
    connection_created = Signal(object)  # BaseConnection
    connection_closed = Signal(str)  # connection_id
    SYNC_SCOPE_ALL = "all"
    SYNC_SCOPE_SAME_TYPE = "same_type"
    SYNC_SCOPE_SAME_CONNECTION = "same_connection"
    SYNC_TARGET_TYPE_ALL = "__all_types__"
    SYNC_TARGET_TYPE_LOCAL = "__local_terminal__"
    SYNC_TARGET_GROUP_ALL = "__all_targets__"
    SYNC_TARGET_GROUP_REMOTE = "__remote_targets__"
    SYNC_TARGET_GROUP_LOCAL = "__local_targets__"
    SYNC_TARGET_GROUP_FAVORITE = "__favorite_targets__"
    SYNC_TARGET_GROUP_RECENT = "__recent_targets__"
    SYNC_HISTORY_LIMIT = 50
    TASK_PRESET_ORDER = (
        "quick_inspection",
        "system_inspection",
        "network_inspection",
        "disk_inspection",
        "log_sampling",
        "release_precheck",
    )
    TASK_PRESET_DEFINITIONS = {
        "quick_inspection": TaskPresetDefinition(
            key="quick_inspection",
            title="快速巡检",
            keywords=(
                "快速巡检",
                "系统巡检",
                "巡检",
                "检查",
                "inspection",
                "audit",
                "health",
            ),
            default_commands=(
                "pwd",
                "whoami",
                "hostname",
                "uptime",
                "df -h",
                "free -h",
                "uname -a",
            ),
        ),
        "system_inspection": TaskPresetDefinition(
            key="system_inspection",
            title="系统巡检",
            keywords=("系统巡检", "主机巡检", "system check", "host check"),
            default_commands=(
                "hostnamectl 2>/dev/null || hostname",
                "uptime",
                "free -h",
                "df -h",
                "systemctl --failed --no-pager",
            ),
        ),
        "network_inspection": TaskPresetDefinition(
            key="network_inspection",
            title="网络巡检",
            keywords=("网络巡检", "网络检查", "network check", "network inspection"),
            default_commands=(
                "hostname -I 2>/dev/null || ip addr show",
                "ip route",
                "ss -tulpn",
                "ping -c 1 127.0.0.1",
            ),
        ),
        "disk_inspection": TaskPresetDefinition(
            key="disk_inspection",
            title="磁盘巡检",
            keywords=("磁盘巡检", "磁盘检查", "disk check", "storage check"),
            default_commands=(
                "df -h",
                "lsblk",
                "du -sh /var/log 2>/dev/null",
                "du -sh /tmp 2>/dev/null",
            ),
        ),
        "log_sampling": TaskPresetDefinition(
            key="log_sampling",
            title="日志采样",
            keywords=("日志采样", "日志检查", "log sample", "journal check"),
            default_commands=(
                "journalctl -n 100 --no-pager 2>/dev/null",
                "dmesg | tail -n 50",
                "tail -n 100 /var/log/syslog 2>/dev/null || tail -n 100 /var/log/messages 2>/dev/null",
            ),
        ),
        "release_precheck": TaskPresetDefinition(
            key="release_precheck",
            title="发布前检查",
            keywords=("发布前检查", "上线前检查", "release check", "precheck"),
            default_commands=(
                "whoami",
                "hostname",
                "date",
                "df -h",
                "free -h",
                "systemctl --failed --no-pager",
            ),
        ),
    }
    QUICK_INSPECTION_KEYWORDS = TASK_PRESET_DEFINITIONS["quick_inspection"].keywords
    DEFAULT_QUICK_INSPECTION_COMMANDS = TASK_PRESET_DEFINITIONS["quick_inspection"].default_commands
    TASK_RESULT_CAPTURE_TTL_SECONDS = 30.0
    TASK_RESULT_CAPTURE_MAX_CHUNKS = 16
    TASK_RESULT_CAPTURE_MAX_CHARS = 2400
    TEMP_TERMINAL_PREFIX = "__terminal__:"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._logger = get_logger("MainWindow")
        self._config_manager: Optional[ConfigManager] = None
        self._connections: Dict[str, BaseConnection] = {}
        self._connection_configs: Dict[str, Dict[str, Any]] = {}
        self._connection_status_handlers: Dict[str, Any] = {}
        self._restoring_workspace = False
        self._sync_input_enabled = False
        self._sync_input_scope = self.SYNC_SCOPE_ALL
        self._sync_history: list[SyncDispatchRecord] = []
        self._next_sync_batch_id = 1
        self._sync_history_dialog: Optional[SyncHistoryDialog] = None
        self.favorite_connections_menu: Optional[QMenu] = None
        self.recent_connections_menu: Optional[QMenu] = None
        self.workspace_templates_menu: Optional[QMenu] = None
        self.connection_filter_presets_menu: Optional[QMenu] = None
        self._task_preset_actions: Dict[str, QAction] = {}
        self._active_task_archives: dict[int, list[dict[str, object]]] = {}
        self._workspace_primary_action_handler: Optional[Callable[[], None]] = None
        self._workspace_secondary_action_handler: Optional[Callable[[], None]] = None

        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._setup_connections()
        self._update_terminal_actions_state()

        self.setWindowTitle("Neko_Shell")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1024, 768)

    @staticmethod
    def _status_label_text(status: ConnectionStatus) -> str:
        return {
            ConnectionStatus.DISCONNECTED: "离线",
            ConnectionStatus.CONNECTING: "连接中",
            ConnectionStatus.CONNECTED: "已连接",
            ConnectionStatus.RECONNECTING: "重连中",
            ConnectionStatus.ERROR: "错误",
        }.get(status, "未知")

    def _register_connection_status_handler(
        self, conn_id: str, connection: BaseConnection
    ) -> SyncDispatchRecord:
        """把连接状态变化同步到连接树与状态栏。"""
        if not conn_id or conn_id in self._connection_status_handlers:
            return
        if not hasattr(connection, "on"):
            return

        def _on_status_changed(new_status: ConnectionStatus, _old_status: ConnectionStatus) -> None:
            # 临时 tab（__xxx__）没有对应树节点，update_connection_status 会自然忽略。
            self.connection_tree.update_connection_status(conn_id, new_status)

            current = self._current_tab_connection()
            if current is connection:
                name = getattr(getattr(connection, "config", None), "name", conn_id) or conn_id
                self.update_status(f"{name}: {self._status_label_text(new_status)}")

        connection.on("status_changed", _on_status_changed)
        self._connection_status_handlers[conn_id] = _on_status_changed

    def _unregister_connection_status_handler(
        self, conn_id: str, connection: BaseConnection
    ) -> None:
        handler = self._connection_status_handlers.pop(conn_id, None)
        if handler is None:
            return
        if hasattr(connection, "off"):
            try:
                connection.off("status_changed", handler)
            except Exception:
                pass

    def _setup_ui(self) -> None:
        """设置 UI 布局"""
        # 中央部件
        central_widget = QWidget()
        central_widget.setObjectName("shellRoot")
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # 分割器
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(10)
        main_layout.addWidget(self.main_splitter)

        # 左侧面板 - 连接管理
        self.connection_tree = ConnectionTreeWidget()
        self.connection_tree.setObjectName("sidePanel")
        self.connection_tree.setMaximumWidth(380)
        self.connection_tree.setMinimumWidth(260)
        self.main_splitter.addWidget(self.connection_tree)

        # 右侧工作区
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.main_splitter.addWidget(right_panel)

        self.workspace_header = QFrame()
        self.workspace_header.setObjectName("workspaceHeaderCard")
        self.workspace_header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        workspace_header_layout = QVBoxLayout(self.workspace_header)
        workspace_header_layout.setContentsMargins(12, 10, 12, 10)
        workspace_header_layout.setSpacing(4)
        workspace_title_row = QHBoxLayout()
        workspace_title_row.setContentsMargins(0, 0, 0, 0)
        workspace_title_row.setSpacing(6)
        self.workspace_title_label = QLabel(self.tr("个人工作台"))
        self.workspace_title_label.setObjectName("panelTitle")
        workspace_title_row.addWidget(self.workspace_title_label)
        workspace_title_row.addStretch()
        self.workspace_tab_count_badge = QLabel(self.tr("空闲"))
        self.workspace_tab_count_badge.setObjectName("summaryBadge")
        workspace_title_row.addWidget(self.workspace_tab_count_badge)
        workspace_header_layout.addLayout(workspace_title_row)

        self.workspace_subtitle_label = QLabel(
            self.tr("从左侧连接区打开终端、文件浏览器或本地终端。")
        )
        self.workspace_subtitle_label.setObjectName("panelMeta")
        self.workspace_subtitle_label.setWordWrap(True)
        workspace_header_layout.addWidget(self.workspace_subtitle_label)

        workspace_meta_row = QHBoxLayout()
        workspace_meta_row.setContentsMargins(0, 0, 0, 0)
        workspace_meta_row.setSpacing(6)
        self.workspace_context_badge = QLabel(self.tr("待开始"))
        self.workspace_context_badge.setObjectName("summaryBadge")
        workspace_meta_row.addWidget(self.workspace_context_badge)
        self.workspace_mode_badge = QLabel(self.tr("左侧双击连接可直接打开"))
        self.workspace_mode_badge.setObjectName("panelMeta")
        workspace_meta_row.addWidget(self.workspace_mode_badge)
        workspace_meta_row.addStretch()
        workspace_header_layout.addLayout(workspace_meta_row)

        workspace_action_row = QHBoxLayout()
        workspace_action_row.setContentsMargins(0, 0, 0, 0)
        workspace_action_row.setSpacing(6)
        self.workspace_primary_action_btn = QPushButton(self.tr("快速打开"))
        self.workspace_primary_action_btn.setIcon(icon("quick_connect"))
        self.workspace_primary_action_btn.clicked.connect(self._trigger_workspace_primary_action)
        workspace_action_row.addWidget(self.workspace_primary_action_btn)
        self.workspace_secondary_action_btn = QPushButton(self.tr("本地终端"))
        self.workspace_secondary_action_btn.setIcon(icon("local_terminal"))
        self.workspace_secondary_action_btn.setProperty("secondary", True)
        self.workspace_secondary_action_btn.clicked.connect(
            self._trigger_workspace_secondary_action
        )
        workspace_action_row.addWidget(self.workspace_secondary_action_btn)
        self.workspace_sync_toggle_btn = QPushButton(self.tr("同步输入"))
        self.workspace_sync_toggle_btn.setIcon(icon("terminal"))
        self.workspace_sync_toggle_btn.setProperty("secondary", True)
        self.workspace_sync_toggle_btn.clicked.connect(self._toggle_workspace_sync_input)
        workspace_action_row.addWidget(self.workspace_sync_toggle_btn)
        self.workspace_more_btn = QToolButton()
        self.workspace_more_btn.setObjectName("toolbarMenuButton")
        self.workspace_more_btn.setText(self.tr("更多"))
        self.workspace_more_btn.setIcon(icon("settings"))
        self.workspace_more_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.workspace_more_btn.setPopupMode(QToolButton.InstantPopup)
        workspace_action_row.addWidget(self.workspace_more_btn)
        workspace_action_row.addStretch()
        workspace_header_layout.addLayout(workspace_action_row)
        right_layout.addWidget(self.workspace_header)

        self.sync_input_bar = QWidget()
        self.sync_input_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        sync_root_layout = QVBoxLayout(self.sync_input_bar)
        sync_root_layout.setContentsMargins(10, 8, 10, 8)
        sync_root_layout.setSpacing(6)
        self.sync_input_bar.setObjectName("syncInputBar")
        sync_header_layout = QHBoxLayout()
        sync_header_layout.setContentsMargins(0, 0, 0, 0)
        sync_header_layout.setSpacing(6)
        self.sync_input_label = QLabel(self.tr("同步输入"))
        self.sync_input_label.setObjectName("panelTitle")
        sync_header_layout.addWidget(self.sync_input_label)

        self.sync_input_mode_badge = QLabel(self.tr("已关闭"))
        self.sync_input_mode_badge.setObjectName("summaryBadge")
        sync_header_layout.addWidget(self.sync_input_mode_badge)

        sync_header_layout.addStretch()
        self.sync_input_scope_combo = QComboBox()
        self.sync_input_scope_combo.addItem(self.tr("所有终端"), self.SYNC_SCOPE_ALL)
        self.sync_input_scope_combo.addItem(self.tr("同协议终端"), self.SYNC_SCOPE_SAME_TYPE)
        self.sync_input_scope_combo.addItem(self.tr("当前会话"), self.SYNC_SCOPE_SAME_CONNECTION)
        self.sync_input_scope_combo.currentIndexChanged.connect(self._on_sync_scope_changed)
        self.sync_input_scope_combo.setMinimumWidth(128)
        sync_header_layout.addWidget(self.sync_input_scope_combo)

        self.sync_actions_btn = QToolButton()
        self.sync_actions_btn.setObjectName("toolbarMenuButton")
        self.sync_actions_btn.setText(self.tr("更多"))
        self.sync_actions_btn.setIcon(icon("settings"))
        self.sync_actions_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.sync_actions_btn.setPopupMode(QToolButton.InstantPopup)
        sync_header_layout.addWidget(self.sync_actions_btn)

        self.sync_history_btn = QPushButton(self.tr("记录"))
        self.sync_history_btn.setProperty("secondary", True)
        self.sync_history_btn.clicked.connect(self._on_open_sync_history)
        sync_header_layout.addWidget(self.sync_history_btn)
        self.sync_collapse_btn = QPushButton(self.tr("收起"))
        self.sync_collapse_btn.setObjectName("syncCollapseButton")
        self.sync_collapse_btn.setProperty("secondary", True)
        self.sync_collapse_btn.clicked.connect(lambda: self.sync_input_action.setChecked(False))
        sync_header_layout.addWidget(self.sync_collapse_btn)
        sync_root_layout.addLayout(sync_header_layout)

        self.sync_input_hint_label = QLabel(self.tr("目标: 暂无匹配终端"))
        self.sync_input_hint_label.setObjectName("syncInputHint")
        self.sync_input_hint_label.setWordWrap(True)
        sync_root_layout.addWidget(self.sync_input_hint_label)

        sync_input_layout = QHBoxLayout()
        sync_input_layout.setContentsMargins(0, 0, 0, 0)
        sync_input_layout.setSpacing(8)
        self.sync_input_edit = QLineEdit()
        self.sync_input_edit.setPlaceholderText(self.tr("输入后回车，可同步发送到已打开终端"))
        self.sync_input_edit.returnPressed.connect(self._on_sync_input_submitted)
        sync_input_layout.addWidget(self.sync_input_edit, 1)
        self.sync_input_send_btn = QPushButton(self.tr("发送"))
        self.sync_input_send_btn.clicked.connect(self._on_sync_input_submitted)
        sync_input_layout.addWidget(self.sync_input_send_btn)
        sync_root_layout.addLayout(sync_input_layout)

        self.sync_result_label = QLabel(self.tr("最近发送: 暂无"))
        self.sync_result_label.setObjectName("syncResultLabel")
        self.sync_result_label.setWordWrap(True)
        self.sync_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sync_root_layout.addWidget(self.sync_result_label)
        self.sync_input_bar.hide()
        right_layout.addWidget(self.sync_input_bar)

        self.work_splitter = QSplitter(Qt.Vertical)
        self.work_splitter.setHandleWidth(10)
        right_layout.addWidget(self.work_splitter, 1)

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.setObjectName("workspaceStack")

        self.work_empty_state = self._create_workspace_empty_state()
        self.workspace_stack.addWidget(self.work_empty_state)

        # 工作区标签页
        self.work_tabs = QTabWidget()
        self.work_tabs.setObjectName("workspaceTabs")
        self.work_tabs.setTabsClosable(True)
        self.work_tabs.setMovable(True)
        self.work_tabs.setDocumentMode(True)
        self.workspace_stack.addWidget(self.work_tabs)
        self.work_splitter.addWidget(self.workspace_stack)

        # 系统监控面板
        self.system_monitor = SystemMonitorWidget()
        self.system_monitor.setObjectName("monitorPanel")
        self.system_monitor.setMaximumHeight(240)
        self.system_monitor.setMinimumHeight(116)
        self.work_splitter.addWidget(self.system_monitor)

        # 设置分割比例
        self.main_splitter.setSizes([320, 1120])
        self.work_splitter.setSizes([700, 140])
        self._update_workspace_empty_state()

    def _setup_menu(self) -> None:
        """设置菜单栏"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu(self.tr("文件(&F)"))

        new_conn_action = QAction(self.tr("新建连接(&N)"), self)
        new_conn_action.setIcon(icon("new_connection"))
        new_conn_action.setShortcut(QKeySequence.New)
        new_conn_action.triggered.connect(self._on_new_connection)
        file_menu.addAction(new_conn_action)

        quick_open_action = QAction(self.tr("快速打开(&P)"), self)
        quick_open_action.setIcon(icon("quick_connect"))
        quick_open_action.setShortcut(QKeySequence("Ctrl+P"))
        quick_open_action.triggered.connect(self._on_quick_open)
        file_menu.addAction(quick_open_action)

        self.favorite_connections_menu = file_menu.addMenu(self.tr("收藏连接"))
        self.favorite_connections_menu.setIcon(icon("quick_connect"))

        self.recent_connections_menu = file_menu.addMenu(self.tr("最近连接"))
        self.recent_connections_menu.setIcon(icon("quick_connect"))

        self.workspace_templates_menu = file_menu.addMenu(self.tr("工作区模板"))
        self.workspace_templates_menu.setIcon(icon("quick_connect"))
        self.workspace_templates_menu.aboutToShow.connect(
            lambda: self._populate_workspace_template_menu(self.workspace_templates_menu)
        )

        import_connections_action = QAction(self.tr("导入连接"), self)
        import_connections_action.triggered.connect(self._on_import_connections)
        file_menu.addAction(import_connections_action)

        export_connections_action = QAction(self.tr("导出连接"), self)
        export_connections_action.triggered.connect(self._on_export_connections)
        file_menu.addAction(export_connections_action)

        tunnel_action = QAction(self.tr("SSH 隧道(&T)"), self)
        tunnel_action.setIcon(icon("tunnel"))
        tunnel_action.triggered.connect(self._on_show_tunnels)
        file_menu.addAction(tunnel_action)

        local_terminal_action = QAction(self.tr("本地终端(&L)"), self)
        local_terminal_action.setIcon(icon("local_terminal"))
        local_terminal_action.triggered.connect(self._on_open_local_terminal)
        file_menu.addAction(local_terminal_action)

        docker_action = QAction(self.tr("Docker(&D)"), self)
        docker_action.setIcon(icon("docker"))
        docker_action.triggered.connect(self._on_show_docker)
        file_menu.addAction(docker_action)

        frp_action = QAction(self.tr("FRP(&R)"), self)
        frp_action.setIcon(icon("frp"))
        frp_action.triggered.connect(self._on_show_frp)
        file_menu.addAction(frp_action)

        file_menu.addSeparator()

        exit_action = QAction(self.tr("退出(&X)"), self)
        exit_action.setIcon(icon("delete"))
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 编辑菜单
        edit_menu = menubar.addMenu(self.tr("编辑(&E)"))

        settings_action = QAction(self.tr("设置(&S)"), self)
        settings_action.setIcon(icon("settings"))
        settings_action.setShortcut(QKeySequence.Preferences)
        settings_action.triggered.connect(self._on_settings)
        edit_menu.addAction(settings_action)

        # 视图菜单
        view_menu = menubar.addMenu(self.tr("视图(&V)"))

        self.sync_input_action = QAction(self.tr("同步输入"), self)
        self.sync_input_action.setCheckable(True)
        self.sync_input_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.sync_input_action.toggled.connect(self._set_sync_input_enabled)
        view_menu.addAction(self.sync_input_action)

        self.split_terminal_action = QAction(self.tr("终端分屏"), self)
        self.split_terminal_action.setIcon(icon("terminal_split"))
        self.split_terminal_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.split_terminal_action.triggered.connect(self._on_split_terminal)
        view_menu.addAction(self.split_terminal_action)

        self.compose_sync_action = QAction(self.tr("编排发送"), self)
        self.compose_sync_action.setShortcut(QKeySequence("Ctrl+Shift+Return"))
        self.compose_sync_action.triggered.connect(self._on_open_compose_dialog)
        view_menu.addAction(self.compose_sync_action)

        self.command_center_action = QAction(self.tr("快捷命令中心"), self)
        self.command_center_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.command_center_action.triggered.connect(self._on_open_command_center)
        view_menu.addAction(self.command_center_action)

        self._ensure_task_preset_actions()
        self.quick_inspection_action = self._task_preset_actions["quick_inspection"]
        self.quick_inspection_action.setShortcut(QKeySequence("Ctrl+Shift+K"))
        view_menu.addAction(self.quick_inspection_action)
        self.task_preset_menu = view_menu.addMenu(self.tr("任务预设"))
        self.task_preset_menu.setIcon(icon("monitor"))
        for preset_key in self.TASK_PRESET_ORDER:
            self.task_preset_menu.addAction(self._task_preset_actions[preset_key])

        self.sync_history_action = QAction(self.tr("发送记录"), self)
        self.sync_history_action.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.sync_history_action.triggered.connect(self._on_open_sync_history)
        view_menu.addAction(self.sync_history_action)
        self._refresh_sync_actions_menu()

        self.connection_filter_presets_menu = view_menu.addMenu(self.tr("筛选预设"))
        self.connection_filter_presets_menu.setIcon(icon("settings"))
        self.connection_filter_presets_menu.aboutToShow.connect(
            lambda: self._populate_connection_filter_presets_menu(
                self.connection_filter_presets_menu
            )
        )

        # 帮助菜单
        help_menu = menubar.addMenu(self.tr("帮助(&H)"))

        help_action = QAction(self.tr("使用手册(&F1)"), self)
        help_action.setShortcut(QKeySequence.HelpContents)
        help_action.setIcon(icon("about"))
        help_action.triggered.connect(self._on_help)
        help_menu.addAction(help_action)

        help_menu.addSeparator()

        about_action = QAction(self.tr("关于(&A)"), self)
        about_action.setIcon(icon("about"))
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _setup_toolbar(self) -> None:
        """设置工具栏"""
        toolbar = QToolBar(self.tr("主工具栏"))
        self.main_toolbar = toolbar
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        self.quick_open_toolbar_action = QAction(self.tr("快速打开"), self)
        self.quick_open_toolbar_action.setIcon(icon("quick_connect"))
        self.quick_open_toolbar_action.setShortcut(QKeySequence("Ctrl+P"))
        self.quick_open_toolbar_action.triggered.connect(self._on_quick_open)
        toolbar.addAction(self.quick_open_toolbar_action)

        self.new_connection_toolbar_action = QAction(self.tr("新建连接"), self)
        self.new_connection_toolbar_action.setIcon(icon("new_connection"))
        self.new_connection_toolbar_action.triggered.connect(self._on_new_connection)
        toolbar.addAction(self.new_connection_toolbar_action)

        self.local_terminal_toolbar_action = QAction(self.tr("本地终端"), self)
        self.local_terminal_toolbar_action.setIcon(icon("local_terminal"))
        self.local_terminal_toolbar_action.triggered.connect(self._on_open_local_terminal)
        toolbar.addAction(self.local_terminal_toolbar_action)

        self.sync_input_toolbar_action = QAction(self.tr("同步输入"), self)
        self.sync_input_toolbar_action.setCheckable(True)
        self.sync_input_toolbar_action.setIcon(icon("local_terminal"))
        self.sync_input_toolbar_action.toggled.connect(self.sync_input_action.setChecked)
        self.sync_input_action.toggled.connect(self.sync_input_toolbar_action.setChecked)
        toolbar.addAction(self.sync_input_toolbar_action)

        self.toolbar_spacer = QWidget(self)
        self.toolbar_spacer.setObjectName("toolbarSpacer")
        self.toolbar_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(self.toolbar_spacer)

        self.quick_connect_tool_action = QAction(self.tr("快速连接"), self)
        self.quick_connect_tool_action.setIcon(icon("quick_connect"))
        self.quick_connect_tool_action.triggered.connect(self._on_quick_connect)

        self.toolbar_tools_btn = QToolButton(self)
        self.toolbar_tools_btn.setObjectName("toolbarMenuButton")
        self.toolbar_tools_btn.setText(self.tr("工具箱"))
        self.toolbar_tools_btn.setIcon(icon("settings"))
        self.toolbar_tools_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toolbar_tools_btn.setPopupMode(QToolButton.InstantPopup)
        tools_menu = QMenu(self.toolbar_tools_btn)
        tools_menu.aboutToShow.connect(lambda: self._populate_toolbar_tools_menu(tools_menu))
        self._populate_toolbar_tools_menu(tools_menu)
        self.toolbar_tools_btn.setMenu(tools_menu)
        toolbar.addWidget(self.toolbar_tools_btn)

        self.settings_toolbar_action = QAction(self.tr("设置"), self)
        self.settings_toolbar_action.setIcon(icon("settings"))
        self.settings_toolbar_action.triggered.connect(self._on_settings)
        toolbar.addAction(self.settings_toolbar_action)

    def _populate_toolbar_tools_menu(self, menu: Optional[QMenu]) -> None:
        """构建紧凑型工具箱菜单。"""
        if menu is None:
            return
        menu.clear()
        menu.addAction(self.quick_connect_tool_action)
        menu.addAction(self.split_terminal_action)

        menu.addSeparator()

        menu.addAction(self.command_center_action)
        menu.addAction(self.compose_sync_action)
        menu.addAction(self.quick_inspection_action)

        extra_task_menu = menu.addMenu(self.tr("更多巡检"))
        extra_task_menu.setIcon(icon("monitor"))
        for preset_key in self.TASK_PRESET_ORDER[1:]:
            extra_task_menu.addAction(self._task_preset_actions[preset_key])

        menu.addAction(self.sync_history_action)

        menu.addSeparator()

        workspace_menu = menu.addMenu(self.tr("工作区模板"))
        workspace_menu.setIcon(icon("quick_connect"))
        self._populate_workspace_template_menu(workspace_menu)

        filter_menu = menu.addMenu(self.tr("筛选预设"))
        filter_menu.setIcon(icon("settings"))
        self._populate_connection_filter_presets_menu(filter_menu)

        menu.addSeparator()

        tunnel_action = QAction(self.tr("SSH 隧道"), menu)
        tunnel_action.setIcon(icon("tunnel"))
        tunnel_action.triggered.connect(self._on_show_tunnels)
        menu.addAction(tunnel_action)

        docker_action = QAction(self.tr("Docker"), menu)
        docker_action.setIcon(icon("docker"))
        docker_action.triggered.connect(self._on_show_docker)
        menu.addAction(docker_action)

        frp_action = QAction(self.tr("FRP"), menu)
        frp_action.setIcon(icon("frp"))
        frp_action.triggered.connect(self._on_show_frp)
        menu.addAction(frp_action)

    def _refresh_sync_actions_menu(self) -> None:
        """刷新同步输入栏的二级动作菜单。"""
        button = getattr(self, "sync_actions_btn", None)
        if button is None:
            return
        menu = QMenu(button)
        menu.aboutToShow.connect(lambda: self._populate_sync_actions_menu(menu))
        self._populate_sync_actions_menu(menu)
        button.setMenu(menu)

    def _populate_sync_actions_menu(self, menu: Optional[QMenu]) -> None:
        """构建同步输入栏的紧凑动作菜单。"""
        if menu is None:
            return
        menu.clear()
        menu.addAction(self.compose_sync_action)
        menu.addAction(self.command_center_action)

        menu.addSeparator()
        menu.addAction(self.quick_inspection_action)

        extra_task_menu = menu.addMenu(self.tr("更多巡检"))
        extra_task_menu.setIcon(icon("monitor"))
        for preset_key in self.TASK_PRESET_ORDER[1:]:
            extra_task_menu.addAction(self._task_preset_actions[preset_key])

    def _setup_statusbar(self) -> None:
        """设置状态栏"""
        statusbar = self.statusBar()
        statusbar.setObjectName("mainStatusBar")

        # 状态标签
        self.status_label = QLabel(self.tr("就绪"))
        statusbar.addWidget(self.status_label)

        self.sync_status_label = QLabel(self.tr("同步输入: 关闭"))
        statusbar.addPermanentWidget(self.sync_status_label)

        self.connection_count_label = QLabel(self.tr("连接: 0"))
        statusbar.addPermanentWidget(self.connection_count_label)

    def _create_workspace_empty_state(self) -> QWidget:
        """创建空工作区占位页。"""
        page = QWidget(self)
        page.setObjectName("workspaceEmptyState")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addStretch(1)

        card = QFrame(page)
        card.setObjectName("workspaceEmptyCard")
        card.setMaximumWidth(680)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 22, 22, 22)
        card_layout.setSpacing(12)

        title_label = QLabel(self.tr("开始工作"), card)
        title_label.setObjectName("panelTitle")
        card_layout.addWidget(title_label)

        subtitle_label = QLabel(
            self.tr("打开一个连接或本地终端，即可进入终端、文件与巡检。"),
            card,
        )
        subtitle_label.setObjectName("panelMeta")
        subtitle_label.setWordWrap(True)
        card_layout.addWidget(subtitle_label)

        self.empty_guide_label = QLabel(
            self.tr("推荐顺序：新建或导入连接 -> 保存并连接 -> 在终端或文件视图继续操作。"),
            card,
        )
        self.empty_guide_label.setObjectName("panelMeta")
        self.empty_guide_label.setWordWrap(True)
        self.empty_guide_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card_layout.addWidget(self.empty_guide_label)

        summary_grid = QGridLayout()
        summary_grid.setContentsMargins(0, 0, 0, 0)
        summary_grid.setHorizontalSpacing(10)
        summary_grid.setVerticalSpacing(10)

        connections_card, self.empty_connections_count_label = self._create_workspace_metric_card(
            self.tr("已保存连接"),
            self.tr("连接库"),
            card,
        )
        summary_grid.addWidget(connections_card, 0, 0)
        favorites_card, self.empty_favorites_count_label = self._create_workspace_metric_card(
            self.tr("收藏连接"),
            self.tr("常用入口"),
            card,
        )
        summary_grid.addWidget(favorites_card, 0, 1)
        recent_card, self.empty_recent_count_label = self._create_workspace_metric_card(
            self.tr("最近连接"),
            self.tr("最近使用"),
            card,
        )
        summary_grid.addWidget(recent_card, 1, 0)
        templates_card, self.empty_templates_count_label = self._create_workspace_metric_card(
            self.tr("工作区模板"),
            self.tr("个人场景"),
            card,
        )
        summary_grid.addWidget(templates_card, 1, 1)
        card_layout.addLayout(summary_grid)

        primary_action_btn = QPushButton(self.tr("快速打开"), card)
        primary_action_btn.clicked.connect(self._on_quick_open)
        card_layout.addWidget(primary_action_btn)

        secondary_action_grid = QGridLayout()
        secondary_action_grid.setContentsMargins(0, 0, 0, 0)
        secondary_action_grid.setHorizontalSpacing(8)
        secondary_action_grid.setVerticalSpacing(8)

        new_connection_btn = QPushButton(self.tr("新建连接"), card)
        new_connection_btn.setProperty("secondary", True)
        new_connection_btn.clicked.connect(self._on_new_connection)
        secondary_action_grid.addWidget(new_connection_btn, 0, 0)

        quick_connection_btn = QPushButton(self.tr("快速连接"), card)
        quick_connection_btn.setProperty("secondary", True)
        quick_connection_btn.clicked.connect(self._on_quick_connect)
        secondary_action_grid.addWidget(quick_connection_btn, 0, 1)

        local_terminal_btn = QPushButton(self.tr("本地终端"), card)
        local_terminal_btn.setProperty("secondary", True)
        local_terminal_btn.clicked.connect(self._on_open_local_terminal)
        secondary_action_grid.addWidget(local_terminal_btn, 0, 2)

        import_connections_btn = QPushButton(self.tr("导入连接"), card)
        import_connections_btn.setProperty("secondary", True)
        import_connections_btn.clicked.connect(self._on_import_connections)
        secondary_action_grid.addWidget(import_connections_btn, 1, 0)

        help_btn = QPushButton(self.tr("使用帮助"), card)
        help_btn.setProperty("secondary", True)
        help_btn.clicked.connect(self._on_help)
        secondary_action_grid.addWidget(help_btn, 1, 1)
        secondary_action_grid.setColumnStretch(0, 1)
        secondary_action_grid.setColumnStretch(1, 1)
        secondary_action_grid.setColumnStretch(2, 1)

        card_layout.addLayout(secondary_action_grid)

        layout.addWidget(card, 0, Qt.AlignCenter)
        layout.addStretch(2)
        return page

    def _create_workspace_metric_card(
        self,
        title: str,
        hint: str,
        parent: QWidget,
    ) -> tuple[QFrame, QLabel]:
        """创建空工作区指标卡片。"""
        card = QFrame(parent)
        card.setObjectName("workspaceMetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        value_label = QLabel("0", card)
        value_label.setObjectName("workspaceMetricValue")
        layout.addWidget(value_label)

        title_label = QLabel(title, card)
        title_label.setObjectName("panelTitle")
        layout.addWidget(title_label)

        hint_label = QLabel(hint, card)
        hint_label.setObjectName("panelMeta")
        layout.addWidget(hint_label)
        return card, value_label

    def _workspace_summary_counts(self) -> dict[str, int]:
        """返回个人工作台摘要数据。"""
        if self._config_manager is None:
            return {
                "connections": 0,
                "favorites": 0,
                "recent": 0,
                "templates": 0,
            }
        return {
            "connections": len(self._config_manager.load_connections()),
            "favorites": len(self._config_manager.load_favorite_connections()),
            "recent": len(self._config_manager.load_recent_connections(limit=8)),
            "templates": len(self._config_manager.load_workspace_templates()),
        }

    def _update_workspace_empty_summary(self) -> None:
        """刷新空工作区摘要卡。"""
        counts = self._workspace_summary_counts()
        if hasattr(self, "empty_connections_count_label"):
            self.empty_connections_count_label.setText(str(counts["connections"]))
        if hasattr(self, "empty_favorites_count_label"):
            self.empty_favorites_count_label.setText(str(counts["favorites"]))
        if hasattr(self, "empty_recent_count_label"):
            self.empty_recent_count_label.setText(str(counts["recent"]))
        if hasattr(self, "empty_templates_count_label"):
            self.empty_templates_count_label.setText(str(counts["templates"]))

    def _update_workspace_empty_state(self) -> None:
        """根据工作区是否为空切换占位页。"""
        if self.work_tabs.count() == 0:
            self.workspace_stack.setCurrentWidget(self.work_empty_state)
        else:
            self.workspace_stack.setCurrentWidget(self.work_tabs)
        self._update_workspace_header()

    def _workspace_context_label(self, widget: Optional[QWidget]) -> str:
        """返回当前工作区组件的简短类型说明。"""
        if widget is None:
            return self.tr("等待打开工作区")
        if isinstance(widget, TerminalSplitWidget):
            return self.tr("双终端分屏")
        if isinstance(widget, FileBrowserWidget):
            return self.tr("文件浏览")
        if isinstance(widget, VNCWidget):
            return self.tr("VNC 视图")
        if isinstance(widget, TunnelManagerWidget):
            return self.tr("SSH 隧道")
        if isinstance(widget, DockerManagerWidget):
            return self.tr("Docker 管理")
        if isinstance(widget, FRPWidget):
            return self.tr("FRP 管理")
        if isinstance(widget, QTermLocalTerminalWidget):
            return self.tr("本地终端")
        if isinstance(
            widget,
            (
                QTermTerminalWidget,
                QTermExternalTerminalWidget,
                TerminalWidget,
                QTermDockerExecTerminalWidget,
            ),
        ):
            return self.tr("终端会话")
        if isinstance(widget, QWidget) and self._supports_sync_input(widget):
            return self.tr("终端会话")
        return self.tr("工作区")

    def _set_workspace_header_action(
        self,
        button: QPushButton,
        *,
        text: str,
        icon_name: str,
        handler: Optional[Callable[[], None]],
        secondary: bool,
        visible: bool = True,
    ) -> None:
        """统一更新工作区头部按钮。"""
        button.setText(text)
        button.setIcon(icon(icon_name))
        button.setProperty("secondary", secondary)
        button.style().unpolish(button)
        button.style().polish(button)
        button.setVisible(visible)
        button.setEnabled(visible and handler is not None)
        if button is self.workspace_primary_action_btn:
            self._workspace_primary_action_handler = handler
        elif button is self.workspace_secondary_action_btn:
            self._workspace_secondary_action_handler = handler

    def _trigger_workspace_primary_action(self) -> None:
        """执行工作区头部主按钮动作。"""
        if self._workspace_primary_action_handler is not None:
            self._workspace_primary_action_handler()

    def _trigger_workspace_secondary_action(self) -> None:
        """执行工作区头部次按钮动作。"""
        if self._workspace_secondary_action_handler is not None:
            self._workspace_secondary_action_handler()

    def _toggle_workspace_sync_input(self) -> None:
        """切换工作区同步输入。"""
        if hasattr(self, "sync_input_action"):
            self.sync_input_action.setChecked(not self.sync_input_action.isChecked())

    def _workspace_saved_connection_id_for_widget(
        self, widget: Optional[QWidget] = None
    ) -> Optional[str]:
        """获取当前工作区对应的已保存连接 ID。"""
        candidate = widget or self.work_tabs.currentWidget()
        return self._workspace_saved_connection_id(getattr(candidate, "connection_id", None))

    @staticmethod
    def _connection_display_name(conn_data: Optional[Dict[str, Any]]) -> str:
        """返回连接展示名称。"""
        if not isinstance(conn_data, dict):
            return "未命名"
        name = str(conn_data.get("name") or "").strip()
        return name or "未命名"

    @staticmethod
    def _connection_type_key(conn_data: Optional[Dict[str, Any]]) -> str:
        """返回连接类型小写键。"""
        if not isinstance(conn_data, dict):
            return ""
        return str(conn_data.get("connection_type") or "").strip().lower()

    def _connection_primary_surface_label(self, conn_data: Optional[Dict[str, Any]]) -> str:
        """返回连接默认打开面的名称。"""
        conn_type = self._connection_type_key(conn_data)
        mapping = {
            "ssh": self.tr("终端"),
            "serial": self.tr("终端"),
            "tcp": self.tr("终端"),
            "udp": self.tr("终端"),
            "sftp": self.tr("文件视图"),
            "ftp": self.tr("文件视图"),
            "vnc": self.tr("远程桌面"),
        }
        return mapping.get(conn_type, self.tr("工作区"))

    def _connection_primary_open_action_text(self, conn_data: Optional[Dict[str, Any]]) -> str:
        """返回连接集合菜单中的主打开动作文案。"""
        conn_type = self._connection_type_key(conn_data)
        mapping = {
            "ssh": self.tr("打开终端"),
            "serial": self.tr("打开终端"),
            "tcp": self.tr("打开终端"),
            "udp": self.tr("打开终端"),
            "sftp": self.tr("打开文件视图"),
            "ftp": self.tr("打开文件视图"),
            "vnc": self.tr("打开远程桌面"),
        }
        return mapping.get(conn_type, self.tr("打开"))

    def _connection_saved_hint(self, conn_data: Optional[Dict[str, Any]]) -> str:
        """返回保存连接后的下一步提示。"""
        conn_type = self._connection_type_key(conn_data)
        if conn_type == "ssh":
            return self.tr("双击可进入终端，右键或收藏/最近菜单可继续打开文件视图")
        if conn_type in {"sftp", "ftp"}:
            return self.tr("双击可进入文件视图，适合继续上传、下载和整理目录")
        if conn_type in {"serial", "tcp", "udp"}:
            return self.tr("双击可直接进入终端调试")
        if conn_type == "vnc":
            return self.tr("双击可进入远程桌面视图")
        return self.tr("双击或按回车即可打开工作区")

    def _update_connection_saved_status(
        self,
        conn_data: Optional[Dict[str, Any]],
        *,
        edited: bool,
        visible_in_tree: bool,
    ) -> None:
        """在保存或编辑连接后更新状态栏提示。"""
        prefix = self.tr("已更新连接") if edited else self.tr("已保存连接")
        name = self._connection_display_name(conn_data)
        hint = self._connection_saved_hint(conn_data)
        if visible_in_tree:
            self.update_status(self.tr(f"{prefix}: {name} · {hint}"))
            return
        self.update_status(self.tr(f"{prefix}: {name} · {hint} · 当前筛选可能已隐藏该连接"))

    def _update_connection_surface_status(
        self,
        conn_data: Optional[Dict[str, Any]],
        *,
        surface: str = "primary",
        reused: bool = False,
    ) -> None:
        """更新连接打开或切换后的状态栏提示。"""
        name = self._connection_display_name(conn_data)
        if surface == "file_browser":
            surface_label = self.tr("文件视图")
        else:
            surface_label = self._connection_primary_surface_label(conn_data)
        prefix = self.tr("已切换到") if reused else self.tr("已打开")
        message = self.tr(f"{prefix}{surface_label}: {name}")
        conn_type = self._connection_type_key(conn_data)
        if surface == "primary" and conn_type == "ssh":
            message = self.tr(f"{message} · 右键或菜单可继续打开文件视图")
        elif surface == "file_browser" and conn_type == "ssh":
            message = self.tr(f"{message} · 可在文件页中直接切回终端")
        self.update_status(message)

    def _refresh_connection_related_tab_titles(
        self,
        conn_id: str,
        conn_data: Optional[Dict[str, Any]],
    ) -> None:
        """刷新与连接相关的终端和文件页标题。"""
        name = self._connection_display_name(conn_data)
        file_browser_tab_id = f"__file_browser__:{conn_id}"
        temporary_terminal_tab_id = self._temporary_terminal_connection_id(conn_id)
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            tab_connection_id = getattr(widget, "connection_id", None)
            if tab_connection_id == file_browser_tab_id:
                self.work_tabs.setTabText(index, self.tr(f"文件: {name}"))
                continue
            if tab_connection_id in {conn_id, temporary_terminal_tab_id}:
                self.work_tabs.setTabText(index, name)

    def _can_open_file_browser_for_connection_id(self, connection_id: Optional[str]) -> bool:
        """判断连接是否支持文件浏览器。"""
        if not connection_id:
            return False
        conn_data = self._find_connection_config(connection_id)
        if conn_data is None:
            return False
        return str(conn_data.get("connection_type", "")).lower() in {"ssh", "sftp", "ftp"}

    def _open_current_workspace_file_browser(self) -> None:
        """为当前工作区对应连接打开文件浏览器。"""
        connection_id = self._workspace_saved_connection_id_for_widget()
        if connection_id:
            self._open_file_browser_for_connection(connection_id)

    def _open_terminal_for_current_workspace(self) -> None:
        """为当前工作区对应连接打开终端。"""
        connection_id = self._workspace_saved_connection_id_for_widget()
        if connection_id:
            self._open_connection(conn_id=connection_id)
            return
        self._on_open_local_terminal()

    def _refresh_current_workspace_surface(self) -> None:
        """刷新当前工作区内容。"""
        current_widget = self.work_tabs.currentWidget()
        if isinstance(current_widget, FileBrowserWidget):
            current_widget.refresh()
            return
        if isinstance(current_widget, VNCWidget):
            connection = getattr(current_widget, "connection", None)
            if connection is not None and hasattr(connection, "request_frame_update"):
                connection.request_frame_update(incremental=False)

    def _workspace_menu_target(
        self,
        *,
        tab_index: Optional[int] = None,
        widget: Optional[QWidget] = None,
    ) -> tuple[int, Optional[QWidget]]:
        """解析工作区菜单作用目标。"""
        resolved_index = tab_index if isinstance(tab_index, int) else self.work_tabs.currentIndex()
        resolved_widget = widget
        if resolved_widget is None and 0 <= resolved_index < self.work_tabs.count():
            resolved_widget = self.work_tabs.widget(resolved_index)
        if resolved_widget is not None and (
            resolved_index < 0 or resolved_index >= self.work_tabs.count()
        ):
            resolved_index = self.work_tabs.indexOf(resolved_widget)
        return resolved_index, resolved_widget

    def _close_other_workspace_tabs(self, keep_index: int) -> None:
        """关闭除指定标签外的全部工作区。"""
        if keep_index < 0 or keep_index >= self.work_tabs.count():
            return
        for index in range(self.work_tabs.count() - 1, -1, -1):
            if index == keep_index:
                continue
            self._on_tab_close(index)

    def _close_all_workspace_tabs(self) -> None:
        """关闭全部工作区标签页。"""
        for index in range(self.work_tabs.count() - 1, -1, -1):
            self._on_tab_close(index)

    def _build_workspace_context_menu(
        self,
        parent: QWidget,
        *,
        tab_index: Optional[int] = None,
        widget: Optional[QWidget] = None,
        include_global_actions: bool = True,
        include_tab_management: bool = False,
    ) -> QMenu:
        """构建统一的工作区上下文菜单。"""
        resolved_index, current_widget = self._workspace_menu_target(
            tab_index=tab_index,
            widget=widget,
        )
        menu = QMenu(parent)

        if include_global_actions:
            quick_open_action = menu.addAction(self.tr("快速打开"))
            quick_open_action.setIcon(icon("quick_connect"))
            quick_open_action.triggered.connect(self._on_quick_open)

            new_connection_action = menu.addAction(self.tr("新建连接"))
            new_connection_action.setIcon(icon("new_connection"))
            new_connection_action.triggered.connect(self._on_new_connection)

            local_terminal_action = menu.addAction(self.tr("本地终端"))
            local_terminal_action.setIcon(icon("local_terminal"))
            local_terminal_action.triggered.connect(self._on_open_local_terminal)

            quick_connect_action = menu.addAction(self.tr("快速连接"))
            quick_connect_action.setIcon(icon("quick_connect"))
            quick_connect_action.triggered.connect(self._on_quick_connect)

            if current_widget is not None:
                menu.addSeparator()

        if current_widget is None:
            return menu

        sync_context_available = self._preferred_sync_context_widget(current_widget) is not None
        connection_id = self._workspace_saved_connection_id_for_widget(current_widget)

        if sync_context_available:
            menu.addAction(self.command_center_action)
            menu.addAction(self.compose_sync_action)
            menu.addAction(self.quick_inspection_action)

        if self._can_open_file_browser_for_connection_id(connection_id):
            browser_action = menu.addAction(self.tr("打开文件浏览器"))
            browser_action.setIcon(icon("sftp"))
            browser_action.triggered.connect(
                lambda checked=False, current_connection_id=connection_id: (
                    self._open_file_browser_for_connection(str(current_connection_id or ""))
                )
            )

        if isinstance(current_widget, FileBrowserWidget):
            refresh_action = menu.addAction(self.tr("刷新文件列表"))
            refresh_action.setIcon(icon("refresh"))
            refresh_action.triggered.connect(self._refresh_current_workspace_surface)

            terminal_action = menu.addAction(self.tr("打开终端"))
            terminal_action.setIcon(icon("terminal"))
            terminal_action.triggered.connect(self._open_terminal_for_current_workspace)

        if self._can_split_terminal_widget(current_widget):
            menu.addAction(self.split_terminal_action)

        menu.addSeparator()

        save_workspace_action = menu.addAction(self.tr("保存当前工作区为模板"))
        save_workspace_action.setIcon(icon("edit"))
        save_workspace_action.triggered.connect(self._on_save_current_workspace_as_template)

        if include_tab_management:
            close_tab_action = menu.addAction(self.tr("关闭当前页签"))
            close_tab_action.setIcon(icon("delete"))
            close_tab_action.triggered.connect(
                lambda checked=False, current_index=resolved_index: self._on_tab_close(
                    current_index
                )
            )

            if self.work_tabs.count() > 1:
                close_other_tabs_action = menu.addAction(self.tr("关闭其他页签"))
                close_other_tabs_action.triggered.connect(
                    lambda checked=False, keep_index=resolved_index: (
                        self._close_other_workspace_tabs(keep_index)
                    )
                )

            close_all_tabs_action = menu.addAction(self.tr("关闭全部页签"))
            close_all_tabs_action.triggered.connect(self._close_all_workspace_tabs)

        return menu

    def _refresh_workspace_header_menu(self) -> None:
        """刷新工作区头部菜单。"""
        button = getattr(self, "workspace_more_btn", None)
        if button is None or not hasattr(self, "command_center_action"):
            return
        button.setMenu(
            self._build_workspace_context_menu(
                button,
                tab_index=self.work_tabs.currentIndex(),
                include_global_actions=True,
                include_tab_management=self.work_tabs.count() > 0,
            )
        )

    def _build_workspace_tab_context_menu(self, tab_index: int) -> QMenu:
        """为指定工作区标签构建右键菜单。"""
        return self._build_workspace_context_menu(
            self.work_tabs.tabBar(),
            tab_index=tab_index,
            include_global_actions=False,
            include_tab_management=True,
        )

    def _show_work_tab_context_menu(self, pos) -> None:
        """显示工作区标签页右键菜单。"""
        tab_bar = self.work_tabs.tabBar()
        tab_index = tab_bar.tabAt(pos)
        if tab_index < 0:
            return
        self.work_tabs.setCurrentIndex(tab_index)
        menu = self._build_workspace_tab_context_menu(tab_index)
        menu.exec(tab_bar.mapToGlobal(pos))

    def _update_workspace_header(self) -> None:
        """刷新工作区顶部摘要。"""
        self._update_workspace_empty_summary()
        tab_count = self.work_tabs.count()
        if tab_count <= 0:
            summary_counts = self._workspace_summary_counts()
            self.workspace_title_label.setText(self.tr("个人工作台"))
            if summary_counts["connections"] > 0:
                self.workspace_subtitle_label.setText(
                    self.tr(f"已整理 {summary_counts['connections']} 个连接，双击左侧即可打开。")
                )
            else:
                self.workspace_subtitle_label.setText(self.tr("从左侧双击连接，或先打开本地终端。"))
            self.workspace_tab_count_badge.setText(self.tr("空闲"))
            self.workspace_context_badge.setText(self.tr("待开始"))
            self.workspace_mode_badge.setText(
                self.tr(f"{summary_counts['favorites']} 收藏 · {summary_counts['templates']} 模板")
            )
            self._set_workspace_header_action(
                self.workspace_primary_action_btn,
                text=self.tr("快速打开"),
                icon_name="quick_connect",
                handler=self._on_quick_open,
                secondary=False,
            )
            self._set_workspace_header_action(
                self.workspace_secondary_action_btn,
                text=self.tr("本地终端"),
                icon_name="local_terminal",
                handler=self._on_open_local_terminal,
                secondary=True,
            )
            self.workspace_sync_toggle_btn.setVisible(False)
            self.workspace_more_btn.setVisible(True)
            self._refresh_workspace_header_menu()
            return

        current_index = self.work_tabs.currentIndex()
        current_widget = self.work_tabs.currentWidget()
        current_title = self.work_tabs.tabText(current_index).strip() or self.tr("未命名工作区")
        context_label = self._workspace_context_label(current_widget)
        target_type_key = self._widget_target_type_key(current_widget)
        target_type_label = (
            self.tr(self._target_type_label(target_type_key))
            if target_type_key
            else self.tr("通用工作区")
        )
        saved_connection_id = self._workspace_saved_connection_id_for_widget(current_widget)
        sync_context_available = self._preferred_sync_context_widget(current_widget) is not None

        self.workspace_title_label.setText(current_title)
        self.workspace_subtitle_label.setText(self.tr(f"{context_label} · 共 {tab_count} 个页签"))
        self.workspace_tab_count_badge.setText(self.tr(f"{tab_count} 个页签"))
        self.workspace_context_badge.setText(context_label)
        if isinstance(current_widget, FileBrowserWidget):
            self.workspace_mode_badge.setText(
                self.tr(f"{target_type_label} · 上传 / 下载 / 切换目录")
            )
            self._set_workspace_header_action(
                self.workspace_primary_action_btn,
                text=self.tr("刷新列表"),
                icon_name="refresh",
                handler=self._refresh_current_workspace_surface,
                secondary=False,
            )
            self._set_workspace_header_action(
                self.workspace_secondary_action_btn,
                text=self.tr("打开终端"),
                icon_name="terminal",
                handler=self._open_terminal_for_current_workspace,
                secondary=True,
                visible=True,
            )
        elif sync_context_available:
            tip_text = (
                self.tr("同步已开启") if self._sync_input_enabled else self.tr("广播与快捷命令")
            )
            self.workspace_mode_badge.setText(self.tr(f"{target_type_label} · {tip_text}"))
            secondary_handler = (
                self._open_current_workspace_file_browser
                if self._can_open_file_browser_for_connection_id(saved_connection_id)
                else (
                    self._on_split_terminal
                    if self._can_split_terminal_widget(current_widget)
                    else self._on_open_compose_dialog
                )
            )
            secondary_text = (
                self.tr("文件浏览")
                if self._can_open_file_browser_for_connection_id(saved_connection_id)
                else (
                    self.tr("终端分屏")
                    if self._can_split_terminal_widget(current_widget)
                    else self.tr("编排发送")
                )
            )
            secondary_icon = (
                "sftp"
                if self._can_open_file_browser_for_connection_id(saved_connection_id)
                else (
                    "terminal_split"
                    if self._can_split_terminal_widget(current_widget)
                    else "quick_connect"
                )
            )
            self._set_workspace_header_action(
                self.workspace_primary_action_btn,
                text=self.tr("快捷命令"),
                icon_name="terminal",
                handler=self._on_open_command_center,
                secondary=False,
            )
            self._set_workspace_header_action(
                self.workspace_secondary_action_btn,
                text=secondary_text,
                icon_name=secondary_icon,
                handler=secondary_handler,
                secondary=True,
            )
        elif isinstance(current_widget, VNCWidget):
            self.workspace_mode_badge.setText(self.tr(f"{target_type_label} · 键鼠直连"))
            self._set_workspace_header_action(
                self.workspace_primary_action_btn,
                text=self.tr("请求刷新"),
                icon_name="refresh",
                handler=self._refresh_current_workspace_surface,
                secondary=False,
            )
            self._set_workspace_header_action(
                self.workspace_secondary_action_btn,
                text=self.tr("快速打开"),
                icon_name="quick_connect",
                handler=self._on_quick_open,
                secondary=True,
            )
        else:
            self.workspace_mode_badge.setText(self.tr(f"{target_type_label} · 常用动作见更多"))
            self._set_workspace_header_action(
                self.workspace_primary_action_btn,
                text=self.tr("快速打开"),
                icon_name="quick_connect",
                handler=self._on_quick_open,
                secondary=False,
            )
            self._set_workspace_header_action(
                self.workspace_secondary_action_btn,
                text=self.tr("本地终端"),
                icon_name="local_terminal",
                handler=self._on_open_local_terminal,
                secondary=True,
            )

        self.workspace_sync_toggle_btn.setVisible(sync_context_available)
        self.workspace_sync_toggle_btn.setEnabled(sync_context_available)
        self.workspace_sync_toggle_btn.setText(
            self.tr("关闭同步") if self._sync_input_enabled else self.tr("同步输入")
        )
        self.workspace_more_btn.setVisible(True)
        self._refresh_workspace_header_menu()

    def _setup_connections(self) -> None:
        """设置信号连接"""
        # 连接树信号
        self.connection_tree.connection_created.connect(self._on_connection_created)
        self.connection_tree.connection_activated.connect(self._on_connection_activated)
        self.connection_tree.connection_batch_open_requested.connect(
            self._on_connection_batch_open_requested
        )
        self.connection_tree.connection_file_browser_requested.connect(
            self._on_connection_file_browser_requested
        )
        self.connection_tree.connection_scope_workspace_requested.connect(
            self._on_connection_scope_open_workspace
        )
        self.connection_tree.connection_scope_workspace_template_requested.connect(
            self._on_connection_scope_save_as_workspace_template
        )
        self.connection_tree.connection_scope_task_preset_requested.connect(
            self._on_connection_scope_task_preset_requested
        )
        self.connection_tree.connection_deleted.connect(self._on_connection_deleted)
        self.connection_tree.connection_edited.connect(self._on_connection_edited)
        self.connection_tree.connection_favorite_toggled.connect(
            self._on_connection_favorite_toggled
        )

        # 工作区标签页关闭
        self.work_tabs.tabCloseRequested.connect(self._on_tab_close)
        self.work_tabs.currentChanged.connect(self._on_current_tab_changed)
        self.work_tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.work_tabs.tabBar().customContextMenuRequested.connect(self._show_work_tab_context_menu)
        self.system_monitor.refresh_requested.connect(self._refresh_monitor)

    def set_config_manager(self, manager: ConfigManager) -> None:
        """
        设置配置管理器

        Args:
            manager: 配置管理器实例
        """
        self._config_manager = manager
        self.connection_tree.set_config_manager(manager)
        self._reload_connection_tree()
        self._restore_workspace_if_enabled()
        self._refresh_workspace_templates_menu()
        self._refresh_connection_filter_presets_menu()
        self._apply_shared_library_sync_policy()
        self._update_workspace_header()

    def _load_connection_configs(self) -> list[Dict[str, Any]]:
        """加载并缓存连接配置。"""
        if not self._config_manager:
            self._connection_configs = {}
            return []
        connections = [dict(conn) for conn in self._config_manager.load_connections()]
        self._connection_configs = {
            conn["id"]: conn for conn in connections if isinstance(conn, dict) and conn.get("id")
        }
        return connections

    def _cache_connection_config(self, conn_data: Dict[str, Any]) -> None:
        """更新单条连接配置缓存。"""
        conn_id = conn_data.get("id")
        if conn_id:
            self._connection_configs[conn_id] = dict(conn_data)

    def _remove_connection_config(self, conn_id: str) -> None:
        """移除连接配置缓存。"""
        self._connection_configs.pop(conn_id, None)

    def _reload_connection_tree(self) -> None:
        """从配置层重载连接树。"""
        self.connection_tree.clear_connections()
        for conn_data in self._load_connection_configs():
            self.connection_tree.add_connection_item(conn_data)
        self._refresh_session_shortcuts()
        self._update_workspace_header()

    @staticmethod
    def _default_connection_filter_state() -> Dict[str, str]:
        """返回默认连接筛选条件。"""
        return {
            "search": "",
            "type": "__all__",
            "view": ConnectionTreeWidget.VIEW_GROUP,
            "favorite": "__all__",
            "group": "__all__",
        }

    def _capture_workspace_layout(self) -> Dict[str, Any]:
        """采集工作区布局状态。"""
        return {
            "main_splitter_sizes": self.main_splitter.sizes(),
            "work_splitter_sizes": self.work_splitter.sizes(),
            "sync_input_enabled": bool(self.sync_input_action.isChecked()),
            "sync_input_scope": str(
                self.sync_input_scope_combo.currentData() or self.SYNC_SCOPE_ALL
            ),
        }

    def _apply_workspace_layout(self, layout: Optional[Dict[str, Any]]) -> None:
        """恢复工作区布局状态。"""
        if not isinstance(layout, dict):
            return

        main_sizes = layout.get("main_splitter_sizes")
        if isinstance(main_sizes, list) and len(main_sizes) >= 2:
            self.main_splitter.setSizes([int(value) for value in main_sizes[:2]])

        work_sizes = layout.get("work_splitter_sizes")
        if isinstance(work_sizes, list) and len(work_sizes) >= 2:
            self.work_splitter.setSizes([int(value) for value in work_sizes[:2]])

        scope = str(layout.get("sync_input_scope") or self.SYNC_SCOPE_ALL).strip()
        scope_index = self.sync_input_scope_combo.findData(scope)
        if scope_index >= 0:
            self.sync_input_scope_combo.setCurrentIndex(scope_index)

        sync_input_enabled = layout.get("sync_input_enabled")
        if isinstance(sync_input_enabled, bool):
            self.sync_input_action.setChecked(sync_input_enabled)

    def _workspace_state_from_connection_ids(self, connection_ids: list[str]) -> Dict[str, Any]:
        """根据连接列表构造工作区状态。"""
        return {
            "tabs": [
                {"kind": "connection", "connection_id": connection_id}
                for connection_id in connection_ids
                if isinstance(connection_id, str) and connection_id.strip()
            ],
            "current_index": 0,
            "layout": self._capture_workspace_layout(),
        }

    @staticmethod
    def _workspace_file_browser_connection_id(tab_connection_id: object) -> Optional[str]:
        """从文件浏览器标签页 ID 中解析原始连接 ID。"""
        if not isinstance(tab_connection_id, str):
            return None
        prefix = "__file_browser__:"
        if not tab_connection_id.startswith(prefix):
            return None
        connection_id = tab_connection_id[len(prefix) :].strip()
        return connection_id or None

    @classmethod
    def _workspace_saved_connection_id(cls, tab_connection_id: object) -> Optional[str]:
        """从工作区标签页 ID 中解析配置层连接 ID。"""
        file_browser_connection_id = cls._workspace_file_browser_connection_id(tab_connection_id)
        if file_browser_connection_id:
            return file_browser_connection_id
        if not isinstance(tab_connection_id, str):
            return None
        if tab_connection_id.startswith(cls.TEMP_TERMINAL_PREFIX):
            connection_id = tab_connection_id[len(cls.TEMP_TERMINAL_PREFIX) :].strip()
            return connection_id or None
        if tab_connection_id and not tab_connection_id.startswith("__"):
            return tab_connection_id
        return None

    @classmethod
    def _temporary_terminal_connection_id(cls, conn_id: str) -> str:
        """返回临时终端标签页 ID。"""
        return f"{cls.TEMP_TERMINAL_PREFIX}{conn_id}"

    def _capture_workspace_state(self) -> Dict[str, Any]:
        """采集当前工作区标签状态。"""
        tabs: list[Dict[str, Any]] = []
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            connection_id = getattr(widget, "connection_id", None)
            file_browser_connection_id = self._workspace_file_browser_connection_id(connection_id)
            if file_browser_connection_id:
                tabs.append(
                    {
                        "kind": "file_browser",
                        "connection_id": file_browser_connection_id,
                    }
                )
                continue
            if connection_id == "__local_terminal__":
                tabs.append({"kind": "local_terminal"})
                continue
            if (
                isinstance(connection_id, str)
                and connection_id
                and not connection_id.startswith("__")
            ):
                tabs.append({"kind": "connection", "connection_id": connection_id})
                continue
            if isinstance(widget, TunnelManagerWidget):
                tabs.append({"kind": "tunnels"})
                continue
            if isinstance(widget, DockerManagerWidget):
                tabs.append({"kind": "docker"})
                continue
            if isinstance(widget, FRPWidget):
                tabs.append({"kind": "frp"})
        current_index = self.work_tabs.currentIndex()
        return {
            "tabs": tabs,
            "current_index": max(0, current_index),
            "layout": self._capture_workspace_layout(),
        }

    def _save_workspace_state(self) -> None:
        """持久化当前工作区状态。"""
        if not self._config_manager:
            return
        self._config_manager.save_workspace_state(self._capture_workspace_state())

    def _restore_workspace_if_enabled(self) -> None:
        """根据设置恢复上次工作区。"""
        if not self._config_manager:
            return
        if not self._config_manager.app_config.restore_workspace_on_startup:
            return
        self._restore_workspace_state(self._config_manager.load_workspace_state())

    def _restore_workspace_state(
        self,
        workspace_state: Dict[str, Any],
        *,
        append: bool = False,
    ) -> None:
        """恢复工作区标签。"""
        tabs = workspace_state.get("tabs", [])
        if not isinstance(tabs, list):
            tabs = []
        if not tabs:
            self._apply_workspace_layout(workspace_state.get("layout"))
            return

        initial_count = self.work_tabs.count()
        self._restoring_workspace = True
        try:
            for tab in tabs:
                if not isinstance(tab, dict):
                    continue
                kind = tab.get("kind")
                if kind == "connection" and tab.get("connection_id"):
                    self._open_connection(conn_id=tab["connection_id"], show_errors=False)
                    continue
                if kind == "file_browser" and tab.get("connection_id"):
                    self._open_file_browser_for_connection(
                        str(tab["connection_id"]),
                        show_errors=False,
                    )
                    continue
                if kind == "local_terminal":
                    self._on_open_local_terminal()
                    continue
                if kind == "tunnels":
                    self._on_show_tunnels()
                    continue
                if kind == "docker":
                    self._on_show_docker()
                    continue
                if kind == "frp":
                    self._on_show_frp()
                    continue
        finally:
            self._restoring_workspace = False

        self._apply_workspace_layout(workspace_state.get("layout"))
        current_index = workspace_state.get("current_index", 0)
        if self.work_tabs.count():
            if not isinstance(current_index, int):
                current_index = 0
            if append and self.work_tabs.count() > initial_count:
                appended_count = self.work_tabs.count() - initial_count
                current_index = initial_count + min(max(0, current_index), appended_count - 1)
            self.work_tabs.setCurrentIndex(min(max(0, current_index), self.work_tabs.count() - 1))

    def _populate_connection_menu(
        self,
        menu: Optional[QMenu],
        connections: list[Dict[str, Any]],
        empty_text: str,
        *,
        collection_label: str,
    ) -> None:
        """刷新收藏/最近连接菜单。"""
        if menu is None:
            return

        menu.clear()
        connection_list = [
            dict(conn_data) for conn_data in connections if isinstance(conn_data, dict)
        ]

        open_workspace_action = menu.addAction(self.tr(f"打开全部{collection_label}为运维工作台"))
        open_workspace_action.setEnabled(bool(connection_list))
        if connection_list:
            open_workspace_action.triggered.connect(
                lambda checked=False, current_connections=connection_list: (
                    self._open_connection_collection_workspace(
                        collection_label, current_connections
                    )
                )
            )

        save_workspace_action = menu.addAction(
            self.tr(f"将全部{collection_label}保存为运维工作台模板")
        )
        save_workspace_action.setEnabled(bool(connection_list) and self._config_manager is not None)
        if connection_list and self._config_manager is not None:
            save_workspace_action.triggered.connect(
                lambda checked=False, current_connections=connection_list: (
                    self._save_connection_collection_as_workspace_template(
                        collection_label, current_connections
                    )
                )
            )

        menu.addSeparator()
        if not connection_list:
            placeholder = menu.addAction(empty_text)
            placeholder.setEnabled(False)
            return

        for conn_data in connection_list:
            conn_id = conn_data.get("id")
            if not conn_id:
                continue
            name = conn_data.get("name", self.tr("未命名"))
            if conn_data.get("favorite"):
                name = f"★ {name}"
            connection_menu = menu.addMenu(
                connection_type_icon(conn_data.get("connection_type", "ssh")),
                name,
            )
            if conn_data.get("last_connected_at"):
                connection_menu.menuAction().setStatusTip(
                    self.tr(f"最近连接: {conn_data['last_connected_at']}")
                )

            open_action = connection_menu.addAction(
                self._connection_primary_open_action_text(conn_data)
            )
            open_action.triggered.connect(
                lambda checked=False, connection_id=conn_id: self._open_connection(
                    conn_id=connection_id
                )
            )
            if self._connection_can_open_file_browser(conn_data):
                browser_action = connection_menu.addAction(self.tr("打开文件浏览器"))
                browser_action.triggered.connect(
                    lambda checked=False, connection_id=conn_id: (
                        self._open_file_browser_for_connection(connection_id)
                    )
                )

    def _refresh_session_shortcuts(self) -> None:
        """刷新会话快捷入口。"""
        if not self._config_manager:
            self._populate_connection_menu(
                self.favorite_connections_menu,
                [],
                self.tr("暂无收藏连接"),
                collection_label=self.tr("收藏连接"),
            )
            self._populate_connection_menu(
                self.recent_connections_menu,
                [],
                self.tr("暂无最近连接"),
                collection_label=self.tr("最近连接"),
            )
            return

        self._populate_connection_menu(
            self.favorite_connections_menu,
            self._config_manager.load_favorite_connections(),
            self.tr("暂无收藏连接"),
            collection_label=self.tr("收藏连接"),
        )
        self._populate_connection_menu(
            self.recent_connections_menu,
            self._config_manager.load_recent_connections(limit=8),
            self.tr("暂无最近连接"),
            collection_label=self.tr("最近连接"),
        )

    def _current_workspace_connection_ids(self) -> list[str]:
        """返回当前工作区中的已保存连接 ID，去重且保留顺序。"""
        connection_ids: list[str] = []
        seen: set[str] = set()
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            connection_id = getattr(widget, "connection_id", None)
            if (
                not isinstance(connection_id, str)
                or not connection_id
                or connection_id.startswith("__")
                or connection_id in seen
            ):
                continue
            seen.add(connection_id)
            connection_ids.append(connection_id)
        return connection_ids

    def _prompt_workspace_template_name(self, default_name: str) -> Optional[str]:
        """弹出对话框获取工作区模板名称。"""
        template_name, ok = QInputDialog.getText(
            self,
            self.tr("保存工作区模板"),
            self.tr("模板名称:"),
            text=default_name,
        )
        if not ok:
            return None
        normalized = template_name.strip()
        return normalized or None

    def _prompt_connection_filter_preset_name(self, default_name: str) -> Optional[str]:
        """弹出对话框获取筛选预设名称。"""
        preset_name, ok = QInputDialog.getText(
            self,
            self.tr("保存筛选预设"),
            self.tr("预设名称:"),
            text=default_name,
        )
        if not ok:
            return None
        normalized = preset_name.strip()
        return normalized or None

    def _prompt_workspace_template_choice(
        self,
        *,
        title: str,
        label: str,
        template_kind: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """弹出对话框选择工作区模板。"""
        if not self._config_manager:
            return None
        templates = self._sort_records_by_recent_usage(
            self._config_manager.load_workspace_templates()
        )
        if template_kind is not None:
            templates = [
                template
                for template in templates
                if str(template.get("template_kind") or "workspace") == template_kind
            ]
        if not templates:
            return None
        choices = [str(template.get("name") or self.tr("未命名模板")) for template in templates]
        selected_name, ok = QInputDialog.getItem(
            self,
            title,
            label,
            choices,
            0,
            False,
        )
        if not ok or not selected_name:
            return None
        return next(
            (template for template in templates if template.get("name") == selected_name), None
        )

    def _prompt_connection_filter_preset_choice(
        self,
        *,
        title: str,
        label: str,
    ) -> Optional[Dict[str, Any]]:
        """弹出对话框选择筛选预设。"""
        if not self._config_manager:
            return None
        presets = self._sort_records_by_recent_usage(
            self._config_manager.load_connection_filter_presets()
        )
        if not presets:
            return None
        choices = [str(preset.get("name") or self.tr("未命名预设")) for preset in presets]
        selected_name, ok = QInputDialog.getItem(
            self,
            title,
            label,
            choices,
            0,
            False,
        )
        if not ok or not selected_name:
            return None
        return next((preset for preset in presets if preset.get("name") == selected_name), None)

    def _prompt_shared_library_record_choice(
        self,
        *,
        title: str,
        label: str,
        package_type: str,
    ) -> Optional[Dict[str, Any]]:
        """弹出对话框选择共享中心记录。"""
        if not self._config_manager:
            return None
        records = self._sort_records_by_recent_usage(
            self._config_manager.load_shared_library_records(package_type=package_type)
        )
        if not records:
            return None
        choices = [self._shared_library_record_menu_text(record) for record in records]
        selected_name, ok = QInputDialog.getItem(
            self,
            title,
            label,
            choices,
            0,
            False,
        )
        if not ok or not selected_name:
            return None
        for record in records:
            if self._shared_library_record_menu_text(record) == selected_name:
                return record
        return None

    def _prompt_import_conflict_strategy(self, item_label: str) -> Optional[str]:
        """让用户选择导入冲突处理策略。"""
        strategy_items = [
            (self.tr("覆盖冲突项"), "replace"),
            (self.tr("跳过冲突项"), "skip"),
            (self.tr("冲突项自动重命名"), "rename"),
        ]
        selected_label, ok = QInputDialog.getItem(
            self,
            self.tr(f"{item_label}导入策略"),
            self.tr("检测到同名或同 ID 冲突，请选择处理方式:"),
            [label for label, _value in strategy_items],
            0,
            False,
        )
        if not ok or not selected_label:
            return None
        for label, value in strategy_items:
            if label == selected_label:
                return value
        return "replace"

    def _format_shared_import_summary(self, item_label: str, summary: Dict[str, Any]) -> str:
        """格式化共享导入摘要。"""
        package = dict(summary.get("package") or {})
        lines = [
            self.tr(f"类型: {item_label}"),
            self.tr(f"导入项数: {int(summary.get('item_count') or 0)}"),
            self.tr(f"可直接新增: {int(summary.get('new_count') or 0)}"),
            self.tr(f"存在冲突: {int(summary.get('conflict_count') or 0)}"),
        ]

        package_name = str(package.get("name") or "").strip()
        if package_name:
            lines.append(self.tr(f"共享包名称: {package_name}"))
        source_app = str(package.get("source_app") or "").strip()
        source_version = str(package.get("source_version") or "").strip()
        if source_app:
            source_label = source_app
            if source_version:
                source_label = f"{source_label} {source_version}"
            lines.append(self.tr(f"来源应用: {source_label}"))
        description = str(package.get("description") or "").strip()
        if description:
            lines.append(self.tr(f"说明: {description}"))
        source_scope = str(package.get("source_scope") or "").strip()
        if source_scope:
            lines.append(self.tr(f"来源范围: {source_scope}"))
        exported_by = str(package.get("exported_by") or "").strip()
        if exported_by:
            lines.append(self.tr(f"导出人: {exported_by}"))
        exported_at = str(package.get("exported_at") or "").strip()
        if exported_at:
            lines.append(self.tr(f"导出时间: {exported_at}"))
        labels = package.get("labels") or []
        if labels:
            lines.append(self.tr(f"标签: {', '.join(str(label) for label in labels)}"))

        sample_names = [
            str(name) for name in summary.get("sample_names") or [] if str(name).strip()
        ]
        if sample_names:
            lines.append(self.tr(f"示例项: {', '.join(sample_names[:5])}"))

        conflict_items = summary.get("conflicts") or []
        if conflict_items:
            preview_parts: list[str] = []
            for conflict in conflict_items[:3]:
                name = str(conflict.get("name") or "未命名项")
                reason = str(conflict.get("reason") or "name")
                preview_parts.append(f"{name} [{reason}]")
            lines.append(self.tr(f"冲突预览: {'; '.join(preview_parts)}"))

        return "\n".join(lines)

    def _build_workspace_template_export_package_info(
        self,
        template: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造工作区模板共享包元数据。"""
        template_kind = self._workspace_template_kind_label(
            str(template.get("template_kind") or "workspace")
        )
        scope_view = str(template.get("scope_view") or "").strip()
        scope_name = str(template.get("scope_name") or "").strip()
        description = self.tr(f"导出{template_kind}")
        if scope_view and scope_name:
            description = self.tr(f"{description}，来源 {scope_view} / {scope_name}")

        labels = [template_kind]
        if template.get("include_file_browsers"):
            labels.append(self.tr("文件页"))
        if template.get("include_local_terminal"):
            labels.append(self.tr("本地终端"))

        return {
            "name": str(template.get("name") or "").strip() or None,
            "description": description,
            "source_scope": f"{scope_view} / {scope_name}" if scope_view and scope_name else None,
            "labels": labels,
        }

    def _build_connection_filter_preset_export_package_info(
        self,
        preset: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造筛选预设共享包元数据。"""
        filters = dict(preset.get("filters") or {})
        description = self.tr(
            f"导出筛选预设，范围 {self._describe_connection_filter_state(filters)}"
        )
        return {
            "name": str(preset.get("name") or "").strip() or None,
            "description": description,
            "source_scope": self._describe_connection_filter_state(filters),
            "labels": [self.tr("筛选预设")],
        }

    def _shared_library_record_kind_label(self, package_type: str) -> str:
        """返回共享包类型标签。"""
        if package_type == "workspace_templates":
            return self.tr("工作区模板共享包")
        if package_type == "connection_filter_presets":
            return self.tr("筛选预设共享包")
        return self.tr("共享包")

    def _shared_library_package_type_label(self, package_type: str) -> str:
        """返回共享包类型短标签。"""
        if package_type == "workspace_templates":
            return self.tr("工作区模板")
        if package_type == "connection_filter_presets":
            return self.tr("筛选预设")
        return package_type or self.tr("未知类型")

    def _shared_library_record_menu_text(self, record: Dict[str, Any]) -> str:
        """生成共享中心记录菜单文本。"""
        name = str(record.get("name") or self.tr("未命名共享包"))
        item_count = int(record.get("item_count") or 0)
        exported_at = str(record.get("exported_at") or "").strip()
        if exported_at:
            return self.tr(f"{name} ({item_count}) · {exported_at}")
        return self.tr(f"{name} ({item_count})")

    def _shared_library_record_status_text(self, record: Dict[str, Any]) -> str:
        """生成共享中心记录状态文本。"""
        parts = [
            self._shared_library_record_kind_label(str(record.get("package_type") or "")),
            self.tr(
                f"来源 {record.get('source_app', 'Neko_Shell')} {record.get('source_version', '0.1.0')}"
            ),
        ]
        package_version = int(record.get("package_version") or 1)
        parts.append(self.tr(f"版本 v{package_version}"))
        description = str(record.get("description") or "").strip()
        if description:
            parts.append(description)
        source_scope = str(record.get("source_scope") or "").strip()
        if source_scope:
            parts.append(self.tr(f"范围 {source_scope}"))
        labels = record.get("labels") or []
        if labels:
            parts.append(self.tr(f"标签 {', '.join(str(label) for label in labels)}"))
        sample_names = [str(name) for name in record.get("sample_names") or [] if str(name).strip()]
        if sample_names:
            parts.append(self.tr(f"示例 {', '.join(sample_names[:3])}"))
        return " · ".join(parts)

    def _format_shared_library_sync_preview(
        self,
        action_label: str,
        preview: Dict[str, Any],
    ) -> str:
        """格式化共享中心推拉预览信息。"""
        lines = [
            self.tr(f"操作: {action_label}"),
            self.tr(f"目录: {preview.get('sync_dir', '')}"),
            self.tr(f"共享包总数: {int(preview.get('record_count') or 0)}"),
            self.tr(f"可新增: {int(preview.get('new_count') or 0)}"),
            self.tr(f"完全一致: {int(preview.get('exact_match_count') or 0)}"),
        ]
        external_record_count = int(preview.get("external_record_count") or 0)
        trusted_record_count = int(preview.get("trusted_record_count") or 0)
        untrusted_count = int(preview.get("untrusted_count") or 0)
        if external_record_count:
            lines.append(self.tr(f"外部记录总数: {external_record_count}"))
        if trusted_record_count or untrusted_count:
            lines.append(self.tr(f"受信任记录: {trusted_record_count}"))
        if untrusted_count:
            lines.append(self.tr(f"未受信任记录: {untrusted_count}"))
            untrusted_sources = [
                str(item) for item in preview.get("untrusted_sources") or [] if str(item).strip()
            ]
            if untrusted_sources:
                lines.append(self.tr(f"未受信任来源: {', '.join(untrusted_sources[:5])}"))
        untrusted_signer_count = int(preview.get("untrusted_signer_count") or 0)
        if untrusted_signer_count:
            lines.append(self.tr(f"未受信任签名者记录: {untrusted_signer_count}"))
            untrusted_signers = [
                str(item) for item in preview.get("untrusted_signers") or [] if str(item).strip()
            ]
            if untrusted_signers:
                lines.append(self.tr(f"未受信任签名者: {', '.join(untrusted_signers[:5])}"))
        revoked_signer_count = int(preview.get("revoked_signer_count") or 0)
        if revoked_signer_count:
            lines.append(self.tr(f"已撤销签名者记录: {revoked_signer_count}"))
            revoked_signers = [
                str(item) for item in preview.get("revoked_signers") or [] if str(item).strip()
            ]
            if revoked_signers:
                lines.append(self.tr(f"已撤销签名者: {', '.join(revoked_signers[:5])}"))
        expired_signer_policy_count = int(preview.get("expired_signer_policy_count") or 0)
        if expired_signer_policy_count:
            lines.append(self.tr(f"签名策略已过期记录: {expired_signer_policy_count}"))
            expired_policy_signers = [
                str(item)
                for item in preview.get("expired_policy_signers") or []
                if str(item).strip()
            ]
            if expired_policy_signers:
                lines.append(self.tr(f"策略已过期签名者: {', '.join(expired_policy_signers[:5])}"))
        rotation_due_count = int(preview.get("rotation_due_count") or 0)
        if rotation_due_count:
            lines.append(self.tr(f"轮换临近截止记录: {rotation_due_count}"))
            rotation_due_signers = [
                str(item) for item in preview.get("rotation_due_signers") or [] if str(item).strip()
            ]
            if rotation_due_signers:
                lines.append(self.tr(f"临近轮换签名者: {', '.join(rotation_due_signers[:5])}"))
        rotation_overdue_count = int(preview.get("rotation_overdue_count") or 0)
        if rotation_overdue_count:
            lines.append(self.tr(f"轮换已超期记录: {rotation_overdue_count}"))
            rotation_overdue_signers = [
                str(item)
                for item in preview.get("rotation_overdue_signers") or []
                if str(item).strip()
            ]
            if rotation_overdue_signers:
                lines.append(
                    self.tr(f"轮换已超期签名者: {', '.join(rotation_overdue_signers[:5])}")
                )
        rotation_warning_count = int(preview.get("rotation_warning_count") or 0)
        if rotation_warning_count:
            lines.append(self.tr(f"轮换提示记录: {rotation_warning_count}"))
        rotation_exception_count = int(preview.get("rotation_exception_count") or 0)
        if rotation_exception_count:
            lines.append(self.tr(f"轮换例外放行记录: {rotation_exception_count}"))
            rotation_exception_signers = [
                str(item)
                for item in preview.get("rotation_exception_signers") or []
                if str(item).strip()
            ]
            if rotation_exception_signers:
                lines.append(
                    self.tr(f"命中轮换例外签名者: {', '.join(rotation_exception_signers[:5])}")
                )
        integrity_blocked_count = int(preview.get("integrity_blocked_count") or 0)
        if integrity_blocked_count:
            lines.append(self.tr(f"完整性异常记录: {integrity_blocked_count}"))
        integrity_unverified_count = int(preview.get("integrity_unverified_count") or 0)
        if integrity_unverified_count:
            lines.append(self.tr(f"未校验摘要记录: {integrity_unverified_count}"))
        signature_blocked_count = int(preview.get("signature_blocked_count") or 0)
        if signature_blocked_count:
            lines.append(self.tr(f"签名异常记录: {signature_blocked_count}"))
        signature_unverified_count = int(preview.get("signature_unverified_count") or 0)
        if signature_unverified_count:
            lines.append(self.tr(f"未签名记录: {signature_unverified_count}"))
        blocked_package_type_count = int(preview.get("blocked_package_type_count") or 0)
        if blocked_package_type_count:
            lines.append(self.tr(f"需审批包类型记录: {blocked_package_type_count}"))
            blocked_package_types = [
                self._shared_library_package_type_label(str(item))
                for item in preview.get("blocked_package_types") or []
                if str(item).strip()
            ]
            if blocked_package_types:
                lines.append(self.tr(f"未自动拉取包类型: {', '.join(blocked_package_types)}"))
        approval_required_count = int(preview.get("approval_required_count") or 0)
        if approval_required_count:
            lines.append(self.tr(f"待审批记录: {approval_required_count}"))
        approved_override_count = int(preview.get("approved_override_count") or 0)
        if approved_override_count:
            lines.append(self.tr(f"已审批放行记录: {approved_override_count}"))
        if preview.get("action") == "push":
            lines.append(self.tr(f"本地版本更新: {int(preview.get('newer_local_count') or 0)}"))
            lines.append(self.tr(f"外部版本更新: {int(preview.get('older_local_count') or 0)}"))
        else:
            lines.append(self.tr(f"外部版本更新: {int(preview.get('newer_external_count') or 0)}"))
            lines.append(self.tr(f"本地版本更新: {int(preview.get('older_external_count') or 0)}"))
        lines.append(self.tr(f"同版本内容冲突: {int(preview.get('conflict_count') or 0)}"))
        skipped_missing = int(preview.get("skipped_missing") or 0)
        if skipped_missing:
            lines.append(self.tr(f"缺失文件: {skipped_missing}"))

        conflicts = preview.get("conflicts") or []
        if conflicts:
            samples: list[str] = []
            for conflict in conflicts[:5]:
                name = str(conflict.get("name") or "未命名共享包")
                local_version = int(conflict.get("local_version") or 1)
                external_version = int(conflict.get("external_version") or 1)
                status = str(conflict.get("status") or "").strip()
                if status == "newer_local":
                    status_label = self.tr("本地较新")
                elif status == "older_local":
                    status_label = self.tr("外部较新")
                elif status == "newer_external":
                    status_label = self.tr("外部较新")
                elif status == "older_external":
                    status_label = self.tr("本地较新")
                else:
                    status_label = self.tr("同版本冲突")
                samples.append(f"{name} (v{local_version} / v{external_version}, {status_label})")
            lines.append(self.tr(f"冲突预览: {'; '.join(samples)}"))

        return "\n".join(lines)

    def _format_shared_library_sync_history_text(
        self,
        records: list[Dict[str, Any]],
    ) -> str:
        """格式化共享中心同步历史。"""
        if not records:
            return self.tr("暂无共享同步历史")

        lines: list[str] = []
        for index, record in enumerate(records[:12], start=1):
            action = (
                self.tr("推送") if str(record.get("action") or "") == "push" else self.tr("拉取")
            )
            line = (
                f"{index}. {action} · "
                f"{record.get('recorded_at', '')} · "
                f"{record.get('sync_dir', '')}"
            )
            lines.append(line)
            stats: list[str] = [
                self.tr(f"总数 {int(record.get('record_count') or 0)}"),
                self.tr(f"新增 {int(record.get('new_count') or 0)}"),
                self.tr(f"一致 {int(record.get('exact_match_count') or 0)}"),
                self.tr(f"冲突 {int(record.get('conflict_count') or 0)}"),
            ]
            if str(record.get("action") or "") == "push":
                stats.append(self.tr(f"写入 {int(record.get('pushed_count') or 0)}"))
                stats.append(self.tr(f"创建 {int(record.get('created_count') or 0)}"))
                stats.append(self.tr(f"更新 {int(record.get('updated_count') or 0)}"))
            else:
                stats.append(self.tr(f"导入 {int(record.get('imported_count') or 0)}"))
                stats.append(self.tr(f"跳过 {int(record.get('skipped_count') or 0)}"))
                if int(record.get("untrusted_count") or 0):
                    stats.append(self.tr(f"未受信任 {int(record.get('untrusted_count') or 0)}"))
                if int(record.get("untrusted_signer_count") or 0):
                    stats.append(
                        self.tr(f"未受信任签名者 {int(record.get('untrusted_signer_count') or 0)}")
                    )
                if int(record.get("revoked_signer_count") or 0):
                    stats.append(
                        self.tr(f"已撤销签名者 {int(record.get('revoked_signer_count') or 0)}")
                    )
                if int(record.get("expired_signer_policy_count") or 0):
                    stats.append(
                        self.tr(f"策略过期 {int(record.get('expired_signer_policy_count') or 0)}")
                    )
                if int(record.get("rotation_due_count") or 0):
                    stats.append(self.tr(f"轮换临近 {int(record.get('rotation_due_count') or 0)}"))
                if int(record.get("rotation_overdue_count") or 0):
                    stats.append(
                        self.tr(f"轮换超期 {int(record.get('rotation_overdue_count') or 0)}")
                    )
                if int(record.get("rotation_exception_count") or 0):
                    stats.append(
                        self.tr(f"轮换例外 {int(record.get('rotation_exception_count') or 0)}")
                    )
                if int(record.get("integrity_blocked_count") or 0):
                    stats.append(
                        self.tr(f"完整性异常 {int(record.get('integrity_blocked_count') or 0)}")
                    )
                if int(record.get("integrity_unverified_count") or 0):
                    stats.append(
                        self.tr(f"未校验摘要 {int(record.get('integrity_unverified_count') or 0)}")
                    )
                if int(record.get("signature_blocked_count") or 0):
                    stats.append(
                        self.tr(f"签名异常 {int(record.get('signature_blocked_count') or 0)}")
                    )
                if int(record.get("signature_unverified_count") or 0):
                    stats.append(
                        self.tr(f"未签名 {int(record.get('signature_unverified_count') or 0)}")
                    )
                if int(record.get("blocked_package_type_count") or 0):
                    stats.append(
                        self.tr(f"待审批类型 {int(record.get('blocked_package_type_count') or 0)}")
                    )
                if int(record.get("approval_required_count") or 0):
                    stats.append(self.tr(f"待审 {int(record.get('approval_required_count') or 0)}"))
                if int(record.get("approved_override_count") or 0):
                    stats.append(
                        self.tr(f"已放行 {int(record.get('approved_override_count') or 0)}")
                    )
            index_version = int(record.get("index_version") or 0)
            if index_version:
                stats.append(self.tr(f"索引版本 {index_version}"))
            lines.append("   " + " · ".join(stats))
        return "\n".join(lines)

    def _format_shared_library_approval_queue_text(
        self,
        records: list[Dict[str, Any]],
    ) -> str:
        """格式化共享审批队列。"""
        if not records:
            return self.tr("当前没有共享待审记录")

        pending_records = [record for record in records if record.get("decision") == "pending"]
        approved_records = [record for record in records if record.get("decision") == "approved"]
        rejected_records = [record for record in records if record.get("decision") == "rejected"]
        lines = [
            self.tr(
                f"待审 {len(pending_records)} 项 · 已批准 {len(approved_records)} 项 · "
                f"已拒绝 {len(rejected_records)} 项"
            )
        ]

        for index, record in enumerate(records[:12], start=1):
            decision = str(record.get("decision") or "pending")
            if decision == "approved":
                decision_label = self.tr("已批准")
            elif decision == "rejected":
                decision_label = self.tr("已拒绝")
            else:
                decision_label = self.tr("待审")
            package_type = self._shared_library_package_type_label(
                str(record.get("package_type") or "")
            )
            reasons = []
            for reason in record.get("reasons") or []:
                if str(reason).startswith("team_rule_block:"):
                    rule_name = str(reason).split(":", 1)[1].strip()
                    reasons.append(self.tr(f"命中团队阻断规则: {rule_name or '未命名规则'}"))
                elif str(reason).startswith("team_rule:"):
                    rule_name = str(reason).split(":", 1)[1].strip()
                    reasons.append(self.tr(f"命中团队审批规则: {rule_name or '未命名规则'}"))
                elif reason == "untrusted_source":
                    reasons.append(self.tr("来源未受信任"))
                elif reason == "blocked_package_type":
                    reasons.append(self.tr("包类型未加入自动拉取"))
                elif reason == "untrusted_signer":
                    reasons.append(self.tr("签名者未受信任"))
                elif reason == "revoked_signer":
                    reasons.append(self.tr("签名者已撤销"))
                elif reason == "invalid_integrity":
                    reasons.append(self.tr("完整性校验失败"))
                elif reason == "invalid_signature":
                    reasons.append(self.tr("签名校验失败"))
                elif str(reason).strip():
                    reasons.append(str(reason))
            reason_text = self.tr(f"原因: {', '.join(reasons)}") if reasons else ""
            decided_or_requested_at = (
                str(record.get("decided_at") or "").strip()
                or str(record.get("requested_at") or "").strip()
            )
            line = self.tr(
                f"{index}. {decision_label} · {record.get('name', '未命名共享包')} · "
                f"{package_type} · 来源 {record.get('source_app', 'Neko_Shell')} · "
                f"版本 v{int(record.get('package_version') or 1)}"
            )
            if decided_or_requested_at:
                line += self.tr(f" · 时间 {decided_or_requested_at}")
            if reason_text:
                line += self.tr(f"\n   {reason_text}")
            lines.append(line)
        return "\n".join(lines)

    def _shared_library_sync_policy_label(self, policy: str) -> str:
        """返回共享同步策略标签。"""
        if policy == "startup_pull_if_changed":
            return self.tr("仅在索引更新时自动拉取")
        if policy == "startup_pull":
            return self.tr("启动时自动拉取")
        return self.tr("手动同步")

    def _shared_library_rotation_policy_label(self, policy: str) -> str:
        """返回共享签名轮换治理动作标签。"""
        if policy == "approval":
            return self.tr("进入审批")
        if policy == "block":
            return self.tr("直接阻断")
        return self.tr("仅提示")

    def _format_shared_library_lock_text(self, lock_info: Dict[str, Any]) -> str:
        """格式化共享仓库锁信息。"""
        if not lock_info.get("exists"):
            return self.tr("当前无共享仓库锁")
        state_label = self.tr("锁定中") if lock_info.get("active") else self.tr("已过期")
        lines = [
            self.tr(f"锁状态: {state_label}"),
            self.tr(f"操作: {lock_info.get('operation') or '未知'}"),
            self.tr(f"持有者: {lock_info.get('owner') or '未知'}"),
        ]
        created_at = str(lock_info.get("created_at") or "").strip()
        if created_at:
            lines.append(self.tr(f"创建时间: {created_at}"))
        expires_at = str(lock_info.get("expires_at") or "").strip()
        if expires_at:
            lines.append(self.tr(f"过期时间: {expires_at}"))
        return "\n".join(lines)

    def _maybe_resolve_shared_library_force_lock(
        self,
        sync_dir: str,
        action_label: str,
    ) -> Optional[bool]:
        """检查共享仓库锁，并在过期时允许用户强制接管。"""
        if not self._config_manager:
            return None
        lock_info = self._config_manager.inspect_shared_library_lock(sync_dir)
        if not lock_info.get("exists"):
            return False
        if lock_info.get("active"):
            QMessageBox.warning(
                self,
                self.tr("共享仓库已锁定"),
                self.tr(f"无法执行 {action_label}。\n\n")
                + self._format_shared_library_lock_text(lock_info),
            )
            return None
        confirm = QMessageBox.question(
            self,
            self.tr("检测到过期锁"),
            self.tr(f"执行 {action_label} 前发现共享仓库存在过期锁。\n\n")
            + self._format_shared_library_lock_text(lock_info)
            + "\n\n"
            + self.tr("是否强制接管该锁并继续？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return confirm == QMessageBox.StandardButton.Yes

    def _apply_shared_library_sync_policy(self) -> None:
        """根据配置的共享同步策略在启动时执行动作。"""
        if not self._config_manager:
            return
        config = self._config_manager.app_config
        sync_dir = str(config.shared_library_sync_dir or "").strip()
        if (
            config.shared_library_sync_policy not in {"startup_pull", "startup_pull_if_changed"}
            or not sync_dir
        ):
            return
        if not Path(sync_dir).exists():
            self.update_status(self.tr(f"共享仓库目录不存在，已跳过自动拉取: {sync_dir}"))
            return

        lock_info = self._config_manager.inspect_shared_library_lock(sync_dir)
        if lock_info.get("active"):
            self.update_status(
                self.tr(
                    f"共享仓库正被占用，已跳过自动拉取: {lock_info.get('owner') or '未知持有者'}"
                )
            )
            return

        try:
            preview = self._config_manager.preview_shared_library_pull(
                sync_dir,
                trusted_source_apps=config.shared_library_trusted_source_apps,
                trusted_signer_fingerprints=config.shared_library_trusted_signer_fingerprints,
                revoked_signer_fingerprints=config.shared_library_revoked_signer_fingerprints,
                allowed_package_types=config.shared_library_auto_pull_allowed_package_types,
                rotation_due_policy=config.shared_library_rotation_due_policy,
                rotation_overdue_policy=config.shared_library_rotation_overdue_policy,
            )
            current_index_version = int(preview.get("index_version") or 0)
            cached_index_version = self._config_manager.get_shared_library_cached_index_version(
                sync_dir
            )
            if (
                config.shared_library_sync_policy == "startup_pull_if_changed"
                and current_index_version <= cached_index_version
            ):
                return
            if (
                int(preview.get("new_count") or 0) <= 0
                and int(preview.get("newer_external_count") or 0) <= 0
                and int(preview.get("conflict_count") or 0) <= 0
                and int(preview.get("approval_required_count") or 0) <= 0
                and int(preview.get("integrity_blocked_count") or 0) <= 0
                and int(preview.get("integrity_unverified_count") or 0) <= 0
                and int(preview.get("signature_blocked_count") or 0) <= 0
                and int(preview.get("signature_unverified_count") or 0) <= 0
            ):
                if current_index_version:
                    self._config_manager.update_shared_library_cached_index_version(
                        sync_dir,
                        current_index_version,
                    )
                return
            result = self._config_manager.pull_shared_library_from_directory(
                sync_dir,
                force_lock=bool(lock_info.get("stale")),
                trusted_source_apps=config.shared_library_trusted_source_apps,
                trusted_signer_fingerprints=config.shared_library_trusted_signer_fingerprints,
                revoked_signer_fingerprints=config.shared_library_revoked_signer_fingerprints,
                allowed_package_types=config.shared_library_auto_pull_allowed_package_types,
                rotation_due_policy=config.shared_library_rotation_due_policy,
                rotation_overdue_policy=config.shared_library_rotation_overdue_policy,
                queue_pending_approvals=True,
            )
        except Exception as exc:
            self.update_status(self.tr(f"共享中心自动拉取失败: {exc}"))
            return

        if int(result.get("index_version") or 0):
            self._config_manager.update_shared_library_cached_index_version(
                sync_dir,
                int(result.get("index_version") or 0),
            )
        self._refresh_workspace_templates_menu()
        self._refresh_connection_filter_presets_menu()
        trusted_sources = [
            str(item)
            for item in config.shared_library_trusted_source_apps or []
            if str(item).strip()
        ]
        allowed_package_types = [
            self._shared_library_package_type_label(str(item))
            for item in config.shared_library_auto_pull_allowed_package_types or []
            if str(item).strip()
        ]
        trusted_suffix = (
            self.tr(f" · 信任来源 {', '.join(trusted_sources[:3])}")
            if trusted_sources
            else self.tr(" · 允许全部来源")
        )
        package_type_suffix = (
            self.tr(f" · 自动拉取类型 {', '.join(allowed_package_types)}")
            if allowed_package_types
            else self.tr(" · 自动拉取类型 已关闭")
        )
        approval_suffix = ""
        if int(result.get("pending_approval_count") or 0):
            approval_suffix = self.tr(
                f" · 待审 {int(result.get('pending_approval_count') or 0)} 项"
            )
        integrity_suffix = ""
        if int(result.get("integrity_blocked_count") or 0):
            integrity_suffix = self.tr(
                f" · 完整性异常 {int(result.get('integrity_blocked_count') or 0)} 项"
            )
        signature_suffix = ""
        if int(result.get("revoked_signer_count") or 0):
            signature_suffix += self.tr(
                f" · 已撤销签名者 {int(result.get('revoked_signer_count') or 0)} 项"
            )
        if int(result.get("expired_signer_policy_count") or 0):
            signature_suffix += self.tr(
                f" · 策略已过期签名者 {int(result.get('expired_signer_policy_count') or 0)} 项"
            )
        if int(result.get("rotation_due_count") or 0):
            signature_suffix += self.tr(
                f" · 轮换临近 {int(result.get('rotation_due_count') or 0)} 项"
            )
        if int(result.get("rotation_overdue_count") or 0):
            signature_suffix += self.tr(
                f" · 轮换超期 {int(result.get('rotation_overdue_count') or 0)} 项"
            )
        if int(result.get("rotation_warning_count") or 0):
            signature_suffix += self.tr(
                f" · 轮换提示 {int(result.get('rotation_warning_count') or 0)} 项"
            )
        if int(result.get("rotation_exception_count") or 0):
            signature_suffix += self.tr(
                f" · 轮换例外 {int(result.get('rotation_exception_count') or 0)} 项"
            )
        if int(result.get("untrusted_signer_count") or 0):
            signature_suffix += self.tr(
                f" · 未受信任签名者 {int(result.get('untrusted_signer_count') or 0)} 项"
            )
        if int(result.get("signature_blocked_count") or 0):
            signature_suffix += self.tr(
                f" · 签名异常 {int(result.get('signature_blocked_count') or 0)} 项"
            )
        if int(result.get("signature_unverified_count") or 0):
            signature_suffix += self.tr(
                f" · 未签名 {int(result.get('signature_unverified_count') or 0)} 项"
            )
        self.update_status(
            self.tr(
                f"已按策略自动拉取共享仓库: {sync_dir} · "
                f"导入 {int(result.get('imported_count') or 0)} 项"
            )
            + trusted_suffix
            + package_type_suffix
            + approval_suffix
            + integrity_suffix
            + signature_suffix
        )

    def _resolve_shared_library_sync_dir(self) -> Optional[str]:
        """获取共享仓库目录，未配置时允许用户选择并持久化。"""
        if not self._config_manager:
            return None

        sync_dir = str(self._config_manager.app_config.shared_library_sync_dir or "").strip()
        if sync_dir:
            return sync_dir

        selected_dir = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择共享仓库目录"),
        )
        if not selected_dir:
            return None

        app_config = self._config_manager.app_config
        app_config.shared_library_sync_dir = selected_dir
        self._config_manager.save_app_config(app_config)
        return selected_dir

    @staticmethod
    def _sort_records_by_recent_usage(records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """按最近使用、使用次数和名称排序。"""
        sorted_records = [dict(record) for record in records if isinstance(record, dict)]
        sorted_records.sort(key=lambda record: str(record.get("name") or "").casefold())
        sorted_records.sort(key=lambda record: str(record.get("updated_at") or ""), reverse=True)
        sorted_records.sort(key=lambda record: int(record.get("usage_count") or 0), reverse=True)
        sorted_records.sort(key=lambda record: str(record.get("last_used_at") or ""), reverse=True)
        return sorted_records

    def _workspace_template_kind_label(self, template_kind: str) -> str:
        """返回工作区模板类型标签。"""
        if template_kind == "ops_workspace":
            return self.tr("运维工作台模板")
        if template_kind == "scene_workspace":
            return self.tr("场景模板")
        return self.tr("工作区模板")

    def _workspace_template_menu_text(self, template: Dict[str, Any]) -> str:
        """生成工作区模板菜单文案。"""
        name = str(template.get("name") or self.tr("未命名模板"))
        connection_count = len(template.get("connection_ids", []) or [])
        text = self.tr(f"{name} ({connection_count})")
        usage_count = int(template.get("usage_count") or 0)
        if usage_count:
            text = self.tr(f"{text} · {usage_count} 次")
        return text

    def _workspace_template_status_text(self, template: Dict[str, Any]) -> str:
        """生成工作区模板状态提示。"""
        parts = [
            self._workspace_template_kind_label(str(template.get("template_kind") or "workspace"))
        ]
        scope_view = str(template.get("scope_view") or "").strip()
        scope_name = str(template.get("scope_name") or "").strip()
        if scope_view and scope_name:
            parts.append(self.tr(f"来源 {scope_view} / {scope_name}"))
        if template.get("include_file_browsers"):
            parts.append(self.tr("包含文件页"))
        if template.get("include_local_terminal"):
            parts.append(self.tr("包含本地终端"))
        filter_state = template.get("filter_state")
        if isinstance(filter_state, dict):
            parts.append(self.tr(f"筛选 {self._describe_connection_filter_state(filter_state)}"))
        task_preset_title = str(template.get("task_preset_title") or "").strip()
        if task_preset_title:
            parts.append(self.tr(f"推荐任务 {task_preset_title}"))
        if template.get("last_used_at"):
            parts.append(self.tr(f"最近使用 {template['last_used_at']}"))
        return " · ".join(parts)

    @staticmethod
    def _connection_template_status_text(template: Dict[str, Any]) -> str:
        """生成连接模板状态说明。"""
        payload = dict(template.get("payload") or {})
        parts = [str(template.get("connection_type") or "").upper()]
        host = str(payload.get("host") or payload.get("remote_host") or "").strip()
        if host:
            parts.append(host)
        port = payload.get("port") or payload.get("remote_port")
        if port not in (None, ""):
            parts.append(f":{port}")
        group = str(payload.get("group") or "").strip()
        if group:
            parts.append(group)
        updated_at = str(template.get("updated_at") or "").strip()
        if updated_at:
            parts.append(f"更新 {updated_at}")
        return " · ".join(part for part in parts if part)

    @staticmethod
    def _sort_connections_for_quick_open(
        connections: list[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        """为快速打开面板排序连接。"""
        sorted_connections = [dict(conn) for conn in connections if isinstance(conn, dict)]
        sorted_connections.sort(key=lambda conn: str(conn.get("name") or "").casefold())
        sorted_connections.sort(key=lambda conn: str(conn.get("host") or "").casefold())
        sorted_connections.sort(key=lambda conn: bool(conn.get("favorite")), reverse=True)
        sorted_connections.sort(
            key=lambda conn: str(conn.get("last_connected_at") or ""), reverse=True
        )
        return sorted_connections

    @staticmethod
    def _connection_can_open_file_browser(conn_data: Dict[str, Any]) -> bool:
        """判断连接是否支持文件浏览器入口。"""
        return str(conn_data.get("connection_type") or "").lower() in {"ssh", "sftp", "ftp"}

    def _build_quick_open_entries(self) -> list[Dict[str, Any]]:
        """构建快速打开面板候选项。"""
        entries: list[Dict[str, Any]] = [
            {
                "kind": "local_terminal",
                "title": self.tr("本地终端"),
                "subtitle": self.tr("立即打开本地 shell"),
                "detail": self.tr("常用入口 · 打开本地终端标签页。"),
                "searchable_text": "本地终端 local shell terminal",
                "icon": icon("local_terminal"),
            },
            {
                "kind": "page",
                "page_key": "command_center",
                "title": self.tr("快捷命令中心"),
                "subtitle": self.tr("搜索并执行收藏命令、片段和命令宏"),
                "detail": self.tr("常用页面 · 打开快捷命令中心，快速执行或编排常用命令。"),
                "searchable_text": "快捷命令中心 command center macro snippet 收藏命令",
                "icon": icon("terminal"),
            },
            {
                "kind": "page",
                "page_key": "tunnels",
                "title": self.tr("SSH 隧道"),
                "subtitle": self.tr("打开 SSH 隧道管理页"),
                "detail": self.tr("常用页面 · 管理本地转发、远程转发和动态转发。"),
                "searchable_text": "ssh 隧道 tunnel port forward",
                "icon": icon("tunnel"),
            },
            {
                "kind": "page",
                "page_key": "docker",
                "title": self.tr("Docker"),
                "subtitle": self.tr("打开 Docker 管理页"),
                "detail": self.tr("常用页面 · 查看容器、日志和终端入口。"),
                "searchable_text": "docker 容器 container",
                "icon": icon("docker"),
            },
            {
                "kind": "page",
                "page_key": "frp",
                "title": self.tr("FRP"),
                "subtitle": self.tr("打开 FRP 管理页"),
                "detail": self.tr("常用页面 · 管理 FRP 配置和运行状态。"),
                "searchable_text": "frp 内网穿透 proxy tunnel",
                "icon": icon("frp"),
            },
        ]

        if not self._config_manager:
            return entries

        connections = self._sort_connections_for_quick_open(self._config_manager.load_connections())
        favorite_connections = self._config_manager.load_favorite_connections()
        recent_connections = self._config_manager.load_recent_connections(limit=8)
        favorite_ids = {str(conn.get("id") or "") for conn in favorite_connections}
        recent_ids = {str(conn.get("id") or "") for conn in recent_connections}

        if favorite_connections:
            entries.append(
                {
                    "kind": "collection_workspace",
                    "collection_label": self.tr("收藏连接"),
                    "connections": [dict(conn) for conn in favorite_connections],
                    "title": self.tr("打开全部收藏连接"),
                    "subtitle": self.tr(f"{len(favorite_connections)} 个连接 · 运维工作台"),
                    "detail": self.tr("聚合入口 · 以工作区方式一次打开全部收藏连接。"),
                    "searchable_text": "收藏连接 favorite workspace",
                    "icon": icon("quick_connect"),
                }
            )

        if recent_connections:
            entries.append(
                {
                    "kind": "collection_workspace",
                    "collection_label": self.tr("最近连接"),
                    "connections": [dict(conn) for conn in recent_connections],
                    "title": self.tr("打开全部最近连接"),
                    "subtitle": self.tr(f"{len(recent_connections)} 个连接 · 运维工作台"),
                    "detail": self.tr("聚合入口 · 以工作区方式一次打开最近使用的连接。"),
                    "searchable_text": "最近连接 recent workspace",
                    "icon": icon("quick_connect"),
                }
            )

        filtered_connections = self.connection_tree.get_filtered_connections()
        if filtered_connections:
            filter_summary = self._describe_connection_filter_state(
                self.connection_tree.export_filter_state()
            )
            entries.append(
                {
                    "kind": "filtered_workspace",
                    "title": self.tr("打开当前筛选结果"),
                    "subtitle": self.tr(f"{len(filtered_connections)} 个连接 · {filter_summary}"),
                    "detail": self.tr("聚合入口 · 直接把当前连接树筛选结果打开成工作区。"),
                    "searchable_text": f"当前筛选 过滤 filter {filter_summary}",
                    "icon": icon("quick_connect"),
                }
            )

        for conn_data in connections:
            conn_id = str(conn_data.get("id") or "").strip()
            if not conn_id:
                continue
            name = str(conn_data.get("name") or self.tr("未命名连接")).strip()
            host = str(conn_data.get("host") or "").strip()
            group = str(conn_data.get("group") or "").strip()
            username = str(conn_data.get("username") or "").strip()
            port = str(conn_data.get("port") or "").strip()
            conn_type = str(conn_data.get("connection_type") or "ssh").lower()
            badges: list[str] = []
            if conn_id in favorite_ids:
                badges.append(self.tr("收藏"))
            if conn_id in recent_ids:
                badges.append(self.tr("最近"))
            if group:
                badges.append(group)
            subtitle_parts = [part for part in [host, username, f":{port}" if port else ""] if part]
            subtitle = " ".join(subtitle_parts).strip()
            if badges:
                subtitle = (
                    self.tr(f"{subtitle} · {' / '.join(badges)}")
                    if subtitle
                    else " / ".join(badges)
                )

            searchable_parts = [
                name,
                host,
                group,
                username,
                str(conn_data.get("description") or ""),
                str(conn_data.get("tags") or ""),
                conn_type,
            ]
            entries.append(
                {
                    "kind": "connection",
                    "connection_id": conn_id,
                    "title": name,
                    "subtitle": subtitle or self.tr("打开连接"),
                    "detail": self.tr(f"{conn_type.upper()} 连接 · 终端/视图入口"),
                    "searchable_text": " ".join(part for part in searchable_parts if part),
                    "icon": connection_type_icon(conn_type),
                }
            )
            if self._connection_can_open_file_browser(conn_data):
                entries.append(
                    {
                        "kind": "file_browser",
                        "connection_id": conn_id,
                        "title": self.tr(f"文件 · {name}"),
                        "subtitle": subtitle or self.tr("打开文件浏览器"),
                        "detail": self.tr("文件入口 · 直接打开该连接的文件浏览器。"),
                        "searchable_text": " ".join(
                            part
                            for part in [name, host, group, username, "文件 file browser sftp ftp"]
                            if part
                        ),
                        "icon": icon("sftp" if conn_type in {"ssh", "sftp"} else "ftp"),
                    }
                )

        for template in self._sort_records_by_recent_usage(
            self._config_manager.load_workspace_templates()
        ):
            template_id = str(template.get("id") or "").strip()
            if not template_id:
                continue
            name = str(template.get("name") or self.tr("未命名模板")).strip()
            status_text = self._workspace_template_status_text(template)
            entries.append(
                {
                    "kind": "workspace_template",
                    "template_id": template_id,
                    "title": self.tr(f"模板 · {name}"),
                    "subtitle": status_text,
                    "detail": self.tr("工作区模板 · 按保存布局恢复一组连接与页面。"),
                    "searchable_text": " ".join(
                        [
                            name,
                            status_text,
                            str(template.get("scope_name") or ""),
                            str(template.get("scope_view") or ""),
                            "workspace template 模板 工作区",
                        ]
                    ),
                    "icon": icon("quick_connect"),
                }
            )

        connection_templates = [
            dict(template)
            for template in self._config_manager.load_connection_templates()
            if isinstance(template, dict)
            and str(template.get("template_scope") or "connection") == "connection"
        ]
        connection_templates.sort(key=lambda template: str(template.get("name") or "").casefold())
        connection_templates.sort(
            key=lambda template: str(template.get("updated_at") or ""),
            reverse=True,
        )
        for template in connection_templates:
            template_id = str(template.get("id") or "").strip()
            if not template_id:
                continue
            status_text = self._connection_template_status_text(template)
            title = self.tr(f"模板连接 · {template.get('name', '未命名模板')}")
            entries.append(
                {
                    "kind": "connection_template",
                    "template_id": template_id,
                    "title": title,
                    "subtitle": status_text or self.tr("使用连接模板快速发起临时连接"),
                    "detail": self.tr("连接模板 · 直接使用模板发起临时连接，不写入连接列表。"),
                    "searchable_text": " ".join(
                        [
                            title,
                            status_text,
                            str(template.get("connection_type") or ""),
                            str((template.get("payload") or {}).get("host") or ""),
                            str((template.get("payload") or {}).get("group") or ""),
                            "template login auth quick connect 模板连接 登录模板",
                        ]
                    ),
                    "icon": connection_type_icon(str(template.get("connection_type") or "ssh")),
                }
            )

        return entries

    def _build_command_center_entries(
        self,
        context_widget: Optional[QWidget] = None,
    ) -> list[Dict[str, Any]]:
        """构建快捷命令中心候选项。"""
        payload = self._compose_command_library(context_widget)
        favorite_snippets = list(payload.get("favorite_snippets") or [])
        snippet_groups = dict(payload.get("snippet_groups") or {})
        macros = dict(payload.get("macros") or {})

        entries: list[Dict[str, Any]] = []
        seen_commands: set[tuple[str, str]] = set()

        for command in favorite_snippets:
            normalized = str(command).strip()
            if not normalized:
                continue
            key = ("favorite", normalized)
            if key in seen_commands:
                continue
            seen_commands.add(key)
            entries.append(
                {
                    "kind": "snippet",
                    "title": normalized,
                    "subtitle": self.tr("收藏命令"),
                    "detail": self.tr("可立即发送到当前终端，也可转入编排发送继续整理。"),
                    "commands": [normalized],
                    "searchable_text": f"{normalized} 收藏 favorite command",
                    "icon": icon("flash"),
                }
            )

        for group_name, commands in snippet_groups.items():
            for command in commands:
                normalized = str(command).strip()
                if not normalized:
                    continue
                key = ("snippet", group_name, normalized)
                if key in seen_commands:
                    continue
                seen_commands.add(key)
                entries.append(
                    {
                        "kind": "snippet",
                        "title": normalized,
                        "subtitle": self.tr(f"命令片段 · {group_name}"),
                        "detail": self.tr(
                            f"来源 {group_name} · 单条命令可立即执行或转入编排发送。"
                        ),
                        "commands": [normalized],
                        "searchable_text": f"{normalized} {group_name} snippet command",
                        "icon": icon("terminal"),
                    }
                )

        for macro_name, commands in macros.items():
            normalized_commands = [
                str(command).strip() for command in commands if str(command).strip()
            ]
            if not normalized_commands:
                continue
            entries.append(
                {
                    "kind": "macro",
                    "title": macro_name,
                    "subtitle": self.tr(f"命令宏 · {len(normalized_commands)} 条命令"),
                    "detail": self.tr(f"命令宏 {macro_name} · 可直接批量执行或转入编排发送。"),
                    "commands": normalized_commands,
                    "searchable_text": " ".join(
                        [macro_name, *normalized_commands, "macro command 命令宏"]
                    ),
                    "icon": icon("quick_connect"),
                }
            )

        entries.sort(key=lambda entry: str(entry.get("title") or "").casefold())
        entries.sort(key=lambda entry: 0 if entry.get("kind") == "macro" else 1)
        entries.sort(key=lambda entry: 0 if "收藏" in str(entry.get("subtitle") or "") else 1)
        return entries

    def _save_commands_to_global_favorites(self, commands: list[str]) -> list[str]:
        """将命令保存到全局收藏与个人收藏分组。"""
        if not self._config_manager:
            raise ConfigurationError("配置管理器未初始化")

        normalized_commands = [str(command).strip() for command in commands if str(command).strip()]
        if not normalized_commands:
            return []

        config = self._config_manager.app_config
        snippet_groups = normalize_terminal_snippet_groups(
            getattr(config, "terminal_snippet_groups", None)
            or getattr(config, "terminal_snippets", None)
        )
        favorite_group_name = self.tr("个人收藏")
        favorite_group = list(snippet_groups.get(favorite_group_name, []))
        appended_commands: list[str] = []
        for command in normalized_commands:
            if command not in favorite_group:
                favorite_group.append(command)
                appended_commands.append(command)
        snippet_groups[favorite_group_name] = favorite_group

        config.terminal_snippet_groups = snippet_groups
        config.terminal_snippets = flatten_terminal_snippet_groups(snippet_groups)
        existing_favorites = list(getattr(config, "terminal_favorite_snippets", []) or [])
        config.terminal_favorite_snippets = normalize_terminal_favorite_snippets(
            [*existing_favorites, *normalized_commands],
            snippet_groups,
            allow_empty=True,
        )
        self._config_manager.save_app_config(config)
        self._apply_terminal_preferences()
        return normalized_commands

    def _save_commands_as_global_macro(self, macro_name: str, commands: list[str]) -> list[str]:
        """将命令保存为全局命令宏。"""
        if not self._config_manager:
            raise ConfigurationError("配置管理器未初始化")

        normalized_name = str(macro_name or "").strip()
        normalized_commands = [str(command).strip() for command in commands if str(command).strip()]
        if not normalized_name:
            raise ConfigurationError("宏名称不能为空")
        if not normalized_commands:
            raise ConfigurationError("宏内容不能为空")

        config = self._config_manager.app_config
        macros = normalize_terminal_macros(
            getattr(config, "terminal_macros", None),
            allow_empty=True,
        )
        macros[normalized_name] = normalized_commands
        config.terminal_macros = normalize_terminal_macros(macros, allow_empty=True)
        self._config_manager.save_app_config(config)
        self._apply_terminal_preferences()
        return normalized_commands

    def _execute_commands_on_context_widget(
        self,
        commands: list[str],
        *,
        context_widget: Optional[QWidget] = None,
        source_label: Optional[str] = None,
    ) -> bool:
        """直接在当前上下文终端执行命令列表。"""
        widget = self._preferred_sync_context_widget(context_widget)
        if widget is None:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前没有可用于执行命令的终端"),
            )
            return False

        normalized_commands = [str(command).strip() for command in commands if str(command).strip()]
        if not normalized_commands:
            QMessageBox.information(self, self.tr("提示"), self.tr("没有可执行的命令"))
            return False

        try:
            for command in normalized_commands:
                widget.execute_broadcast_command(command)
        except Exception as exc:
            self._logger.error("快捷命令执行失败: %s", exc)
            QMessageBox.critical(self, self.tr("执行失败"), str(exc))
            return False

        label = source_label or self.tr("快捷命令")
        self.update_status(self.tr(f"{label} 已发送到当前终端"))
        return True

    def _execute_quick_open_entry(self, entry: Dict[str, Any]) -> None:
        """执行快速打开条目。"""
        kind = str(entry.get("kind") or "").strip()
        if kind == "local_terminal":
            self._on_open_local_terminal()
            self.update_status(self.tr("已打开本地终端"))
            return
        if kind == "page":
            page_key = str(entry.get("page_key") or "").strip()
            if page_key == "command_center":
                self._on_open_command_center()
            elif page_key == "tunnels":
                self._on_show_tunnels()
            elif page_key == "docker":
                self._on_show_docker()
            elif page_key == "frp":
                self._on_show_frp()
            self.update_status(self.tr(f"已打开: {entry.get('title', '')}"))
            return
        if kind == "connection":
            self._open_connection(conn_id=str(entry.get("connection_id") or ""))
            return
        if kind == "file_browser":
            self._open_file_browser_for_connection(str(entry.get("connection_id") or ""))
            return
        if kind == "workspace_template":
            self._open_workspace_template(str(entry.get("template_id") or ""))
            return
        if kind == "connection_template":
            if not self._config_manager:
                return
            template_id = str(entry.get("template_id") or "").strip()
            template = next(
                (
                    current
                    for current in self._config_manager.load_connection_templates()
                    if str(current.get("id") or "") == template_id
                ),
                None,
            )
            if not isinstance(template, dict):
                return
            payload = dict(template.get("payload") or {})
            payload.pop("id", None)
            payload.setdefault(
                "name",
                str(template.get("name") or self.tr("未命名模板连接")).strip(),
            )
            payload["connection_type"] = str(template.get("connection_type") or "ssh").lower()
            try:
                template_connection = ConnectionFactory.create_from_dict(payload)
            except Exception as exc:
                QMessageBox.critical(self, self.tr("模板连接失败"), str(exc))
                return
            self._open_connection(config=template_connection.config, persist=False)
            return
        if kind == "collection_workspace":
            self._open_connection_collection_workspace(
                str(entry.get("collection_label") or self.tr("连接集合")),
                list(entry.get("connections") or []),
            )
            return
        if kind == "filtered_workspace":
            self._on_open_filtered_connections_workspace()

    def _find_workspace_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 查找工作区模板。"""
        if not self._config_manager:
            return None
        return next(
            (
                item
                for item in self._config_manager.load_workspace_templates()
                if item.get("id") == template_id
            ),
            None,
        )

    def _filtered_scope_name(self) -> str:
        """返回当前筛选范围名称。"""
        return self._describe_connection_filter_state(self.connection_tree.export_filter_state())

    def _current_filtered_scope_payload(
        self,
        *,
        template_kind: str,
        include_file_browsers: bool,
        include_local_terminal: bool,
        task_preset_key: Optional[str] = None,
        task_preset_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """根据当前筛选结果构造范围载荷。"""
        return {
            "scope_name": self._filtered_scope_name(),
            "view_mode": "filtered",
            "view_label": self.tr("筛选结果"),
            "connection_ids": self.connection_tree.get_filtered_connection_ids(),
            "include_file_browsers": include_file_browsers,
            "include_local_terminal": include_local_terminal,
            "template_kind": template_kind,
            "filter_state": self.connection_tree.export_filter_state(),
            "task_preset_key": task_preset_key,
            "task_preset_title": task_preset_title,
        }

    def _prompt_task_preset_choice(
        self,
        *,
        title: str,
        label: str,
        default_key: Optional[str] = None,
        allow_none: bool = True,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """让用户选择推荐任务预设。"""
        choices: list[tuple[str, Optional[str]]] = []
        if allow_none:
            choices.append((self.tr("不设置推荐任务"), None))
        for preset_key in self.TASK_PRESET_ORDER:
            preset = self._task_preset_definition(preset_key)
            choices.append((self.tr(preset.title), preset_key))

        labels = [choice_label for choice_label, _key in choices]
        default_index = 0
        if default_key:
            for index, (_choice_label, preset_key) in enumerate(choices):
                if preset_key == default_key:
                    default_index = index
                    break

        selected_label, ok = QInputDialog.getItem(
            self,
            title,
            label,
            labels,
            default_index,
            False,
        )
        if not ok:
            return False, None, None

        for choice_label, preset_key in choices:
            if choice_label != selected_label:
                continue
            preset_title = (
                self.tr(self._task_preset_definition(preset_key).title) if preset_key else None
            )
            return True, preset_key, preset_title
        return True, None, None

    def _suggest_connection_filter_preset_name(self, filter_state: Dict[str, Any]) -> str:
        """根据筛选条件生成更合适的预设名。"""
        summary = self._describe_connection_filter_state(filter_state)
        if summary == self.tr("全部连接"):
            return self.tr("当前筛选")
        return summary[:48]

    def _describe_connection_filter_state(self, filter_state: Dict[str, Any]) -> str:
        """生成连接筛选条件摘要。"""
        filters = dict(filter_state) if isinstance(filter_state, dict) else {}
        parts: list[str] = []

        keyword = str(filters.get("search") or "").strip()
        if keyword:
            parts.append(self.tr(f"搜索 {keyword}"))

        type_value = str(filters.get("type") or "__all__")
        if type_value != "__all__":
            parts.append(self.tr(f"类型 {type_value.upper()}"))

        view_value = str(filters.get("view") or ConnectionTreeWidget.VIEW_GROUP)
        if view_value != ConnectionTreeWidget.VIEW_GROUP:
            parts.append(self.tr(f"视图 {self.connection_tree._view_label(view_value)}"))

        favorite_value = str(filters.get("favorite") or "__all__")
        if favorite_value == "__favorite_only__":
            parts.append(self.tr("仅收藏"))
        elif favorite_value == "__non_favorite_only__":
            parts.append(self.tr("未收藏"))

        group_value = str(filters.get("group") or "__all__").strip()
        if group_value != "__all__":
            parts.append(self.tr(f"{self.connection_tree._view_label(view_value)} {group_value}"))

        return " · ".join(parts) if parts else self.tr("全部连接")

    def _create_shared_library_share_menu(
        self,
        parent_menu: QMenu,
        *,
        import_text: str,
        import_handler: Callable[[], None],
        publish_text: str,
        publish_handler: Callable[[], None],
        remove_text: str,
        remove_handler: Callable[[], None],
    ) -> SharedLibraryShareMenuBindings:
        """创建共享与同步子菜单。"""
        share_menu = self._add_owned_submenu(parent_menu, self.tr("共享与同步（可选）"))

        import_action = share_menu.addAction(import_text)
        import_action.triggered.connect(import_handler)

        publish_action = share_menu.addAction(publish_text)
        publish_action.triggered.connect(publish_handler)

        remove_action = share_menu.addAction(remove_text)
        remove_action.triggered.connect(remove_handler)

        share_menu.addSeparator()

        push_action = share_menu.addAction(self.tr("同步共享中心到共享仓库"))
        push_action.triggered.connect(self._on_push_shared_library_to_directory)

        pull_action = share_menu.addAction(self.tr("从共享仓库同步到共享中心"))
        pull_action.triggered.connect(self._on_pull_shared_library_from_directory)

        share_menu.addSeparator()

        status_action = share_menu.addAction(self.tr("查看共享仓库状态"))
        status_action.triggered.connect(self._on_view_shared_library_repository_status)

        history_action = share_menu.addAction(self.tr("查看共享同步历史"))
        history_action.triggered.connect(self._on_view_shared_library_sync_history)

        approval_action = share_menu.addAction(self.tr("查看共享待审队列"))
        approval_action.triggered.connect(self._on_view_shared_library_approval_queue)

        integrity_action = share_menu.addAction(self.tr("查看共享完整性异常"))
        integrity_action.triggered.connect(self._on_view_shared_library_integrity_issues)

        governance_action = share_menu.addAction(self.tr("查看共享治理审计"))
        governance_action.triggered.connect(self._on_view_shared_library_governance_audit)

        report_action = share_menu.addAction(self.tr("导出共享治理报告"))
        report_action.triggered.connect(self._on_export_shared_library_governance_report)

        return SharedLibraryShareMenuBindings(
            menu=share_menu,
            import_action=import_action,
            publish_action=publish_action,
            remove_action=remove_action,
            push_action=push_action,
            pull_action=pull_action,
            status_action=status_action,
            history_action=history_action,
            approval_action=approval_action,
            integrity_action=integrity_action,
            governance_action=governance_action,
            report_action=report_action,
        )

    @staticmethod
    def _update_shared_library_share_menu_state(
        bindings: SharedLibraryShareMenuBindings,
        *,
        has_local_records: bool,
        has_shared_records: bool,
        enabled: bool = True,
    ) -> None:
        """刷新共享与同步子菜单可用状态。"""
        bindings.menu.setEnabled(enabled)
        all_actions = (
            bindings.import_action,
            bindings.publish_action,
            bindings.remove_action,
            bindings.push_action,
            bindings.pull_action,
            bindings.status_action,
            bindings.history_action,
            bindings.approval_action,
            bindings.integrity_action,
            bindings.governance_action,
            bindings.report_action,
        )
        if not enabled:
            for action in all_actions:
                action.setEnabled(False)
            return

        bindings.import_action.setEnabled(has_shared_records)
        bindings.publish_action.setEnabled(has_local_records)
        bindings.remove_action.setEnabled(has_shared_records)
        bindings.push_action.setEnabled(has_shared_records)
        bindings.pull_action.setEnabled(True)
        bindings.status_action.setEnabled(True)
        bindings.history_action.setEnabled(True)
        bindings.approval_action.setEnabled(True)
        bindings.integrity_action.setEnabled(True)
        bindings.governance_action.setEnabled(True)
        bindings.report_action.setEnabled(True)

    @staticmethod
    def _add_owned_submenu(parent_menu: QMenu, title: str) -> QMenu:
        """创建带父级归属的子菜单，避免 Qt/PySide 生命周期被过早回收。"""
        submenu = QMenu(title, parent_menu)
        parent_menu.addMenu(submenu)
        return submenu

    def _populate_workspace_template_menu(self, menu: Optional[QMenu]) -> None:
        """刷新工作区模板菜单。"""
        if menu is None:
            return

        menu.clear()

        save_selected_action = menu.addAction(self.tr("将选中连接保存为模板"))
        save_selected_action.triggered.connect(
            self._on_save_selected_connections_as_workspace_template
        )

        save_current_action = menu.addAction(self.tr("将当前工作区保存为模板"))
        save_current_action.triggered.connect(self._on_save_current_workspace_as_template)

        save_filtered_scene_action = menu.addAction(self.tr("将当前筛选保存为场景模板"))
        save_filtered_scene_action.triggered.connect(
            self._on_save_filtered_connections_as_scene_template
        )

        import_templates_action = menu.addAction(self.tr("导入工作区模板"))
        import_templates_action.triggered.connect(self._on_import_workspace_templates)

        import_templates_from_share_root_action = menu.addAction(
            self.tr("从共享中心导入工作区模板")
        )
        import_templates_from_share_root_action.triggered.connect(
            self._on_import_workspace_template_from_shared_library
        )

        export_template_action = menu.addAction(self.tr("导出工作区模板"))
        export_template_action.triggered.connect(self._on_export_workspace_template)

        duplicate_template_action = menu.addAction(self.tr("复制工作区模板"))
        duplicate_template_action.triggered.connect(self._on_duplicate_workspace_template)

        delete_action = menu.addAction(self.tr("删除工作区模板"))
        delete_action.triggered.connect(self._on_delete_workspace_template)

        share_bindings = self._create_shared_library_share_menu(
            menu,
            import_text=self.tr("从共享中心导入工作区模板"),
            import_handler=self._on_import_workspace_template_from_shared_library,
            publish_text=self.tr("发布工作区模板到共享中心"),
            publish_handler=self._on_publish_workspace_template_to_shared_library,
            remove_text=self.tr("从共享中心移除工作区模板包"),
            remove_handler=self._on_remove_workspace_template_shared_package,
        )

        menu.addSeparator()

        if not self._config_manager:
            save_selected_action.setEnabled(False)
            save_current_action.setEnabled(False)
            save_filtered_scene_action.setEnabled(False)
            import_templates_action.setEnabled(False)
            import_templates_from_share_root_action.setEnabled(False)
            export_template_action.setEnabled(False)
            duplicate_template_action.setEnabled(False)
            delete_action.setEnabled(False)
            self._update_shared_library_share_menu_state(
                share_bindings,
                has_local_records=False,
                has_shared_records=False,
                enabled=False,
            )
            placeholder = menu.addAction(self.tr("配置管理器未初始化"))
            placeholder.setEnabled(False)
            return

        save_filtered_scene_action.setEnabled(
            bool(self.connection_tree.get_filtered_connection_ids())
        )
        templates = self._sort_records_by_recent_usage(
            self._config_manager.load_workspace_templates()
        )
        shared_records = self._config_manager.load_shared_library_records(
            package_type="workspace_templates"
        )
        has_templates = bool(templates)
        has_shared_records = bool(shared_records)
        import_templates_from_share_root_action.setEnabled(has_shared_records)
        export_template_action.setEnabled(has_templates)
        self._update_shared_library_share_menu_state(
            share_bindings,
            has_local_records=has_templates,
            has_shared_records=has_shared_records,
        )
        duplicate_template_action.setEnabled(has_templates)
        delete_action.setEnabled(has_templates)
        if not templates:
            placeholder = menu.addAction(self.tr("暂无工作区模板"))
            placeholder.setEnabled(False)
            return

        grouped_templates = {
            "scene_workspace": [
                template
                for template in templates
                if str(template.get("template_kind") or "workspace") == "scene_workspace"
            ],
            "ops_workspace": [
                template
                for template in templates
                if str(template.get("template_kind") or "workspace") == "ops_workspace"
            ],
            "workspace": [
                template
                for template in templates
                if str(template.get("template_kind") or "workspace")
                not in {"ops_workspace", "scene_workspace"}
            ],
        }
        visible_groups = [
            (template_kind, items) for template_kind, items in grouped_templates.items() if items
        ]

        for template_kind, items in visible_groups:
            target_menu = menu
            if len(visible_groups) > 1:
                target_menu = self._add_owned_submenu(
                    menu,
                    self._workspace_template_kind_label(template_kind),
                )
            for template in items:
                template_id = template.get("id")
                status_text = self._workspace_template_status_text(template)
                if template_kind == "scene_workspace":
                    scene_menu = self._add_owned_submenu(
                        target_menu,
                        self._workspace_template_menu_text(template),
                    )
                    scene_menu.setToolTip(status_text)
                    open_action = scene_menu.addAction(self.tr("打开场景"))
                    open_action.setStatusTip(status_text)
                    open_action.triggered.connect(
                        lambda checked=False, current_template_id=template_id: self._open_workspace_template(
                            str(current_template_id or "")
                        )
                    )
                    run_task_action = scene_menu.addAction(self.tr("执行推荐任务"))
                    has_task_preset = bool(template.get("task_preset_key"))
                    run_task_action.setEnabled(has_task_preset)
                    run_task_action.setStatusTip(status_text)
                    if has_task_preset:
                        run_task_action.triggered.connect(
                            lambda checked=False, current_template_id=template_id: self._run_workspace_template_task_preset(
                                str(current_template_id or "")
                            )
                        )
                    apply_filter_action = scene_menu.addAction(self.tr("仅应用场景筛选"))
                    apply_filter_action.setEnabled(isinstance(template.get("filter_state"), dict))
                    apply_filter_action.setStatusTip(status_text)
                    if isinstance(template.get("filter_state"), dict):
                        apply_filter_action.triggered.connect(
                            lambda checked=False, current_template_id=template_id: self._apply_workspace_template_filter(
                                str(current_template_id or "")
                            )
                        )
                else:
                    action = target_menu.addAction(self._workspace_template_menu_text(template))
                    action.setStatusTip(status_text)
                    action.setToolTip(status_text)
                    action.triggered.connect(
                        lambda checked=False, current_template_id=template_id: self._open_workspace_template(
                            str(current_template_id or "")
                        )
                    )

    def _populate_connection_filter_presets_menu(self, menu: Optional[QMenu]) -> None:
        """刷新连接筛选预设菜单。"""
        if menu is None:
            return

        menu.clear()

        save_action = menu.addAction(self.tr("将当前筛选保存为预设"))
        save_action.triggered.connect(self._on_save_connection_filter_preset)

        open_filtered_workspace_action = menu.addAction(self.tr("打开当前筛选为工作区"))
        open_filtered_workspace_action.triggered.connect(
            self._on_open_filtered_connections_workspace
        )

        open_filtered_ops_action = menu.addAction(self.tr("打开当前筛选为运维工作台"))
        open_filtered_ops_action.triggered.connect(self._on_open_filtered_connections_ops_workspace)

        save_filtered_workspace_action = menu.addAction(self.tr("将当前筛选保存为工作区模板"))
        save_filtered_workspace_action.triggered.connect(
            self._on_save_filtered_connections_as_workspace_template
        )

        save_filtered_ops_action = menu.addAction(self.tr("将当前筛选保存为运维工作台模板"))
        save_filtered_ops_action.triggered.connect(
            self._on_save_filtered_connections_as_ops_workspace_template
        )

        save_filtered_scene_action = menu.addAction(self.tr("将当前筛选保存为场景模板"))
        save_filtered_scene_action.triggered.connect(
            self._on_save_filtered_connections_as_scene_template
        )

        create_scene_from_preset_action = menu.addAction(self.tr("从筛选预设生成场景模板"))
        create_scene_from_preset_action.triggered.connect(
            self._on_save_scene_template_from_filter_preset
        )

        import_presets_action = menu.addAction(self.tr("导入筛选预设"))
        import_presets_action.triggered.connect(self._on_import_connection_filter_presets)

        export_preset_action = menu.addAction(self.tr("导出筛选预设"))
        export_preset_action.triggered.connect(self._on_export_connection_filter_preset)

        filtered_task_menu = self._add_owned_submenu(menu, self.tr("对当前筛选执行任务预设"))

        clear_action = menu.addAction(self.tr("清除当前筛选"))
        clear_action.triggered.connect(self._on_reset_connection_filters)

        delete_action = menu.addAction(self.tr("删除筛选预设"))
        delete_action.triggered.connect(self._on_delete_connection_filter_preset)

        share_bindings = self._create_shared_library_share_menu(
            menu,
            import_text=self.tr("从共享中心导入筛选预设"),
            import_handler=self._on_import_connection_filter_preset_from_shared_library,
            publish_text=self.tr("发布筛选预设到共享中心"),
            publish_handler=self._on_publish_connection_filter_preset_to_shared_library,
            remove_text=self.tr("从共享中心移除筛选预设包"),
            remove_handler=self._on_remove_connection_filter_preset_shared_package,
        )

        menu.addSeparator()

        if not self._config_manager:
            save_action.setEnabled(False)
            open_filtered_workspace_action.setEnabled(False)
            open_filtered_ops_action.setEnabled(False)
            save_filtered_workspace_action.setEnabled(False)
            save_filtered_ops_action.setEnabled(False)
            save_filtered_scene_action.setEnabled(False)
            create_scene_from_preset_action.setEnabled(False)
            import_presets_action.setEnabled(False)
            export_preset_action.setEnabled(False)
            filtered_task_menu.setEnabled(False)
            clear_action.setEnabled(False)
            delete_action.setEnabled(False)
            self._update_shared_library_share_menu_state(
                share_bindings,
                has_local_records=False,
                has_shared_records=False,
                enabled=False,
            )
            placeholder = menu.addAction(self.tr("配置管理器未初始化"))
            placeholder.setEnabled(False)
            return

        filtered_ids = self.connection_tree.get_filtered_connection_ids()
        has_filtered_connections = bool(filtered_ids)
        open_filtered_workspace_action.setEnabled(has_filtered_connections)
        open_filtered_ops_action.setEnabled(has_filtered_connections)
        save_filtered_workspace_action.setEnabled(has_filtered_connections)
        save_filtered_ops_action.setEnabled(has_filtered_connections)
        save_filtered_scene_action.setEnabled(has_filtered_connections)
        presets = self._sort_records_by_recent_usage(
            self._config_manager.load_connection_filter_presets()
        )
        shared_records = self._config_manager.load_shared_library_records(
            package_type="connection_filter_presets"
        )
        has_presets = bool(presets)
        has_shared_records = bool(shared_records)
        create_scene_from_preset_action.setEnabled(has_presets)
        export_preset_action.setEnabled(has_presets)
        self._update_shared_library_share_menu_state(
            share_bindings,
            has_local_records=has_presets,
            has_shared_records=has_shared_records,
        )
        filtered_task_menu.setEnabled(has_filtered_connections)
        for preset_key in self.TASK_PRESET_ORDER:
            preset = self._task_preset_definition(preset_key)
            action = filtered_task_menu.addAction(self.tr(preset.title))
            action.triggered.connect(
                lambda checked=False, current_preset_key=preset_key: self._on_filtered_connections_task_preset_requested(
                    current_preset_key
                )
            )
        clear_action.setEnabled(self.connection_tree.has_active_filters())
        delete_action.setEnabled(has_presets)
        if not presets:
            placeholder = menu.addAction(self.tr("暂无筛选预设"))
            placeholder.setEnabled(False)
            return

        for preset in presets:
            preset_id = preset.get("id")
            summary = self._describe_connection_filter_state(preset.get("filters", {}))
            action_text = self.tr(f"{preset.get('name', '未命名预设')} · {summary}")
            usage_count = int(preset.get("usage_count") or 0)
            if usage_count:
                action_text = self.tr(f"{action_text} · {usage_count} 次")
            action = menu.addAction(action_text)
            if preset.get("last_used_at"):
                action.setStatusTip(self.tr(f"最近使用: {preset['last_used_at']}"))
            action.triggered.connect(
                lambda checked=False, current_preset_id=preset_id: self._apply_connection_filter_preset(
                    str(current_preset_id or "")
                )
            )

    def _refresh_workspace_templates_menu(self) -> None:
        """刷新文件菜单和工具栏中的工作区模板入口。"""
        self._populate_workspace_template_menu(getattr(self, "workspace_templates_menu", None))
        toolbar_button = getattr(self, "workspace_template_toolbar_btn", None)
        if toolbar_button is not None:
            menu = QMenu(toolbar_button)
            menu.aboutToShow.connect(lambda: self._populate_workspace_template_menu(menu))
            self._populate_workspace_template_menu(menu)
            toolbar_button.setMenu(menu)
        self._update_workspace_header()

    def _refresh_connection_filter_presets_menu(self) -> None:
        """刷新筛选预设菜单与工具栏按钮。"""
        self._populate_connection_filter_presets_menu(
            getattr(self, "connection_filter_presets_menu", None)
        )
        toolbar_button = getattr(self, "connection_filter_toolbar_btn", None)
        if toolbar_button is not None:
            menu = QMenu(toolbar_button)
            menu.aboutToShow.connect(lambda: self._populate_connection_filter_presets_menu(menu))
            self._populate_connection_filter_presets_menu(menu)
            toolbar_button.setMenu(menu)

    def _open_connection_batch(self, conn_ids: list[str]) -> tuple[int, int]:
        """批量打开连接并返回请求数与新增工作区数。"""
        requested_count = 0
        opened_count = 0
        seen: set[str] = set()
        for conn_id in conn_ids:
            if not isinstance(conn_id, str):
                continue
            normalized = conn_id.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            requested_count += 1
            before_tabs = self.work_tabs.count()
            self._open_connection(conn_id=normalized)
            if self.work_tabs.count() > before_tabs:
                opened_count += 1
        return requested_count, opened_count

    def _scope_payload_connection_ids(self, payload: object) -> list[str]:
        """从连接视图范围载荷中提取连接 ID。"""
        if not isinstance(payload, dict):
            return []
        connection_ids: list[str] = []
        seen: set[str] = set()
        for value in payload.get("connection_ids", []) or []:
            if not isinstance(value, str):
                continue
            connection_id = value.strip()
            if not connection_id or connection_id in seen:
                continue
            seen.add(connection_id)
            connection_ids.append(connection_id)
        return connection_ids

    def _scope_payload_label(self, payload: object) -> str:
        """生成连接视图范围的人类可读标签。"""
        if not isinstance(payload, dict):
            return self.tr("连接范围")
        view_label = str(payload.get("view_label") or self.tr("分组")).strip() or self.tr("分组")
        scope_name = str(payload.get("scope_name") or self.tr("未命名范围")).strip() or self.tr(
            "未命名范围"
        )
        return self.tr(f"{view_label} / {scope_name}")

    def _scope_payload_from_connections(
        self,
        connections: list[Dict[str, Any]],
        *,
        view_label: str,
        scope_name: str,
        template_kind: str = "ops_workspace",
        include_file_browsers: bool = True,
        include_local_terminal: bool = True,
    ) -> Dict[str, Any]:
        """根据一组连接构造视图范围载荷。"""
        connection_ids: list[str] = []
        seen: set[str] = set()
        for conn_data in connections:
            if not isinstance(conn_data, dict):
                continue
            conn_id = str(conn_data.get("id") or "").strip()
            if not conn_id or conn_id in seen:
                continue
            seen.add(conn_id)
            connection_ids.append(conn_id)

        return {
            "scope_name": scope_name,
            "view_mode": "collection",
            "view_label": view_label,
            "connection_ids": connection_ids,
            "include_file_browsers": include_file_browsers,
            "include_local_terminal": include_local_terminal,
            "template_kind": template_kind,
        }

    def _scope_terminal_connection_ids(self, payload: object) -> list[str]:
        """筛选出支持终端任务的连接 ID。"""
        supported_types = {"ssh", "serial", "tcp", "udp"}
        terminal_ids: list[str] = []
        for connection_id in self._scope_payload_connection_ids(payload):
            conn_data = self._find_connection_config(connection_id)
            if not conn_data:
                continue
            if str(conn_data.get("connection_type") or "").lower() not in supported_types:
                continue
            terminal_ids.append(connection_id)
        return terminal_ids

    def _scope_file_browser_connection_ids(self, payload: object) -> list[str]:
        """筛选出支持文件浏览器的连接 ID。"""
        supported_types = {"ssh", "sftp", "ftp"}
        browser_ids: list[str] = []
        for connection_id in self._scope_payload_connection_ids(payload):
            conn_data = self._find_connection_config(connection_id)
            if not conn_data:
                continue
            if str(conn_data.get("connection_type") or "").lower() not in supported_types:
                continue
            browser_ids.append(connection_id)
        return browser_ids

    def _workspace_state_for_scope(
        self,
        payload: object,
        *,
        include_file_browsers: bool = False,
        include_local_terminal: bool = False,
    ) -> Dict[str, Any]:
        """根据连接视图范围构造工作区状态。"""
        tabs: list[Dict[str, Any]] = []
        for connection_id in self._scope_payload_connection_ids(payload):
            tabs.append({"kind": "connection", "connection_id": connection_id})

        if include_file_browsers:
            for connection_id in self._scope_file_browser_connection_ids(payload):
                tabs.append({"kind": "file_browser", "connection_id": connection_id})

        if include_local_terminal:
            tabs.append({"kind": "local_terminal"})

        current_index = 0
        if tabs:
            current_index = min(
                len(tabs) - 1, max(0, len(self._scope_payload_connection_ids(payload)) - 1)
            )

        return {
            "tabs": tabs,
            "current_index": current_index,
            "layout": self._capture_workspace_layout(),
        }

    def _open_connection_collection_workspace(
        self,
        collection_label: str,
        connections: list[Dict[str, Any]],
    ) -> None:
        """把收藏/最近连接列表直接打开为运维工作台。"""
        payload = self._scope_payload_from_connections(
            connections,
            view_label=collection_label,
            scope_name=self.tr("当前列表"),
            template_kind="ops_workspace",
            include_file_browsers=True,
            include_local_terminal=True,
        )
        self._on_connection_scope_open_workspace(payload)

    def _save_connection_collection_as_workspace_template(
        self,
        collection_label: str,
        connections: list[Dict[str, Any]],
    ) -> None:
        """把收藏/最近连接列表保存为运维工作台模板。"""
        payload = self._scope_payload_from_connections(
            connections,
            view_label=collection_label,
            scope_name=self.tr("当前列表"),
            template_kind="ops_workspace",
            include_file_browsers=True,
            include_local_terminal=True,
        )
        self._on_connection_scope_save_as_workspace_template(payload)

    def _on_open_filtered_connections_workspace(self) -> None:
        """将当前筛选结果打开为普通工作区。"""
        payload = self._current_filtered_scope_payload(
            template_kind="workspace",
            include_file_browsers=False,
            include_local_terminal=False,
        )
        self._on_connection_scope_open_workspace(payload)

    def _on_open_filtered_connections_ops_workspace(self) -> None:
        """将当前筛选结果打开为运维工作台。"""
        payload = self._current_filtered_scope_payload(
            template_kind="ops_workspace",
            include_file_browsers=True,
            include_local_terminal=True,
        )
        self._on_connection_scope_open_workspace(payload)

    def _on_save_filtered_connections_as_workspace_template(self) -> None:
        """将当前筛选结果保存为工作区模板。"""
        payload = self._current_filtered_scope_payload(
            template_kind="workspace",
            include_file_browsers=False,
            include_local_terminal=False,
        )
        self._on_connection_scope_save_as_workspace_template(payload)

    def _on_save_filtered_connections_as_ops_workspace_template(self) -> None:
        """将当前筛选结果保存为运维工作台模板。"""
        payload = self._current_filtered_scope_payload(
            template_kind="ops_workspace",
            include_file_browsers=True,
            include_local_terminal=True,
        )
        self._on_connection_scope_save_as_workspace_template(payload)

    def _on_save_filtered_connections_as_scene_template(self) -> None:
        """将当前筛选结果保存为场景模板。"""
        payload = self._current_filtered_scope_payload(
            template_kind="scene_workspace",
            include_file_browsers=True,
            include_local_terminal=True,
        )
        self._save_scene_template_from_filter_state(
            filter_state=dict(payload.get("filter_state") or {}),
            default_name=self.tr(f"场景 / {self._scope_payload_label(payload)}"),
            scope_name=str(payload.get("scope_name") or self._filtered_scope_name()),
        )

    def _on_filtered_connections_task_preset_requested(self, preset_key: str) -> None:
        """对当前筛选结果直接执行任务预设。"""
        payload = self._current_filtered_scope_payload(
            template_kind="scene_workspace",
            include_file_browsers=False,
            include_local_terminal=False,
            task_preset_key=preset_key,
            task_preset_title=self.tr(self._task_preset_definition(preset_key).title),
        )
        self._on_connection_scope_task_preset_requested(preset_key, payload)

    def _save_scene_template_from_filter_state(
        self,
        *,
        filter_state: Dict[str, Any],
        default_name: str,
        scope_name: str,
    ) -> None:
        """从指定筛选状态生成场景模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        connection_ids = self.connection_tree.get_connection_ids_for_filter_state(filter_state)
        if not connection_ids:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("该筛选条件下没有可保存的连接"),
            )
            return

        template_name = self._prompt_workspace_template_name(default_name)
        if not template_name:
            return

        accepted, task_preset_key, task_preset_title = self._prompt_task_preset_choice(
            title=self.tr("场景模板推荐任务"),
            label=self.tr("请选择推荐任务预设:"),
            allow_none=True,
        )
        if not accepted:
            return

        payload = {
            "scope_name": scope_name,
            "view_mode": "preset_filter",
            "view_label": self.tr("筛选结果"),
            "connection_ids": connection_ids,
            "include_file_browsers": True,
            "include_local_terminal": True,
            "template_kind": "scene_workspace",
            "filter_state": dict(filter_state),
            "task_preset_key": task_preset_key,
            "task_preset_title": task_preset_title,
        }
        try:
            template = self._config_manager.upsert_workspace_template(
                template_name,
                connection_ids,
                workspace_state=self._workspace_state_for_scope(
                    payload,
                    include_file_browsers=True,
                    include_local_terminal=True,
                ),
                template_kind="scene_workspace",
                include_file_browsers=True,
                include_local_terminal=True,
                scope_view=self.tr("筛选结果"),
                scope_name=scope_name,
                filter_state=filter_state,
                task_preset_key=task_preset_key,
                task_preset_title=task_preset_title,
            )
        except ConfigurationError as exc:
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        suffix = (
            self.tr(f" · 推荐任务 {task_preset_title}")
            if task_preset_title
            else self.tr(" · 未设置推荐任务")
        )
        self.update_status(
            self.tr(
                f"已保存场景模板: {template.get('name', template_name)} ({len(template.get('connection_ids', []))} 个连接){suffix}"
            )
        )

    def _on_save_selected_connections_as_workspace_template(self) -> None:
        """将连接树中的选中连接保存为工作区模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        connection_ids = self.connection_tree.get_selected_connection_ids()
        if not connection_ids:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("请先在连接树中选择至少一个连接"),
            )
            return

        default_name = self.tr(f"选中连接 {len(connection_ids)} 项")
        template_name = self._prompt_workspace_template_name(default_name)
        if not template_name:
            return

        try:
            template = self._config_manager.upsert_workspace_template(
                template_name,
                connection_ids,
                workspace_state=self._workspace_state_from_connection_ids(connection_ids),
                template_kind="workspace",
            )
        except ConfigurationError as exc:
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        self.update_status(
            self.tr(
                f"已保存工作区模板: {template.get('name', template_name)} ({len(template.get('connection_ids', []))} 个连接)"
            )
        )

    def _on_connection_scope_save_as_workspace_template(self, payload: object) -> None:
        """将当前视图范围保存为工作区模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        connection_ids = self._scope_payload_connection_ids(payload)
        if not connection_ids:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前范围中没有可保存的连接"),
            )
            return

        scope_label = self._scope_payload_label(payload)
        include_file_browsers = bool(
            isinstance(payload, dict) and payload.get("include_file_browsers")
        )
        include_local_terminal = bool(
            isinstance(payload, dict) and payload.get("include_local_terminal")
        )
        default_name = scope_label
        template_kind = (
            str(payload.get("template_kind") or "workspace")
            if isinstance(payload, dict)
            else "workspace"
        )
        if template_kind == "ops_workspace":
            default_name = self.tr(f"{scope_label} 运维工作台")
        elif template_kind == "scene_workspace":
            default_name = self.tr(f"场景 / {scope_label}")

        template_name = self._prompt_workspace_template_name(default_name)
        if not template_name:
            return

        try:
            template = self._config_manager.upsert_workspace_template(
                template_name,
                connection_ids,
                workspace_state=self._workspace_state_for_scope(
                    payload,
                    include_file_browsers=include_file_browsers,
                    include_local_terminal=include_local_terminal,
                ),
                template_kind=(
                    str(payload.get("template_kind") or "workspace")
                    if isinstance(payload, dict)
                    else "workspace"
                ),
                include_file_browsers=include_file_browsers,
                include_local_terminal=include_local_terminal,
                scope_view=(
                    str(payload.get("view_label") or "").strip()
                    if isinstance(payload, dict)
                    else None
                ),
                scope_name=(
                    str(payload.get("scope_name") or "").strip()
                    if isinstance(payload, dict)
                    else None
                ),
                filter_state=(
                    payload.get("filter_state")
                    if isinstance(payload, dict) and isinstance(payload.get("filter_state"), dict)
                    else None
                ),
                task_preset_key=(
                    str(payload.get("task_preset_key") or "").strip() or None
                    if isinstance(payload, dict)
                    else None
                ),
                task_preset_title=(
                    str(payload.get("task_preset_title") or "").strip() or None
                    if isinstance(payload, dict)
                    else None
                ),
            )
        except ConfigurationError as exc:
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        kind_label_map = {
            "ops_workspace": self.tr("视图运维工作台模板"),
            "scene_workspace": self.tr("场景模板"),
            "workspace": self.tr("视图工作区模板"),
        }
        kind_label = kind_label_map.get(template_kind, self.tr("视图工作区模板"))
        self.update_status(
            self.tr(
                f"已保存{kind_label}: {template.get('name', template_name)} ({len(template.get('connection_ids', []))} 个连接)"
            )
        )

    def _on_connection_scope_open_workspace(self, payload: object) -> None:
        """将当前视图范围直接打开为工作区或运维工作台。"""
        connection_ids = self._scope_payload_connection_ids(payload)
        if not connection_ids:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前范围中没有可打开的连接"),
            )
            return

        include_file_browsers = bool(
            isinstance(payload, dict) and payload.get("include_file_browsers")
        )
        include_local_terminal = bool(
            isinstance(payload, dict) and payload.get("include_local_terminal")
        )
        scope_label = self._scope_payload_label(payload)
        workspace_state = self._workspace_state_for_scope(
            payload,
            include_file_browsers=include_file_browsers,
            include_local_terminal=include_local_terminal,
        )
        template_kind = (
            str(payload.get("template_kind") or "workspace")
            if isinstance(payload, dict)
            else "workspace"
        )
        before_tabs = self.work_tabs.count()
        self._restore_workspace_state(workspace_state, append=True)
        opened_count = max(0, self.work_tabs.count() - before_tabs)
        kind_label = (
            self.tr("运维工作台")
            if template_kind in {"ops_workspace", "scene_workspace"}
            else self.tr("工作区")
        )
        self.update_status(
            self.tr(f"已打开{kind_label}: {scope_label} · 新增 {opened_count} 个工作区")
        )

    def _on_save_current_workspace_as_template(self) -> None:
        """将当前工作区中的连接保存为工作区模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        connection_ids = self._current_workspace_connection_ids()
        if not connection_ids:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前工作区中没有可保存的连接标签"),
            )
            return

        default_name = self.tr(f"当前工作区 {len(connection_ids)} 项")
        template_name = self._prompt_workspace_template_name(default_name)
        if not template_name:
            return

        try:
            template = self._config_manager.upsert_workspace_template(
                template_name,
                connection_ids,
                workspace_state=self._capture_workspace_state(),
                template_kind="workspace",
            )
        except ConfigurationError as exc:
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        self.update_status(
            self.tr(
                f"已保存当前工作区模板: {template.get('name', template_name)} ({len(template.get('connection_ids', []))} 个连接)"
            )
        )

    def _open_workspace_template(self, template_id: str) -> None:
        """按模板 ID 打开一组连接。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        template = self._find_workspace_template(template_id)
        if template is None:
            QMessageBox.warning(self, self.tr("错误"), self.tr("未找到工作区模板"))
            return

        filter_state = template.get("filter_state")
        if isinstance(filter_state, dict):
            self.connection_tree.apply_filter_state(filter_state)

        workspace_state = template.get("workspace_state")
        if not isinstance(workspace_state, dict):
            workspace_state = self._workspace_state_from_connection_ids(
                list(template.get("connection_ids", []) or [])
            )
        requested_count = len(list(workspace_state.get("tabs", []) or []))
        before_tabs = self.work_tabs.count()
        self._restore_workspace_state(workspace_state, append=True)
        opened_count = max(0, self.work_tabs.count() - before_tabs)
        template = self._config_manager.mark_workspace_template_used(template_id) or template
        self._refresh_workspace_templates_menu()
        extra_parts: list[str] = []
        if isinstance(filter_state, dict):
            extra_parts.append(
                self.tr(f"筛选 {self._describe_connection_filter_state(filter_state)}")
            )
        task_preset_title = str(template.get("task_preset_title") or "").strip()
        if task_preset_title:
            extra_parts.append(self.tr(f"推荐任务 {task_preset_title}"))
        suffix = f" · {' · '.join(extra_parts)}" if extra_parts else ""
        self.update_status(
            self.tr(
                f"{self._workspace_template_kind_label(str(template.get('template_kind') or 'workspace'))}已打开: "
                f"{template.get('name', '未命名模板')} · 请求 {requested_count} 个标签，新增 {opened_count} 个工作区{suffix}"
            )
        )

    def _apply_workspace_template_filter(self, template_id: str) -> None:
        """仅应用场景模板中的筛选条件。"""
        template = self._find_workspace_template(template_id)
        if template is None:
            QMessageBox.warning(self, self.tr("错误"), self.tr("未找到工作区模板"))
            return

        filter_state = template.get("filter_state")
        if not isinstance(filter_state, dict):
            QMessageBox.information(self, self.tr("提示"), self.tr("该模板没有保存筛选条件"))
            return

        self.connection_tree.apply_filter_state(filter_state)
        self.update_status(
            self.tr(
                f"已应用场景筛选: {template.get('name', '未命名模板')} · {self._describe_connection_filter_state(filter_state)}"
            )
        )

    def _run_workspace_template_task_preset(self, template_id: str) -> None:
        """执行场景模板保存的推荐任务。"""
        template = self._find_workspace_template(template_id)
        if template is None:
            QMessageBox.warning(self, self.tr("错误"), self.tr("未找到工作区模板"))
            return

        preset_key = str(template.get("task_preset_key") or "").strip()
        if not preset_key:
            QMessageBox.information(self, self.tr("提示"), self.tr("该模板未设置推荐任务"))
            return
        if preset_key not in self.TASK_PRESET_DEFINITIONS:
            QMessageBox.warning(self, self.tr("错误"), self.tr("该模板的推荐任务已不存在"))
            return

        filter_state = template.get("filter_state")
        if isinstance(filter_state, dict):
            self.connection_tree.apply_filter_state(filter_state)

        payload = {
            "scope_name": str(template.get("name") or self.tr("场景模板")).strip()
            or self.tr("场景模板"),
            "view_mode": "scene_template",
            "view_label": self.tr("场景模板"),
            "connection_ids": list(template.get("connection_ids", []) or []),
        }
        self._config_manager.mark_workspace_template_used(template_id)
        self._refresh_workspace_templates_menu()
        self._on_connection_scope_task_preset_requested(preset_key, payload)

    def _on_delete_workspace_template(self) -> None:
        """删除一个工作区模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        templates = self._config_manager.load_workspace_templates()
        if not templates:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前没有可删除的工作区模板"))
            return

        choices = [str(template.get("name", "未命名模板")) for template in templates]
        selected_name, ok = QInputDialog.getItem(
            self,
            self.tr("删除工作区模板"),
            self.tr("请选择要删除的模板:"),
            choices,
            0,
            False,
        )
        if not ok or not selected_name:
            return

        template = next((item for item in templates if item.get("name") == selected_name), None)
        if template is None:
            return

        self._config_manager.remove_workspace_template(str(template.get("id", "")))
        self._refresh_workspace_templates_menu()
        self.update_status(self.tr(f"已删除工作区模板: {selected_name}"))

    def _on_import_workspace_templates(self) -> None:
        """导入工作区模板文件。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("导入工作区模板"),
            "",
            self.tr("YAML 文件 (*.yaml *.yml);;JSON 文件 (*.json);;所有文件 (*)"),
        )
        if not file_path:
            return

        try:
            preview = self._config_manager.preview_workspace_template_import(file_path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        if int(preview.get("item_count") or 0) <= 0:
            QMessageBox.information(
                self, self.tr("提示"), self.tr("导入文件中没有可用的工作区模板")
            )
            return

        QMessageBox.information(
            self,
            self.tr("导入预览"),
            self._format_shared_import_summary(self.tr("工作区模板"), preview),
        )

        conflict_strategy = "replace"
        if int(preview.get("conflict_count") or 0) > 0:
            selected_strategy = self._prompt_import_conflict_strategy(self.tr("工作区模板"))
            if not selected_strategy:
                return
            conflict_strategy = selected_strategy

        try:
            result = self._config_manager.import_workspace_templates_with_summary(
                file_path,
                conflict_strategy=conflict_strategy,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        self.update_status(
            self.tr(
                "工作区模板已导入，共 "
                f"{int(result.get('imported_count') or 0)} 项，"
                f"新增 {int(result.get('new_count') or 0)} 项，"
                f"覆盖 {int(result.get('replaced_count') or 0)} 项，"
                f"重命名 {int(result.get('renamed_count') or 0)} 项，"
                f"跳过 {int(result.get('skipped_count') or 0)} 项"
            )
        )

    def _on_import_workspace_template_from_shared_library(self) -> None:
        """从共享中心导入工作区模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        shared_records = self._config_manager.load_shared_library_records(
            package_type="workspace_templates"
        )
        if not shared_records:
            QMessageBox.information(self, self.tr("提示"), self.tr("共享中心中还没有工作区模板包"))
            return

        record = self._prompt_shared_library_record_choice(
            title=self.tr("从共享中心导入工作区模板"),
            label=self.tr("请选择要导入的共享包:"),
            package_type="workspace_templates",
        )
        if record is None:
            return

        try:
            preview = self._config_manager.preview_shared_library_import(
                str(record.get("id") or "")
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        QMessageBox.information(
            self,
            self.tr("导入预览"),
            self._format_shared_import_summary(self.tr("工作区模板"), preview),
        )

        conflict_strategy = "replace"
        if int(preview.get("conflict_count") or 0) > 0:
            selected_strategy = self._prompt_import_conflict_strategy(self.tr("工作区模板"))
            if not selected_strategy:
                return
            conflict_strategy = selected_strategy

        try:
            result = self._config_manager.import_from_shared_library(
                str(record.get("id") or ""),
                conflict_strategy=conflict_strategy,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        self.update_status(
            self.tr(
                f"已从共享中心导入工作区模板包: {record.get('name', '未命名共享包')} · "
                f"新增 {int(result.get('new_count') or 0)} 项，"
                f"覆盖 {int(result.get('replaced_count') or 0)} 项，"
                f"重命名 {int(result.get('renamed_count') or 0)} 项，"
                f"跳过 {int(result.get('skipped_count') or 0)} 项"
            )
        )

    def _on_export_workspace_template(self) -> None:
        """导出一个工作区模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        template = self._prompt_workspace_template_choice(
            title=self.tr("导出工作区模板"),
            label=self.tr("请选择要导出的模板:"),
        )
        if template is None:
            return

        default_name = str(template.get("name") or "workspace-template").replace("/", "-")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出工作区模板"),
            f"{default_name}.yaml",
            self.tr("YAML 文件 (*.yaml *.yml);;JSON 文件 (*.json)"),
        )
        if not file_path:
            return

        try:
            self._config_manager.export_workspace_templates(
                file_path,
                template_ids=[str(template.get("id") or "")],
                package_info=self._build_workspace_template_export_package_info(template),
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导出失败"), str(exc))
            return

        self.update_status(self.tr(f"工作区模板已导出: {template.get('name', '未命名模板')}"))

    def _on_publish_workspace_template_to_shared_library(self) -> None:
        """将工作区模板发布到共享中心。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        template = self._prompt_workspace_template_choice(
            title=self.tr("发布工作区模板到共享中心"),
            label=self.tr("请选择要发布的模板:"),
        )
        if template is None:
            return

        try:
            record = self._config_manager.publish_workspace_template_to_shared_library(
                str(template.get("id") or ""),
                package_info=self._build_workspace_template_export_package_info(template),
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("发布失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        self.update_status(
            self.tr(f"工作区模板已发布到共享中心: {record.get('name', '未命名共享包')}")
        )

    def _on_remove_workspace_template_shared_package(self) -> None:
        """从共享中心移除工作区模板共享包。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        shared_records = self._config_manager.load_shared_library_records(
            package_type="workspace_templates"
        )
        if not shared_records:
            QMessageBox.information(self, self.tr("提示"), self.tr("共享中心中还没有工作区模板包"))
            return

        record = self._prompt_shared_library_record_choice(
            title=self.tr("从共享中心移除工作区模板包"),
            label=self.tr("请选择要移除的共享包:"),
            package_type="workspace_templates",
        )
        if record is None:
            return

        try:
            self._config_manager.remove_shared_library_record(str(record.get("id") or ""))
        except Exception as exc:
            QMessageBox.critical(self, self.tr("移除失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        self.update_status(
            self.tr(f"已从共享中心移除工作区模板包: {record.get('name', '未命名共享包')}")
        )

    def _on_duplicate_workspace_template(self) -> None:
        """复制一个工作区模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        template = self._prompt_workspace_template_choice(
            title=self.tr("复制工作区模板"),
            label=self.tr("请选择要复制的模板:"),
        )
        if template is None:
            return

        default_name = self.tr(f"{template.get('name', '未命名模板')} 副本")
        new_name = self._prompt_workspace_template_name(default_name)
        if not new_name:
            return

        try:
            duplicated = self._config_manager.duplicate_workspace_template(
                str(template.get("id") or ""),
                new_name,
            )
        except ConfigurationError as exc:
            QMessageBox.critical(self, self.tr("复制失败"), str(exc))
            return

        self._refresh_workspace_templates_menu()
        self.update_status(self.tr(f"已复制工作区模板: {duplicated.get('name', new_name)}"))

    def _on_connection_scope_task_preset_requested(self, preset_key: str, payload: object) -> None:
        """对当前连接视图范围直接执行任务预设。"""
        preset = self._task_preset_definition(preset_key)
        connection_ids = self._scope_terminal_connection_ids(payload)
        if not connection_ids:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr(f"当前范围中没有可用于{preset.title}的终端连接"),
            )
            return

        self._open_connection_batch(connection_ids)
        commands = self._default_task_preset_commands(preset_key)
        if not commands:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr(f"{preset.title}当前没有可执行命令"),
            )
            return

        scope_label = self._scope_payload_label(payload)
        source_label = self.tr(f"{preset.title} · {scope_label}")
        sent_count, target_count = self._broadcast_sync_commands(
            commands,
            scope_override=self.SYNC_SCOPE_ALL,
            target_connection_ids=connection_ids,
            source_label=source_label,
            source_kind="task_preset",
            task_preset_key=preset.key,
            task_preset_title=self.tr(preset.title),
            archive_tags=[
                self.tr("任务预设"),
                self.tr(preset.title),
                self.tr(f"连接视图 / {scope_label}"),
            ],
        )
        if sent_count and target_count:
            self._logger.info(
                "视图范围任务预设完成: %s -> %s 个终端 [%s]",
                preset.title,
                target_count,
                scope_label,
            )

    def _on_save_connection_filter_preset(self) -> None:
        """将当前连接树筛选保存为预设。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        filter_state = self.connection_tree.export_filter_state()
        if filter_state == self._default_connection_filter_state():
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前没有可保存的筛选条件"),
            )
            return

        default_name = self._suggest_connection_filter_preset_name(filter_state)
        preset_name = self._prompt_connection_filter_preset_name(default_name)
        if not preset_name:
            return

        try:
            preset = self._config_manager.upsert_connection_filter_preset(preset_name, filter_state)
        except ConfigurationError as exc:
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return

        self._refresh_connection_filter_presets_menu()
        self.update_status(
            self.tr(
                f"已保存筛选预设: {preset.get('name', preset_name)} · {self._describe_connection_filter_state(filter_state)}"
            )
        )

    def _apply_connection_filter_preset(self, preset_id: str) -> None:
        """应用一个连接树筛选预设。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        preset = next(
            (
                item
                for item in self._config_manager.load_connection_filter_presets()
                if item.get("id") == preset_id
            ),
            None,
        )
        if preset is None:
            QMessageBox.warning(self, self.tr("错误"), self.tr("未找到筛选预设"))
            return

        self.connection_tree.apply_filter_state(preset.get("filters", {}))
        preset = self._config_manager.mark_connection_filter_preset_used(preset_id) or preset
        self._refresh_connection_filter_presets_menu()
        self.update_status(
            self.tr(
                f"已应用筛选预设: {preset.get('name', '未命名预设')} · "
                f"{self._describe_connection_filter_state(preset.get('filters', {}))} · "
                f"已使用 {int(preset.get('usage_count') or 0)} 次"
            )
        )

    def _on_reset_connection_filters(self) -> None:
        """清空连接树筛选。"""
        self.connection_tree.reset_filters()
        self._refresh_connection_filter_presets_menu()
        self.update_status(self.tr("已清除连接筛选"))

    def _on_delete_connection_filter_preset(self) -> None:
        """删除一个连接筛选预设。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        presets = self._config_manager.load_connection_filter_presets()
        if not presets:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前没有可删除的筛选预设"))
            return

        choices = [str(preset.get("name", "未命名预设")) for preset in presets]
        selected_name, ok = QInputDialog.getItem(
            self,
            self.tr("删除筛选预设"),
            self.tr("请选择要删除的预设:"),
            choices,
            0,
            False,
        )
        if not ok or not selected_name:
            return

        preset = next((item for item in presets if item.get("name") == selected_name), None)
        if preset is None:
            return

        self._config_manager.remove_connection_filter_preset(str(preset.get("id", "")))
        self._refresh_connection_filter_presets_menu()
        self.update_status(self.tr(f"已删除筛选预设: {selected_name}"))

    def _on_import_connection_filter_presets(self) -> None:
        """导入筛选预设文件。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("导入筛选预设"),
            "",
            self.tr("YAML 文件 (*.yaml *.yml);;JSON 文件 (*.json);;所有文件 (*)"),
        )
        if not file_path:
            return

        try:
            preview = self._config_manager.preview_connection_filter_preset_import(file_path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        if int(preview.get("item_count") or 0) <= 0:
            QMessageBox.information(self, self.tr("提示"), self.tr("导入文件中没有可用的筛选预设"))
            return

        QMessageBox.information(
            self,
            self.tr("导入预览"),
            self._format_shared_import_summary(self.tr("筛选预设"), preview),
        )

        conflict_strategy = "replace"
        if int(preview.get("conflict_count") or 0) > 0:
            selected_strategy = self._prompt_import_conflict_strategy(self.tr("筛选预设"))
            if not selected_strategy:
                return
            conflict_strategy = selected_strategy

        try:
            result = self._config_manager.import_connection_filter_presets_with_summary(
                file_path,
                conflict_strategy=conflict_strategy,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        self._refresh_connection_filter_presets_menu()
        self.update_status(
            self.tr(
                "筛选预设已导入，共 "
                f"{int(result.get('imported_count') or 0)} 项，"
                f"新增 {int(result.get('new_count') or 0)} 项，"
                f"覆盖 {int(result.get('replaced_count') or 0)} 项，"
                f"重命名 {int(result.get('renamed_count') or 0)} 项，"
                f"跳过 {int(result.get('skipped_count') or 0)} 项"
            )
        )

    def _on_import_connection_filter_preset_from_shared_library(self) -> None:
        """从共享中心导入筛选预设。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        shared_records = self._config_manager.load_shared_library_records(
            package_type="connection_filter_presets"
        )
        if not shared_records:
            QMessageBox.information(self, self.tr("提示"), self.tr("共享中心中还没有筛选预设包"))
            return

        record = self._prompt_shared_library_record_choice(
            title=self.tr("从共享中心导入筛选预设"),
            label=self.tr("请选择要导入的共享包:"),
            package_type="connection_filter_presets",
        )
        if record is None:
            return

        try:
            preview = self._config_manager.preview_shared_library_import(
                str(record.get("id") or "")
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        QMessageBox.information(
            self,
            self.tr("导入预览"),
            self._format_shared_import_summary(self.tr("筛选预设"), preview),
        )

        conflict_strategy = "replace"
        if int(preview.get("conflict_count") or 0) > 0:
            selected_strategy = self._prompt_import_conflict_strategy(self.tr("筛选预设"))
            if not selected_strategy:
                return
            conflict_strategy = selected_strategy

        try:
            result = self._config_manager.import_from_shared_library(
                str(record.get("id") or ""),
                conflict_strategy=conflict_strategy,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        self._refresh_connection_filter_presets_menu()
        self.update_status(
            self.tr(
                f"已从共享中心导入筛选预设包: {record.get('name', '未命名共享包')} · "
                f"新增 {int(result.get('new_count') or 0)} 项，"
                f"覆盖 {int(result.get('replaced_count') or 0)} 项，"
                f"重命名 {int(result.get('renamed_count') or 0)} 项，"
                f"跳过 {int(result.get('skipped_count') or 0)} 项"
            )
        )

    def _on_export_connection_filter_preset(self) -> None:
        """导出一个筛选预设。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        preset = self._prompt_connection_filter_preset_choice(
            title=self.tr("导出筛选预设"),
            label=self.tr("请选择要导出的预设:"),
        )
        if preset is None:
            return

        default_name = str(preset.get("name") or "filter-preset").replace("/", "-")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出筛选预设"),
            f"{default_name}.yaml",
            self.tr("YAML 文件 (*.yaml *.yml);;JSON 文件 (*.json)"),
        )
        if not file_path:
            return

        try:
            self._config_manager.export_connection_filter_presets(
                file_path,
                preset_ids=[str(preset.get("id") or "")],
                package_info=self._build_connection_filter_preset_export_package_info(preset),
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导出失败"), str(exc))
            return

        self.update_status(self.tr(f"筛选预设已导出: {preset.get('name', '未命名预设')}"))

    def _on_publish_connection_filter_preset_to_shared_library(self) -> None:
        """将筛选预设发布到共享中心。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        preset = self._prompt_connection_filter_preset_choice(
            title=self.tr("发布筛选预设到共享中心"),
            label=self.tr("请选择要发布的预设:"),
        )
        if preset is None:
            return

        try:
            record = self._config_manager.publish_connection_filter_preset_to_shared_library(
                str(preset.get("id") or ""),
                package_info=self._build_connection_filter_preset_export_package_info(preset),
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("发布失败"), str(exc))
            return

        self._refresh_connection_filter_presets_menu()
        self.update_status(
            self.tr(f"筛选预设已发布到共享中心: {record.get('name', '未命名共享包')}")
        )

    def _on_remove_connection_filter_preset_shared_package(self) -> None:
        """从共享中心移除筛选预设包。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        shared_records = self._config_manager.load_shared_library_records(
            package_type="connection_filter_presets"
        )
        if not shared_records:
            QMessageBox.information(self, self.tr("提示"), self.tr("共享中心中还没有筛选预设包"))
            return

        record = self._prompt_shared_library_record_choice(
            title=self.tr("从共享中心移除筛选预设包"),
            label=self.tr("请选择要移除的共享包:"),
            package_type="connection_filter_presets",
        )
        if record is None:
            return

        try:
            self._config_manager.remove_shared_library_record(str(record.get("id") or ""))
        except Exception as exc:
            QMessageBox.critical(self, self.tr("移除失败"), str(exc))
            return

        self._refresh_connection_filter_presets_menu()
        self.update_status(
            self.tr(f"已从共享中心移除筛选预设包: {record.get('name', '未命名共享包')}")
        )

    def _on_push_shared_library_to_directory(self) -> None:
        """将共享中心同步到外部共享仓库目录。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        sync_dir = self._resolve_shared_library_sync_dir()
        if not sync_dir:
            return

        try:
            preview = self._config_manager.preview_shared_library_push(sync_dir)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("预览失败"), str(exc))
            return

        force_lock = self._maybe_resolve_shared_library_force_lock(
            sync_dir,
            self.tr("推送到共享仓库"),
        )
        if force_lock is None:
            return

        confirm = QMessageBox.question(
            self,
            self.tr("确认同步到共享仓库"),
            self._format_shared_library_sync_preview(self.tr("推送到共享仓库"), preview)
            + "\n\n"
            + self.tr("继续执行该同步吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            result = self._config_manager.push_shared_library_to_directory(
                sync_dir,
                force_lock=force_lock,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("同步失败"), str(exc))
            return

        if int(result.get("index_version") or 0):
            self._config_manager.update_shared_library_cached_index_version(
                sync_dir,
                int(result.get("index_version") or 0),
            )
        self.update_status(
            self.tr(
                f"共享中心已同步到共享仓库: {sync_dir} · "
                f"记录 {int(result.get('record_count') or 0)} 项，"
                f"写入 {int(result.get('pushed_count') or 0)} 项，"
                f"索引版本 {int(result.get('index_version') or 0)}"
            )
        )

    def _on_pull_shared_library_from_directory(self) -> None:
        """从外部共享仓库目录同步到共享中心。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        sync_dir = self._resolve_shared_library_sync_dir()
        if not sync_dir:
            return
        config = self._config_manager.app_config

        try:
            preview = self._config_manager.preview_shared_library_pull(
                sync_dir,
                trusted_source_apps=config.shared_library_trusted_source_apps,
                trusted_signer_fingerprints=config.shared_library_trusted_signer_fingerprints,
                revoked_signer_fingerprints=config.shared_library_revoked_signer_fingerprints,
                allowed_package_types=config.shared_library_auto_pull_allowed_package_types,
                rotation_due_policy=config.shared_library_rotation_due_policy,
                rotation_overdue_policy=config.shared_library_rotation_overdue_policy,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("预览失败"), str(exc))
            return

        force_lock = self._maybe_resolve_shared_library_force_lock(
            sync_dir,
            self.tr("从共享仓库拉取"),
        )
        if force_lock is None:
            return

        confirm = QMessageBox.question(
            self,
            self.tr("确认从共享仓库同步"),
            self._format_shared_library_sync_preview(self.tr("从共享仓库拉取"), preview)
            + "\n\n"
            + self.tr("继续执行该同步吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            result = self._config_manager.pull_shared_library_from_directory(
                sync_dir,
                force_lock=force_lock,
                trusted_source_apps=config.shared_library_trusted_source_apps,
                trusted_signer_fingerprints=config.shared_library_trusted_signer_fingerprints,
                revoked_signer_fingerprints=config.shared_library_revoked_signer_fingerprints,
                allowed_package_types=config.shared_library_auto_pull_allowed_package_types,
                rotation_due_policy=config.shared_library_rotation_due_policy,
                rotation_overdue_policy=config.shared_library_rotation_overdue_policy,
                queue_pending_approvals=True,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("同步失败"), str(exc))
            return

        if int(result.get("index_version") or 0):
            self._config_manager.update_shared_library_cached_index_version(
                sync_dir,
                int(result.get("index_version") or 0),
            )
        self._refresh_workspace_templates_menu()
        self._refresh_connection_filter_presets_menu()
        self.update_status(
            self.tr(
                f"已从共享仓库同步到共享中心: {sync_dir} · "
                f"发现 {int(result.get('record_count') or 0)} 项，"
                f"导入 {int(result.get('imported_count') or 0)} 项，"
                f"跳过 {int(result.get('skipped_count') or 0)} 项，"
                f"索引版本 {int(result.get('index_version') or 0)}"
            )
            + (
                self.tr(f" · 完整性异常 {int(result.get('integrity_blocked_count') or 0)} 项")
                if int(result.get("integrity_blocked_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 已撤销签名者 {int(result.get('revoked_signer_count') or 0)} 项")
                if int(result.get("revoked_signer_count") or 0)
                else ""
            )
            + (
                self.tr(
                    f" · 策略已过期签名者 {int(result.get('expired_signer_policy_count') or 0)} 项"
                )
                if int(result.get("expired_signer_policy_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 轮换临近 {int(result.get('rotation_due_count') or 0)} 项")
                if int(result.get("rotation_due_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 轮换超期 {int(result.get('rotation_overdue_count') or 0)} 项")
                if int(result.get("rotation_overdue_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 轮换提示 {int(result.get('rotation_warning_count') or 0)} 项")
                if int(result.get("rotation_warning_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 轮换例外 {int(result.get('rotation_exception_count') or 0)} 项")
                if int(result.get("rotation_exception_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 未受信任签名者 {int(result.get('untrusted_signer_count') or 0)} 项")
                if int(result.get("untrusted_signer_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 签名异常 {int(result.get('signature_blocked_count') or 0)} 项")
                if int(result.get("signature_blocked_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 未签名 {int(result.get('signature_unverified_count') or 0)} 项")
                if int(result.get("signature_unverified_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 待审 {int(result.get('pending_approval_count') or 0)} 项")
                if int(result.get("pending_approval_count") or 0)
                else ""
            )
        )

    def _on_view_shared_library_repository_status(self) -> None:
        """查看共享仓库状态。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        sync_dir = self._resolve_shared_library_sync_dir()
        if not sync_dir:
            return

        config = self._config_manager.app_config
        governance = self._config_manager.inspect_shared_library_signer_governance(sync_dir)
        lock_info = self._config_manager.inspect_shared_library_lock(sync_dir)
        history = self._config_manager.load_shared_library_sync_history()
        approvals = self._config_manager.load_shared_library_approval_records()
        try:
            integrity_result = self._config_manager.inspect_shared_library_pull_integrity(
                sync_dir,
                trusted_source_apps=config.shared_library_trusted_source_apps,
                trusted_signer_fingerprints=config.shared_library_trusted_signer_fingerprints,
                revoked_signer_fingerprints=config.shared_library_revoked_signer_fingerprints,
                allowed_package_types=config.shared_library_auto_pull_allowed_package_types,
                rotation_due_policy=config.shared_library_rotation_due_policy,
                rotation_overdue_policy=config.shared_library_rotation_overdue_policy,
            )
            integrity_note = ""
        except ConfigurationError:
            integrity_result = {
                "blocked_count": 0,
                "unverified_count": 0,
            }
            integrity_note = self.tr("（目录尚未创建）")
        cached_index_version = self._config_manager.get_shared_library_cached_index_version(
            sync_dir
        )
        trusted_sources = [
            str(item)
            for item in config.shared_library_trusted_source_apps or []
            if str(item).strip()
        ]
        trusted_signers = [
            str(item)
            for item in config.shared_library_trusted_signer_fingerprints or []
            if str(item).strip()
        ]
        revoked_signers = [
            str(item)
            for item in config.shared_library_revoked_signer_fingerprints or []
            if str(item).strip()
        ]
        signer_profiles = dict(config.shared_library_signer_profiles or {})
        revoked_signer_records = list(config.shared_library_revoked_signer_records or [])
        signer_group_summaries = list(governance.get("group_summaries") or [])
        pending_approvals = [record for record in approvals if record.get("decision") == "pending"]
        allowed_package_types = [
            self._shared_library_package_type_label(str(item))
            for item in config.shared_library_auto_pull_allowed_package_types or []
            if str(item).strip()
        ]
        lines = [
            self.tr(f"共享仓库目录: {sync_dir}"),
            self.tr(
                f"共享同步策略: {self._shared_library_sync_policy_label(config.shared_library_sync_policy)}"
            ),
            self.tr(f"共享锁超时: {int(config.shared_library_lock_timeout)} 秒"),
            self.tr(
                f"临近轮换治理: {self._shared_library_rotation_policy_label(config.shared_library_rotation_due_policy)}"
            ),
            self.tr(
                f"轮换超期治理: {self._shared_library_rotation_policy_label(config.shared_library_rotation_overdue_policy)}"
            ),
            self.tr(
                f"自动拉取信任来源: {', '.join(trusted_sources)}"
                if trusted_sources
                else "自动拉取信任来源: 全部来源"
            ),
            self.tr(
                f"自动拉取信任签名者: {', '.join(trusted_signers[:3])}"
                + (" ..." if len(trusted_signers) > 3 else "")
                if trusted_signers
                else "自动拉取信任签名者: 不限制"
            ),
            self.tr(
                f"已撤销签名者: {', '.join(revoked_signers[:3])}"
                + (" ..." if len(revoked_signers) > 3 else "")
                if revoked_signers
                else "已撤销签名者: 无"
            ),
            self.tr(f"签名者资料数: {len(signer_profiles)}"),
            self.tr(f"签名者分组数: {int(governance.get('signer_group_count') or 0)}"),
            self.tr(f"已分组签名者: {int(governance.get('grouped_signer_count') or 0)}"),
            self.tr(f"未分组资料: {int(governance.get('ungrouped_profile_count') or 0)}"),
            self.tr(f"已过期策略: {int(governance.get('expired_policy_count') or 0)}"),
            self.tr(f"临近到期策略: {int(governance.get('expiring_policy_count') or 0)}"),
            self.tr(f"轮换临近截止: {int(governance.get('rotation_due_count') or 0)}"),
            self.tr(f"轮换已超期: {int(governance.get('rotation_overdue_count') or 0)}"),
            self.tr(
                f"生效轮换例外授权: {int(governance.get('active_rotation_exception_count') or 0)}"
            ),
            self.tr(
                f"失效轮换例外授权: {int(governance.get('expired_rotation_exception_count') or 0)}"
            ),
            self.tr(f"团队级审批规则: {int(governance.get('team_approval_rule_count') or 0)}"),
            self.tr(f"团队审批门禁: {int(governance.get('team_approval_gate_count') or 0)}"),
            self.tr(f"团队阻断规则: {int(governance.get('team_block_rule_count') or 0)}"),
            self.tr(f"撤销记录数: {len(revoked_signer_records)}"),
            self.tr(f"治理审计事件: {int(governance.get('audit_event_count') or 0)}"),
            self.tr(f"治理操作者: {int(governance.get('audit_actor_count') or 0)}"),
            self.tr(
                f"自动拉取包类型: {', '.join(allowed_package_types)}"
                if allowed_package_types
                else "自动拉取包类型: 已关闭"
            ),
            self.tr(f"共享待审队列: {len(pending_approvals)} 项"),
            self.tr(
                f"共享完整性异常: {int(integrity_result.get('blocked_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(
                f"共享未校验摘要: {int(integrity_result.get('unverified_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(
                f"签名异常记录: {int(integrity_result.get('signature_blocked_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(
                f"已撤销签名者命中: {int(integrity_result.get('revoked_signer_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(
                f"策略过期签名者命中: {int(integrity_result.get('expired_signer_policy_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(
                f"轮换临近命中: {int(integrity_result.get('rotation_due_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(
                f"轮换超期命中: {int(integrity_result.get('rotation_overdue_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(
                f"轮换例外授权命中: {int(integrity_result.get('rotation_exception_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(
                f"未签名记录: {int(integrity_result.get('signature_unverified_count') or 0)} 项"
                f"{integrity_note}"
            ),
            self.tr(f"已缓存索引版本: {cached_index_version}"),
            "",
            self._format_shared_library_lock_text(lock_info),
        ]
        if signer_group_summaries:
            lines.extend(["", self.tr("签名分组摘要:")])
            for summary in signer_group_summaries[:5]:
                lines.append(
                    self.tr(
                        f"- {summary.get('name', '未命名分组')}: "
                        f"{int(summary.get('fingerprint_count') or 0)} 名 · "
                        f"受信任 {int(summary.get('trusted_count') or 0)} · "
                        f"已撤销 {int(summary.get('revoked_count') or 0)}"
                    )
                )
        team_rule_summaries = list(governance.get("team_approval_rule_summaries") or [])
        if team_rule_summaries:
            lines.extend(["", self.tr("团队级审批规则:")])
            for summary in team_rule_summaries[:5]:
                parts = [str(summary.get("action_label") or "").strip()]
                source_apps = [
                    str(item).strip()
                    for item in summary.get("source_apps") or []
                    if str(item).strip()
                ]
                signer_groups = [
                    str(item).strip()
                    for item in summary.get("signer_groups") or []
                    if str(item).strip()
                ]
                package_type_labels = [
                    str(item).strip()
                    for item in summary.get("package_type_labels") or []
                    if str(item).strip()
                ]
                if source_apps:
                    parts.append(self.tr(f"来源 {', '.join(source_apps)}"))
                if signer_groups:
                    parts.append(self.tr(f"分组 {', '.join(signer_groups)}"))
                if package_type_labels:
                    parts.append(self.tr(f"包类型 {', '.join(package_type_labels)}"))
                minimum_signature_count = int(summary.get("minimum_signature_count") or 0)
                if minimum_signature_count > 0:
                    parts.append(self.tr(f"最小签名数 {minimum_signature_count}"))
                approval_level = str(summary.get("approval_level") or "").strip()
                if approval_level:
                    parts.append(self.tr(f"审批级别 {approval_level}"))
                note = str(summary.get("note") or "").strip()
                if note:
                    parts.append(note)
                lines.append(
                    self.tr(f"- {summary.get('name', '未命名规则')} · {' · '.join(parts)}")
                )
        recent_revocations = list(governance.get("recent_revocations") or [])
        if recent_revocations:
            lines.extend(["", self.tr("最近撤销记录:")])
            for record in recent_revocations[:3]:
                label = str(record.get("label") or record.get("fingerprint") or "").strip()
                revoked_at = str(record.get("revoked_at") or "").strip()
                reason = str(record.get("reason") or "").strip()
                suffix = f" · {revoked_at}" if revoked_at else ""
                if reason:
                    suffix += f" · {reason}"
                lines.append(self.tr(f"- {label}{suffix}"))
        expired_policies = list(governance.get("expired_policies") or [])
        if expired_policies:
            lines.extend(["", self.tr("已过期策略:")])
            for record in expired_policies[:3]:
                label = str(record.get("label") or record.get("fingerprint") or "").strip()
                expires_at = str(record.get("expires_at") or "").strip()
                suffix = f" · {expires_at}" if expires_at else ""
                lines.append(self.tr(f"- {label}{suffix}"))
        rotation_overdue_signers = list(governance.get("rotation_overdue_signers") or [])
        if rotation_overdue_signers:
            lines.extend(["", self.tr("轮换已超期:")])
            for record in rotation_overdue_signers[:3]:
                label = str(record.get("label") or record.get("fingerprint") or "").strip()
                rotate_before_at = str(record.get("rotate_before_at") or "").strip()
                suffix = f" · {rotate_before_at}" if rotate_before_at else ""
                lines.append(self.tr(f"- {label}{suffix}"))
        active_rotation_exceptions = list(governance.get("active_rotation_exceptions") or [])
        if active_rotation_exceptions:
            lines.extend(["", self.tr("生效中的轮换例外授权:")])
            for record in active_rotation_exceptions[:3]:
                label = str(record.get("label") or record.get("fingerprint") or "").strip()
                package_labels = ", ".join(record.get("package_type_labels") or []) or self.tr(
                    "全部共享包"
                )
                state_labels = ", ".join(record.get("rotation_state_labels") or []) or self.tr(
                    "全部轮换状态"
                )
                suffix_parts = [package_labels, state_labels]
                if record.get("expires_at"):
                    suffix_parts.append(str(record.get("expires_at")))
                if record.get("note"):
                    suffix_parts.append(str(record.get("note")))
                lines.append(self.tr(f"- {label} · {' · '.join(suffix_parts)}"))
        recent_audit_events = list(governance.get("recent_audit_events") or [])
        if recent_audit_events:
            lines.extend(["", self.tr("最近治理动作:")])
            for record in recent_audit_events[:5]:
                lines.append(
                    self.tr(
                        f"- {str(record.get('recorded_at') or '').strip()} · "
                        f"{str(record.get('actor') or '未知操作者').strip()} · "
                        f"{str(record.get('summary') or record.get('event_kind') or '未知事件').strip()}"
                    )
                )
        if history:
            latest = history[0]
            action_label = self.tr("推送") if latest.get("action") == "push" else self.tr("拉取")
            lines.extend(
                [
                    "",
                    self.tr(
                        f"最近同步: {action_label} · {latest.get('recorded_at', '')} · "
                        f"总数 {int(latest.get('record_count') or 0)}"
                    ),
                ]
            )
        QMessageBox.information(
            self,
            self.tr("共享仓库状态"),
            "\n".join(lines),
        )

    def _on_view_shared_library_sync_history(self) -> None:
        """查看共享中心同步历史。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        records = self._config_manager.load_shared_library_sync_history()
        QMessageBox.information(
            self,
            self.tr("共享同步历史"),
            self._format_shared_library_sync_history_text(records),
        )

    def _on_view_shared_library_governance_audit(self) -> None:
        """查看共享治理审计。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        records = self._config_manager.load_shared_library_governance_audit_records()
        if not records:
            QMessageBox.information(
                self, self.tr("共享治理审计"), self.tr("当前没有共享治理审计记录")
            )
            return

        lines = []
        for record in records[:30]:
            lines.append(
                self.tr(
                    f"{str(record.get('recorded_at') or '').strip()} · "
                    f"{str(record.get('actor') or '未知操作者').strip()} · "
                    f"{str(record.get('summary') or record.get('event_kind') or '未知事件').strip()}"
                )
            )
            for detail in record.get("detail_lines") or []:
                detail_text = str(detail).strip()
                if detail_text:
                    lines.append(self.tr(f"  - {detail_text}"))
            lines.append("")
        QMessageBox.information(
            self,
            self.tr("共享治理审计"),
            "\n".join(lines).strip(),
        )

    def _on_export_shared_library_governance_report(self) -> None:
        """导出共享治理报告。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        sync_dir = self._config_manager.app_config.shared_library_sync_dir
        default_name = "shared-governance-report.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出共享治理报告"),
            str(Path.home() / default_name),
            self.tr("文本报告 (*.txt);;JSON 报告 (*.json)"),
        )
        if not file_path:
            return
        try:
            target = self._config_manager.export_shared_library_governance_report(
                file_path,
                sync_dir=sync_dir,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导出失败"), str(exc))
            return
        self.update_status(self.tr(f"已导出共享治理报告: {target}"))
        QMessageBox.information(
            self,
            self.tr("导出完成"),
            self.tr(f"共享治理报告已导出到:\n{target}"),
        )

    def _on_view_shared_library_approval_queue(self) -> None:
        """查看共享待审队列。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        dialog = SharedLibraryApprovalDialog(self)
        dialog.set_config_manager(self._config_manager)
        dialog.approvals_changed.connect(self._on_shared_library_approvals_changed)
        dialog.sync_completed.connect(self._on_shared_library_approval_sync_completed)
        dialog.policy_changed.connect(self._on_shared_library_policy_changed)
        dialog.exec()

    def _on_view_shared_library_integrity_issues(self) -> None:
        """查看共享完整性异常记录。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        sync_dir = self._resolve_shared_library_sync_dir()
        if not sync_dir:
            return

        config = self._config_manager.app_config
        dialog = SharedLibraryIntegrityDialog(self)
        dialog.set_context(
            self._config_manager,
            sync_dir,
            trusted_source_apps=config.shared_library_trusted_source_apps,
            trusted_signer_fingerprints=config.shared_library_trusted_signer_fingerprints,
            revoked_signer_fingerprints=config.shared_library_revoked_signer_fingerprints,
            allowed_package_types=config.shared_library_auto_pull_allowed_package_types,
            rotation_due_policy=config.shared_library_rotation_due_policy,
            rotation_overdue_policy=config.shared_library_rotation_overdue_policy,
        )
        dialog.exec()

    def _on_shared_library_approvals_changed(self, count: int, decision: str) -> None:
        """处理共享审批记录更新。"""
        if not self._config_manager:
            return
        decision_label = SharedLibraryApprovalDialog._decision_label(str(decision or "pending"))
        pending_count = len(
            [
                record
                for record in self._config_manager.load_shared_library_approval_records()
                if record.get("decision") == "pending"
            ]
        )
        self.update_status(
            self.tr(
                f"共享审批已更新: {decision_label} {int(count or 0)} 项 · "
                f"当前待审 {pending_count} 项"
            )
        )

    def _on_shared_library_approval_sync_completed(self, result: Dict[str, Any]) -> None:
        """处理共享审批面板触发的同步结果。"""
        if not self._config_manager:
            return
        self._refresh_workspace_templates_menu()
        self._refresh_connection_filter_presets_menu()
        self.update_status(
            self.tr(
                f"已同步放行的共享包 · 导入 {int(result.get('imported_count') or 0)} 项，"
                f"待审 {int(result.get('pending_approval_count') or 0)} 项，"
                f"索引版本 {int(result.get('index_version') or 0)}"
            )
            + (
                self.tr(f" · 已撤销签名者 {int(result.get('revoked_signer_count') or 0)} 项")
                if int(result.get("revoked_signer_count") or 0)
                else ""
            )
            + (
                self.tr(
                    f" · 策略已过期签名者 {int(result.get('expired_signer_policy_count') or 0)} 项"
                )
                if int(result.get("expired_signer_policy_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 轮换临近 {int(result.get('rotation_due_count') or 0)} 项")
                if int(result.get("rotation_due_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 轮换超期 {int(result.get('rotation_overdue_count') or 0)} 项")
                if int(result.get("rotation_overdue_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 轮换提示 {int(result.get('rotation_warning_count') or 0)} 项")
                if int(result.get("rotation_warning_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 轮换例外 {int(result.get('rotation_exception_count') or 0)} 项")
                if int(result.get("rotation_exception_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 未受信任签名者 {int(result.get('untrusted_signer_count') or 0)} 项")
                if int(result.get("untrusted_signer_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 签名异常 {int(result.get('signature_blocked_count') or 0)} 项")
                if int(result.get("signature_blocked_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 未签名 {int(result.get('signature_unverified_count') or 0)} 项")
                if int(result.get("signature_unverified_count") or 0)
                else ""
            )
        )

    def _on_shared_library_policy_changed(self, payload: Dict[str, Any]) -> None:
        """处理共享来源与包类型策略更新。"""
        kind = str(payload.get("kind") or "").strip()
        value = str(payload.get("value") or "").strip()
        if kind == "trusted_source":
            self.update_status(self.tr(f"已将来源 {value} 加入自动拉取信任列表"))
            return
        if kind == "trusted_signer":
            signer = str(payload.get("signature_signer") or "").strip()
            signer_display_name = str(payload.get("signer_display_name") or "").strip()
            signer_label = signer_display_name or signer
            suffix = self.tr(f"（{signer_label}）") if signer_label else ""
            self.update_status(self.tr(f"已将签名者 {value[:12]} 加入自动拉取信任列表{suffix}"))
            return
        if kind == "revoked_signer":
            signer = str(payload.get("signature_signer") or "").strip()
            signer_display_name = str(payload.get("signer_display_name") or "").strip()
            signer_label = signer_display_name or signer
            suffix = self.tr(f"（{signer_label}）") if signer_label else ""
            revoked_reason = str(payload.get("revoked_reason") or "").strip()
            reason_suffix = self.tr(f" · 原因: {revoked_reason}") if revoked_reason else ""
            self.update_status(
                self.tr(f"已将签名者 {value[:12]} 加入撤销列表{suffix}{reason_suffix}")
            )
            return
        if kind == "signer_profile_updated":
            signer_display_name = str(payload.get("signer_display_name") or "").strip()
            suffix = self.tr(f"（{signer_display_name}）") if signer_display_name else ""
            self.update_status(self.tr(f"已更新签名者资料 {value[:12]}{suffix}"))
            return
        if kind == "allowed_package_type":
            label = self._shared_library_package_type_label(value)
            self.update_status(self.tr(f"已允许 {label} 自动拉取"))
            return
        if kind == "rotation_exception_granted":
            signer = str(payload.get("signature_signer") or "").strip()
            signer_display_name = str(payload.get("signer_display_name") or "").strip()
            signer_label = signer_display_name or signer
            suffix = self.tr(f"（{signer_label}）") if signer_label else ""
            package_type = str(payload.get("package_type") or "").strip()
            package_suffix = (
                self.tr(f" · 包类型: {self._shared_library_package_type_label(package_type)}")
                if package_type
                else ""
            )
            rotation_status = str(payload.get("rotation_status") or "").strip()
            rotation_suffix = (
                self.tr(" · 轮换临近")
                if rotation_status == "due"
                else self.tr(" · 轮换超期") if rotation_status == "overdue" else ""
            )
            expires_at = str(payload.get("expires_at") or "").strip()
            expires_suffix = self.tr(f" · 截止: {expires_at}") if expires_at else ""
            self.update_status(
                self.tr(f"已授予签名者 {value[:12]} 的轮换例外授权{suffix}")
                + package_suffix
                + rotation_suffix
                + expires_suffix
            )
            return
        if kind == "rotation_exception_removed":
            signer = str(payload.get("signature_signer") or "").strip()
            signer_display_name = str(payload.get("signer_display_name") or "").strip()
            signer_label = signer_display_name or signer
            suffix = self.tr(f"（{signer_label}）") if signer_label else ""
            self.update_status(self.tr(f"已移除签名者 {value[:12]} 的轮换例外授权{suffix}"))

    def _on_save_scene_template_from_filter_preset(self) -> None:
        """从已保存的筛选预设生成场景模板。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        preset = self._prompt_connection_filter_preset_choice(
            title=self.tr("从筛选预设生成场景模板"),
            label=self.tr("请选择要转换的筛选预设:"),
        )
        if preset is None:
            return

        filters = dict(preset.get("filters") or {})
        scope_name = self._describe_connection_filter_state(filters)
        default_name = self.tr(f"场景 / {preset.get('name', '未命名预设')}")
        self._save_scene_template_from_filter_state(
            filter_state=filters,
            default_name=default_name,
            scope_name=scope_name,
        )

    def _on_new_connection(self) -> None:
        """新建连接"""
        dialog = ConnectionDialog(parent=self)
        dialog.set_open_after_save_enabled(True)
        if self._config_manager:
            dialog.set_config_manager(self._config_manager)
        if dialog.exec():
            self._on_connection_created(
                dialog.get_config(),
                auto_open=dialog.should_open_after_accept(),
            )

    def _on_connection_created(
        self, config, *, auto_open: bool = False
    ) -> Optional[dict[str, Any]]:
        """处理新连接配置创建。"""
        if self._config_manager:
            try:
                conn_dict = self._config_manager.add_connection(config)
            except ConfigurationError as exc:
                QMessageBox.critical(self, self.tr("保存失败"), str(exc))
                return None
            self._cache_connection_config(conn_dict)
            self.connection_tree.add_connection_item(conn_dict)
            self._refresh_management_widgets()
            self._refresh_session_shortcuts()
            visible_in_tree = self.connection_tree.focus_connection(str(conn_dict.get("id") or ""))
            self._update_connection_saved_status(
                conn_dict,
                edited=False,
                visible_in_tree=visible_in_tree,
            )
            if auto_open and conn_dict.get("id"):
                self._open_connection(conn_id=str(conn_dict["id"]))
            return conn_dict
        return None

    def _on_quick_connect(self) -> None:
        """快速连接"""
        dialog = ConnectionDialog(parent=self)
        dialog.setWindowTitle(self.tr("快速连接"))
        dialog.set_quick_connect_mode(True)
        dialog.set_open_after_save_enabled(False)
        if self._config_manager:
            dialog.set_config_manager(self._config_manager)
        if dialog.exec():
            self._open_connection(config=dialog.get_config(), persist=False)

    def _on_quick_open(self) -> None:
        """打开统一快速打开面板。"""
        dialog = QuickOpenDialog(self)
        dialog.set_entries(self._build_quick_open_entries())
        if dialog.exec() != QDialog.Accepted:
            return
        entry = dialog.selected_entry()
        if not entry:
            return
        self._execute_quick_open_entry(entry)

    def _on_open_command_center(self) -> None:
        """打开快捷命令中心。"""
        dialog = CommandCenterDialog(self)
        dialog.set_entries(self._build_command_center_entries())
        if dialog.exec() != QDialog.Accepted:
            return
        entry = dialog.selected_entry()
        if not entry:
            return
        commands = [
            str(command).strip()
            for command in (entry.get("commands") or [])
            if str(command).strip()
        ]
        if not commands:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前条目没有可用命令"))
            return

        selected_mode = dialog.selected_mode()
        title = str(entry.get("title") or self.tr("快捷命令")).strip()
        if selected_mode == CommandCenterDialog.MODE_EXECUTE:
            self._execute_commands_on_context_widget(commands, source_label=title)
            return
        if selected_mode == CommandCenterDialog.MODE_COPY:
            QApplication.clipboard().setText("\n".join(commands))
            self.update_status(self.tr(f"已复制命令: {title}"))
            return
        if selected_mode == CommandCenterDialog.MODE_FAVORITE:
            try:
                saved_commands = self._save_commands_to_global_favorites(commands)
            except Exception as exc:
                QMessageBox.critical(self, self.tr("保存收藏失败"), str(exc))
                return
            self.update_status(self.tr(f"已加入全局收藏: {title} · {len(saved_commands)} 条命令"))
            return
        if selected_mode == CommandCenterDialog.MODE_MACRO:
            suggested_name = title or self.tr("新命令宏")
            macro_name, ok = QInputDialog.getText(
                self,
                self.tr("保存为命令宏"),
                self.tr("宏名称:"),
                text=suggested_name,
            )
            if not ok:
                return
            try:
                saved_commands = self._save_commands_as_global_macro(macro_name, commands)
            except Exception as exc:
                QMessageBox.critical(self, self.tr("保存命令宏失败"), str(exc))
                return
            self.update_status(
                self.tr(f"已保存命令宏: {macro_name.strip()} · {len(saved_commands)} 条命令")
            )
            return

        compose_dialog = ComposeCommandDialog(
            self,
            initial_text="\n".join(commands),
            title_text=self.tr(f"编排发送 · {title}"),
            summary_text=self.tr(f"已从快捷命令中心载入“{title}”，可继续调整后发送。"),
            **self._compose_command_library(),
        )
        if compose_dialog.exec() != QDialog.Accepted:
            return
        compose_commands = compose_dialog.commands()
        if not compose_commands:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("请输入至少一条命令"),
            )
            return
        self._broadcast_sync_commands(compose_commands)

    def _on_import_connections(self) -> None:
        """导入连接配置文件。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        selected_filter = ""
        file_path, selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("导入连接"),
            "",
            self.tr(
                "YAML 文件 (*.yaml *.yml);;JSON 文件 (*.json);;OpenSSH 配置 (config *.sshconfig *.conf);;主机清单 (*.txt *.list *.hosts);;所有文件 (*)"
            ),
        )
        if not file_path:
            return

        try:
            path = Path(file_path)
            is_structured_connection_file = path.suffix.lower() in {".yaml", ".yml", ".json"}
            is_host_list_file = path.suffix.lower() in {".txt", ".list", ".hosts"}
            if is_structured_connection_file and "OpenSSH" not in selected_filter:
                self._config_manager.import_connections(file_path)
            elif is_host_list_file or "主机清单" in selected_filter:
                self._config_manager.import_host_list(file_path)
            else:
                self._config_manager.import_openssh_config(file_path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导入失败"), str(exc))
            return

        self._reload_connection_tree()
        self._refresh_management_widgets()
        self._refresh_session_shortcuts()
        self.update_status(self.tr("连接已导入"))

    def _on_export_connections(self) -> None:
        """导出连接配置文件。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出连接"),
            "neko-shell-connections.yaml",
            self.tr("YAML 文件 (*.yaml *.yml);;JSON 文件 (*.json)"),
        )
        if not file_path:
            return

        try:
            self._config_manager.export_connections(file_path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("导出失败"), str(exc))
            return

        self.update_status(self.tr("连接已导出"))

    def _on_settings(self) -> None:
        """打开设置"""
        dialog = SettingsDialog(self)
        if self._config_manager:
            dialog.set_config_manager(self._config_manager)
            dialog.load_config(self._config_manager.app_config)
        if dialog.exec():
            if self._config_manager:
                config = dialog.get_config()
                self._config_manager.save_app_config(config)
                ThemeManager.apply_theme(QApplication.instance(), config.theme)
                self._apply_terminal_preferences()

    def _on_open_local_terminal(self) -> None:
        """打开本地终端。"""
        local_terminal_id = "__local_terminal__"
        if self._focus_existing_tab(local_terminal_id):
            return

        try:
            widget = self._bind_terminal_widget(
                QTermLocalTerminalWidget(self, app_config=self._app_config())
            )
        except Exception as exc:
            self._logger.error("本地终端初始化失败: %s", exc)
            QMessageBox.critical(self, self.tr("终端初始化失败"), str(exc))
            return

        self._open_workspace_tab(widget, self.tr("本地终端"), local_terminal_id)

    def _on_help(self) -> None:
        """显示帮助对话框。"""
        dialog = HelpDialog(self, initial_tab=HelpDialog.TAB_GUIDE)
        dialog.exec()

    def _on_about(self) -> None:
        """显示关于页签。"""
        dialog = HelpDialog(self, initial_tab=HelpDialog.TAB_ABOUT)
        dialog.exec()

    def _on_show_tunnels(self) -> None:
        """打开 SSH 隧道管理页面。"""
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if isinstance(widget, TunnelManagerWidget):
                self.work_tabs.setCurrentIndex(index)
                return

        widget = TunnelManagerWidget(self)
        if self._config_manager:
            widget.set_config_manager(self._config_manager)
        self.work_tabs.addTab(widget, self.tr("SSH 隧道"))
        self.work_tabs.setCurrentWidget(widget)
        if self._config_manager and not self._restoring_workspace:
            self._save_workspace_state()

    def _on_show_docker(self) -> None:
        """打开 Docker 管理页面。"""
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if isinstance(widget, DockerManagerWidget):
                self.work_tabs.setCurrentIndex(index)
                return

        widget = DockerManagerWidget(self)
        widget.container_terminal_requested.connect(self._on_open_docker_container_terminal)
        if self._config_manager:
            widget.set_config_manager(self._config_manager)
        self.work_tabs.addTab(widget, self.tr("Docker"))
        self.work_tabs.setCurrentWidget(widget)
        if self._config_manager and not self._restoring_workspace:
            self._save_workspace_state()

    def _on_show_frp(self) -> None:
        """打开 FRP 管理页面。"""
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if isinstance(widget, FRPWidget):
                self.work_tabs.setCurrentIndex(index)
                return

        widget = FRPWidget(self)
        if self._config_manager:
            widget.set_config_manager(self._config_manager)
        self.work_tabs.addTab(widget, self.tr("FRP"))
        self.work_tabs.setCurrentWidget(widget)
        if self._config_manager and not self._restoring_workspace:
            self._save_workspace_state()

    def _refresh_management_widgets(self) -> None:
        """刷新已打开的管理页，保证连接列表与名称保持最新。"""
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if isinstance(widget, TunnelManagerWidget):
                widget.refresh()
                continue
            if isinstance(widget, (DockerManagerWidget, FRPWidget)):
                widget.refresh_connections()

    def _app_config(self):
        """获取当前应用配置。"""
        if self._config_manager:
            return self._config_manager.app_config
        return None

    def _compose_command_library(
        self,
        context_widget: Optional[QWidget] = None,
    ) -> dict[str, object]:
        """收集编排发送可用的全局与会话命令库。"""
        snippet_groups: dict[str, list[str]] = {}
        favorite_snippets: list[str] = []
        macros: dict[str, list[str]] = {}

        app_config = self._app_config()
        if app_config:
            global_groups = normalize_terminal_snippet_groups(
                getattr(app_config, "terminal_snippet_groups", None)
                or getattr(app_config, "terminal_snippets", None)
            )
            for group_name, commands in global_groups.items():
                snippet_groups[f"全局 / {group_name}"] = list(commands)
            favorite_snippets.extend(
                normalize_terminal_favorite_snippets(
                    getattr(app_config, "terminal_favorite_snippets", None),
                    global_groups,
                    allow_empty=True,
                )
            )
            for macro_name, commands in normalize_terminal_macros(
                getattr(app_config, "terminal_macros", None),
                allow_empty=True,
            ).items():
                macros[f"全局 / {macro_name}"] = list(commands)

        reference_widget = self._preferred_sync_context_widget(context_widget)
        if reference_widget is not None and hasattr(reference_widget, "export_session_state"):
            try:
                session_data = reference_widget.export_session_state()
            except Exception as exc:
                self._logger.debug("读取会话命令库失败: %s", exc)
                session_data = {}
            if isinstance(session_data, dict):
                session_groups = normalize_terminal_snippet_groups(
                    session_data.get("session_snippet_groups"),
                    allow_empty=True,
                )
                for group_name, commands in session_groups.items():
                    snippet_groups[f"会话 / {group_name}"] = list(commands)
                favorite_snippets.extend(
                    normalize_terminal_favorite_snippets(
                        session_data.get("session_favorite_snippets"),
                        session_groups,
                        allow_empty=True,
                    )
                )
                for macro_name, commands in normalize_terminal_macros(
                    session_data.get("session_macros"),
                    allow_empty=True,
                ).items():
                    macros[f"会话 / {macro_name}"] = list(commands)

        deduped_favorites: list[str] = []
        seen_favorites: set[str] = set()
        for command in favorite_snippets:
            if command in seen_favorites:
                continue
            deduped_favorites.append(command)
            seen_favorites.add(command)

        return {
            "snippet_groups": snippet_groups,
            "favorite_snippets": deduped_favorites,
            "macros": macros,
        }

    @classmethod
    def _task_preset_definition(cls, preset_key: str) -> TaskPresetDefinition:
        """返回任务预设定义。"""
        return cls.TASK_PRESET_DEFINITIONS[preset_key]

    def _ensure_task_preset_actions(self) -> None:
        """创建任务预设动作。"""
        if self._task_preset_actions:
            return
        for preset_key in self.TASK_PRESET_ORDER:
            preset = self._task_preset_definition(preset_key)
            action = QAction(self.tr(preset.title), self)
            action.setIcon(icon("monitor"))
            action.triggered.connect(
                lambda _checked=False, key=preset_key: self._on_open_task_preset(key)
            )
            self._task_preset_actions[preset_key] = action

    def _build_task_preset_menu(self, parent: QWidget) -> QMenu:
        """构建任务预设菜单。"""
        menu = QMenu(self.tr("任务预设"), parent)
        for preset_key in self.TASK_PRESET_ORDER:
            menu.addAction(self._task_preset_actions[preset_key])
        return menu

    def _configure_task_preset_button(self, button: QToolButton) -> None:
        """为按钮接入任务预设下拉菜单。"""
        button.setDefaultAction(self._task_preset_actions["quick_inspection"])
        button.setPopupMode(QToolButton.MenuButtonPopup)
        button.setMenu(self._build_task_preset_menu(button))
        button.setIcon(icon("monitor"))

    @classmethod
    def _match_task_preset_macro_name(cls, preset_key: str, macro_name: str) -> bool:
        """判断宏名称是否适合作为目标任务预设。"""
        preset = cls._task_preset_definition(preset_key)
        normalized = (macro_name or "").casefold()
        return any(keyword.casefold() in normalized for keyword in preset.keywords)

    @classmethod
    def _default_task_preset_commands(cls, preset_key: str) -> list[str]:
        """返回任务预设的默认命令。"""
        return list(cls._task_preset_definition(preset_key).default_commands)

    def _matching_task_preset_macros(
        self,
        preset_key: str,
        macros: dict[str, list[str]],
    ) -> list[tuple[str, list[str]]]:
        """返回与任务预设匹配的宏，按优先级排序。"""
        preset = self._task_preset_definition(preset_key)
        candidates: list[tuple[int, str, list[str]]] = []
        for macro_name, commands in macros.items():
            if not self._match_task_preset_macro_name(preset_key, macro_name):
                continue
            normalized_commands = [
                command.strip()
                for command in commands
                if isinstance(command, str) and command.strip()
            ]
            if not normalized_commands:
                continue
            score = 0
            if macro_name.startswith("会话 / "):
                score += 10
            if preset.title in macro_name:
                score += 6
            for keyword in preset.keywords:
                if keyword and keyword in macro_name:
                    score += 2
            candidates.append((score, macro_name, normalized_commands))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [(macro_name, commands) for _score, macro_name, commands in candidates]

    def _pick_task_preset_macro(
        self,
        preset_key: str,
        macros: dict[str, list[str]],
    ) -> tuple[Optional[str], list[str]]:
        """从命令宏中挑选最合适的任务预设。"""
        candidates = self._matching_task_preset_macros(preset_key, macros)
        if not candidates:
            return None, []
        macro_name, commands = candidates[0]
        return macro_name, commands

    def _task_preset_dialog_payload(
        self,
        preset_key: str,
        context_widget: Optional[QWidget] = None,
    ) -> dict[str, object]:
        """构建任务预设对话框的默认载荷。"""
        preset = self._task_preset_definition(preset_key)
        command_label = (
            self.tr("巡检") if preset_key == "quick_inspection" else self.tr(preset.title)
        )
        payload = self._compose_command_library(context_widget)
        macros = payload.get("macros")
        macro_name: Optional[str] = None
        commands: list[str] = []
        template_choices: list[dict[str, object]] = []
        if isinstance(macros, dict):
            macro_name, commands = self._pick_task_preset_macro(preset_key, macros)
            for matched_macro_name, matched_commands in self._matching_task_preset_macros(
                preset_key,
                macros,
            ):
                template_choices.append(
                    {
                        "label": self.tr(f"宏模板 / {matched_macro_name}"),
                        "commands": list(matched_commands),
                        "summary": self.tr(
                            f"已从命令宏“{matched_macro_name}”预填充{command_label}命令，可继续调整后批量发送。"
                        ),
                    }
                )

        default_template = {
            "label": self.tr("内置模板 / 默认"),
            "commands": self._default_task_preset_commands(preset_key),
            "summary": self.tr(f"已填入默认 Linux {command_label}命令，可继续编辑后批量发送。"),
        }
        template_choices.insert(0, default_template)
        if macro_name and commands:
            summary_text = self.tr(
                f"已从命令宏“{macro_name}”预填充{command_label}命令，可继续调整后批量发送。"
            )
            initial_text = "\n".join(commands)
            current_template_label = self.tr(f"宏模板 / {macro_name}")
        else:
            summary_text = self.tr(
                f"未找到匹配的{preset.title}宏，已填入默认 Linux {command_label}命令，可继续编辑后批量发送。"
            )
            initial_text = "\n".join(self._default_task_preset_commands(preset_key))
            current_template_label = self.tr("内置模板 / 默认")

        target_scope_choices = [
            (self.tr("所有终端"), self.SYNC_SCOPE_ALL),
            (self.tr("同协议终端"), self.SYNC_SCOPE_SAME_TYPE),
            (self.tr("当前会话"), self.SYNC_SCOPE_SAME_CONNECTION),
        ]
        target_type_choices = self._task_preset_target_type_choices()
        target_group_choices = self._task_preset_target_group_choices()
        current_target_scope = self._sync_input_scope
        current_target_type = self.SYNC_TARGET_TYPE_ALL
        current_target_group = self.SYNC_TARGET_GROUP_ALL
        target_preview_text = self._task_preset_target_preview(
            scope=current_target_scope,
            target_type_filter=current_target_type,
            target_group_filter=current_target_group,
            context_widget=context_widget,
        )
        target_preview_map = self._task_preset_target_preview_map(context_widget=context_widget)

        return {
            "title_text": self.tr(preset.title),
            "summary_text": summary_text,
            "initial_text": initial_text,
            "template_choices": template_choices,
            "current_template_label": current_template_label,
            "target_scope_choices": target_scope_choices,
            "current_target_scope": current_target_scope,
            "target_type_choices": target_type_choices,
            "current_target_type": current_target_type,
            "target_group_choices": target_group_choices,
            "current_target_group": current_target_group,
            "target_preview_text": target_preview_text,
            "target_preview_map": target_preview_map,
            **payload,
        }

    def _quick_inspection_dialog_payload(
        self,
        context_widget: Optional[QWidget] = None,
    ) -> dict[str, object]:
        """兼容旧入口，返回快速巡检预设载荷。"""
        return self._task_preset_dialog_payload("quick_inspection", context_widget)

    def _apply_terminal_preferences(self) -> None:
        """将终端设置应用到已打开终端。"""
        config = self._app_config()
        if not config:
            return
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if hasattr(widget, "apply_preferences"):
                widget.apply_preferences(config)
        self._update_sync_input_status()

    @staticmethod
    def _supports_sync_input(widget: QWidget) -> bool:
        """判断组件是否支持同步输入广播。"""
        return hasattr(widget, "execute_broadcast_command")

    @staticmethod
    def _can_split_terminal_widget(widget: Optional[QWidget]) -> bool:
        """判断当前标签页是否支持终端分屏。"""
        if widget is None or isinstance(widget, TerminalSplitWidget):
            return False
        if isinstance(widget, QTermLocalTerminalWidget):
            return True

        connection = getattr(widget, "connection", None)
        connection_type = getattr(getattr(connection, "config", None), "connection_type", None)
        if connection_type in {
            ConnectionType.SSH,
            ConnectionType.SERIAL,
            ConnectionType.TCP,
            ConnectionType.UDP,
        }:
            return True

        return hasattr(widget, "execute_broadcast_command")

    def _bind_terminal_widget(self, widget: QWidget) -> QWidget:
        """绑定终端组件的配置同步信号。"""
        self._unbind_terminal_widget(widget)
        bindings: Dict[str, Any] = {}
        if hasattr(widget, "snippets_changed"):
            widget.snippets_changed.connect(self._on_terminal_snippets_changed)
            bindings["snippets_changed"] = self._on_terminal_snippets_changed
        if hasattr(widget, "command_executed"):
            command_handler = lambda command, source_widget=widget: (
                self._on_terminal_command_executed(
                    source_widget,
                    command,
                )
            )
            widget.command_executed.connect(command_handler)
            bindings["command_executed"] = command_handler
        if hasattr(widget, "session_state_changed"):
            session_handler = lambda payload, source_widget=widget: (
                self._on_terminal_session_state_changed(
                    source_widget,
                    payload,
                )
            )
            widget.session_state_changed.connect(session_handler)
            bindings["session_state_changed"] = session_handler
        if hasattr(widget, "output_appended"):
            output_handler = lambda text, source_widget=widget: (
                self._on_terminal_output_appended(
                    source_widget,
                    text,
                )
            )
            widget.output_appended.connect(output_handler)
            bindings["output_appended"] = output_handler
        if hasattr(widget, "execution_reported"):
            execution_handler = lambda payload, source_widget=widget: (
                self._on_terminal_execution_reported(
                    source_widget,
                    payload,
                )
            )
            widget.execution_reported.connect(execution_handler)
            bindings["execution_reported"] = execution_handler
        if hasattr(widget, "file_browser_requested"):
            file_browser_handler = lambda source_widget=widget: (
                self._on_terminal_file_browser_requested(source_widget)
            )
            widget.file_browser_requested.connect(file_browser_handler)
            bindings["file_browser_requested"] = file_browser_handler
        if hasattr(widget, "split_requested"):
            split_handler = lambda source_widget=widget: (
                self._on_terminal_split_requested(source_widget)
            )
            widget.split_requested.connect(split_handler)
            bindings["split_requested"] = split_handler
        if hasattr(widget, "sync_toggle_requested"):
            sync_toggle_handler = lambda source_widget=widget: (
                self._on_terminal_sync_toggle_requested(source_widget)
            )
            widget.sync_toggle_requested.connect(sync_toggle_handler)
            bindings["sync_toggle_requested"] = sync_toggle_handler
        if hasattr(widget, "command_center_requested"):
            command_center_handler = lambda source_widget=widget: (
                self._on_terminal_command_center_requested(source_widget)
            )
            widget.command_center_requested.connect(command_center_handler)
            bindings["command_center_requested"] = command_center_handler
        if hasattr(widget, "compose_requested"):
            compose_handler = lambda source_widget=widget: (
                self._on_terminal_compose_requested(source_widget)
            )
            widget.compose_requested.connect(compose_handler)
            bindings["compose_requested"] = compose_handler
        if hasattr(widget, "quick_inspection_requested"):
            inspection_handler = lambda source_widget=widget: (
                self._on_terminal_quick_inspection_requested(source_widget)
            )
            widget.quick_inspection_requested.connect(inspection_handler)
            bindings["quick_inspection_requested"] = inspection_handler
        widget._main_window_bindings = bindings
        return widget

    def _bind_file_browser_widget(self, widget: QWidget) -> QWidget:
        """绑定文件浏览器与主窗口之间的交互信号。"""
        bindings: Dict[str, Any] = {}
        if hasattr(widget, "terminal_requested"):
            terminal_handler = lambda remote_path, source_widget=widget: (
                self._on_file_browser_terminal_requested(source_widget, remote_path)
            )
            widget.terminal_requested.connect(terminal_handler)
            bindings["terminal_requested"] = terminal_handler
        widget._main_window_file_browser_bindings = bindings
        return widget

    def _unbind_terminal_widget(self, widget: Optional[QWidget]) -> None:
        """解绑终端组件与主窗口之间的信号连接。"""
        if widget is None:
            return

        bindings = getattr(widget, "_main_window_bindings", None)
        if not isinstance(bindings, dict):
            return

        snippets_handler = bindings.get("snippets_changed")
        if snippets_handler is not None and hasattr(widget, "snippets_changed"):
            try:
                widget.snippets_changed.disconnect(snippets_handler)
            except Exception:
                pass

        command_handler = bindings.get("command_executed")
        if command_handler is not None and hasattr(widget, "command_executed"):
            try:
                widget.command_executed.disconnect(command_handler)
            except Exception:
                pass

        session_handler = bindings.get("session_state_changed")
        if session_handler is not None and hasattr(widget, "session_state_changed"):
            try:
                widget.session_state_changed.disconnect(session_handler)
            except Exception:
                pass

        output_handler = bindings.get("output_appended")
        if output_handler is not None and hasattr(widget, "output_appended"):
            try:
                widget.output_appended.disconnect(output_handler)
            except Exception:
                pass

        execution_handler = bindings.get("execution_reported")
        if execution_handler is not None and hasattr(widget, "execution_reported"):
            try:
                widget.execution_reported.disconnect(execution_handler)
            except Exception:
                pass

        file_browser_handler = bindings.get("file_browser_requested")
        if file_browser_handler is not None and hasattr(widget, "file_browser_requested"):
            try:
                widget.file_browser_requested.disconnect(file_browser_handler)
            except Exception:
                pass

        split_handler = bindings.get("split_requested")
        if split_handler is not None and hasattr(widget, "split_requested"):
            try:
                widget.split_requested.disconnect(split_handler)
            except Exception:
                pass

        sync_toggle_handler = bindings.get("sync_toggle_requested")
        if sync_toggle_handler is not None and hasattr(widget, "sync_toggle_requested"):
            try:
                widget.sync_toggle_requested.disconnect(sync_toggle_handler)
            except Exception:
                pass

        command_center_handler = bindings.get("command_center_requested")
        if command_center_handler is not None and hasattr(widget, "command_center_requested"):
            try:
                widget.command_center_requested.disconnect(command_center_handler)
            except Exception:
                pass

        compose_handler = bindings.get("compose_requested")
        if compose_handler is not None and hasattr(widget, "compose_requested"):
            try:
                widget.compose_requested.disconnect(compose_handler)
            except Exception:
                pass

        inspection_handler = bindings.get("quick_inspection_requested")
        if inspection_handler is not None and hasattr(widget, "quick_inspection_requested"):
            try:
                widget.quick_inspection_requested.disconnect(inspection_handler)
            except Exception:
                pass

        widget._main_window_bindings = {}

    def _focus_workspace_owner_for_widget(self, widget: Optional[QWidget]) -> Optional[QWidget]:
        """聚焦包含指定组件的工作区标签页。"""
        if widget is None:
            return None

        direct_index = self.work_tabs.indexOf(widget)
        if direct_index >= 0:
            self.work_tabs.setCurrentIndex(direct_index)
            return self.work_tabs.widget(direct_index)

        for index in range(self.work_tabs.count()):
            tab_widget = self.work_tabs.widget(index)
            if isinstance(tab_widget, TerminalSplitWidget) and widget in {
                tab_widget.primary_terminal,
                tab_widget.secondary_terminal,
            }:
                self.work_tabs.setCurrentIndex(index)
                return tab_widget

        return None

    def _on_terminal_file_browser_requested(self, source_widget: QWidget) -> None:
        """从终端右键菜单打开对应连接的文件浏览器。"""
        self._focus_workspace_owner_for_widget(source_widget)
        connection_id = self._workspace_saved_connection_id(
            getattr(source_widget, "connection_id", None)
        )
        if connection_id:
            self._open_file_browser_for_connection(connection_id)

    def _on_terminal_split_requested(self, source_widget: QWidget) -> None:
        """从终端右键菜单触发终端分屏。"""
        owner_widget = self._focus_workspace_owner_for_widget(source_widget)
        if owner_widget is not None and self._can_split_terminal_widget(owner_widget):
            self._on_split_terminal()

    def _on_terminal_sync_toggle_requested(self, source_widget: QWidget) -> None:
        """从终端右键菜单切换同步输入。"""
        self._focus_workspace_owner_for_widget(source_widget)
        self._toggle_workspace_sync_input()

    def _on_terminal_command_center_requested(self, source_widget: QWidget) -> None:
        """从终端右键菜单打开快捷命令中心。"""
        self._focus_workspace_owner_for_widget(source_widget)
        self._on_open_command_center()

    def _on_terminal_compose_requested(self, source_widget: QWidget) -> None:
        """从终端右键菜单打开编排发送。"""
        self._focus_workspace_owner_for_widget(source_widget)
        self._on_open_compose_dialog()

    def _on_terminal_quick_inspection_requested(self, source_widget: QWidget) -> None:
        """从终端右键菜单打开快速巡检。"""
        self._focus_workspace_owner_for_widget(source_widget)
        self._on_open_quick_inspection()

    def _update_terminal_actions_state(self) -> None:
        """刷新终端相关动作的可用状态。"""
        if hasattr(self, "split_terminal_action"):
            self.split_terminal_action.setEnabled(
                self._can_split_terminal_widget(self.work_tabs.currentWidget())
            )
        can_compose = self._preferred_sync_context_widget() is not None
        can_open_command_center = True
        if hasattr(self, "compose_sync_action"):
            self.compose_sync_action.setEnabled(can_compose)
        if hasattr(self, "command_center_action"):
            self.command_center_action.setEnabled(can_open_command_center)
        if hasattr(self, "quick_inspection_action"):
            self.quick_inspection_action.setEnabled(can_compose)
        if hasattr(self, "task_preset_menu"):
            self.task_preset_menu.setEnabled(can_compose)
        for action in getattr(self, "_task_preset_actions", {}).values():
            action.setEnabled(can_compose)
        if hasattr(self, "sync_actions_btn"):
            self.sync_actions_btn.setEnabled(can_open_command_center or can_compose)
        has_history = bool(self._sync_history)
        if hasattr(self, "sync_history_action"):
            self.sync_history_action.setEnabled(has_history)
        if hasattr(self, "sync_history_btn"):
            self.sync_history_btn.setEnabled(has_history)

    @classmethod
    def _sync_scope_label(cls, scope: str) -> str:
        """返回同步输入范围文案。"""
        return {
            cls.SYNC_SCOPE_ALL: "所有终端",
            cls.SYNC_SCOPE_SAME_TYPE: "同协议终端",
            cls.SYNC_SCOPE_SAME_CONNECTION: "当前会话",
        }.get(scope, "所有终端")

    @staticmethod
    def _widget_connection_id(widget: Optional[QWidget]) -> Optional[str]:
        """提取标签页组件的连接 ID。"""
        connection_id = getattr(widget, "connection_id", None)
        return connection_id if isinstance(connection_id, str) and connection_id else None

    @staticmethod
    def _widget_connection_type(widget: Optional[QWidget]) -> Optional[object]:
        """提取标签页组件的连接类型。"""
        connection = getattr(widget, "connection", None)
        return getattr(getattr(connection, "config", None), "connection_type", None)

    @classmethod
    def _widget_target_type_key(cls, widget: Optional[QWidget]) -> Optional[str]:
        """提取标签页组件的目标类型键。"""
        connection_type = cls._widget_connection_type(widget)
        if isinstance(connection_type, ConnectionType):
            return connection_type.value
        if isinstance(connection_type, str) and connection_type:
            return connection_type
        connection_id = cls._widget_connection_id(widget)
        if isinstance(connection_id, str) and connection_id.startswith("__local_terminal__"):
            return cls.SYNC_TARGET_TYPE_LOCAL
        return None

    @classmethod
    def _target_type_label(cls, target_type_key: Optional[str]) -> str:
        """返回目标类型文案。"""
        mapping = {
            cls.SYNC_TARGET_TYPE_ALL: "全部类型",
            cls.SYNC_TARGET_TYPE_LOCAL: "本地终端",
            ConnectionType.SSH.value: "SSH",
            ConnectionType.SFTP.value: "SFTP",
            ConnectionType.FTP.value: "FTP",
            ConnectionType.FTPS.value: "FTPS",
            ConnectionType.SERIAL.value: "Serial",
            ConnectionType.TCP.value: "TCP",
            ConnectionType.UDP.value: "UDP",
            ConnectionType.VNC.value: "VNC",
            ConnectionType.RDP.value: "RDP",
        }
        normalized_key = str(target_type_key or "").strip()
        if not normalized_key:
            return "未知"
        return mapping.get(normalized_key, normalized_key.upper())

    @classmethod
    def _target_group_label(cls, target_group_key: Optional[str]) -> str:
        """返回目标分组文案。"""
        mapping = {
            cls.SYNC_TARGET_GROUP_ALL: "全部目标",
            cls.SYNC_TARGET_GROUP_REMOTE: "远程终端",
            cls.SYNC_TARGET_GROUP_LOCAL: "本地终端",
            cls.SYNC_TARGET_GROUP_FAVORITE: "收藏连接",
            cls.SYNC_TARGET_GROUP_RECENT: "最近连接",
        }
        normalized_key = str(target_group_key or "").strip()
        if not normalized_key:
            return "未知"
        return mapping.get(normalized_key, normalized_key)

    def _sync_scope_context(self, widget: Optional[QWidget] = None) -> dict[str, object]:
        """生成同步输入范围判定所需上下文。"""
        reference_widget = self._preferred_sync_context_widget(widget)
        return {
            "connection_id": self._widget_connection_id(reference_widget),
            "connection_type": self._widget_connection_type(reference_widget),
        }

    def _preferred_sync_context_widget(
        self,
        widget: Optional[QWidget] = None,
    ) -> Optional[QWidget]:
        """返回同步输入优先使用的上下文终端。"""
        candidate = widget or self.work_tabs.currentWidget()
        if isinstance(candidate, QWidget) and self._supports_sync_input(candidate):
            return candidate
        for index in range(self.work_tabs.count()):
            tab_widget = self.work_tabs.widget(index)
            if isinstance(tab_widget, QWidget) and self._supports_sync_input(tab_widget):
                return tab_widget
        return None

    def _sync_widget_matches_scope(
        self,
        widget: QWidget,
        scope: str,
        context: dict[str, object],
    ) -> bool:
        """判断终端组件是否匹配当前同步范围。"""
        if scope == self.SYNC_SCOPE_ALL:
            return True

        if scope == self.SYNC_SCOPE_SAME_TYPE:
            context_type = context.get("connection_type")
            if context_type is None:
                return False
            return self._widget_connection_type(widget) == context_type

        if scope == self.SYNC_SCOPE_SAME_CONNECTION:
            context_id = context.get("connection_id")
            if not isinstance(context_id, str) or not context_id:
                return False
            return self._widget_connection_id(widget) == context_id

        return True

    def _sync_widget_matches_target_type(
        self,
        widget: QWidget,
        target_type_filter: Optional[str],
    ) -> bool:
        """判断终端组件是否匹配目标类型筛选。"""
        if target_type_filter in (None, "", self.SYNC_TARGET_TYPE_ALL):
            return True
        return self._widget_target_type_key(widget) == target_type_filter

    def _sync_widget_matches_target_group(
        self,
        widget: QWidget,
        target_group_filter: Optional[str],
    ) -> bool:
        """判断终端组件是否匹配目标分组筛选。"""
        if target_group_filter in (None, "", self.SYNC_TARGET_GROUP_ALL):
            return True

        target_type_key = self._widget_target_type_key(widget)
        connection_id = self._widget_connection_id(widget)

        if target_group_filter == self.SYNC_TARGET_GROUP_REMOTE:
            return target_type_key not in (None, self.SYNC_TARGET_TYPE_LOCAL)
        if target_group_filter == self.SYNC_TARGET_GROUP_LOCAL:
            return target_type_key == self.SYNC_TARGET_TYPE_LOCAL

        if not connection_id or connection_id.startswith("__"):
            return False
        if self._config_manager is None:
            return False

        if target_group_filter == self.SYNC_TARGET_GROUP_FAVORITE:
            favorites = {
                connection.get("id")
                for connection in self._config_manager.load_favorite_connections()
                if connection.get("id")
            }
            return connection_id in favorites

        if target_group_filter == self.SYNC_TARGET_GROUP_RECENT:
            recents = {
                connection.get("id")
                for connection in self._config_manager.load_recent_connections(limit=20)
                if connection.get("id")
            }
            return connection_id in recents

        return True

    def _sync_target_widgets(
        self,
        exclude: Optional[QWidget] = None,
        *,
        scope: Optional[str] = None,
        context_widget: Optional[QWidget] = None,
        target_type_filter: Optional[str] = None,
        target_group_filter: Optional[str] = None,
        target_connection_ids: Optional[set[str]] = None,
    ) -> list[QWidget]:
        """返回当前可接收同步输入的终端组件。"""
        active_scope = scope or self._sync_input_scope
        context = self._sync_scope_context(context_widget)
        targets: list[QWidget] = []
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if widget is None or widget is exclude:
                continue
            if self._supports_sync_input(widget):
                if (
                    self._sync_widget_matches_scope(widget, active_scope, context)
                    and self._sync_widget_matches_target_type(widget, target_type_filter)
                    and self._sync_widget_matches_target_group(widget, target_group_filter)
                    and (
                        not target_connection_ids
                        or self._widget_connection_id(widget) in target_connection_ids
                    )
                ):
                    targets.append(widget)
        return targets

    def _sync_target_entries(
        self,
        exclude: Optional[QWidget] = None,
        *,
        scope: Optional[str] = None,
        context_widget: Optional[QWidget] = None,
        target_type_filter: Optional[str] = None,
        target_group_filter: Optional[str] = None,
        target_connection_ids: Optional[set[str]] = None,
    ) -> list[tuple[QWidget, str]]:
        """返回同步输入目标及其标签标题。"""
        active_scope = scope or self._sync_input_scope
        context = self._sync_scope_context(context_widget)
        entries: list[tuple[QWidget, str]] = []
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if widget is None or widget is exclude:
                continue
            if not self._supports_sync_input(widget):
                continue
            if not self._sync_widget_matches_scope(widget, active_scope, context):
                continue
            if not self._sync_widget_matches_target_type(widget, target_type_filter):
                continue
            if not self._sync_widget_matches_target_group(widget, target_group_filter):
                continue
            if (
                target_connection_ids
                and self._widget_connection_id(widget) not in target_connection_ids
            ):
                continue
            title = self.work_tabs.tabText(index).strip() or self.tr("未命名终端")
            entries.append((widget, title))
        return entries

    def _sync_target_entry_metadata(
        self,
        entries: list[tuple[QWidget, str]],
    ) -> list[dict[str, object]]:
        """把同步目标条目规整为可归档的元数据。"""
        metadata: list[dict[str, object]] = []
        for widget, title in entries:
            metadata.append(
                {
                    "target_name": (title or "").strip(),
                    "target_connection_id": self._widget_connection_id(widget) or "",
                    "target_type_key": self._widget_target_type_key(widget) or "",
                }
            )
        return metadata

    @staticmethod
    def _format_sync_target_summary(target_names: list[str]) -> str:
        """格式化目标终端摘要。"""
        if not target_names:
            return "暂无匹配终端"
        if len(target_names) <= 3:
            return "、".join(target_names)
        return f"{'、'.join(target_names[:3])} 等 {len(target_names)} 个终端"

    def _task_preset_target_type_choices(self) -> list[tuple[str, str]]:
        """返回任务预设目标类型下拉项。"""
        seen: set[str] = set()
        choices: list[tuple[str, str]] = [(self.tr("全部类型"), self.SYNC_TARGET_TYPE_ALL)]
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if widget is None or not self._supports_sync_input(widget):
                continue
            target_type_key = self._widget_target_type_key(widget)
            if not target_type_key or target_type_key in seen:
                continue
            seen.add(target_type_key)
            choices.append((self.tr(self._target_type_label(target_type_key)), target_type_key))
        return choices

    def _task_preset_target_group_choices(self) -> list[tuple[str, str]]:
        """返回任务预设目标分组下拉项。"""
        choices: list[tuple[str, str]] = [
            (self.tr("全部目标"), self.SYNC_TARGET_GROUP_ALL),
            (self.tr("远程终端"), self.SYNC_TARGET_GROUP_REMOTE),
            (self.tr("本地终端"), self.SYNC_TARGET_GROUP_LOCAL),
        ]
        if self._config_manager is not None:
            if self._config_manager.load_favorite_connections():
                choices.append((self.tr("收藏连接"), self.SYNC_TARGET_GROUP_FAVORITE))
            if self._config_manager.load_recent_connections(limit=20):
                choices.append((self.tr("最近连接"), self.SYNC_TARGET_GROUP_RECENT))
        return choices

    def _task_preset_target_preview(
        self,
        *,
        scope: Optional[str],
        target_type_filter: Optional[str],
        target_group_filter: Optional[str],
        context_widget: Optional[QWidget] = None,
    ) -> str:
        """返回任务预设目标预览文案。"""
        entries = self._sync_target_entries(
            scope=scope,
            context_widget=context_widget,
            target_type_filter=target_type_filter,
            target_group_filter=target_group_filter,
        )
        target_names = [title for _widget, title in entries]
        scope_label = self.tr(self._sync_scope_label(scope or self._sync_input_scope))
        type_label = (
            self.tr("全部类型")
            if target_type_filter in (None, "", self.SYNC_TARGET_TYPE_ALL)
            else self.tr(self._target_type_label(target_type_filter))
        )
        group_label = (
            self.tr("全部目标")
            if target_group_filter in (None, "", self.SYNC_TARGET_GROUP_ALL)
            else self.tr(self._target_group_label(target_group_filter))
        )
        return self.tr(
            f"目标范围: {scope_label} · 目标类型: {type_label} · 目标分组: {group_label} · 匹配: {self._format_sync_target_summary(target_names)}"
        )

    def _task_preset_target_preview_map(
        self,
        *,
        context_widget: Optional[QWidget] = None,
    ) -> dict[str, str]:
        """返回任务预设目标预览映射。"""
        preview_map: dict[str, str] = {}
        for _scope_label, scope_value in (
            (self.tr("所有终端"), self.SYNC_SCOPE_ALL),
            (self.tr("同协议终端"), self.SYNC_SCOPE_SAME_TYPE),
            (self.tr("当前会话"), self.SYNC_SCOPE_SAME_CONNECTION),
        ):
            for _type_label, type_value in self._task_preset_target_type_choices():
                for _group_label, group_value in self._task_preset_target_group_choices():
                    preview_map[f"{scope_value}::{type_value}::{group_value}"] = (
                        self._task_preset_target_preview(
                            scope=scope_value,
                            target_type_filter=type_value,
                            target_group_filter=group_value,
                            context_widget=context_widget,
                        )
                    )
        return preview_map

    def _set_sync_result_feedback(
        self,
        message: str,
        *,
        target_names: Optional[list[str]] = None,
    ) -> None:
        """刷新最近一次同步输入结果展示。"""
        names = [name for name in (target_names or []) if isinstance(name, str) and name]
        self.sync_result_label.setText(self.tr(f"最近发送: {message}"))
        if names:
            self.sync_result_label.setToolTip("\n".join(names))
        else:
            self.sync_result_label.setToolTip("")

    def _record_sync_dispatch(
        self,
        *,
        source_label: str,
        scope_label: str,
        scope_key: Optional[str] = None,
        commands: list[str],
        target_names: list[str],
        target_connection_ids: Optional[list[str]] = None,
        target_entries_metadata: Optional[list[dict[str, object]]] = None,
        delivery_count: int,
        failed_targets: Optional[list[str]] = None,
        source_kind: str = "compose",
        origin_batch_id: Optional[int] = None,
        retry_mode: Optional[str] = None,
        task_preset_key: Optional[str] = None,
        task_preset_title: Optional[str] = None,
        task_template_label: Optional[str] = None,
        target_type_key: Optional[str] = None,
        target_filter_label: Optional[str] = None,
        target_group_key: Optional[str] = None,
        target_group_label: Optional[str] = None,
        archive_tags: Optional[list[str]] = None,
    ) -> SyncDispatchRecord:
        """记录一次同步输入或编排发送结果。"""
        failed_target_names = list(failed_targets or [])
        normalized_target_connection_ids = [
            str(connection_id).strip()
            for connection_id in (target_connection_ids or [])
            if isinstance(connection_id, str) and str(connection_id).strip()
        ]
        target_result_entries: list[dict[str, object]] = []
        metadata_entries = [
            entry for entry in (target_entries_metadata or []) if isinstance(entry, dict)
        ]
        if metadata_entries:
            for entry in metadata_entries:
                target_name = str(entry.get("target_name", "") or "").strip()
                if not target_name:
                    continue
                target_result_entries.append(
                    self._build_target_result_entry(
                        target_name,
                        target_connection_id=entry.get("target_connection_id", None),
                        target_type_key=entry.get("target_type_key", None),
                        delivery_state="failed" if target_name in failed_target_names else "sent",
                    )
                )
        else:
            for index, target_name in enumerate(target_names):
                target_connection_id = None
                if index < len(normalized_target_connection_ids):
                    target_connection_id = normalized_target_connection_ids[index]
                target_result_entries.append(
                    self._build_target_result_entry(
                        target_name,
                        target_connection_id=target_connection_id,
                        delivery_state="failed" if target_name in failed_target_names else "sent",
                    )
                )
        record = SyncDispatchRecord(
            batch_id=self._next_sync_batch_id,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            source_label=source_label,
            scope_label=scope_label,
            scope_key=scope_key,
            command_count=len(commands),
            delivery_count=delivery_count,
            target_count=len(target_names),
            target_names=list(target_names),
            target_connection_ids=normalized_target_connection_ids,
            commands=list(commands),
            failed_targets=failed_target_names,
            source_kind=source_kind,
            origin_batch_id=origin_batch_id,
            retry_mode=retry_mode,
            task_preset_key=task_preset_key,
            task_preset_title=task_preset_title,
            task_template_label=task_template_label,
            target_type_key=target_type_key,
            target_filter_label=target_filter_label,
            target_group_key=target_group_key,
            target_group_label=target_group_label,
            archive_tags=list(archive_tags or []),
            target_result_entries=target_result_entries,
        )
        self._next_sync_batch_id += 1
        self._sync_history.insert(0, record)
        del self._sync_history[self.SYNC_HISTORY_LIMIT :]
        self._refresh_sync_history_dialog()
        self._update_terminal_actions_state()
        self._prune_task_archives()
        return record

    @staticmethod
    def _sanitize_task_output_excerpt(text: object) -> str:
        """规整任务结果回显片段。"""
        if text is None:
            return ""
        sanitized = str(text).replace("\r", "")
        sanitized = sanitized.replace("\x00", "")
        sanitized = "".join(
            character
            for character in sanitized
            if character == "\n" or character == "\t" or ord(character) >= 32
        )
        return sanitized.strip()

    def _find_sync_record(self, batch_id: int) -> Optional[SyncDispatchRecord]:
        """按批次号查找发送记录。"""
        for record in self._sync_history:
            if record.batch_id == batch_id:
                return record
        return None

    @classmethod
    def _build_target_result_entry(
        cls,
        target_name: str,
        *,
        target_connection_id: Optional[object] = None,
        target_type_key: Optional[object] = None,
        delivery_state: str = "sent",
    ) -> dict[str, object]:
        """构造标准化的终端结果记录。"""
        return {
            "target_name": (target_name or "").strip(),
            "target_connection_id": str(target_connection_id or "").strip(),
            "target_type_key": str(target_type_key or "").strip(),
            "result_excerpt": "",
            "result_excerpt_updated_at": None,
            "result_sample_count": 0,
            "delivery_state": delivery_state,
            "stdout_excerpt": "",
            "stdout_sample_count": 0,
            "stderr_excerpt": "",
            "stderr_sample_count": 0,
            "last_output_kind": "",
            "exit_code": None,
            "exit_code_updated_at": None,
        }

    def _ensure_target_result_entry(
        self,
        record: SyncDispatchRecord,
        target_name: str,
        *,
        target_connection_id: Optional[object] = None,
        target_type_key: Optional[object] = None,
    ) -> Optional[dict[str, object]]:
        """返回并补齐目标终端的结果记录。"""
        normalized_target_name = (target_name or "").strip()
        normalized_target_connection_id = str(target_connection_id or "").strip()
        normalized_target_type_key = str(target_type_key or "").strip()
        if not normalized_target_name:
            return None
        for entry in record.target_result_entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("target_name", "")).strip() != normalized_target_name:
                continue
            normalized = self._build_target_result_entry(
                normalized_target_name,
                target_connection_id=(
                    normalized_target_connection_id or entry.get("target_connection_id", None)
                ),
                target_type_key=(normalized_target_type_key or entry.get("target_type_key", None)),
                delivery_state=str(entry.get("delivery_state", "sent") or "sent"),
            )
            normalized.update(entry)
            if normalized_target_connection_id:
                normalized["target_connection_id"] = normalized_target_connection_id
            if normalized_target_type_key:
                normalized["target_type_key"] = normalized_target_type_key
            entry.clear()
            entry.update(normalized)
            return entry

        entry = self._build_target_result_entry(
            normalized_target_name,
            target_connection_id=normalized_target_connection_id,
            target_type_key=normalized_target_type_key,
        )
        record.target_result_entries.append(entry)
        return entry

    @classmethod
    def _append_excerpt_text(cls, current: object, snippet: object) -> str:
        """把新的文本片段追加到已有摘要中。"""
        normalized_snippet = cls._sanitize_task_output_excerpt(snippet)
        if not normalized_snippet:
            return str(current or "").strip()
        current_excerpt = str(current or "").strip()
        if normalized_snippet in current_excerpt:
            combined = current_excerpt
        elif current_excerpt:
            combined = f"{current_excerpt}\n{normalized_snippet}"
        else:
            combined = normalized_snippet
        if len(combined) > cls.TASK_RESULT_CAPTURE_MAX_CHARS:
            combined = combined[-cls.TASK_RESULT_CAPTURE_MAX_CHARS :]
        return combined

    @classmethod
    def _guess_output_kind(cls, text: object) -> str:
        """对输出片段做轻量级流分类。"""
        snippet = cls._sanitize_task_output_excerpt(text)
        if not snippet:
            return "output"
        lower_text = snippet.lower()
        if snippet.startswith("错误:") or "traceback" in lower_text:
            return "stderr"
        return "stdout"

    @staticmethod
    def _normalize_execution_report(payload: object) -> Optional[dict[str, object]]:
        """规整终端执行回执。"""
        if not isinstance(payload, dict):
            return None
        report = {
            "command": str(payload.get("command", "") or "").strip(),
            "stdout": str(payload.get("stdout", "") or ""),
            "stderr": str(payload.get("stderr", "") or ""),
            "completed_at": str(payload.get("completed_at", "") or "").strip(),
            "source": str(payload.get("source", "") or "").strip(),
        }
        exit_code = payload.get("exit_code", None)
        if exit_code is None or exit_code == "":
            report["exit_code"] = None
        else:
            try:
                report["exit_code"] = int(exit_code)
            except (TypeError, ValueError):
                report["exit_code"] = None
        return report

    def _prune_task_archives(self) -> None:
        """清理已过期的任务结果采集会话。"""
        now = time.monotonic()
        active: dict[int, list[dict[str, object]]] = {}
        for widget_id, captures in self._active_task_archives.items():
            kept = [
                capture
                for capture in captures
                if float(capture.get("expires_at", 0.0) or 0.0) > now
                and int(capture.get("remaining_chunks", 0) or 0) > 0
                and self._find_sync_record(int(capture.get("batch_id", 0) or 0)) is not None
            ]
            if kept:
                active[widget_id] = kept
        self._active_task_archives = active

    def _arm_task_result_capture(
        self,
        record: SyncDispatchRecord,
        entries: list[tuple[QWidget, str]],
    ) -> None:
        """为任务预设批次绑定一段时间的结果摘要采集。"""
        if record.source_kind != "task_preset":
            return
        expires_at = time.monotonic() + self.TASK_RESULT_CAPTURE_TTL_SECONDS
        known_targets = {
            str(entry.get("target_name", "")).strip()
            for entry in record.target_result_entries
            if isinstance(entry, dict)
        }
        for widget, title in entries:
            normalized_title = (title or "").strip()
            target_connection_id = self._widget_connection_id(widget) or ""
            target_type_key = self._widget_target_type_key(widget) or ""
            if normalized_title:
                self._ensure_target_result_entry(
                    record,
                    normalized_title,
                    target_connection_id=target_connection_id,
                    target_type_key=target_type_key,
                )
                known_targets.add(normalized_title)
            widget_id = id(widget)
            captures = self._active_task_archives.setdefault(widget_id, [])
            captures.append(
                {
                    "batch_id": record.batch_id,
                    "expires_at": expires_at,
                    "remaining_chunks": self.TASK_RESULT_CAPTURE_MAX_CHUNKS,
                    "target_name": normalized_title,
                    "target_connection_id": target_connection_id,
                    "target_type_key": target_type_key,
                }
            )

    def _append_task_result_excerpt(
        self,
        record: SyncDispatchRecord,
        target_name: str,
        excerpt: str,
        *,
        output_kind: str = "output",
        target_connection_id: Optional[object] = None,
        target_type_key: Optional[object] = None,
    ) -> None:
        """将结果片段追加到批次记录。"""
        snippet = self._sanitize_task_output_excerpt(excerpt)
        if not snippet:
            return
        record.result_excerpt = self._append_excerpt_text(record.result_excerpt, snippet)
        record.result_sample_count += 1
        record.result_excerpt_updated_at = datetime.now().strftime("%H:%M:%S")
        normalized_target_name = (target_name or "").strip()
        if normalized_target_name:
            target_entry = self._ensure_target_result_entry(
                record,
                normalized_target_name,
                target_connection_id=target_connection_id,
                target_type_key=target_type_key,
            )
            if target_entry is None:
                return
            target_entry["result_excerpt"] = self._append_excerpt_text(
                target_entry.get("result_excerpt", ""),
                snippet,
            )
            target_entry["result_excerpt_updated_at"] = record.result_excerpt_updated_at
            target_entry["result_sample_count"] = (
                int(target_entry.get("result_sample_count", 0) or 0) + 1
            )
            target_entry["delivery_state"] = "captured"
            normalized_kind = output_kind if output_kind in {"stdout", "stderr"} else ""
            if normalized_kind:
                field_name = f"{normalized_kind}_excerpt"
                sample_field = f"{normalized_kind}_sample_count"
                target_entry[field_name] = self._append_excerpt_text(
                    target_entry.get(field_name, ""),
                    snippet,
                )
                target_entry[sample_field] = int(target_entry.get(sample_field, 0) or 0) + 1
                target_entry["last_output_kind"] = normalized_kind
        if self._sync_history_dialog is not None:
            self._refresh_sync_history_dialog()

    def _apply_execution_report_to_record(
        self,
        record: SyncDispatchRecord,
        target_name: str,
        report: dict[str, object],
        *,
        target_connection_id: Optional[object] = None,
        target_type_key: Optional[object] = None,
    ) -> None:
        """把结构化执行回执写入批次记录。"""
        target_entry = self._ensure_target_result_entry(
            record,
            target_name,
            target_connection_id=target_connection_id,
            target_type_key=target_type_key,
        )
        if target_entry is None:
            return
        completed_at = str(report.get("completed_at", "") or "").strip() or datetime.now().strftime(
            "%H:%M:%S"
        )
        exit_code = report.get("exit_code", None)
        if isinstance(exit_code, int):
            target_entry["exit_code"] = exit_code
            target_entry["exit_code_updated_at"] = completed_at
        stdout_excerpt = self._sanitize_task_output_excerpt(report.get("stdout", ""))
        stderr_excerpt = self._sanitize_task_output_excerpt(report.get("stderr", ""))
        if stdout_excerpt:
            target_entry["stdout_excerpt"] = self._append_excerpt_text(
                target_entry.get("stdout_excerpt", ""),
                stdout_excerpt,
            )
            target_entry["stdout_sample_count"] = max(
                1,
                int(target_entry.get("stdout_sample_count", 0) or 0),
            )
            target_entry["last_output_kind"] = "stdout"
            if not record.result_excerpt:
                record.result_excerpt = stdout_excerpt
                record.result_excerpt_updated_at = completed_at
                record.result_sample_count = max(record.result_sample_count, 1)
        if stderr_excerpt:
            target_entry["stderr_excerpt"] = self._append_excerpt_text(
                target_entry.get("stderr_excerpt", ""),
                stderr_excerpt,
            )
            target_entry["stderr_sample_count"] = max(
                1,
                int(target_entry.get("stderr_sample_count", 0) or 0),
            )
            target_entry["last_output_kind"] = "stderr"
            if not record.result_excerpt:
                record.result_excerpt = stderr_excerpt
                record.result_excerpt_updated_at = completed_at
                record.result_sample_count = max(record.result_sample_count, 1)
        if (
            isinstance(exit_code, int)
            and exit_code == 0
            and str(target_entry.get("delivery_state", "") or "") != "failed"
        ):
            target_entry["delivery_state"] = "captured"
        elif (
            isinstance(exit_code, int)
            and exit_code != 0
            and str(target_entry.get("delivery_state", "") or "") not in {"failed", "captured"}
        ):
            target_entry["delivery_state"] = "captured"

    def _on_terminal_output_appended(self, source_widget: QWidget, text: str) -> None:
        """接收终端输出并写入任务批次的最近结果摘要。"""
        self._prune_task_archives()
        captures = self._active_task_archives.get(id(source_widget), [])
        if not captures:
            return
        updated = False
        for capture in captures:
            batch_id = int(capture.get("batch_id", 0) or 0)
            record = self._find_sync_record(batch_id)
            if record is None:
                continue
            self._append_task_result_excerpt(
                record,
                str(capture.get("target_name", "") or ""),
                text,
                output_kind=self._guess_output_kind(text),
                target_connection_id=capture.get("target_connection_id", None),
                target_type_key=capture.get("target_type_key", None),
            )
            capture["remaining_chunks"] = max(
                0,
                int(capture.get("remaining_chunks", 0) or 0) - 1,
            )
            updated = True
        if updated:
            self._prune_task_archives()

    def _on_terminal_execution_reported(
        self,
        source_widget: QWidget,
        payload: object,
    ) -> None:
        """接收终端结构化执行回执并写入任务批次。"""
        report = self._normalize_execution_report(payload)
        if report is None:
            return
        self._prune_task_archives()
        captures = self._active_task_archives.get(id(source_widget), [])
        if not captures:
            return
        updated = False
        for capture in captures:
            batch_id = int(capture.get("batch_id", 0) or 0)
            record = self._find_sync_record(batch_id)
            if record is None:
                continue
            self._apply_execution_report_to_record(
                record,
                str(capture.get("target_name", "") or ""),
                report,
                target_connection_id=capture.get("target_connection_id", None),
                target_type_key=capture.get("target_type_key", None),
            )
            updated = True
        if updated and self._sync_history_dialog is not None:
            self._refresh_sync_history_dialog()

    def _refresh_sync_history_dialog(self) -> None:
        """刷新已打开的发送记录对话框。"""
        if self._sync_history_dialog is not None:
            self._sync_history_dialog.set_records(self._sync_history)

    def _sync_record_compose_payload(
        self,
        record: object,
        *,
        context_widget: Optional[QWidget] = None,
    ) -> dict[str, object]:
        """将历史批次转换为新的编排发送载荷。"""
        commands = [
            str(command).strip()
            for command in getattr(record, "commands", [])
            if isinstance(command, str) and command.strip()
        ]
        batch_id = int(getattr(record, "batch_id", 0) or 0)
        source_label = str(getattr(record, "source_label", self.tr("发送")) or self.tr("发送"))
        task_preset_key = getattr(record, "task_preset_key", None)
        if (
            not isinstance(task_preset_key, str)
            or task_preset_key not in self.TASK_PRESET_DEFINITIONS
        ):
            task_preset_key = None

        if task_preset_key is not None:
            payload = self._task_preset_dialog_payload(
                task_preset_key,
                context_widget=context_widget,
            )
        else:
            payload = {
                **self._compose_command_library(context_widget),
                "title_text": self.tr("历史任务复用"),
                "summary_text": self.tr("已载入历史批次命令，可编辑后再次批量发送。"),
            }

        history_template_label = self.tr(f"历史回放 / 批次 #{batch_id:03d}")
        template_choices = [
            choice for choice in payload.get("template_choices", []) if isinstance(choice, dict)
        ]
        template_choices = [
            {
                "label": history_template_label,
                "commands": list(commands),
                "summary": self.tr(
                    f"已从批次 #{batch_id:03d} 载入 {len(commands)} 条命令，来源为“{source_label}”。"
                ),
            },
            *[
                choice
                for choice in template_choices
                if str(choice.get("label", "") or "") != history_template_label
            ],
        ]

        scope_key = str(getattr(record, "scope_key", None) or self._sync_input_scope)
        target_type_key = str(getattr(record, "target_type_key", None) or self.SYNC_TARGET_TYPE_ALL)
        target_group_key = str(
            getattr(record, "target_group_key", None) or self.SYNC_TARGET_GROUP_ALL
        )
        target_preview_map = self._task_preset_target_preview_map(context_widget=context_widget)
        target_preview_text = self._task_preset_target_preview(
            scope=scope_key,
            target_type_filter=target_type_key,
            target_group_filter=target_group_key,
            context_widget=context_widget,
        )

        payload.update(
            {
                "title_text": self.tr(f"复用批次 #{batch_id:03d}"),
                "summary_text": self.tr(
                    f"已从历史批次 #{batch_id:03d} 载入命令与目标条件，可调整后重新发送。"
                ),
                "initial_text": "\n".join(commands),
                "template_choices": template_choices,
                "current_template_label": history_template_label,
                "target_scope_choices": payload.get(
                    "target_scope_choices",
                    [
                        (self.tr("所有终端"), self.SYNC_SCOPE_ALL),
                        (self.tr("同协议终端"), self.SYNC_SCOPE_SAME_TYPE),
                        (self.tr("当前会话"), self.SYNC_SCOPE_SAME_CONNECTION),
                    ],
                ),
                "current_target_scope": scope_key,
                "target_type_choices": payload.get(
                    "target_type_choices",
                    self._task_preset_target_type_choices(),
                ),
                "current_target_type": target_type_key,
                "target_group_choices": payload.get(
                    "target_group_choices",
                    self._task_preset_target_group_choices(),
                ),
                "current_target_group": target_group_key,
                "target_preview_text": target_preview_text,
                "target_preview_map": target_preview_map,
            }
        )
        return payload

    @staticmethod
    def _normalize_record_origin_batch_id(record: object) -> Optional[int]:
        """规整历史批次来源编号。"""
        value = getattr(record, "origin_batch_id", None)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_retry_mode(value: object) -> Optional[str]:
        """规整重试模式。"""
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _record_target_entries(record: object) -> list[dict[str, object]]:
        """返回历史批次中可用于精确重试的目标条目。"""
        raw_entries = getattr(record, "target_result_entries", [])
        if not isinstance(raw_entries, list):
            return []
        entries: list[dict[str, object]] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            target_name = str(entry.get("target_name", "") or "").strip()
            if not target_name:
                continue
            entries.append(
                {
                    "target_name": target_name,
                    "target_connection_id": str(
                        entry.get("target_connection_id", "") or ""
                    ).strip(),
                    "target_type_key": str(entry.get("target_type_key", "") or "").strip(),
                    "delivery_state": str(entry.get("delivery_state", "") or "").strip(),
                    "exit_code": entry.get("exit_code", None),
                }
            )
        return entries

    def _retryable_record_targets(
        self,
        record: object,
        *,
        retry_mode: str,
    ) -> list[dict[str, object]]:
        """返回可重试的历史目标。"""
        entries = self._record_target_entries(record)
        failed_names = {
            str(name).strip()
            for name in getattr(record, "failed_targets", [])
            if isinstance(name, str) and str(name).strip()
        }
        retryable: list[dict[str, object]] = []
        for entry in entries:
            target_name = str(entry.get("target_name", "") or "").strip()
            if not target_name:
                continue
            exit_code = entry.get("exit_code", None)
            should_include = False
            if retry_mode == "failed":
                should_include = (
                    target_name in failed_names
                    or str(entry.get("delivery_state", "") or "").strip() == "failed"
                )
            elif retry_mode == "nonzero":
                should_include = isinstance(exit_code, int) and exit_code != 0
            elif retry_mode == "pending":
                should_include = (
                    exit_code is None
                    and target_name not in failed_names
                    and str(entry.get("delivery_state", "") or "").strip() != "failed"
                )
            if should_include:
                retryable.append(entry)
        return retryable

    def _build_retry_compose_payload(
        self,
        record: object,
        *,
        retry_mode: str,
    ) -> tuple[dict[str, object], list[str], list[str]]:
        """构建失败/非零退出重试对话框载荷。"""
        retryable_entries = self._retryable_record_targets(record, retry_mode=retry_mode)
        retryable_entries = [
            entry
            for entry in retryable_entries
            if str(entry.get("target_connection_id", "") or "").strip()
        ]
        target_ids = [
            str(entry.get("target_connection_id", "") or "").strip()
            for entry in retryable_entries
            if str(entry.get("target_connection_id", "") or "").strip()
        ]
        target_names = [
            str(entry.get("target_name", "") or "").strip()
            for entry in retryable_entries
            if str(entry.get("target_name", "") or "").strip()
        ]
        payload = self._sync_record_compose_payload(record)
        batch_id = int(getattr(record, "batch_id", 0) or 0)
        action_label_map = {
            "failed": self.tr("失败终端重试"),
            "nonzero": self.tr("非零退出重试"),
            "pending": self.tr("待回执重试"),
        }
        action_label = action_label_map.get(retry_mode, self.tr("历史重试"))
        target_summary = self._format_sync_target_summary(target_names)
        payload.update(
            {
                "title_text": self.tr(f"{action_label} · 批次 #{batch_id:03d}"),
                "summary_text": self.tr(
                    f"已从批次 #{batch_id:03d} 载入命令，并将目标限定为 {target_summary}。确认后将仅重发到这些终端。"
                ),
            }
        )
        return payload, target_ids, target_names

    def _on_open_sync_history(self) -> None:
        """打开发送记录对话框。"""
        if not self._sync_history:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前还没有发送记录"),
            )
            return
        if self._sync_history_dialog is None:
            self._sync_history_dialog = SyncHistoryDialog(self)
            self._sync_history_dialog.replay_requested.connect(self._on_replay_sync_record)
            self._sync_history_dialog.retry_failed_requested.connect(
                self._on_retry_failed_sync_record
            )
            self._sync_history_dialog.retry_nonzero_requested.connect(
                self._on_retry_nonzero_sync_record
            )
            self._sync_history_dialog.retry_pending_requested.connect(
                self._on_retry_pending_sync_record
            )
            self._sync_history_dialog.recommended_retry_requested.connect(
                self._on_apply_recommended_sync_retry
            )
        self._sync_history_dialog.set_records(self._sync_history)
        self._sync_history_dialog.show()
        self._sync_history_dialog.raise_()
        self._sync_history_dialog.activateWindow()

    def _on_replay_sync_record(self, record: object) -> None:
        """将历史批次复用为新的编排发送任务。"""
        if self._preferred_sync_context_widget() is None:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前没有可用于批量发送的终端"),
            )
            return

        payload = self._sync_record_compose_payload(record)
        dialog = ComposeCommandDialog(self, **payload)
        if dialog.exec() != QDialog.Accepted:
            return

        commands = dialog.commands()
        if not commands:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("请输入至少一条命令"),
            )
            return

        selected_scope = (
            dialog.selected_target_scope()
            if hasattr(dialog, "selected_target_scope")
            else self._sync_input_scope
        )
        selected_target_type = (
            dialog.selected_target_type()
            if hasattr(dialog, "selected_target_type")
            else self.SYNC_TARGET_TYPE_ALL
        )
        selected_target_group = (
            dialog.selected_target_group()
            if hasattr(dialog, "selected_target_group")
            else self.SYNC_TARGET_GROUP_ALL
        )
        selected_template_label = (
            dialog.selected_template_label() if hasattr(dialog, "selected_template_label") else None
        )
        target_filter_label = None
        if selected_target_type not in (None, "", self.SYNC_TARGET_TYPE_ALL):
            target_filter_label = self.tr(self._target_type_label(selected_target_type))
        target_group_label = None
        if selected_target_group not in (None, "", self.SYNC_TARGET_GROUP_ALL):
            target_group_label = self.tr(self._target_group_label(selected_target_group))

        batch_id = int(getattr(record, "batch_id", 0) or 0)
        original_source_label = str(
            getattr(record, "source_label", self.tr("发送")) or self.tr("发送")
        )
        task_preset_key = getattr(record, "task_preset_key", None)
        task_preset_title = getattr(record, "task_preset_title", None)
        if not isinstance(task_preset_key, str):
            task_preset_key = None
        if not isinstance(task_preset_title, str) or not task_preset_title.strip():
            task_preset_title = None

        sent_count, target_count = self._broadcast_sync_commands(
            commands,
            scope_override=selected_scope,
            target_type_filter=selected_target_type,
            target_group_filter=selected_target_group,
            source_label=self.tr("历史复用"),
            source_kind="history_replay",
            origin_batch_id=batch_id,
            task_preset_key=task_preset_key,
            task_preset_title=task_preset_title,
            task_template_label=selected_template_label,
            target_filter_label=target_filter_label,
            target_group_label=target_group_label,
            archive_tags=[
                self.tr("历史复用"),
                self.tr(f"源批次 / #{batch_id:03d}"),
                self.tr(f"原始来源 / {original_source_label}"),
                *([self.tr(f"任务预设 / {task_preset_title}")] if task_preset_title else []),
                *(
                    [self.tr(f"任务模板 / {selected_template_label}")]
                    if selected_template_label
                    else []
                ),
                self.tr(self._sync_scope_label(selected_scope)),
                *([self.tr(f"目标类型 / {target_filter_label}")] if target_filter_label else []),
                *([self.tr(f"目标分组 / {target_group_label}")] if target_group_label else []),
            ],
        )
        if sent_count and target_count:
            self._logger.info(
                "历史复用完成: 批次 #%03d -> %s 条命令 -> %s 个终端",
                batch_id,
                sent_count,
                target_count,
            )

    def _retry_sync_record(self, record: object, *, retry_mode: str) -> None:
        """按失败/非零退出结果重新发送历史批次。"""
        if self._preferred_sync_context_widget() is None:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前没有可用于批量发送的终端"),
            )
            return

        payload, target_ids, target_names = self._build_retry_compose_payload(
            record,
            retry_mode=retry_mode,
        )
        if not target_names:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前批次没有可重试的目标终端"),
            )
            return
        if not target_ids:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前批次缺少精确目标标识，暂时无法安全重试"),
            )
            return

        dialog = ComposeCommandDialog(self, **payload)
        if dialog.exec() != QDialog.Accepted:
            return
        commands = dialog.commands()
        if not commands:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("请输入至少一条命令"),
            )
            return

        selected_scope = (
            dialog.selected_target_scope()
            if hasattr(dialog, "selected_target_scope")
            else self._sync_input_scope
        )
        selected_target_type = (
            dialog.selected_target_type()
            if hasattr(dialog, "selected_target_type")
            else self.SYNC_TARGET_TYPE_ALL
        )
        selected_target_group = (
            dialog.selected_target_group()
            if hasattr(dialog, "selected_target_group")
            else self.SYNC_TARGET_GROUP_ALL
        )
        selected_template_label = (
            dialog.selected_template_label() if hasattr(dialog, "selected_template_label") else None
        )
        target_filter_label = None
        if selected_target_type not in (None, "", self.SYNC_TARGET_TYPE_ALL):
            target_filter_label = self.tr(self._target_type_label(selected_target_type))
        target_group_label = None
        if selected_target_group not in (None, "", self.SYNC_TARGET_GROUP_ALL):
            target_group_label = self.tr(self._target_group_label(selected_target_group))

        batch_id = int(getattr(record, "batch_id", 0) or 0)
        original_source_label = str(
            getattr(record, "source_label", self.tr("发送")) or self.tr("发送")
        )
        task_preset_key = getattr(record, "task_preset_key", None)
        task_preset_title = getattr(record, "task_preset_title", None)
        if not isinstance(task_preset_key, str):
            task_preset_key = None
        if not isinstance(task_preset_title, str) or not task_preset_title.strip():
            task_preset_title = None

        action_label_map = {
            "failed": self.tr("失败终端重试"),
            "nonzero": self.tr("非零退出重试"),
            "pending": self.tr("待回执重试"),
        }
        action_label = action_label_map.get(retry_mode, self.tr("历史重试"))
        sent_count, target_count = self._broadcast_sync_commands(
            commands,
            scope_override=selected_scope,
            target_type_filter=selected_target_type,
            target_group_filter=selected_target_group,
            target_connection_ids=target_ids,
            source_label=action_label,
            source_kind="history_retry",
            origin_batch_id=batch_id,
            retry_mode=retry_mode,
            task_preset_key=task_preset_key,
            task_preset_title=task_preset_title,
            task_template_label=selected_template_label,
            target_filter_label=target_filter_label,
            target_group_label=target_group_label,
            archive_tags=[
                self.tr("历史重试"),
                self.tr(action_label),
                self.tr(f"源批次 / #{batch_id:03d}"),
                self.tr(f"原始来源 / {original_source_label}"),
                *([self.tr(f"任务预设 / {task_preset_title}")] if task_preset_title else []),
                *(
                    [self.tr(f"任务模板 / {selected_template_label}")]
                    if selected_template_label
                    else []
                ),
                self.tr(self._sync_scope_label(selected_scope)),
                *([self.tr(f"目标类型 / {target_filter_label}")] if target_filter_label else []),
                *([self.tr(f"目标分组 / {target_group_label}")] if target_group_label else []),
                self.tr(f"精确目标 / {len(target_ids)}"),
            ],
        )
        if sent_count and target_count:
            self._logger.info(
                "%s完成: 批次 #%03d -> %s 条命令 -> %s 个终端",
                action_label,
                batch_id,
                sent_count,
                target_count,
            )

    def _on_retry_failed_sync_record(self, record: object) -> None:
        """重试历史批次中的失败终端。"""
        self._retry_sync_record(record, retry_mode="failed")

    def _on_retry_nonzero_sync_record(self, record: object) -> None:
        """重试历史批次中的非零退出终端。"""
        self._retry_sync_record(record, retry_mode="nonzero")

    def _on_retry_pending_sync_record(self, record: object) -> None:
        """重试历史批次中的待回执终端。"""
        self._retry_sync_record(record, retry_mode="pending")

    def _on_apply_recommended_sync_retry(self, record: object, retry_mode: str) -> None:
        """按建议执行历史批次的推荐重试动作。"""
        normalized_retry_mode = str(retry_mode or "").strip()
        if normalized_retry_mode == "pending":
            self._on_retry_pending_sync_record(record)
            return
        if normalized_retry_mode == "failed":
            self._on_retry_failed_sync_record(record)
            return
        if normalized_retry_mode == "nonzero":
            self._on_retry_nonzero_sync_record(record)

    def _set_sync_input_enabled(self, enabled: bool) -> None:
        """切换同步输入模式。"""
        self._sync_input_enabled = bool(enabled)
        self.sync_input_bar.setVisible(self._sync_input_enabled)
        if self._sync_input_enabled:
            self.sync_input_edit.setFocus(Qt.OtherFocusReason)
        self._update_sync_input_status()

    def _on_sync_scope_changed(self) -> None:
        """切换同步输入的广播范围。"""
        self._sync_input_scope = str(
            self.sync_input_scope_combo.currentData() or self.SYNC_SCOPE_ALL
        )
        self._update_sync_input_status()

    def _update_sync_input_status(self) -> None:
        """刷新同步输入状态提示。"""
        scope_label = self.tr(self._sync_scope_label(self._sync_input_scope))
        target_names = [title for _, title in self._sync_target_entries()]
        target_count = len(target_names)
        target_summary = self._format_sync_target_summary(target_names)
        if self._sync_input_enabled:
            self.sync_status_label.setText(
                self.tr(f"同步输入: 开启 · {scope_label} ({target_count} 个终端)")
            )
            self.sync_input_mode_badge.setText(self.tr(f"{scope_label} · {target_count} 个目标"))
        else:
            self.sync_status_label.setText(self.tr("同步输入: 关闭"))
            self.sync_input_mode_badge.setText(self.tr("已关闭"))
        self.sync_input_hint_label.setText(self.tr(f"目标: {target_summary}"))
        tooltip = "\n".join(target_names) if target_names else self.tr("当前没有匹配终端")
        self.sync_status_label.setToolTip(tooltip)
        self.sync_input_hint_label.setToolTip(tooltip)
        self.sync_input_mode_badge.setToolTip(self.tr(f"范围: {scope_label}\n{tooltip}"))

    def _broadcast_sync_command(
        self,
        command: str,
        source_widget: Optional[QWidget] = None,
        *,
        context_widget: Optional[QWidget] = None,
        source_label: Optional[str] = None,
        source_kind: str = "sync_input",
        task_preset_key: Optional[str] = None,
        task_preset_title: Optional[str] = None,
        archive_tags: Optional[list[str]] = None,
    ) -> int:
        """将命令广播到支持同步输入的终端。"""
        normalized = (command or "").strip()
        if not normalized:
            return 0

        active_context_widget = context_widget or source_widget or self.work_tabs.currentWidget()
        exclude_widget = source_widget
        if isinstance(source_widget, TerminalSplitWidget):
            exclude_widget = None
        entries = self._sync_target_entries(
            exclude=exclude_widget,
            context_widget=active_context_widget,
        )
        target_names = [title for _widget, title in entries]
        target_metadata = self._sync_target_entry_metadata(entries)
        resolved_target_ids = [
            str(entry.get("target_connection_id", "") or "").strip()
            for entry in target_metadata
            if str(entry.get("target_connection_id", "") or "").strip()
        ]
        delivered = 0
        failed_targets: list[str] = []
        for widget, title in entries:
            try:
                if widget is source_widget and isinstance(widget, TerminalSplitWidget):
                    delivered += widget.execute_broadcast_command_to_peer(normalized)
                else:
                    widget.execute_broadcast_command(normalized)
                    delivered += 1
            except Exception as exc:
                failed_targets.append(title)
                self._logger.warning("同步输入失败 [%s]: %s", type(widget).__name__, exc)

        scope_label = self.tr(self._sync_scope_label(self._sync_input_scope))
        self._record_sync_dispatch(
            source_label=source_label or self.tr("同步输入"),
            scope_label=scope_label,
            scope_key=self._sync_input_scope,
            commands=[normalized],
            target_names=target_names,
            target_connection_ids=resolved_target_ids,
            target_entries_metadata=target_metadata,
            delivery_count=delivered,
            failed_targets=failed_targets,
            source_kind=source_kind,
            origin_batch_id=None,
            retry_mode=None,
            task_preset_key=task_preset_key,
            task_preset_title=task_preset_title,
            archive_tags=archive_tags,
        )
        if delivered:
            self.update_status(self.tr(f"已按{scope_label}发送到 {delivered} 个终端"))
            feedback = self.tr(f"1 条命令 -> {self._format_sync_target_summary(target_names)}")
            if failed_targets:
                feedback = self.tr(f"{feedback} · 失败 {len(failed_targets)}")
            self._set_sync_result_feedback(feedback, target_names=target_names)
        else:
            self.update_status(self.tr(f"{scope_label}范围内没有可同步的终端"))
            if failed_targets:
                self._set_sync_result_feedback(
                    self.tr(f"发送失败 · 失败 {len(failed_targets)}"),
                    target_names=target_names,
                )
            else:
                self._set_sync_result_feedback(self.tr("未找到匹配终端"))
        self._update_sync_input_status()
        return delivered

    def _broadcast_sync_commands(
        self,
        commands: list[str],
        source_widget: Optional[QWidget] = None,
        *,
        context_widget: Optional[QWidget] = None,
        scope_override: Optional[str] = None,
        target_type_filter: Optional[str] = None,
        target_group_filter: Optional[str] = None,
        target_connection_ids: Optional[list[str]] = None,
        source_label: Optional[str] = None,
        source_kind: str = "compose",
        origin_batch_id: Optional[int] = None,
        retry_mode: Optional[str] = None,
        task_preset_key: Optional[str] = None,
        task_preset_title: Optional[str] = None,
        task_template_label: Optional[str] = None,
        target_filter_label: Optional[str] = None,
        target_group_label: Optional[str] = None,
        archive_tags: Optional[list[str]] = None,
    ) -> tuple[int, int]:
        """将多条命令按顺序广播到支持同步输入的终端。"""
        normalized_commands = [command.strip() for command in commands if command.strip()]
        if not normalized_commands:
            return 0, 0

        active_context_widget = (
            self._preferred_sync_context_widget(context_widget)
            or self._preferred_sync_context_widget(source_widget)
            or self._preferred_sync_context_widget()
        )
        exclude_widget = source_widget
        if isinstance(source_widget, TerminalSplitWidget):
            exclude_widget = None
        active_scope = scope_override or self._sync_input_scope
        exact_target_ids = {
            str(connection_id).strip()
            for connection_id in (target_connection_ids or [])
            if isinstance(connection_id, str) and str(connection_id).strip()
        }
        entries = self._sync_target_entries(
            exclude=exclude_widget,
            scope=active_scope,
            context_widget=active_context_widget,
            target_type_filter=target_type_filter,
            target_group_filter=target_group_filter,
            target_connection_ids=exact_target_ids,
        )
        target_names = [title for _widget, title in entries]
        target_metadata = self._sync_target_entry_metadata(entries)
        resolved_target_ids = [
            str(entry.get("target_connection_id", "") or "").strip()
            for entry in target_metadata
            if str(entry.get("target_connection_id", "") or "").strip()
        ]

        total_deliveries = 0
        failed_targets: list[str] = []
        for command in normalized_commands:
            for widget, title in entries:
                try:
                    if widget is source_widget and isinstance(widget, TerminalSplitWidget):
                        total_deliveries += widget.execute_broadcast_command_to_peer(command)
                    else:
                        widget.execute_broadcast_command(command)
                        total_deliveries += 1
                except Exception as exc:
                    if title not in failed_targets:
                        failed_targets.append(title)
                    self._logger.warning("编排发送失败 [%s]: %s", type(widget).__name__, exc)

        scope_label = self.tr(self._sync_scope_label(active_scope))
        scope_display_label = (
            self.tr(f"{scope_label} · {target_filter_label}")
            if target_filter_label
            else scope_label
        )
        target_count = len(entries)
        record = self._record_sync_dispatch(
            source_label=source_label or self.tr("编排发送"),
            scope_label=scope_label,
            scope_key=active_scope,
            commands=normalized_commands,
            target_names=target_names,
            target_connection_ids=resolved_target_ids,
            target_entries_metadata=target_metadata,
            delivery_count=total_deliveries,
            failed_targets=failed_targets,
            source_kind=source_kind,
            origin_batch_id=origin_batch_id,
            retry_mode=retry_mode,
            task_preset_key=task_preset_key,
            task_preset_title=task_preset_title,
            task_template_label=task_template_label,
            target_type_key=target_type_filter,
            target_filter_label=target_filter_label,
            target_group_key=target_group_filter,
            target_group_label=target_group_label,
            archive_tags=archive_tags,
        )
        self._arm_task_result_capture(record, entries)
        if total_deliveries:
            self.update_status(
                self.tr(
                    f"已按{scope_display_label}发送 {len(normalized_commands)} 条命令到 {target_count} 个终端"
                )
            )
            feedback = self.tr(
                f"{len(normalized_commands)} 条命令 -> {self._format_sync_target_summary(target_names)}"
            )
            if target_filter_label:
                feedback = self.tr(f"{feedback} · {target_filter_label}")
            if failed_targets:
                feedback = self.tr(f"{feedback} · 失败 {len(failed_targets)}")
            self._set_sync_result_feedback(feedback, target_names=target_names)
        else:
            self.update_status(self.tr(f"{scope_display_label}范围内没有可同步的终端"))
            if failed_targets:
                self._set_sync_result_feedback(
                    self.tr(f"发送失败 · 失败 {len(failed_targets)}"),
                    target_names=target_names,
                )
            else:
                self._set_sync_result_feedback(self.tr("未找到匹配终端"))
        self._update_sync_input_status()
        return len(normalized_commands), target_count

    def _on_sync_input_submitted(self) -> None:
        """从同步输入栏广播命令。"""
        command = self.sync_input_edit.text().strip()
        if not command:
            return
        delivered = self._broadcast_sync_command(command)
        if delivered:
            self.sync_input_edit.clear()

    def _on_terminal_command_executed(self, source_widget: QWidget, command: str) -> None:
        """当终端执行命令且开启同步输入时，将其广播到其他终端。"""
        if not self._sync_input_enabled:
            return
        self._broadcast_sync_command(command, source_widget=source_widget)

    def _on_open_compose_dialog(self) -> None:
        """打开编排发送对话框。"""
        if self._preferred_sync_context_widget() is None:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前没有可用于编排发送的终端"),
            )
            return

        dialog = ComposeCommandDialog(
            self,
            initial_text=self.sync_input_edit.text().strip(),
            **self._compose_command_library(),
        )
        if dialog.exec() != QDialog.Accepted:
            return

        commands = dialog.commands()
        if not commands:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("请输入至少一条命令"),
            )
            return

        sent_count, target_count = self._broadcast_sync_commands(commands)
        if sent_count and self.sync_input_edit.text().strip():
            self.sync_input_edit.clear()
        if sent_count and target_count:
            self._logger.info(
                "编排发送完成: %s 条命令 -> %s 个终端",
                sent_count,
                target_count,
            )

    def _on_open_quick_inspection(self) -> None:
        """打开快速巡检对话框。"""
        self._on_open_task_preset("quick_inspection")

    def _on_open_task_preset(self, preset_key: str) -> None:
        """打开任务预设对话框。"""
        preset = self._task_preset_definition(preset_key)
        if self._preferred_sync_context_widget() is None:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr(f"当前没有可用于{preset.title}的终端"),
            )
            return

        dialog = ComposeCommandDialog(
            self,
            **self._task_preset_dialog_payload(preset_key),
        )
        if dialog.exec() != QDialog.Accepted:
            return

        commands = dialog.commands()
        if not commands:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr(f"请输入至少一条{preset.title}命令"),
            )
            return

        selected_scope = (
            dialog.selected_target_scope()
            if hasattr(dialog, "selected_target_scope")
            else self._sync_input_scope
        )
        selected_target_type = (
            dialog.selected_target_type()
            if hasattr(dialog, "selected_target_type")
            else self.SYNC_TARGET_TYPE_ALL
        )
        selected_target_group = (
            dialog.selected_target_group()
            if hasattr(dialog, "selected_target_group")
            else self.SYNC_TARGET_GROUP_ALL
        )
        selected_template_label = (
            dialog.selected_template_label() if hasattr(dialog, "selected_template_label") else None
        )
        target_filter_label = None
        if selected_target_type not in (None, "", self.SYNC_TARGET_TYPE_ALL):
            target_filter_label = self.tr(self._target_type_label(selected_target_type))
        target_group_label = None
        if selected_target_group not in (None, "", self.SYNC_TARGET_GROUP_ALL):
            target_group_label = self.tr(self._target_group_label(selected_target_group))

        sent_count, target_count = self._broadcast_sync_commands(
            commands,
            scope_override=selected_scope,
            target_type_filter=selected_target_type,
            target_group_filter=selected_target_group,
            source_label=self.tr(preset.title),
            source_kind="task_preset",
            task_preset_key=preset.key,
            task_preset_title=self.tr(preset.title),
            task_template_label=selected_template_label,
            target_filter_label=target_filter_label,
            target_group_label=target_group_label,
            archive_tags=[
                self.tr("任务预设"),
                self.tr(preset.title),
                *(
                    [self.tr(f"任务模板 / {selected_template_label}")]
                    if selected_template_label
                    else []
                ),
                self.tr(self._sync_scope_label(selected_scope)),
                *([self.tr(f"目标类型 / {target_filter_label}")] if target_filter_label else []),
                *([self.tr(f"目标分组 / {target_group_label}")] if target_group_label else []),
            ],
        )
        if sent_count and target_count:
            self._logger.info(
                "%s发送完成: %s 条命令 -> %s 个终端",
                preset.title,
                sent_count,
                target_count,
            )

    def _on_terminal_snippets_changed(self, snippets: object) -> None:
        """持久化终端快捷命令并同步到全部已打开终端。"""
        if not self._config_manager:
            return
        config = self._config_manager.app_config
        if isinstance(snippets, dict):
            groups = normalize_terminal_snippet_groups(snippets.get("terminal_snippet_groups"))
            favorites = normalize_terminal_favorite_snippets(
                snippets.get("terminal_favorite_snippets"),
                groups,
            )
            config.terminal_snippet_groups = groups
            config.terminal_snippets = flatten_terminal_snippet_groups(groups)
            config.terminal_favorite_snippets = favorites
        elif isinstance(snippets, list):
            config.terminal_snippets = normalize_terminal_snippets(snippets)
            config.terminal_snippet_groups = normalize_terminal_snippet_groups(
                config.terminal_snippets
            )
            config.terminal_favorite_snippets = normalize_terminal_favorite_snippets(
                config.terminal_favorite_snippets,
                config.terminal_snippet_groups,
            )
        else:
            return
        if isinstance(snippets, dict):
            config.terminal_macros = normalize_terminal_macros(snippets.get("terminal_macros"))
        self._config_manager.save_app_config(config)
        self._apply_terminal_preferences()

    def _on_terminal_session_state_changed(self, source_widget: QWidget, payload: object) -> None:
        """持久化会话级终端数据。"""
        if not self._config_manager or not isinstance(payload, dict):
            return
        connection_id = getattr(source_widget, "connection_id", None)
        if (
            not isinstance(connection_id, str)
            or not connection_id
            or connection_id.startswith("__")
        ):
            return
        try:
            updated = self._config_manager.update_connection_session_data(connection_id, payload)
        except ConfigurationError as exc:
            self._logger.warning("保存会话终端数据失败 [%s]: %s", connection_id, exc)
            return
        self._cache_connection_config(updated)

    @staticmethod
    def _ssh_data_from_connection_data(conn_data: Dict[str, Any]) -> Dict[str, Any]:
        """把 SSH/SFTP 配置规整成可创建 SSHConnection 的字典。"""
        allowed = {field.name for field in fields(SSHConfig)}
        ssh_data = {key: value for key, value in conn_data.items() if key in allowed}
        ssh_data["connection_type"] = "ssh"
        return ssh_data

    @staticmethod
    def _sftp_data_from_connection_data(conn_data: Dict[str, Any]) -> Dict[str, Any]:
        """把 SSH/SFTP 配置规整成可创建 SFTPConnection 的字典。"""
        allowed = {field.name for field in fields(SFTPConfig)}
        sftp_data = {key: value for key, value in conn_data.items() if key in allowed}
        sftp_data["connection_type"] = "sftp"
        sftp_data.setdefault("initial_path", ".")
        return sftp_data

    def _terminal_backend(self) -> str:
        """返回当前终端后端配置。"""
        if not self._config_manager:
            return "auto"
        return self._config_manager.app_config.terminal_backend

    def _open_workspace_tab(
        self,
        widget: QWidget,
        title: str,
        connection_id: Optional[str] = None,
    ) -> None:
        """统一添加工作区标签页并聚焦。"""
        if connection_id is not None:
            widget.connection_id = connection_id
        self.work_tabs.addTab(widget, title)
        self.work_tabs.setCurrentWidget(widget)
        self._update_workspace_empty_state()
        self._sync_monitor_connection()
        self._update_sync_input_status()
        self._update_terminal_actions_state()
        if self._config_manager and not self._restoring_workspace:
            self._save_workspace_state()

    def _disconnect_safely(self, connection: BaseConnection) -> None:
        """尽力断开连接，不传播清理阶段异常。"""
        try:
            connection.disconnect()
        except Exception:
            pass

    def _create_classic_terminal_widget(
        self,
        connection: BaseConnection,
        initial_output: Optional[str] = None,
        startup_command: Optional[str] = None,
    ) -> TerminalWidget:
        """创建经典终端并应用统一设置。"""
        widget = self._bind_terminal_widget(TerminalWidget(self, app_config=self._app_config()))
        if self._config_manager:
            widget.apply_preferences(self._config_manager.app_config)
        widget.set_connection(connection)
        if initial_output:
            widget.append_output(initial_output)
        if startup_command:
            widget.send_command(startup_command)
        return widget

    @staticmethod
    def _apply_connection_session_state(
        widget: QWidget, conn_data: Optional[Dict[str, Any]]
    ) -> None:
        """将连接记录中的会话级终端数据应用到终端组件。"""
        if not conn_data or not hasattr(widget, "apply_session_state"):
            return
        widget.apply_session_state(
            {
                "session_snippet_groups": conn_data.get("session_snippet_groups"),
                "session_favorite_snippets": conn_data.get("session_favorite_snippets"),
                "session_macros": conn_data.get("session_macros"),
            }
        )

    def _on_open_docker_container_terminal(
        self, conn_data: Dict[str, Any], container: Dict[str, Any]
    ) -> None:
        """打开 Docker 容器交互终端。"""
        container_id = container.get("ID") or container.get("Names")
        if not container_id:
            QMessageBox.warning(self, self.tr("错误"), self.tr("容器 ID 无效"))
            return

        conn_id = conn_data.get("id", "docker")
        tab_id = f"__docker_terminal__:{conn_id}:{container_id}"
        if self._focus_existing_tab(tab_id):
            return

        ssh_data = self._ssh_data_from_connection_data(conn_data)
        try:
            connection = ConnectionFactory.create_from_dict(ssh_data)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("终端创建失败"), str(exc))
            return

        title = self.tr(f"容器终端: {container.get('Names') or container_id}")
        if should_use_qtermwidget(self._terminal_backend(), connection):
            try:
                widget = QTermDockerExecTerminalWidget(
                    str(container_id),
                    self,
                    app_config=self._app_config(),
                )
                self._bind_terminal_widget(widget)
                widget.set_connection(connection)
                self._open_workspace_tab(widget, title, tab_id)
                return
            except Exception as exc:
                self._logger.warning("Docker qtermwidget 终端初始化失败，回退经典终端: %s", exc)

        try:
            connection.connect()
            widget = self._create_classic_terminal_widget(
                connection,
                initial_output=self.tr(f"正在进入容器: {container_id}\n"),
                startup_command=build_docker_exec_shell_command(str(container_id)),
            )
            self._open_workspace_tab(widget, title, tab_id)
        except Exception as exc:
            self._disconnect_safely(connection)
            QMessageBox.critical(self, self.tr("容器终端失败"), str(exc))

    def _on_connection_activated(self, conn_id: str) -> None:
        """
        连接被激活

        Args:
            conn_id: 连接 ID
        """
        self._logger.info(f"激活连接: {conn_id}")
        self._open_connection(conn_id=conn_id)

    def _on_connection_batch_open_requested(self, conn_ids: list[str]) -> None:
        """处理连接树发起的批量打开请求。"""
        requested_count, opened_count = self._open_connection_batch(conn_ids)
        if requested_count:
            self.update_status(
                self.tr(
                    f"批量打开完成: 请求 {requested_count} 个连接，新增 {opened_count} 个工作区"
                )
            )

    def _on_connection_file_browser_requested(self, conn_id: str) -> None:
        """为连接打开文件浏览器。"""
        self._open_file_browser_for_connection(conn_id)

    def _find_terminal_widget_for_connection(self, conn_id: str) -> Optional[QWidget]:
        """按保存连接 ID 查找已打开的终端标签页。"""
        candidate_ids = {conn_id, self._temporary_terminal_connection_id(conn_id)}
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            tab_connection_id = getattr(widget, "connection_id", None)
            if tab_connection_id not in candidate_ids:
                continue
            if hasattr(widget, "execute_broadcast_command") or hasattr(widget, "send_command"):
                return widget
        return None

    @staticmethod
    def _directory_change_command(remote_path: str) -> str:
        """构造切换目录命令。"""
        normalized = str(remote_path or "").strip() or "/"
        return f"cd -- {shlex.quote(normalized)}"

    @staticmethod
    def _send_command_to_terminal_widget(widget: QWidget, command: str) -> None:
        """向终端组件发送命令。"""
        if hasattr(widget, "execute_broadcast_command"):
            widget.execute_broadcast_command(command)
            return
        if hasattr(widget, "send_command"):
            widget.send_command(command)
            return
        raise RuntimeError("目标工作区不支持终端命令发送")

    def _open_temporary_ssh_terminal_for_connection(
        self,
        conn_id: str,
        conn_data: Dict[str, Any],
        *,
        show_errors: bool = True,
    ) -> Optional[QWidget]:
        """为 SFTP 连接派生并打开临时 SSH 终端。"""
        tab_id = self._temporary_terminal_connection_id(conn_id)
        if self._focus_existing_tab(tab_id):
            return self.work_tabs.currentWidget()

        connection = None
        try:
            connection = ConnectionFactory.create_from_dict(
                self._ssh_data_from_connection_data(conn_data)
            )
            self._register_connection_status_handler(tab_id, connection)
            connection.connect()
            widget = self._create_connection_widget(connection)
            if widget is None:
                raise RuntimeError(self.tr("当前连接类型没有可用终端组件"))
            self._apply_connection_session_state(widget, conn_data)
        except Exception as exc:
            if connection is not None:
                self._disconnect_safely(connection)
                self._unregister_connection_status_handler(tab_id, connection)
            self._logger.error("打开临时 SSH 终端失败 [%s]: %s", conn_id, exc)
            if show_errors:
                QMessageBox.critical(self, self.tr("终端打开失败"), str(exc))
            return None

        if self._config_manager:
            try:
                updated_conn_data = self._config_manager.mark_connection_used(conn_id)
                self._cache_connection_config(updated_conn_data)
                self.connection_tree.update_connection_item(conn_id, updated_conn_data)
                conn_data = updated_conn_data
            except ConfigurationError as exc:
                self._logger.warning("记录最近连接失败 [%s]: %s", conn_id, exc)

        title = self.tr(f"终端: {conn_data.get('name', '未命名')}")
        self._connections[tab_id] = connection
        self._open_workspace_tab(widget, title, tab_id)
        self._refresh_session_shortcuts()
        self.update_connection_count()
        return widget

    def _open_terminal_for_connection_id(
        self,
        conn_id: str,
        *,
        show_errors: bool = True,
    ) -> Optional[QWidget]:
        """按连接 ID 打开或复用终端工作区。"""
        terminal_widget = self._find_terminal_widget_for_connection(conn_id)
        if terminal_widget is not None:
            self.work_tabs.setCurrentWidget(terminal_widget)
            return terminal_widget

        conn_data = self._find_connection_config(conn_id)
        if conn_data is None:
            if show_errors:
                QMessageBox.warning(self, self.tr("错误"), self.tr("未找到连接配置"))
            return None

        conn_type = str(conn_data.get("connection_type", "")).strip().lower()
        if conn_type == "ssh":
            self._open_connection(conn_id=conn_id, show_errors=show_errors)
            return self._find_terminal_widget_for_connection(conn_id)
        if conn_type == "sftp":
            return self._open_temporary_ssh_terminal_for_connection(
                conn_id,
                conn_data,
                show_errors=show_errors,
            )
        if show_errors:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前连接类型不支持终端联动"),
            )
        return None

    def _on_file_browser_terminal_requested(self, source_widget: QWidget, remote_path: str) -> None:
        """处理文件浏览器发起的“在终端打开目录”请求。"""
        conn_id = self._workspace_saved_connection_id(getattr(source_widget, "connection_id", None))
        if not conn_id:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前文件页未关联可用的终端连接"),
            )
            return

        terminal_widget = self._open_terminal_for_connection_id(conn_id, show_errors=True)
        if terminal_widget is None:
            return

        try:
            self._send_command_to_terminal_widget(
                terminal_widget,
                self._directory_change_command(remote_path),
            )
        except Exception as exc:
            self._logger.error("文件浏览器终端联动失败 [%s]: %s", conn_id, exc)
            QMessageBox.critical(self, self.tr("终端联动失败"), str(exc))
            return

        self.work_tabs.setCurrentWidget(terminal_widget)
        self.update_status(self.tr(f"已在终端打开目录: {remote_path}"))

    def _on_connection_favorite_toggled(self, conn_id: str, favorite: bool) -> None:
        """同步收藏状态到配置层。"""
        if not self._config_manager:
            return
        try:
            updated = self._config_manager.set_connection_favorite(conn_id, favorite)
        except ConfigurationError as exc:
            QMessageBox.warning(self, self.tr("收藏失败"), str(exc))
            return
        self._cache_connection_config(updated)
        self.connection_tree.update_connection_item(conn_id, updated)
        self._refresh_session_shortcuts()
        self._update_workspace_header()

    def _find_connection_config(self, conn_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 查找已保存的连接配置。"""
        if conn_id in self._connection_configs:
            return dict(self._connection_configs[conn_id])
        if not self._config_manager:
            return None
        self._load_connection_configs()
        cached = self._connection_configs.get(conn_id)
        return dict(cached) if cached else None

    def _focus_existing_tab(self, conn_id: str) -> bool:
        """如果连接已打开则直接聚焦现有标签页。"""
        for index in range(self.work_tabs.count()):
            widget = self.work_tabs.widget(index)
            if getattr(widget, "connection_id", None) == conn_id:
                self.work_tabs.setCurrentIndex(index)
                return True
        return False

    @staticmethod
    def _docker_container_id_from_widget(widget: QWidget) -> Optional[str]:
        """从 Docker 容器终端标签页中解析容器 ID。"""
        tab_connection_id = getattr(widget, "connection_id", None)
        if not isinstance(tab_connection_id, str):
            return None
        prefix = "__docker_terminal__:"
        if not tab_connection_id.startswith(prefix):
            return None
        parts = tab_connection_id.split(":", 2)
        if len(parts) < 3:
            return None
        return parts[2] or None

    def _create_split_peer_widget(self, current_widget: QWidget) -> QWidget:
        """基于当前终端创建分屏副终端。"""
        if isinstance(current_widget, QTermLocalTerminalWidget):
            return QTermLocalTerminalWidget(self, app_config=self._app_config())

        connection = getattr(current_widget, "connection", None)
        if connection is None:
            raise RuntimeError(self.tr("当前标签页没有可复用的终端连接"))

        connection_type = getattr(getattr(connection, "config", None), "connection_type", None)
        if connection_type not in {
            ConnectionType.SSH,
            ConnectionType.SERIAL,
            ConnectionType.TCP,
            ConnectionType.UDP,
        }:
            raise RuntimeError(self.tr("当前终端类型暂不支持分屏"))

        peer_connection = ConnectionFactory.create_from_dict(connection.config.to_dict())
        try:
            peer_connection.connect()
            docker_container_id = self._docker_container_id_from_widget(current_widget)
            if docker_container_id:
                if isinstance(current_widget, QTermDockerExecTerminalWidget):
                    peer_widget = QTermDockerExecTerminalWidget(
                        docker_container_id,
                        self,
                        app_config=self._app_config(),
                        shell=getattr(current_widget, "_shell", "sh"),
                    )
                    peer_widget.set_connection(peer_connection)
                else:
                    peer_widget = self._create_classic_terminal_widget(
                        peer_connection,
                        initial_output=self.tr(f"正在进入容器: {docker_container_id}\n"),
                        startup_command=build_docker_exec_shell_command(
                            docker_container_id,
                            shell=getattr(current_widget, "_shell", "sh"),
                        ),
                    )
            else:
                peer_widget = self._create_connection_widget(peer_connection)
                if peer_widget is None:
                    raise RuntimeError(self.tr("当前连接无法创建分屏终端"))
            if hasattr(current_widget, "export_session_state") and hasattr(
                peer_widget, "apply_session_state"
            ):
                peer_widget.apply_session_state(current_widget.export_session_state())
            self._unbind_terminal_widget(peer_widget)
            return peer_widget
        except Exception:
            self._disconnect_safely(peer_connection)
            raise

    def _on_split_terminal(self) -> None:
        """将当前终端标签转换为双终端分屏。"""
        current_index = self.work_tabs.currentIndex()
        current_widget = self.work_tabs.currentWidget()
        if current_index < 0 or current_widget is None:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前没有可分屏的终端"))
            return
        if isinstance(current_widget, TerminalSplitWidget):
            QMessageBox.information(self, self.tr("提示"), self.tr("当前标签已经是双终端分屏"))
            return
        if not self._can_split_terminal_widget(current_widget):
            QMessageBox.information(self, self.tr("提示"), self.tr("当前标签页不支持终端分屏"))
            return

        try:
            peer_widget = self._create_split_peer_widget(current_widget)
            split_widget = TerminalSplitWidget(current_widget, peer_widget, self)
            self._unbind_terminal_widget(current_widget)
            self._unbind_terminal_widget(peer_widget)
            self._bind_terminal_widget(split_widget)
        except Exception as exc:
            self._logger.error("创建终端分屏失败: %s", exc)
            QMessageBox.critical(self, self.tr("终端分屏失败"), str(exc))
            return

        if self._config_manager:
            split_widget.apply_preferences(self._config_manager.app_config)

        title = self.work_tabs.tabText(current_index)
        connection_id = getattr(current_widget, "connection_id", None)
        if connection_id is not None:
            split_widget.connection_id = connection_id

        self.work_tabs.removeTab(current_index)
        self.work_tabs.insertTab(current_index, split_widget, title)
        self.work_tabs.setCurrentIndex(current_index)
        self.update_status(self.tr("已创建双终端分屏"))
        self._sync_monitor_connection()
        self._update_sync_input_status()
        self._update_terminal_actions_state()
        if self._config_manager and not self._restoring_workspace:
            self._save_workspace_state()

    def _open_connection(
        self,
        conn_id: Optional[str] = None,
        config: Optional[object] = None,
        persist: bool = True,
        show_errors: bool = True,
    ) -> None:
        """统一处理保存连接和快速连接的打开流程。"""
        conn_data: Optional[Dict[str, Any]] = None
        if config is None and conn_id:
            conn_data = self._find_connection_config(conn_id)
        if conn_id and self._focus_existing_tab(conn_id):
            self._update_connection_surface_status(conn_data, reused=True)
            return

        if config is None:
            if not self._config_manager:
                if show_errors:
                    QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
                return
            if conn_data is None:
                if show_errors:
                    QMessageBox.warning(self, self.tr("错误"), self.tr("未找到连接配置"))
                return
            connection = ConnectionFactory.create_from_dict(conn_data)
        else:
            connection = ConnectionFactory.create(config)
            conn_id = connection.id
            conn_data = connection.config.to_dict()

        # 绑定状态变化到 UI（必须在 connect 之前注册，才能捕获 CONNECTING/RECONNECTING）。
        if conn_id:
            self._register_connection_status_handler(conn_id, connection)

        try:
            connection.connect()
        except Exception as e:
            self._logger.error(f"连接失败 [{conn_id}]: {e}")
            if conn_id:
                self._unregister_connection_status_handler(conn_id, connection)
            if show_errors:
                message = str(e)
                if getattr(connection.config, "connection_type", None) == ConnectionType.VNC and (
                    "DES" in message or "pycryptodome" in message or "pyDes" in message
                ):
                    message = self.tr(
                        "VNC 连接失败。\n\n{error}\n\nLinux 下请安装 VNC 认证依赖，例如:\n"
                        "pip install pycryptodome\n"
                        "或安装 Neko_Shell[vnc]"
                    ).format(error=message)
                QMessageBox.critical(self, self.tr("连接失败"), message)
            return

        widget = self._create_connection_widget(connection)
        if widget is None:
            self._disconnect_safely(connection)
            if conn_id:
                self._unregister_connection_status_handler(conn_id, connection)
            if show_errors:
                QMessageBox.warning(
                    self, self.tr("错误"), self.tr("当前连接类型没有可用工作区组件")
                )
            return

        self._apply_connection_session_state(widget, conn_data)
        self._connections[conn_id] = connection
        if persist and self._config_manager and conn_id:
            try:
                updated_conn_data = self._config_manager.mark_connection_used(conn_id)
                self._cache_connection_config(updated_conn_data)
                self.connection_tree.update_connection_item(conn_id, updated_conn_data)
                conn_data = updated_conn_data
            except ConfigurationError as exc:
                self._logger.warning("记录最近连接失败 [%s]: %s", conn_id, exc)
        tab_title = conn_data.get("name", connection.config.name)
        self._open_workspace_tab(widget, tab_title, conn_id)
        if persist:
            self.connection_tree.update_connection_status(conn_id, connection.status)
            self._refresh_session_shortcuts()
        self.update_connection_count()
        self._update_connection_surface_status(conn_data)

    def _open_file_browser_for_connection(self, conn_id: str, show_errors: bool = True) -> None:
        """为 SSH/SFTP/FTP 连接打开文件浏览器。"""
        conn_data = self._find_connection_config(conn_id)
        if conn_data is None:
            if show_errors:
                QMessageBox.warning(self, self.tr("错误"), self.tr("未找到连接配置"))
            return

        conn_type = str(conn_data.get("connection_type", "")).lower()
        if conn_type in {"sftp", "ftp"}:
            self._open_connection(conn_id=conn_id, show_errors=show_errors)
            return
        if conn_type != "ssh":
            if show_errors:
                QMessageBox.information(
                    self, self.tr("提示"), self.tr("当前连接类型不支持文件浏览器")
                )
            return

        tab_id = f"__file_browser__:{conn_id}"
        if self._focus_existing_tab(tab_id):
            self._update_connection_surface_status(
                conn_data,
                surface="file_browser",
                reused=True,
            )
            return

        connection: Optional[BaseConnection] = None
        try:
            connection = ConnectionFactory.create_from_dict(
                self._sftp_data_from_connection_data(conn_data)
            )
            self._register_connection_status_handler(tab_id, connection)
            connection.connect()
        except Exception as exc:
            self._logger.error("打开 SSH 文件浏览器失败 [%s]: %s", conn_id, exc)
            if connection is not None:
                self._unregister_connection_status_handler(tab_id, connection)
            if show_errors:
                QMessageBox.critical(self, self.tr("文件浏览器打开失败"), str(exc))
            return

        widget = self._bind_file_browser_widget(FileBrowserWidget(self))
        try:
            widget.set_connection(connection)
        except Exception as exc:
            self._disconnect_safely(connection)
            self._unregister_connection_status_handler(tab_id, connection)
            self._logger.error("初始化 SSH 文件浏览器失败 [%s]: %s", conn_id, exc)
            if show_errors:
                QMessageBox.critical(self, self.tr("文件浏览器打开失败"), str(exc))
            return
        title = self.tr(f"文件: {conn_data.get('name', '未命名')}")
        self._connections[tab_id] = connection
        self._open_workspace_tab(widget, title, tab_id)
        self.update_connection_count()
        self._update_connection_surface_status(conn_data, surface="file_browser")

    def _create_connection_widget(self, connection: BaseConnection) -> Optional[QWidget]:
        """根据连接类型创建工作区组件。"""
        if connection.config.connection_type in {
            ConnectionType.FTP,
            ConnectionType.SFTP,
        }:
            widget = self._bind_file_browser_widget(FileBrowserWidget(self))
            widget.set_connection(connection)
            return widget

        if connection.config.connection_type in {
            ConnectionType.SSH,
            ConnectionType.SERIAL,
            ConnectionType.TCP,
            ConnectionType.UDP,
        }:
            if should_use_qtermwidget(self._terminal_backend(), connection):
                try:
                    if connection.config.connection_type == ConnectionType.SSH:
                        widget = QTermTerminalWidget(self, app_config=self._app_config())
                    else:
                        widget = QTermExternalTerminalWidget(self, app_config=self._app_config())
                    self._bind_terminal_widget(widget)
                    widget.set_connection(connection)
                    return widget
                except Exception as exc:
                    self._logger.warning("QTermWidget 终端初始化失败，回退经典终端: %s", exc)

            return self._create_classic_terminal_widget(
                connection,
                initial_output=f"已连接到 {connection.config.name}\n",
            )

        if connection.config.connection_type == ConnectionType.VNC:
            widget = VNCWidget(self)
            widget.set_connection(connection)
            return widget

        return None

    def _current_tab_connection(self) -> Optional[BaseConnection]:
        """获取当前标签页绑定的连接。"""
        widget = self.work_tabs.currentWidget()
        if widget is None:
            return None
        return getattr(widget, "connection", None)

    def _sync_monitor_connection(self) -> None:
        """同步系统监控面板绑定的连接。"""
        connection = self._current_tab_connection()
        if connection and hasattr(connection, "get_monitor_data"):
            self.system_monitor.set_connection(connection)
            self._refresh_monitor()
            return
        self.system_monitor.set_connection(None)
        self.system_monitor.clear_data()

    def _refresh_monitor(self) -> None:
        """刷新当前连接的系统监控数据。"""
        connection = self._current_tab_connection()
        if connection is None or not hasattr(connection, "get_monitor_data"):
            self.system_monitor.clear_data()
            return
        if not connection.is_connected():
            self.system_monitor.clear_data()
            return

        try:
            data = connection.get_monitor_data()
            self.system_monitor.update_data(data)
        except Exception as exc:
            self._logger.debug("刷新系统监控失败 [%s]: %s", connection.id, exc)

    def _on_current_tab_changed(self, _index: int) -> None:
        """当前标签页切换。"""
        self._update_workspace_empty_state()
        self._sync_monitor_connection()
        self._update_sync_input_status()
        self._update_terminal_actions_state()

    def _on_connection_edited(self, conn_id: str) -> None:
        """编辑已有连接配置。"""
        conn_data = self._find_connection_config(conn_id)
        if conn_data is None:
            QMessageBox.warning(self, self.tr("错误"), self.tr("未找到连接配置"))
            return

        config = ConnectionFactory.create_from_dict(conn_data).config
        dialog = ConnectionDialog(parent=self)
        dialog.setWindowTitle(self.tr("编辑连接"))
        dialog.set_open_after_save_enabled(False)
        if self._config_manager:
            dialog.set_config_manager(self._config_manager)
        dialog.set_config(config)
        if not dialog.exec():
            return

        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        try:
            updated = self._config_manager.update_connection(conn_id, dialog.get_config())
        except ConfigurationError as exc:
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))
            return
        self._cache_connection_config(updated)
        self.connection_tree.update_connection_item(conn_id, updated)
        self._refresh_management_widgets()
        self._refresh_session_shortcuts()
        self._refresh_connection_related_tab_titles(conn_id, updated)
        visible_in_tree = self.connection_tree.focus_connection(conn_id)
        self._update_connection_saved_status(
            updated,
            edited=True,
            visible_in_tree=visible_in_tree,
        )

    def _on_connection_deleted(self, conn_id: str) -> None:
        """
        连接被删除

        Args:
            conn_id: 连接 ID
        """
        self._logger.info(f"删除连接: {conn_id}")

        if self._config_manager:
            self._config_manager.remove_connection(conn_id)
            self._remove_connection_config(conn_id)
            self._refresh_management_widgets()
            self._refresh_session_shortcuts()
        self._close_connection_by_id(conn_id)

    def _close_connection_by_id(self, conn_id: str) -> None:
        """关闭指定连接及其标签页。"""
        for index in range(self.work_tabs.count() - 1, -1, -1):
            widget = self.work_tabs.widget(index)
            if getattr(widget, "connection_id", None) == conn_id:
                self._on_tab_close(index)

    def _on_tab_close(self, index: int) -> None:
        """
        关闭标签页

        Args:
            index: 标签页索引
        """
        widget = self.work_tabs.widget(index)
        if widget:
            tab_connection_id = getattr(widget, "connection_id", None)
            is_temporary_tab = isinstance(tab_connection_id, str) and tab_connection_id.startswith(
                "__"
            )
            if isinstance(widget, TerminalSplitWidget):
                primary_connection = getattr(widget.primary_terminal, "connection", None)
                if primary_connection and tab_connection_id:
                    self._unregister_connection_status_handler(
                        str(tab_connection_id), primary_connection
                    )
                try:
                    widget.close()
                except Exception as exc:
                    self._logger.warning("关闭分屏终端失败: %s", exc)
                if primary_connection:
                    primary_connection_id = getattr(primary_connection, "id", None)
                    primary_connection_status = getattr(
                        primary_connection,
                        "status",
                        ConnectionStatus.DISCONNECTED,
                    )
                    if not is_temporary_tab:
                        if primary_connection_id:
                            self._connections.pop(primary_connection_id, None)
                            self.connection_tree.update_connection_status(
                                str(primary_connection_id),
                                primary_connection_status,
                            )
                    elif tab_connection_id:
                        self._connections.pop(tab_connection_id, None)
            else:
                connection = getattr(widget, "connection", None)
                if connection:
                    connection_id = getattr(connection, "id", None)
                    connection_status = getattr(
                        connection,
                        "status",
                        ConnectionStatus.DISCONNECTED,
                    )
                    if tab_connection_id:
                        self._unregister_connection_status_handler(
                            str(tab_connection_id), connection
                        )
                    try:
                        disconnect = getattr(connection, "disconnect", None)
                        if callable(disconnect):
                            disconnect()
                    except Exception as e:
                        self._logger.warning(
                            "关闭连接失败 [%s]: %s",
                            connection_id or tab_connection_id or "unknown",
                            e,
                        )
                    if not is_temporary_tab:
                        if connection_id:
                            self._connections.pop(connection_id, None)
                            self.connection_tree.update_connection_status(
                                str(connection_id), connection_status
                            )
                    elif tab_connection_id:
                        self._connections.pop(tab_connection_id, None)
            self.work_tabs.removeTab(index)
            widget.deleteLater()
            self._update_workspace_empty_state()
            self.update_connection_count()
            self._sync_monitor_connection()
            self._update_sync_input_status()
            self._update_terminal_actions_state()
            if self._config_manager and not self._restoring_workspace:
                self._save_workspace_state()

    def update_status(self, message: str) -> None:
        """
        更新状态栏消息

        Args:
            message: 状态消息
        """
        self.status_label.setText(message)

    def update_connection_count(self) -> None:
        """更新连接计数"""
        count = len(self._connections)
        self.connection_count_label.setText(self.tr(f"连接: {count}"))
        self._update_workspace_empty_summary()

    def closeEvent(self, event) -> None:
        """窗口关闭事件"""
        self._save_workspace_state()
        # 关闭所有连接
        for conn in self._connections.values():
            try:
                conn.disconnect()
            except Exception as e:
                self._logger.error(f"关闭连接失败: {e}")

        event.accept()
