#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接树组件

显示和管理连接列表。
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QMenu,
    QMessageBox,
    QInputDialog,
    QDialog,
    QLineEdit,
    QComboBox,
    QLabel,
    QGridLayout,
    QFrame,
    QToolButton,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction

from typing import Optional, Dict, Any, List

from neko_shell.core.connection import ConnectionType, ConnectionStatus
from neko_shell.ui.icons import connection_type_icon, icon, status_brush, status_icon
from neko_shell.utils.config import ConfigManager
from neko_shell.utils import get_logger


class ConnectionTreeWidget(QWidget):
    """
    连接树组件

    显示所有连接的树形列表，支持：
    - 分组显示
    - 右键菜单
    - 拖拽排序
    - 连接状态图标

    Signals:
        connection_created: 新连接配置已创建
        connection_activated: 连接被双击激活
        connection_batch_open_requested: 请求批量打开连接
        connection_file_browser_requested: 请求打开文件浏览器
        connection_scope_workspace_requested: 请求打开当前视图范围工作台
        connection_scope_workspace_template_requested: 请求将当前视图范围保存为工作区模板
        connection_scope_task_preset_requested: 请求对当前视图范围执行任务预设
        connection_deleted: 连接被删除
        connection_edited: 连接被编辑
        connection_favorite_toggled: 连接收藏状态切换
    """

    # 信号
    connection_created = Signal(object)  # BaseConnectionConfig
    connection_activated = Signal(str)  # connection_id
    connection_batch_open_requested = Signal(list)  # list[str]
    connection_file_browser_requested = Signal(str)  # connection_id
    connection_scope_workspace_requested = Signal(object)  # dict[str, object]
    connection_scope_workspace_template_requested = Signal(object)  # dict[str, object]
    connection_scope_task_preset_requested = Signal(str, object)  # preset_key, dict[str, object]
    connection_deleted = Signal(str)  # connection_id
    connection_edited = Signal(str)  # connection_id
    connection_favorite_toggled = Signal(str, bool)  # connection_id, favorite

    # 树列索引
    COL_NAME = 0
    COL_TYPE = 1
    COL_STATUS = 2
    ROLE_CONNECTION_ID = Qt.UserRole
    ROLE_CONNECTION_DATA = Qt.UserRole + 1
    DEFAULT_GROUP_NAME = "默认分组"
    DEFAULT_ENVIRONMENT_NAME = "未分类环境"
    DEFAULT_PROJECT_NAME = "未分类项目"
    DEFAULT_BUSINESS_DOMAIN_NAME = "未分类业务域"
    VIEW_GROUP = "group"
    VIEW_ENVIRONMENT = "environment"
    VIEW_PROJECT = "project"
    VIEW_BUSINESS_DOMAIN = "business_domain"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._logger = get_logger("ConnectionTreeWidget")
        self._connection_items: Dict[str, QTreeWidgetItem] = {}
        self._config_manager: Optional[ConfigManager] = None
        self._filters_expanded = False

        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self) -> None:
        """设置 UI"""
        self.setObjectName("connectionTreePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header_card = QFrame(self)
        header_card.setObjectName("connectionHeaderCard")
        header_card_layout = QVBoxLayout(header_card)
        header_card_layout.setContentsMargins(12, 12, 12, 12)
        header_card_layout.setSpacing(6)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title_label = QLabel(self.tr("连接"), self)
        title_label.setObjectName("panelTitle")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        self.summary_label = QLabel(self.tr("0 个连接"), self)
        self.summary_label.setObjectName("summaryBadge")
        header_layout.addWidget(self.summary_label)
        header_card_layout.addLayout(header_layout)
        self.selection_summary_label = QLabel(self.tr("未选择连接 · 当前按分组查看"), self)
        self.selection_summary_label.setObjectName("panelMeta")
        self.selection_summary_label.setWordWrap(True)
        header_card_layout.addWidget(self.selection_summary_label)
        layout.addWidget(header_card)

        self.action_card = QFrame(self)
        self.action_card.setObjectName("connectionActionCard")
        action_card_layout = QVBoxLayout(self.action_card)
        action_card_layout.setContentsMargins(12, 12, 12, 12)
        action_card_layout.setSpacing(8)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)

        self.add_btn = QPushButton(self.tr("新建"), self.action_card)
        self.add_btn.setProperty("secondary", True)
        self.add_btn.setIcon(icon("new_connection"))
        self.add_btn.setMenu(self._create_add_menu())
        action_row.addWidget(self.add_btn)

        self.open_btn = QPushButton(self.tr("打开"), self.action_card)
        self.open_btn.setProperty("secondary", True)
        self.open_btn.setIcon(icon("quick_connect"))
        self.open_btn.setEnabled(False)
        action_row.addWidget(self.open_btn)

        self.edit_btn = QPushButton(self.tr("编辑"), self.action_card)
        self.edit_btn.setProperty("secondary", True)
        self.edit_btn.setIcon(icon("edit"))
        self.edit_btn.setEnabled(False)
        action_row.addWidget(self.edit_btn)

        self.delete_btn = QPushButton(self.tr("删除"), self.action_card)
        self.delete_btn.setProperty("secondary", True)
        self.delete_btn.setIcon(icon("delete"))
        self.delete_btn.setEnabled(False)
        action_row.addWidget(self.delete_btn)
        action_card_layout.addLayout(action_row)

        self.quick_hint_label = QLabel(
            self.tr("双击连接立即打开，右键可进入文件浏览器或工作区操作"),
            self,
        )
        self.quick_hint_label.setObjectName("panelMeta")
        self.quick_hint_label.setWordWrap(True)
        action_card_layout.addWidget(self.quick_hint_label)
        self.action_card.hide()

        search_card = QFrame(self)
        search_card.setObjectName("connectionSearchCard")
        search_card_layout = QVBoxLayout(search_card)
        search_card_layout.setContentsMargins(12, 12, 12, 12)
        search_card_layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(6)
        self.search_edit = QLineEdit(self)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(self.tr("搜索名称、主机、标签或描述"))
        search_row.addWidget(self.search_edit, 1)

        self.filter_toggle_btn = QToolButton(self)
        self.filter_toggle_btn.setObjectName("filterToggleButton")
        self.filter_toggle_btn.setProperty("secondary", True)
        self.filter_toggle_btn.setCheckable(True)
        self.filter_toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        search_row.addWidget(self.filter_toggle_btn)

        self.clear_filters_btn = QPushButton(self.tr("清空"))
        self.clear_filters_btn.setProperty("secondary", True)
        self.clear_filters_btn.clicked.connect(self._clear_filters)
        search_row.addWidget(self.clear_filters_btn)
        search_card_layout.addLayout(search_row)

        self.type_filter_combo = QComboBox(self)
        self.type_filter_combo.addItem(self.tr("全部类型"), "__all__")
        for label, value in (
            ("SSH", "ssh"),
            ("SFTP", "sftp"),
            ("FTP", "ftp"),
            ("SERIAL", "serial"),
            ("TCP", "tcp"),
            ("UDP", "udp"),
            ("VNC", "vnc"),
        ):
            self.type_filter_combo.addItem(label, value)

        self.view_mode_combo = QComboBox(self)
        self.view_mode_combo.addItem(self.tr("按分组"), self.VIEW_GROUP)
        self.view_mode_combo.addItem(self.tr("按环境"), self.VIEW_ENVIRONMENT)
        self.view_mode_combo.addItem(self.tr("按项目"), self.VIEW_PROJECT)
        self.view_mode_combo.addItem(self.tr("按业务域"), self.VIEW_BUSINESS_DOMAIN)

        self.favorite_filter_combo = QComboBox(self)
        self.favorite_filter_combo.addItem(self.tr("全部连接"), "__all__")
        self.favorite_filter_combo.addItem(self.tr("仅收藏"), "__favorite_only__")
        self.favorite_filter_combo.addItem(self.tr("未收藏"), "__non_favorite_only__")

        self.group_filter_combo = QComboBox(self)
        self.group_filter_combo.addItem(self.tr("全部分组"), "__all__")
        filter_grid = QGridLayout()
        filter_grid.setContentsMargins(0, 0, 0, 0)
        filter_grid.setHorizontalSpacing(6)
        filter_grid.setVerticalSpacing(6)
        filter_grid.addWidget(self.view_mode_combo, 0, 0)
        filter_grid.addWidget(self.type_filter_combo, 0, 1)
        filter_grid.addWidget(self.favorite_filter_combo, 1, 0)
        filter_grid.addWidget(self.group_filter_combo, 1, 1)
        self.filter_panel = QWidget(self)
        self.filter_panel.setObjectName("connectionFilterPanel")
        self.filter_panel.setLayout(filter_grid)
        search_card_layout.addWidget(self.filter_panel)

        self.filter_summary_label = QLabel(self.tr("未启用高级筛选"), self)
        self.filter_summary_label.setObjectName("panelMeta")
        self.filter_summary_label.setWordWrap(True)
        search_card_layout.addWidget(self.filter_summary_label)
        layout.addWidget(search_card)

        # 连接树
        self.tree = QTreeWidget()
        self.tree.setObjectName("connectionTreeView")
        self.tree.setHeaderLabels([self.tr("名称"), self.tr("类型"), self.tr("状态")])
        self.tree.setRootIsDecorated(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)

        # 设置列宽
        self.tree.setColumnWidth(self.COL_NAME, 150)
        self.tree.setColumnWidth(self.COL_TYPE, 60)
        self.tree.setColumnWidth(self.COL_STATUS, 60)

        layout.addWidget(self.tree)
        self._set_filter_panel_expanded(False)
        self._refresh_summary_label()

    def set_config_manager(self, manager: Optional[ConfigManager]) -> None:
        """设置配置管理器，供连接对话框读取模板。"""
        self._config_manager = manager

    def _create_add_menu(self) -> QMenu:
        """创建添加菜单"""
        menu = QMenu(self)

        connections = [
            (self.tr("SSH 连接"), ConnectionType.SSH),
            (self.tr("SFTP 连接"), ConnectionType.SFTP),
            (self.tr("FTP 连接"), ConnectionType.FTP),
            (self.tr("串口连接"), ConnectionType.SERIAL),
            (self.tr("TCP 连接"), ConnectionType.TCP),
            (self.tr("UDP 连接"), ConnectionType.UDP),
            (self.tr("VNC 连接"), ConnectionType.VNC),
        ]

        for text, conn_type in connections:
            action = QAction(text, self)
            action.setIcon(connection_type_icon(conn_type.value))
            action.setData(conn_type)
            action.triggered.connect(lambda checked, t=conn_type: self._on_add_connection(t))
            menu.addAction(action)

        return menu

    def _setup_connections(self) -> None:
        """设置信号连接"""
        # 按钮信号
        self.open_btn.clicked.connect(self._on_open_selected)
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn.clicked.connect(self._on_delete)
        self.filter_toggle_btn.toggled.connect(self._set_filter_panel_expanded)

        # 树信号
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.search_edit.textChanged.connect(self._resort_items)
        self.type_filter_combo.currentIndexChanged.connect(self._resort_items)
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        self.favorite_filter_combo.currentIndexChanged.connect(self._resort_items)
        self.group_filter_combo.currentIndexChanged.connect(self._resort_items)

    def _on_add_connection(self, conn_type: ConnectionType) -> None:
        """
        添加新连接

        Args:
            conn_type: 连接类型
        """
        from ..dialogs.connection_dialog import ConnectionDialog

        dialog = ConnectionDialog(conn_type, self)
        if self._config_manager is not None:
            dialog.set_config_manager(self._config_manager)
        if dialog.exec() == QDialog.Accepted:
            config = dialog.get_config()
            self.connection_created.emit(config)

    def _on_edit(self) -> None:
        """编辑选中连接"""
        item = self._selected_connection_item()
        if item:
            conn_id = item.data(self.COL_NAME, self.ROLE_CONNECTION_ID)
            self.connection_edited.emit(conn_id)

    def _on_open_selected(self) -> None:
        """批量打开当前选中的连接。"""
        connection_ids = self._selected_connection_ids()
        if not connection_ids:
            return
        if len(connection_ids) == 1:
            self.connection_activated.emit(connection_ids[0])
            return
        self.connection_batch_open_requested.emit(connection_ids)

    def _on_delete(self) -> None:
        """删除选中连接"""
        item = self._selected_connection_item()
        if not item:
            return

        conn_data = self._item_connection_data(item)
        conn_id = conn_data.get("id")
        conn_name = conn_data.get("name", item.text(self.COL_NAME))

        reply = QMessageBox.question(
            self,
            self.tr("确认删除"),
            self.tr(f"确定要删除连接 '{conn_name}' 吗？"),
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.remove_connection_item(conn_id)
            self.connection_deleted.emit(conn_id)

    def _on_open_file_browser(self) -> None:
        """请求为当前连接打开文件浏览器。"""
        item = self._selected_connection_item()
        if item is None:
            return
        conn_data = self._item_connection_data(item)
        conn_id = conn_data.get("id")
        if conn_id:
            self.connection_file_browser_requested.emit(conn_id)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """双击项目"""
        conn_id = item.data(self.COL_NAME, self.ROLE_CONNECTION_ID)
        if conn_id:
            self.connection_activated.emit(conn_id)
            return
        item.setExpanded(not item.isExpanded())

    def _on_selection_changed(self) -> None:
        """选择改变"""
        selected_items = self._selected_connection_items()
        count = len(selected_items)
        self.open_btn.setEnabled(count > 0)
        self.edit_btn.setEnabled(count == 1)
        self.delete_btn.setEnabled(count == 1)
        self._refresh_summary_label()

    def _set_filter_panel_expanded(self, expanded: bool) -> None:
        """切换高级筛选区显示状态。"""
        self._filters_expanded = bool(expanded)
        self.filter_panel.setVisible(self._filters_expanded)
        self.filter_toggle_btn.blockSignals(True)
        self.filter_toggle_btn.setChecked(self._filters_expanded)
        self.filter_toggle_btn.blockSignals(False)
        self.filter_toggle_btn.setArrowType(
            Qt.DownArrow if self._filters_expanded else Qt.RightArrow
        )
        self.filter_toggle_btn.setText(
            self.tr("收起筛选") if self._filters_expanded else self.tr("展开筛选")
        )

    def _build_context_menu(self, item: QTreeWidgetItem) -> QMenu:
        """为指定连接项构建右键菜单。"""
        menu = QMenu(self)
        conn_data = self._item_connection_data(item)
        conn_id = conn_data.get("id")
        conn_type = str(conn_data.get("connection_type", "")).lower()

        connect_action = QAction(self.tr(self._connection_open_action_text(conn_type)), self)
        connect_action.setIcon(icon("quick_connect"))
        connect_action.triggered.connect(lambda: self._on_item_double_clicked(item, 0))
        menu.addAction(connect_action)

        selected_items = self._selected_connection_items()
        if len(selected_items) > 1 and item in selected_items:
            open_selected_action = QAction(self.tr("批量打开选中"), self)
            open_selected_action.setIcon(icon("quick_connect"))
            open_selected_action.triggered.connect(self._on_open_selected)
            menu.addAction(open_selected_action)

        if conn_type in {"ssh", "sftp", "ftp"} and conn_id:
            files_action = QAction(self.tr("打开文件浏览器"), self)
            files_action.setIcon(icon("sftp"))
            files_action.triggered.connect(
                lambda checked=False, connection_id=conn_id: (
                    self.connection_file_browser_requested.emit(connection_id)
                )
            )
            menu.addAction(files_action)

        menu.addSeparator()

        favorite_action = QAction(
            self.tr("取消收藏") if conn_data.get("favorite") else self.tr("收藏"),
            self,
        )
        favorite_action.triggered.connect(lambda: self._toggle_connection_favorite(item))
        menu.addAction(favorite_action)

        menu.addSeparator()

        manage_menu = menu.addMenu(self.tr("管理"))
        manage_menu.setIcon(icon("settings"))

        edit_action = QAction(self.tr("编辑"), self)
        edit_action.setIcon(icon("edit"))
        edit_action.triggered.connect(self._on_edit)
        manage_menu.addAction(edit_action)

        delete_action = QAction(self.tr("删除"), self)
        delete_action.setIcon(icon("delete"))
        delete_action.triggered.connect(self._on_delete)
        manage_menu.addAction(delete_action)

        return menu

    def _build_group_context_menu(self, group_item: QTreeWidgetItem) -> QMenu:
        """为分组头构建右键菜单。"""
        menu = QMenu(self)
        connection_ids = self._connection_ids_for_group_item(group_item)
        view_label = self.tr(self._view_label(self._current_view_mode()))
        scope_payload = self._group_scope_payload(group_item)

        open_group_action = QAction(self.tr(f"打开此{view_label}全部连接"), self)
        open_group_action.setIcon(icon("quick_connect"))
        open_group_action.setEnabled(bool(connection_ids))
        open_group_action.triggered.connect(
            lambda checked=False, ids=connection_ids: self._emit_batch_open(ids)
        )
        menu.addAction(open_group_action)

        filter_action = QAction(self.tr(f"按此{view_label}筛选"), self)
        filter_action.triggered.connect(
            lambda checked=False, group_name=self._group_title_to_name(
                group_item.text(self.COL_NAME)
            ): (self._select_group_filter(group_name))
        )
        menu.addAction(filter_action)

        workspace_menu = menu.addMenu(self.tr("工作区"))
        workspace_menu.setIcon(icon("quick_connect"))

        open_workspace_action = QAction(self.tr(f"打开此{view_label}工作区"), self)
        open_workspace_action.setIcon(icon("quick_connect"))
        open_workspace_action.setEnabled(bool(connection_ids))
        open_workspace_action.triggered.connect(
            lambda checked=False, payload=scope_payload: (
                self.connection_scope_workspace_requested.emit(
                    {
                        **dict(payload),
                        "include_file_browsers": True,
                        "include_local_terminal": True,
                    }
                )
            )
        )
        workspace_menu.addAction(open_workspace_action)

        save_template_action = QAction(self.tr(f"将此{view_label}保存为模板"), self)
        save_template_action.setIcon(icon("quick_connect"))
        save_template_action.setEnabled(bool(connection_ids))
        save_template_action.triggered.connect(
            lambda checked=False, payload=scope_payload: (
                self.connection_scope_workspace_template_requested.emit(dict(payload))
            )
        )
        workspace_menu.addAction(save_template_action)

        save_ops_template_action = QAction(self.tr(f"将此{view_label}保存为完整工作区模板"), self)
        save_ops_template_action.setIcon(icon("quick_connect"))
        save_ops_template_action.setEnabled(bool(connection_ids))
        save_ops_template_action.triggered.connect(
            lambda checked=False, payload=scope_payload: (
                self.connection_scope_workspace_template_requested.emit(
                    {
                        **dict(payload),
                        "include_file_browsers": True,
                        "include_local_terminal": True,
                        "template_kind": "ops_workspace",
                    }
                )
            )
        )
        workspace_menu.addAction(save_ops_template_action)

        task_menu = menu.addMenu(self.tr("任务预设"))
        task_menu.setEnabled(bool(connection_ids))
        for preset_key, title in (
            ("quick_inspection", "快速巡检"),
            ("system_inspection", "系统巡检"),
            ("network_inspection", "网络巡检"),
            ("disk_inspection", "磁盘巡检"),
            ("release_precheck", "发布前检查"),
        ):
            action = task_menu.addAction(self.tr(f"执行{title}"))
            action.triggered.connect(
                lambda checked=False, current_preset_key=preset_key, payload=scope_payload: (
                    self.connection_scope_task_preset_requested.emit(
                        current_preset_key,
                        dict(payload),
                    )
                )
            )

        clear_filter_action = QAction(self.tr("清除筛选"), self)
        clear_filter_action.triggered.connect(self._clear_filters)
        menu.addAction(clear_filter_action)

        return menu

    @staticmethod
    def _connection_open_action_text(conn_type: str) -> str:
        """返回连接右键菜单的主打开动作文案。"""
        mapping = {
            "ssh": "打开终端",
            "serial": "打开终端",
            "tcp": "打开终端",
            "udp": "打开终端",
            "sftp": "打开文件",
            "ftp": "打开文件",
            "vnc": "打开远程桌面",
        }
        return mapping.get(conn_type, "打开")

    def _show_context_menu(self, pos) -> None:
        """显示右键菜单"""
        item = self.tree.itemAt(pos)
        if not item:
            return
        self.tree.setCurrentItem(item)
        if item.data(self.COL_NAME, self.ROLE_CONNECTION_ID):
            menu = self._build_context_menu(item)
        else:
            menu = self._build_group_context_menu(item)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def add_connection_item(self, conn_data: Dict[str, Any]) -> None:
        """
        添加连接项目

        Args:
            conn_data: 连接数据字典
        """
        conn_id = conn_data.get("id", conn_data.get("name"))
        if conn_id in self._connection_items:
            self.update_connection_item(conn_id, conn_data)
            return

        item = QTreeWidgetItem()
        item.setText(self.COL_STATUS, self.tr("离线"))
        self._apply_connection_data(item, conn_data)
        self._apply_status_visual(item, "offline")

        self.tree.addTopLevelItem(item)
        self._connection_items[conn_id] = item
        self._refresh_group_filter_choices()
        self._resort_items()

        self._logger.debug(f"添加连接项目: {conn_data.get('name', '未命名')}")

    def remove_connection_item(self, conn_id: str) -> None:
        """
        移除连接项目

        Args:
            conn_id: 连接 ID
        """
        if conn_id in self._connection_items:
            item = self._connection_items.pop(conn_id)
            parent = item.parent()
            if parent is not None:
                child_index = parent.indexOfChild(item)
                if child_index >= 0:
                    parent.takeChild(child_index)
            else:
                index = self.tree.indexOfTopLevelItem(item)
                if index >= 0:
                    self.tree.takeTopLevelItem(index)
            self._refresh_group_filter_choices()
            self._resort_items()

    def clear_connections(self) -> None:
        """清空连接树。"""
        self.tree.clear()
        self._connection_items.clear()
        self._refresh_group_filter_choices()
        self._refresh_summary_label()

    def update_connection_item(self, conn_id: str, conn_data: Dict[str, Any]) -> None:
        """
        更新连接项目显示。

        Args:
            conn_id: 连接 ID
            conn_data: 最新连接数据
        """
        if conn_id not in self._connection_items:
            self.add_connection_item(conn_data)
            return

        item = self._connection_items[conn_id]
        self._apply_connection_data(item, conn_data)
        self._refresh_group_filter_choices()
        self._resort_items()

    def focus_connection(self, conn_id: str) -> bool:
        """聚焦指定连接项，若当前筛选隐藏则返回 False。"""
        item = self._connection_items.get(conn_id)
        if item is None:
            return False
        if not self._matches_filter(self._item_connection_data(item)):
            return False
        self.tree.clearSelection()
        item.setSelected(True)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self._on_selection_changed()
        return True

    def update_connection_status(self, conn_id: str, status: ConnectionStatus) -> None:
        """
        更新连接状态

        Args:
            conn_id: 连接 ID
            status: 连接状态
        """
        if conn_id in self._connection_items:
            item = self._connection_items[conn_id]

            status_text = {
                ConnectionStatus.DISCONNECTED: self.tr("离线"),
                ConnectionStatus.CONNECTING: self.tr("连接中"),
                ConnectionStatus.CONNECTED: self.tr("已连接"),
                ConnectionStatus.RECONNECTING: self.tr("重连中"),
                ConnectionStatus.ERROR: self.tr("错误"),
            }.get(status, self.tr("未知"))

            item.setText(self.COL_STATUS, status_text)
            visual_name = {
                ConnectionStatus.DISCONNECTED: "offline",
                ConnectionStatus.CONNECTING: "connecting",
                ConnectionStatus.CONNECTED: "connected",
                ConnectionStatus.RECONNECTING: "reconnecting",
                ConnectionStatus.ERROR: "error",
            }.get(status, "offline")
            self._apply_status_visual(item, visual_name)

    def _update_item_style(self, item: QTreeWidgetItem, conn_type: str) -> None:
        """更新项目样式"""
        conn_data = self._item_connection_data(item)
        tooltip_lines = [
            self.tr(f"{conn_data.get('name', '未命名')} ({(conn_type or 'unknown').upper()})")
        ]
        group_name = self._group_name_for_connection(conn_data)
        if group_name:
            tooltip_lines.append(self.tr(f"分组: {group_name}"))
        environment_name = self._environment_name_for_connection(conn_data)
        if environment_name:
            tooltip_lines.append(self.tr(f"环境: {environment_name}"))
        project_name = self._project_name_for_connection(conn_data)
        if project_name:
            tooltip_lines.append(self.tr(f"项目: {project_name}"))
        business_domain_name = self._business_domain_name_for_connection(conn_data)
        if business_domain_name:
            tooltip_lines.append(self.tr(f"业务域: {business_domain_name}"))
        host_text = self._primary_host_text(conn_data)
        if host_text:
            tooltip_lines.append(self.tr(f"主机: {host_text}"))
        description = str(conn_data.get("description") or "").strip()
        if description:
            tooltip_lines.append(self.tr(f"描述: {description}"))
        tags = [str(tag).strip() for tag in conn_data.get("tags", []) if str(tag).strip()]
        if tags:
            tooltip_lines.append(self.tr(f"标签: {', '.join(tags)}"))
        if conn_data.get("favorite"):
            tooltip_lines.append(self.tr("已收藏"))
        if conn_data.get("last_connected_at"):
            tooltip_lines.append(self.tr(f"最近连接: {conn_data['last_connected_at']}"))
        item.setToolTip(
            self.COL_NAME,
            "\n".join(tooltip_lines),
        )

    def _apply_status_visual(self, item: QTreeWidgetItem, status_name: str) -> None:
        """为连接状态应用图标与颜色。"""
        item.setIcon(
            self.COL_STATUS,
            status_icon("connecting" if status_name == "reconnecting" else status_name),
        )
        item.setForeground(self.COL_STATUS, status_brush(status_name))

    @staticmethod
    def _display_name(conn_data: Dict[str, Any]) -> str:
        """返回连接树中展示的名称。"""
        name = conn_data.get("name", "未命名")
        return f"★ {name}" if conn_data.get("favorite") else name

    def _item_connection_data(self, item: QTreeWidgetItem) -> Dict[str, Any]:
        """读取条目绑定的完整连接数据。"""
        data = item.data(self.COL_NAME, self.ROLE_CONNECTION_DATA)
        return dict(data) if isinstance(data, dict) else {}

    def _selected_connection_item(self) -> Optional[QTreeWidgetItem]:
        """返回当前选中的连接项，忽略分组头。"""
        items = self._selected_connection_items()
        return items[0] if len(items) == 1 else None

    def _selected_connection_items(self) -> List[QTreeWidgetItem]:
        """返回当前选中的连接项列表，忽略分组头。"""
        return [
            item
            for item in self.tree.selectedItems()
            if item.data(self.COL_NAME, self.ROLE_CONNECTION_ID)
        ]

    def _selected_connection_ids(self) -> List[str]:
        """返回当前选中的连接 ID 列表。"""
        ids: List[str] = []
        seen: set[str] = set()
        for item in self._selected_connection_items():
            conn_id = item.data(self.COL_NAME, self.ROLE_CONNECTION_ID)
            if not isinstance(conn_id, str) or not conn_id or conn_id in seen:
                continue
            seen.add(conn_id)
            ids.append(conn_id)
        return ids

    @classmethod
    def _group_name_for_connection(cls, conn_data: Dict[str, Any]) -> str:
        """返回连接所属分组名。"""
        group_name = str(conn_data.get("group") or "").strip()
        return group_name or cls.DEFAULT_GROUP_NAME

    @classmethod
    def _environment_name_for_connection(cls, conn_data: Dict[str, Any]) -> str:
        """返回连接所属环境名。"""
        environment_name = str(conn_data.get("environment") or "").strip()
        return environment_name or cls.DEFAULT_ENVIRONMENT_NAME

    @classmethod
    def _project_name_for_connection(cls, conn_data: Dict[str, Any]) -> str:
        """返回连接所属项目名。"""
        project_name = str(conn_data.get("project") or "").strip()
        return project_name or cls.DEFAULT_PROJECT_NAME

    @classmethod
    def _business_domain_name_for_connection(cls, conn_data: Dict[str, Any]) -> str:
        """返回连接所属业务域名。"""
        business_domain_name = str(conn_data.get("business_domain") or "").strip()
        return business_domain_name or cls.DEFAULT_BUSINESS_DOMAIN_NAME

    @classmethod
    def _view_label(cls, view_mode: str) -> str:
        """返回视图模式对应的人类可读标签。"""
        return {
            cls.VIEW_GROUP: "分组",
            cls.VIEW_ENVIRONMENT: "环境",
            cls.VIEW_PROJECT: "项目",
            cls.VIEW_BUSINESS_DOMAIN: "业务域",
        }.get(view_mode, "分组")

    def _current_view_mode(self) -> str:
        """返回当前连接组织视图模式。"""
        return str(self.view_mode_combo.currentData() or self.VIEW_GROUP)

    def _view_value_for_connection(self, conn_data: Dict[str, Any]) -> str:
        """根据当前视图模式提取连接归类值。"""
        return self._view_value_for_mode(conn_data, self._current_view_mode())

    @classmethod
    def _view_value_for_mode(cls, conn_data: Dict[str, Any], view_mode: str) -> str:
        """根据指定视图模式提取连接归类值。"""
        mapping = {
            cls.VIEW_GROUP: cls._group_name_for_connection,
            cls.VIEW_ENVIRONMENT: cls._environment_name_for_connection,
            cls.VIEW_PROJECT: cls._project_name_for_connection,
            cls.VIEW_BUSINESS_DOMAIN: cls._business_domain_name_for_connection,
        }
        resolver = mapping.get(view_mode, cls._group_name_for_connection)
        return resolver(conn_data)

    @staticmethod
    def _primary_host_text(conn_data: Dict[str, Any]) -> str:
        """提取连接主要主机信息。"""
        host = str(conn_data.get("host") or conn_data.get("remote_host") or "").strip()
        port = conn_data.get("port") or conn_data.get("remote_port")
        if not host:
            return ""
        return f"{host}:{port}" if port else host

    def _matches_filter(self, conn_data: Dict[str, Any]) -> bool:
        """判断连接是否命中当前搜索关键字。"""
        return self._matches_filter_state(conn_data, self.export_filter_state())

    def _matches_filter_state(
        self, conn_data: Dict[str, Any], filter_state: Dict[str, Any]
    ) -> bool:
        """判断连接是否命中指定筛选状态。"""
        filters = dict(filter_state) if isinstance(filter_state, dict) else {}
        type_filter = str(filters.get("type") or "__all__")
        if (
            type_filter != "__all__"
            and str(conn_data.get("connection_type") or "").lower() != type_filter
        ):
            return False

        favorite_filter = str(filters.get("favorite") or "__all__")
        is_favorite = bool(conn_data.get("favorite"))
        if favorite_filter == "__favorite_only__" and not is_favorite:
            return False
        if favorite_filter == "__non_favorite_only__" and is_favorite:
            return False

        view_mode = str(filters.get("view") or self.VIEW_GROUP)
        group_filter = str(filters.get("group") or "__all__")
        if (
            group_filter != "__all__"
            and self._view_value_for_mode(conn_data, view_mode) != group_filter
        ):
            return False

        keyword = str(filters.get("search") or "").strip().casefold()
        if not keyword:
            return True

        text_parts = [
            str(conn_data.get("name") or ""),
            str(conn_data.get("connection_type") or ""),
            self._group_name_for_connection(conn_data),
            self._environment_name_for_connection(conn_data),
            self._project_name_for_connection(conn_data),
            self._business_domain_name_for_connection(conn_data),
            str(conn_data.get("description") or ""),
            str(conn_data.get("host") or ""),
            str(conn_data.get("remote_host") or ""),
            str(conn_data.get("username") or ""),
            str(conn_data.get("initial_path") or ""),
        ]
        text_parts.extend(str(tag).strip() for tag in conn_data.get("tags", []) if str(tag).strip())
        searchable = " ".join(part for part in text_parts if part).casefold()
        return keyword in searchable

    @classmethod
    def _connection_sort_key(cls, conn_data: Dict[str, Any], view_mode: str) -> tuple[str, str]:
        """连接分组内排序键。"""
        group_name = cls._view_value_for_mode(conn_data, view_mode).casefold()
        name = str(conn_data.get("name") or "").casefold()
        return group_name, name

    @classmethod
    def _group_sort_key(cls, group_name: str, view_mode: str) -> tuple[int, str]:
        """分组排序键，默认占位分组优先，其余按名称排序。"""
        normalized = group_name.strip()
        default_names = {
            cls.VIEW_GROUP: cls.DEFAULT_GROUP_NAME,
            cls.VIEW_ENVIRONMENT: cls.DEFAULT_ENVIRONMENT_NAME,
            cls.VIEW_PROJECT: cls.DEFAULT_PROJECT_NAME,
            cls.VIEW_BUSINESS_DOMAIN: cls.DEFAULT_BUSINESS_DOMAIN_NAME,
        }
        return (
            0 if normalized == default_names.get(view_mode, cls.DEFAULT_GROUP_NAME) else 1,
            normalized.casefold(),
        )

    def _create_group_item(self, group_name: str) -> QTreeWidgetItem:
        """创建分组头节点。"""
        item = QTreeWidgetItem()
        item.setText(self.COL_TYPE, self.tr(self._view_label(self._current_view_mode())))
        item.setFlags(Qt.ItemIsEnabled)
        item.setExpanded(True)
        return item

    @staticmethod
    def _group_title_to_name(title: str) -> str:
        """从分组标题文本中提取原始分组名。"""
        if " (" not in title:
            return title.strip()
        return title.rsplit(" (", 1)[0].strip()

    def _connection_ids_for_group_item(self, group_item: QTreeWidgetItem) -> List[str]:
        """返回分组头下所有连接 ID。"""
        ids: List[str] = []
        for index in range(group_item.childCount()):
            child = group_item.child(index)
            conn_id = child.data(self.COL_NAME, self.ROLE_CONNECTION_ID)
            if isinstance(conn_id, str) and conn_id:
                ids.append(conn_id)
        return ids

    def _group_scope_payload(self, group_item: QTreeWidgetItem) -> Dict[str, Any]:
        """构建当前视图范围操作载荷。"""
        scope_name = self._group_title_to_name(group_item.text(self.COL_NAME))
        view_mode = self._current_view_mode()
        return {
            "scope_name": scope_name,
            "view_mode": view_mode,
            "view_label": self._view_label(view_mode),
            "connection_ids": self._connection_ids_for_group_item(group_item),
        }

    def _emit_batch_open(self, connection_ids: List[str]) -> None:
        """按数量选择单开或批量打开信号。"""
        deduped_ids: List[str] = []
        seen: set[str] = set()
        for conn_id in connection_ids:
            if not conn_id or conn_id in seen:
                continue
            seen.add(conn_id)
            deduped_ids.append(conn_id)
        if not deduped_ids:
            return
        if len(deduped_ids) == 1:
            self.connection_activated.emit(deduped_ids[0])
            return
        self.connection_batch_open_requested.emit(deduped_ids)

    def _refresh_group_filter_choices(self) -> None:
        """根据现有连接刷新分组筛选下拉框。"""
        view_mode = self._current_view_mode()
        current_group = str(self.group_filter_combo.currentData() or "__all__")
        groups = sorted(
            {
                self._view_value_for_connection(self._item_connection_data(item))
                for item in self._connection_items.values()
            },
            key=lambda value: self._group_sort_key(value, view_mode),
        )
        self.group_filter_combo.blockSignals(True)
        self.group_filter_combo.clear()
        self.group_filter_combo.addItem(self.tr(f"全部{self._view_label(view_mode)}"), "__all__")
        for group_name in groups:
            self.group_filter_combo.addItem(group_name, group_name)
        target_index = self.group_filter_combo.findData(current_group)
        self.group_filter_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.group_filter_combo.blockSignals(False)

    def _select_group_filter(self, group_name: str) -> None:
        """切换到指定分组筛选。"""
        index = self.group_filter_combo.findData(group_name)
        if index < 0:
            index = 0
        self.group_filter_combo.setCurrentIndex(index)

    def _clear_filters(self) -> None:
        """清空所有筛选条件。"""
        self.search_edit.clear()
        self.type_filter_combo.setCurrentIndex(0)
        self.view_mode_combo.setCurrentIndex(0)
        self.favorite_filter_combo.setCurrentIndex(0)
        self.group_filter_combo.setCurrentIndex(0)
        self._set_filter_panel_expanded(False)

    def _active_filter_descriptions(self) -> List[str]:
        """返回当前激活的筛选摘要。"""
        descriptions: List[str] = []
        search = self.search_edit.text().strip()
        if search:
            descriptions.append(self.tr(f"搜索“{search}”"))
        if str(self.type_filter_combo.currentData() or "__all__") != "__all__":
            descriptions.append(self.tr(f"类型 {self.type_filter_combo.currentText()}"))
        if self._current_view_mode() != self.VIEW_GROUP:
            descriptions.append(self.tr(f"视图 {self.view_mode_combo.currentText()}"))
        if str(self.favorite_filter_combo.currentData() or "__all__") != "__all__":
            descriptions.append(self.tr(self.favorite_filter_combo.currentText()))
        if str(self.group_filter_combo.currentData() or "__all__") != "__all__":
            descriptions.append(
                self.tr(
                    f"{self._view_label(self._current_view_mode())}: {self.group_filter_combo.currentText()}"
                )
            )
        return descriptions

    def _refresh_summary_label(self) -> None:
        """刷新头部统计信息。"""
        total_count = len(self._connection_items)
        visible_count = len(self.get_filtered_connection_ids()) if total_count else 0
        if total_count and visible_count != total_count:
            self.summary_label.setText(self.tr(f"{visible_count} / {total_count}"))
        else:
            self.summary_label.setText(self.tr(f"{total_count} 个连接"))

        selected_count = len(self._selected_connection_items())
        view_text = self.view_mode_combo.currentText()
        selection_text = (
            self.tr(f"已选 {selected_count} 项 · 当前{view_text}")
            if selected_count
            else self.tr(f"未选择连接 · 当前{view_text}")
        )
        self.selection_summary_label.setText(selection_text)

        active_filters = self._active_filter_descriptions()
        self.clear_filters_btn.setEnabled(bool(active_filters))
        if active_filters:
            self.filter_summary_label.setText(self.tr("已启用：") + " · ".join(active_filters))
            if any(
                (
                    str(self.type_filter_combo.currentData() or "__all__") != "__all__",
                    self._current_view_mode() != self.VIEW_GROUP,
                    str(self.favorite_filter_combo.currentData() or "__all__") != "__all__",
                    str(self.group_filter_combo.currentData() or "__all__") != "__all__",
                )
            ):
                self._set_filter_panel_expanded(True)
        else:
            self.filter_summary_label.setText(self.tr("未启用高级筛选"))

    def _on_view_mode_changed(self) -> None:
        """切换连接组织视图。"""
        self._refresh_group_filter_choices()
        self._resort_items()

    def export_filter_state(self) -> Dict[str, str]:
        """导出当前筛选状态。"""
        return {
            "search": self.search_edit.text().strip(),
            "type": str(self.type_filter_combo.currentData() or "__all__"),
            "view": self._current_view_mode(),
            "favorite": str(self.favorite_filter_combo.currentData() or "__all__"),
            "group": str(self.group_filter_combo.currentData() or "__all__"),
        }

    def has_active_filters(self) -> bool:
        """判断当前是否启用了非默认筛选。"""
        state = self.export_filter_state()
        return any(
            (
                state["search"],
                state["type"] != "__all__",
                state["view"] != self.VIEW_GROUP,
                state["favorite"] != "__all__",
                state["group"] != "__all__",
            )
        )

    def apply_filter_state(self, state: Dict[str, Any]) -> None:
        """应用筛选状态。"""
        filters = dict(state) if isinstance(state, dict) else {}
        search = str(filters.get("search") or "").strip()
        type_value = str(filters.get("type") or "__all__")
        view_value = str(filters.get("view") or self.VIEW_GROUP)
        favorite_value = str(filters.get("favorite") or "__all__")
        group_value = str(filters.get("group") or "__all__")

        self.search_edit.blockSignals(True)
        self.type_filter_combo.blockSignals(True)
        self.view_mode_combo.blockSignals(True)
        self.favorite_filter_combo.blockSignals(True)
        self.group_filter_combo.blockSignals(True)
        try:
            self.search_edit.setText(search)

            type_index = self.type_filter_combo.findData(type_value)
            self.type_filter_combo.setCurrentIndex(type_index if type_index >= 0 else 0)

            view_index = self.view_mode_combo.findData(view_value)
            self.view_mode_combo.setCurrentIndex(view_index if view_index >= 0 else 0)
            self._refresh_group_filter_choices()

            favorite_index = self.favorite_filter_combo.findData(favorite_value)
            self.favorite_filter_combo.setCurrentIndex(favorite_index if favorite_index >= 0 else 0)

            group_index = self.group_filter_combo.findData(group_value)
            self.group_filter_combo.setCurrentIndex(group_index if group_index >= 0 else 0)
        finally:
            self.search_edit.blockSignals(False)
            self.type_filter_combo.blockSignals(False)
            self.view_mode_combo.blockSignals(False)
            self.favorite_filter_combo.blockSignals(False)
            self.group_filter_combo.blockSignals(False)
        self._resort_items()

    def reset_filters(self) -> None:
        """重置到默认筛选状态。"""
        self._clear_filters()

    def _apply_connection_data(self, item: QTreeWidgetItem, conn_data: Dict[str, Any]) -> None:
        """把连接数据写回树条目。"""
        normalized = dict(conn_data)
        normalized["favorite"] = bool(normalized.get("favorite", False))
        normalized["last_connected_at"] = normalized.get("last_connected_at") or None
        normalized["group"] = self._group_name_for_connection(normalized)
        normalized["environment"] = self._environment_name_for_connection(normalized)
        normalized["project"] = self._project_name_for_connection(normalized)
        normalized["business_domain"] = self._business_domain_name_for_connection(normalized)
        conn_id = normalized.get("id", normalized.get("name"))
        conn_type = normalized.get("connection_type", "unknown")
        item.setText(self.COL_NAME, self._display_name(normalized))
        item.setText(self.COL_TYPE, conn_type.upper())
        item.setData(self.COL_NAME, self.ROLE_CONNECTION_ID, conn_id)
        item.setData(self.COL_NAME, self.ROLE_CONNECTION_DATA, normalized)
        item.setIcon(self.COL_NAME, connection_type_icon(conn_type))
        self._update_item_style(item, conn_type)

    def _toggle_connection_favorite(self, item: QTreeWidgetItem) -> None:
        """切换连接收藏状态。"""
        conn_data = self._item_connection_data(item)
        conn_id = conn_data.get("id")
        if not conn_id:
            return
        conn_data["favorite"] = not bool(conn_data.get("favorite"))
        self._apply_connection_data(item, conn_data)
        self._resort_items()
        self.connection_favorite_toggled.emit(conn_id, bool(conn_data["favorite"]))

    def _resort_items(self) -> None:
        """按分组、收藏、最近使用时间与名称重排连接列表。"""
        selected_ids = set(self._selected_connection_ids())
        current_item = self.tree.currentItem()
        current_id = None
        if current_item is not None:
            current_value = current_item.data(self.COL_NAME, self.ROLE_CONNECTION_ID)
            current_id = current_value if isinstance(current_value, str) else None

        for item in self._connection_items.values():
            parent = item.parent()
            if parent is not None:
                child_index = parent.indexOfChild(item)
                if child_index >= 0:
                    parent.takeChild(child_index)

        while self.tree.topLevelItemCount():
            self.tree.takeTopLevelItem(0)

        view_mode = self._current_view_mode()
        items = list(self._connection_items.values())
        items.sort(
            key=lambda item: self._connection_sort_key(self._item_connection_data(item), view_mode)
        )
        items.sort(
            key=lambda item: self._item_connection_data(item).get("last_connected_at") or "",
            reverse=True,
        )
        items.sort(
            key=lambda item: bool(self._item_connection_data(item).get("favorite")),
            reverse=True,
        )

        groups: Dict[str, QTreeWidgetItem] = {}
        group_counts: Dict[str, int] = {}
        for item in items:
            conn_data = self._item_connection_data(item)
            if not self._matches_filter(conn_data):
                continue
            group_name = self._view_value_for_connection(conn_data)
            group_item = groups.get(group_name)
            if group_item is None:
                group_item = self._create_group_item(group_name)
                groups[group_name] = group_item
                group_counts[group_name] = 0
            group_item.addChild(item)
            group_counts[group_name] += 1

        group_label = self.tr(self._view_label(view_mode))
        for group_name in sorted(groups, key=lambda value: self._group_sort_key(value, view_mode)):
            group_item = groups[group_name]
            group_item.setText(self.COL_NAME, self.tr(f"{group_name} ({group_counts[group_name]})"))
            group_item.setToolTip(
                self.COL_NAME,
                self.tr(f"{group_label}: {group_name} · 连接数: {group_counts[group_name]}"),
            )
            self.tree.addTopLevelItem(group_item)
            group_item.setExpanded(True)

        self.tree.clearSelection()
        restored_current = False
        for conn_id in selected_ids:
            item = self._connection_items.get(conn_id)
            if item is None or not self._matches_filter(self._item_connection_data(item)):
                continue
            item.setSelected(True)
            if not restored_current and conn_id == current_id:
                self.tree.setCurrentItem(item)
                restored_current = True

        if (
            not restored_current
            and current_id
            and current_id in self._connection_items
            and self._matches_filter(self._item_connection_data(self._connection_items[current_id]))
        ):
            self.tree.setCurrentItem(self._connection_items[current_id])
            restored_current = True
        elif self.tree.topLevelItemCount():
            first_group = self.tree.topLevelItem(0)
            if first_group.childCount():
                self.tree.setCurrentItem(first_group.child(0))
        self._on_selection_changed()
        self._refresh_summary_label()

    def get_all_connections(self) -> List[Dict[str, Any]]:
        """获取所有连接数据"""
        items = list(self._connection_items.values())
        view_mode = self._current_view_mode()
        items.sort(
            key=lambda item: self._connection_sort_key(self._item_connection_data(item), view_mode)
        )
        items.sort(
            key=lambda item: self._item_connection_data(item).get("last_connected_at") or "",
            reverse=True,
        )
        items.sort(
            key=lambda item: bool(self._item_connection_data(item).get("favorite")),
            reverse=True,
        )
        return [self._item_connection_data(item) for item in items]

    def get_filtered_connections(self) -> List[Dict[str, Any]]:
        """返回当前筛选结果中的连接数据。"""
        return [
            conn_data for conn_data in self.get_all_connections() if self._matches_filter(conn_data)
        ]

    def get_connections_for_filter_state(
        self, filter_state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """返回指定筛选状态下的连接数据。"""
        return [
            conn_data
            for conn_data in self.get_all_connections()
            if self._matches_filter_state(conn_data, filter_state)
        ]

    def get_filtered_connection_ids(self) -> List[str]:
        """返回当前筛选结果中的连接 ID。"""
        connection_ids: List[str] = []
        for conn_data in self.get_filtered_connections():
            conn_id = conn_data.get("id")
            if isinstance(conn_id, str) and conn_id:
                connection_ids.append(conn_id)
        return connection_ids

    def get_connection_ids_for_filter_state(self, filter_state: Dict[str, Any]) -> List[str]:
        """返回指定筛选状态下的连接 ID。"""
        connection_ids: List[str] = []
        for conn_data in self.get_connections_for_filter_state(filter_state):
            conn_id = conn_data.get("id")
            if isinstance(conn_id, str) and conn_id:
                connection_ids.append(conn_id)
        return connection_ids

    def get_selected_connection_ids(self) -> List[str]:
        """返回当前选中的连接 ID 列表。"""
        return self._selected_connection_ids()
