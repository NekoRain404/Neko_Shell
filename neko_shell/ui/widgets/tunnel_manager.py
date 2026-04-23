#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH 隧道管理组件。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from neko_shell.core.forwarder import ForwarderManager

from neko_shell.models import TunnelConfig
from neko_shell.utils import ConfigManager, get_logger
from neko_shell.ui.ui_errors import show_operation_error

from ..dialogs.tunnel_dialog import TunnelDialog


class TunnelManagerWidget(QWidget):
    """基础 SSH 隧道管理界面。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._logger = get_logger("TunnelManagerWidget")
        self._config_manager: Optional[ConfigManager] = None
        self._forwarder = ForwarderManager()
        self._active_tunnels: dict[str, object] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QToolBar()
        layout.addWidget(toolbar)

        self.add_action = QAction(self.tr("新增"), self)
        self.add_action.triggered.connect(self._add_tunnel)
        toolbar.addAction(self.add_action)

        self.edit_action = QAction(self.tr("编辑"), self)
        self.edit_action.triggered.connect(self._edit_selected_tunnel)
        toolbar.addAction(self.edit_action)

        self.delete_action = QAction(self.tr("删除"), self)
        self.delete_action.triggered.connect(self._delete_selected_tunnel)
        toolbar.addAction(self.delete_action)

        toolbar.addSeparator()

        self.start_action = QAction(self.tr("启动"), self)
        self.start_action.triggered.connect(self._start_selected_tunnel)
        toolbar.addAction(self.start_action)

        self.stop_action = QAction(self.tr("停止"), self)
        self.stop_action.triggered.connect(self._stop_selected_tunnel)
        toolbar.addAction(self.stop_action)

        self.open_action = QAction(self.tr("打开"), self)
        self.open_action.triggered.connect(self._open_selected_url)
        toolbar.addAction(self.open_action)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("名称"),
                self.tr("类型"),
                self.tr("SSH 连接"),
                self.tr("本地绑定"),
                self.tr("远程目标"),
                self.tr("状态"),
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(lambda _index: self._edit_selected_tunnel())
        self.table.itemSelectionChanged.connect(self._update_action_states)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self._update_action_states()

    def set_config_manager(self, manager: ConfigManager) -> None:
        """设置配置管理器。"""
        self._config_manager = manager
        self.refresh()

    def refresh(self) -> None:
        """刷新隧道列表。"""
        tunnels = self._config_manager.load_tunnels() if self._config_manager else []
        connections = {
            item.get("id"): item.get("name", "未命名")
            for item in (self._config_manager.load_connections() if self._config_manager else [])
        }

        self.table.setRowCount(0)
        for tunnel in tunnels:
            config = TunnelConfig.from_dict(tunnel)
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                config.name,
                self._translate_tunnel_type(config.tunnel_type),
                connections.get(config.connection_id, self.tr("未找到连接")),
                f"{config.local_host}:{config.local_port}",
                "-" if config.tunnel_type == "dynamic" else f"{config.remote_host}:{config.remote_port}",
                self.tr("运行中") if config.id in self._active_tunnels else self.tr("已停止"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, config.id)
                self.table.setItem(row, column, item)
        self._update_action_states()

    def _available_ssh_connections(self) -> list[dict]:
        """获取可选 SSH 连接。"""
        if not self._config_manager:
            return []
        return [
            connection
            for connection in self._config_manager.load_connections()
            if connection.get("connection_type") == "ssh"
        ]

    def _selected_tunnel_id(self) -> Optional[str]:
        selected = self.table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.UserRole)

    def _selected_tunnel(self) -> Optional[dict]:
        tunnel_id = self._selected_tunnel_id()
        if not tunnel_id or not self._config_manager:
            return None
        for tunnel in self._config_manager.load_tunnels():
            if tunnel.get("id") == tunnel_id:
                return tunnel
        return None

    def _update_action_states(self) -> None:
        """根据当前选择和运行状态刷新操作按钮。"""
        has_manager = self._config_manager is not None
        selected_tunnel = self._selected_tunnel()
        selected_tunnel_id = selected_tunnel.get("id") if selected_tunnel else None
        is_active = bool(selected_tunnel_id and selected_tunnel_id in self._active_tunnels)
        can_open = bool(selected_tunnel and selected_tunnel.get("browser_url"))
        has_available_connections = bool(self._available_ssh_connections()) if has_manager else False

        self.add_action.setEnabled(has_manager and has_available_connections)
        self.edit_action.setEnabled(selected_tunnel is not None)
        self.delete_action.setEnabled(selected_tunnel is not None)
        self.start_action.setEnabled(selected_tunnel is not None and not is_active)
        self.stop_action.setEnabled(is_active)
        self.open_action.setEnabled(can_open)

    def _add_tunnel(self) -> None:
        if not self._config_manager:
            return
        connections = self._available_ssh_connections()
        if not connections:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先创建 SSH 连接"))
            return

        dialog = TunnelDialog(self)
        dialog.setWindowTitle(self.tr("新增 SSH 隧道"))
        dialog.set_connections(connections)
        if not dialog.exec():
            return

        config = dialog.get_config()
        if not config.name or not config.connection_id:
            QMessageBox.warning(self, self.tr("错误"), self.tr("隧道名称和 SSH 连接不能为空"))
            return
        self._config_manager.add_tunnel(config)
        self.refresh()

    def _edit_selected_tunnel(self) -> None:
        if not self._config_manager:
            return
        tunnel = self._selected_tunnel()
        if tunnel is None:
            return

        dialog = TunnelDialog(self)
        dialog.setWindowTitle(self.tr("编辑 SSH 隧道"))
        dialog.set_connections(self._available_ssh_connections())
        dialog.set_config(TunnelConfig.from_dict(tunnel))
        if not dialog.exec():
            return

        self._config_manager.update_tunnel(tunnel["id"], dialog.get_config())
        self.refresh()

    def _delete_selected_tunnel(self) -> None:
        if not self._config_manager:
            return
        tunnel = self._selected_tunnel()
        if tunnel is None:
            return

        reply = QMessageBox.question(
            self,
            self.tr("确认删除"),
            self.tr(f"确定删除隧道“{tunnel.get('name', '')}”吗？"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._stop_tunnel_by_id(tunnel["id"])
        self._config_manager.remove_tunnel(tunnel["id"])
        self.refresh()

    def _start_selected_tunnel(self) -> None:
        tunnel = self._selected_tunnel()
        if tunnel is None:
            return
        self._start_tunnel(TunnelConfig.from_dict(tunnel))

    def _stop_selected_tunnel(self) -> None:
        tunnel = self._selected_tunnel()
        if tunnel is None:
            return
        self._stop_tunnel_by_id(tunnel["id"])
        self.refresh()

    def _open_selected_url(self) -> None:
        tunnel = self._selected_tunnel()
        if tunnel is None:
            return
        browser_url = tunnel.get("browser_url") or ""
        if not browser_url:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前隧道未配置打开地址"))
            return
        QDesktopServices.openUrl(QUrl(browser_url))

    def _start_tunnel(self, config: TunnelConfig) -> None:
        if config.id in self._active_tunnels or not self._config_manager:
            return

        connection = next(
            (
                item
                for item in self._config_manager.load_connections()
                if item.get("id") == config.connection_id
            ),
            None,
        )
        if connection is None:
            QMessageBox.warning(self, self.tr("错误"), self.tr("关联的 SSH 连接不存在"))
            return

        try:
            tunnel, ssh_client, transport = self._forwarder.start_tunnel(
                tunnel_id=config.id,
                tunnel_type=config.tunnel_type,
                local_host=config.local_host,
                local_port=config.local_port,
                remote_host=config.remote_host,
                remote_port=config.remote_port,
                ssh_host=connection.get("host"),
                ssh_port=connection.get("port"),
                ssh_user=connection.get("username"),
                ssh_password=connection.get("password"),
                passphrase=connection.get("passphrase"),
                key_file=connection.get("private_key_path"),
                proxy_command=connection.get("proxy_command"),
                allow_agent=connection.get("allow_agent", True),
                look_for_keys=connection.get("look_for_keys", True),
            )
            self._forwarder.add_tunnel(config.id, tunnel)
            self._forwarder.ssh_clients[ssh_client] = transport
            self._active_tunnels[config.id] = tunnel
            if config.browser_url:
                QDesktopServices.openUrl(QUrl(config.browser_url))
            self.refresh()
        except Exception as exc:
            self._logger.error("启动隧道失败 [%s]: %s", config.name, exc)
            show_operation_error(
                self,
                self.tr("启动失败"),
                self.tr("启动 SSH 隧道"),
                exc,
                context=f"{config.name}\n{config.tunnel_type}\n{config.local_host}:{config.local_port}",
                hint=self.tr("请确认 SSH 连接配置正确、端口未被占用。"),
            )

    def _stop_tunnel_by_id(self, tunnel_id: str) -> None:
        if tunnel_id not in self._active_tunnels:
            return
        try:
            self._forwarder.remove_tunnel(tunnel_id)
        finally:
            self._active_tunnels.pop(tunnel_id, None)

    def _show_context_menu(self, pos) -> None:
        if self.table.itemAt(pos) is None:
            return
        self._update_action_states()
        menu = QMenu(self)
        for action in (self.start_action, self.stop_action, self.open_action, self.edit_action, self.delete_action):
            menu.addAction(action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    @staticmethod
    def _translate_tunnel_type(tunnel_type: str) -> str:
        return {
            "local": "本地",
            "remote": "远程",
            "dynamic": "动态",
        }.get(tunnel_type, tunnel_type)

    def closeEvent(self, event) -> None:
        self._forwarder.stop_all()
        self._active_tunnels.clear()
        super().closeEvent(event)
