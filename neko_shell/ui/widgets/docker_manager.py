#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker 管理组件。
"""

from __future__ import annotations

import json
import shlex
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from neko_shell.core.connection import ConnectionFactory
from neko_shell.utils import ConfigManager, get_logger
from neko_shell.ui.ui_errors import show_operation_error


class DockerManagerWidget(QWidget):
    """基础 Docker 管理工作区。"""

    container_terminal_requested = Signal(object, object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._logger = get_logger("DockerManagerWidget")
        self._config_manager: Optional[ConfigManager] = None
        self._connection = None
        self._aux_windows: list[QWidget] = []
        self._selected_project: Optional[str] = None
        self._selected_container_id: Optional[str] = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel(self.tr("SSH 连接")))
        self.connection_combo = QComboBox()
        header.addWidget(self.connection_combo, 1)
        self.connect_button = QPushButton(self.tr("连接"))
        self.connect_button.clicked.connect(self._toggle_connection)
        header.addWidget(self.connect_button)
        self.detect_button = QPushButton(self.tr("检测 Docker"))
        self.detect_button.clicked.connect(self._detect_docker)
        header.addWidget(self.detect_button)
        self.refresh_button = QPushButton(self.tr("刷新"))
        self.refresh_button.clicked.connect(self._refresh_all)
        header.addWidget(self.refresh_button)
        self.auto_refresh_button = QPushButton(self.tr("自动刷新"))
        self.auto_refresh_button.setCheckable(True)
        self.auto_refresh_button.toggled.connect(self._toggle_auto_refresh)
        header.addWidget(self.auto_refresh_button)
        layout.addLayout(header)

        project_row = QHBoxLayout()
        self.project_up_button = QPushButton(self.tr("项目启动"))
        self.project_up_button.clicked.connect(lambda: self._operate_project("up -d"))
        project_row.addWidget(self.project_up_button)
        self.project_down_button = QPushButton(self.tr("项目停止"))
        self.project_down_button.clicked.connect(lambda: self._operate_project("down"))
        project_row.addWidget(self.project_down_button)
        self.project_restart_button = QPushButton(self.tr("项目重启"))
        self.project_restart_button.clicked.connect(lambda: self._operate_project("restart"))
        project_row.addWidget(self.project_restart_button)
        self.project_logs_button = QPushButton(self.tr("项目日志"))
        self.project_logs_button.clicked.connect(self._show_project_logs)
        project_row.addWidget(self.project_logs_button)
        self.project_edit_button = QPushButton(self.tr("编辑项目"))
        self.project_edit_button.clicked.connect(self._open_project_compose_editor)
        project_row.addWidget(self.project_edit_button)
        self.clear_filter_button = QPushButton(self.tr("显示全部容器"))
        self.clear_filter_button.clicked.connect(self._clear_project_filter)
        project_row.addWidget(self.clear_filter_button)
        project_row.addStretch()
        layout.addLayout(project_row)

        container_row = QHBoxLayout()
        self.start_button = QPushButton(self.tr("启动"))
        self.start_button.clicked.connect(lambda: self._operate_selected("start"))
        container_row.addWidget(self.start_button)
        self.stop_button = QPushButton(self.tr("停止"))
        self.stop_button.clicked.connect(lambda: self._operate_selected("stop"))
        container_row.addWidget(self.stop_button)
        self.restart_button = QPushButton(self.tr("重启"))
        self.restart_button.clicked.connect(lambda: self._operate_selected("restart"))
        container_row.addWidget(self.restart_button)
        self.remove_button = QPushButton(self.tr("删除"))
        self.remove_button.clicked.connect(lambda: self._operate_selected("rm -f"))
        container_row.addWidget(self.remove_button)
        self.logs_button = QPushButton(self.tr("查看日志"))
        self.logs_button.clicked.connect(self._show_logs)
        container_row.addWidget(self.logs_button)
        self.terminal_button = QPushButton(self.tr("容器终端"))
        self.terminal_button.clicked.connect(self._request_container_terminal)
        container_row.addWidget(self.terminal_button)
        self.installer_button = QPushButton(self.tr("安装器"))
        self.installer_button.clicked.connect(self._open_installer)
        container_row.addWidget(self.installer_button)
        self.compose_button = QPushButton(self.tr("Compose 编辑器"))
        self.compose_button.clicked.connect(self._open_compose_editor)
        container_row.addWidget(self.compose_button)
        container_row.addStretch()
        layout.addLayout(container_row)

        self.status_label = QLabel(self.tr("未连接"))
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter, 1)

        self.project_table = QTableWidget(0, 4)
        self.project_table.setHorizontalHeaderLabels(
            [self.tr("项目"), self.tr("状态"), self.tr("配置"), self.tr("容器数")]
        )
        self.project_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.project_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.project_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.project_table.horizontalHeader().setStretchLastSection(True)
        self.project_table.itemSelectionChanged.connect(self._on_project_selected)
        self.project_table.doubleClicked.connect(lambda _index: self._open_project_compose_editor())
        splitter.addWidget(self.project_table)

        self.container_table = QTableWidget(0, 6)
        self.container_table.setHorizontalHeaderLabels(
            [self.tr("ID"), self.tr("名称"), self.tr("镜像"), self.tr("状态"), self.tr("详情"), self.tr("端口")]
        )
        self.container_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.container_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.container_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.container_table.horizontalHeader().setStretchLastSection(True)
        self.container_table.itemSelectionChanged.connect(self._on_container_selected)
        self.container_table.doubleClicked.connect(lambda _index: self._request_container_terminal())
        splitter.addWidget(self.container_table)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        splitter.addWidget(self.log_view)
        splitter.setSizes([180, 280, 220])
        self._update_action_states()

    def set_config_manager(self, manager: ConfigManager) -> None:
        """设置配置管理器。"""
        self._config_manager = manager
        self._reload_connections()

    def _reload_connections(self) -> None:
        current_data = self.connection_combo.currentData()
        selected_id = current_data.get("id") if isinstance(current_data, dict) else None
        self.connection_combo.clear()
        if not self._config_manager:
            self._update_action_states()
            return
        selected_index = -1
        for connection in self._config_manager.load_connections():
            if connection.get("connection_type") == "ssh":
                self.connection_combo.addItem(connection.get("name", "未命名"), connection)
                if selected_id and connection.get("id") == selected_id:
                    selected_index = self.connection_combo.count() - 1
        if selected_index >= 0:
            self.connection_combo.setCurrentIndex(selected_index)
        self._update_action_states()

    def refresh_connections(self) -> None:
        """刷新连接下拉列表并尽量保留当前选择。"""
        self._reload_connections()

    def _toggle_connection(self) -> None:
        if self._connection and self._connection.is_connected():
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        conn_data = self.connection_combo.currentData()
        if not conn_data:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择 SSH 连接"))
            return
        self._disconnect()
        try:
            self._connection = ConnectionFactory.create_from_dict(conn_data)
            self._connection.connect()
            self.connect_button.setText(self.tr("断开"))
            self.status_label.setText(self.tr(f"已连接到 {conn_data.get('name', '')}"))
            self._detect_docker()
            self._refresh_all()
            self._update_action_states()
        except Exception as exc:
            self._connection = None
            self._update_action_states()
            context = ""
            if isinstance(conn_data, dict):
                context = (
                    f"{conn_data.get('name', '')}\n"
                    f"{conn_data.get('username', '')}@{conn_data.get('host', '')}:{conn_data.get('port', '')}"
                ).strip()
            show_operation_error(self, self.tr("连接失败"), self.tr("连接 SSH"), exc, context=context)

    def _disconnect(self) -> None:
        self._refresh_timer.stop()
        self.auto_refresh_button.setChecked(False)
        if self._connection:
            try:
                self._connection.disconnect()
            except Exception as exc:
                self._logger.debug("断开 Docker SSH 连接失败: %s", exc)
        self._connection = None
        self._selected_project = None
        self._selected_container_id = None
        self.connect_button.setText(self.tr("连接"))
        self.status_label.setText(self.tr("未连接"))
        self.project_table.blockSignals(True)
        self.container_table.blockSignals(True)
        try:
            self.project_table.clearSelection()
            self.container_table.clearSelection()
            self.project_table.setRowCount(0)
            self.container_table.setRowCount(0)
        finally:
            self.project_table.blockSignals(False)
            self.container_table.blockSignals(False)
        self.log_view.clear()
        self._update_action_states()

    def _run(self, command: str, sudo: bool = True) -> str:
        if not self._connection or not self._connection.is_connected():
            raise RuntimeError(self.tr("请先连接 SSH"))
        return self._connection.sudo_exec(command) if sudo else self._connection.exec(command)

    def _detect_docker(self) -> None:
        try:
            docker_version = self._run("docker --version 2>/dev/null || true")
            compose_version = self._run("docker compose version 2>/dev/null || docker-compose --version 2>/dev/null || true")
            lines = [line for line in (docker_version.strip(), compose_version.strip()) if line]
            self.status_label.setText(" | ".join(lines) if lines else self.tr("未检测到 Docker"))
        except Exception as exc:
            self.status_label.setText(self.tr(f"Docker 检测失败: {exc}"))

    @staticmethod
    def _parse_compose_projects(output: str) -> list[dict]:
        """解析 docker compose ls 输出。"""
        output = output.strip()
        if not output:
            return []

        try:
            parsed = json.loads(output)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass

        projects = []
        lines = output.splitlines()
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(None, 1)
            if len(parts) < 2:
                continue
            name_and_status, config_file = parts
            name = name_and_status.split()[0]
            status = name_and_status[len(name):].strip()
            projects.append(
                {
                    "Name": name,
                    "Status": status,
                    "ConfigFiles": config_file,
                }
            )
        return projects

    @staticmethod
    def _parse_docker_rows(output: str) -> list[dict]:
        """解析 docker ps JSON 行输出。"""
        rows = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _refresh_all(self) -> None:
        self._refresh_projects()
        self._refresh_containers()

    def _refresh_projects(self) -> None:
        try:
            output = self._run("docker compose ls -a --format json 2>/dev/null || docker compose ls -a 2>/dev/null || true")
            rows = self._parse_compose_projects(output)
            selected_project = self._selected_project
            self.project_table.setRowCount(0)
            selected_row = -1
            for row_data in rows:
                row = self.project_table.rowCount()
                self.project_table.insertRow(row)
                config_files = row_data.get("ConfigFiles", "")
                config_display = config_files.split(",")[0] if isinstance(config_files, str) else ""
                values = [
                    row_data.get("Name", ""),
                    row_data.get("Status", ""),
                    config_display,
                    str(row_data.get("Services", row_data.get("containers", ""))),
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 0:
                        item.setData(Qt.UserRole, row_data)
                    self.project_table.setItem(row, column, item)
                if selected_project and row_data.get("Name") == selected_project:
                    selected_row = row
            if selected_row >= 0:
                self.project_table.blockSignals(True)
                self.project_table.selectRow(selected_row)
                self.project_table.blockSignals(False)
            elif selected_project:
                self._selected_project = None
                self._selected_container_id = None
            self._update_action_states()
        except Exception as exc:
            self._logger.debug("刷新 compose 项目失败: %s", exc)

    def _refresh_containers(self) -> None:
        try:
            output = self._run("docker ps -a --format '{{json .}}' 2>/dev/null || true")
            rows = self._parse_docker_rows(output)

            selected_container_id = self._selected_container_id
            self.container_table.setRowCount(0)
            selected_row = -1
            for row_data in rows:
                if self._selected_project:
                    names = row_data.get("Names", "") or ""
                    labels = row_data.get("Labels", "") or ""
                    if self._selected_project not in names and f"com.docker.compose.project={self._selected_project}" not in labels:
                        continue
                row = self.container_table.rowCount()
                self.container_table.insertRow(row)
                values = [
                    row_data.get("ID", ""),
                    row_data.get("Names", ""),
                    row_data.get("Image", ""),
                    row_data.get("State", ""),
                    row_data.get("Status", ""),
                    row_data.get("Ports", ""),
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setData(Qt.UserRole, row_data)
                    self.container_table.setItem(row, column, item)
                if selected_container_id and row_data.get("ID") == selected_container_id:
                    selected_row = row
            if selected_row >= 0:
                self.container_table.blockSignals(True)
                self.container_table.selectRow(selected_row)
                self.container_table.blockSignals(False)
            elif selected_container_id:
                self._selected_container_id = None
            self._update_action_states()
        except Exception as exc:
            show_operation_error(
                self,
                self.tr("刷新失败"),
                self.tr("刷新容器列表"),
                exc,
                context="docker ps -a --format '{{json .}}'",
            )

    def _selected_container(self) -> Optional[dict]:
        selected = self.container_table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.UserRole)

    def _operate_selected(self, operation: str) -> None:
        container = self._selected_container()
        if not container:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择容器"))
            return
        container_id = container.get("ID", "")
        if not container_id:
            return
        try:
            command = f"docker {operation} {container_id}"
            self._run(command)
            self._refresh_all()
        except Exception as exc:
            show_operation_error(
                self,
                self.tr("操作失败"),
                self.tr("Docker 容器操作"),
                exc,
                context=f"docker {operation} {container_id}",
            )

    def _show_logs(self) -> None:
        container = self._selected_container()
        if not container:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择容器"))
            return
        try:
            container_id = container.get("ID", "")
            logs = self._run(f"docker logs --tail 200 {container_id} 2>&1 || true")
            self.log_view.setPlainText(logs)
        except Exception as exc:
            show_operation_error(
                self,
                self.tr("获取日志失败"),
                self.tr("获取容器日志"),
                exc,
                context=f"docker logs --tail 200 {container.get('ID', '')}",
            )

    def _request_container_terminal(self) -> None:
        """请求主窗口打开容器交互终端。"""
        if not self._connection or not self._connection.is_connected():
            QMessageBox.information(self, self.tr("提示"), self.tr("请先连接 SSH"))
            return
        container = self._selected_container()
        if not container:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择容器"))
            return
        conn_data = self.connection_combo.currentData()
        if not isinstance(conn_data, dict):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接配置无效"))
            return
        self.container_terminal_requested.emit(dict(conn_data), dict(container))

    def _open_installer(self) -> None:
        if not self._connection or not self._connection.is_connected():
            QMessageBox.information(self, self.tr("提示"), self.tr("请先连接 SSH"))
            return
        try:
            from neko_shell.core.docker.docker_installer_ui import DockerInstallerWidget  # type: ignore
        except Exception:
            # Docker 安装器属于可选功能：缺少依赖时不要影响主流程启动。
            QMessageBox.warning(self, self.tr("不可用"), self.tr("Docker 安装器组件未就绪"))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Docker 安装器"))
        dialog.resize(960, 720)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.addWidget(DockerInstallerWidget(self._connection))
        self._aux_windows.append(dialog)
        dialog.show()

    def _open_compose_editor(self) -> None:
        if not self._connection or not self._connection.is_connected():
            QMessageBox.information(self, self.tr("提示"), self.tr("请先连接 SSH"))
            return
        try:
            from neko_shell.core.docker.docker_compose_editor import DockerComposeEditor  # type: ignore
        except Exception:
            QMessageBox.warning(self, self.tr("不可用"), self.tr("Docker Compose 编辑器组件未就绪"))
            return
        window = DockerComposeEditor(ssh=self._connection)
        self._aux_windows.append(window)
        window.show()

    def _selected_project_config_path(self) -> Optional[str]:
        project = self._selected_project_row()
        if not project:
            return None
        return str(project.get("ConfigFiles", "")).split(",")[0].strip() or None

    def _open_project_compose_editor(self) -> None:
        if not self._connection or not self._connection.is_connected():
            QMessageBox.information(self, self.tr("提示"), self.tr("请先连接 SSH"))
            return
        config_file = self._selected_project_config_path()
        if not config_file:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择 compose 项目"))
            return
        try:
            from neko_shell.core.docker.docker_compose_editor import DockerComposeEditor  # type: ignore
        except Exception:
            QMessageBox.warning(self, self.tr("不可用"), self.tr("Docker Compose 编辑器组件未就绪"))
            return
        window = DockerComposeEditor(ssh=self._connection, compose_path=config_file)
        self._aux_windows.append(window)
        window.show()

    def _selected_project_row(self) -> Optional[dict]:
        selected = self.project_table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.UserRole)

    def _on_project_selected(self) -> None:
        project = self._selected_project_row()
        self._selected_project = project.get("Name") if project else None
        self._selected_container_id = None
        self._refresh_containers()
        self._update_action_states()

    def _on_container_selected(self) -> None:
        container = self._selected_container()
        self._selected_container_id = container.get("ID") if container else None
        self._update_action_states()

    def _clear_project_filter(self) -> None:
        self.project_table.clearSelection()
        self._selected_project = None
        self._selected_container_id = None
        self._refresh_containers()
        self._update_action_states()

    def _operate_project(self, action: str) -> None:
        config_file = self._selected_project_config_path()
        if not config_file:
            QMessageBox.warning(self, self.tr("错误"), self.tr("请先选择有效的 compose 项目"))
            return

        try:
            command = f"docker compose --file {shlex.quote(config_file)} {action}"
            self._run(command)
            self._refresh_all()
        except Exception as exc:
            show_operation_error(
                self,
                self.tr("项目操作失败"),
                self.tr("Docker Compose 项目操作"),
                exc,
                context=f"{config_file}\n{action}",
            )

    def _show_project_logs(self) -> None:
        config_file = self._selected_project_config_path()
        if not config_file:
            QMessageBox.warning(self, self.tr("错误"), self.tr("请先选择有效的 compose 项目"))
            return
        try:
            logs = self._run(f"docker compose --file {shlex.quote(config_file)} logs --tail 200 2>&1 || true")
            self.log_view.setPlainText(logs)
        except Exception as exc:
            show_operation_error(
                self,
                self.tr("获取项目日志失败"),
                self.tr("获取 Compose 项目日志"),
                exc,
                context=f"docker compose --file {config_file} logs --tail 200",
            )

    def _toggle_auto_refresh(self, enabled: bool) -> None:
        if enabled and self._connection and self._connection.is_connected():
            self._refresh_timer.start()
            return
        self._refresh_timer.stop()

    def _update_action_states(self) -> None:
        """根据连接和选中状态刷新按钮可用性。"""
        is_connected = bool(self._connection and self._connection.is_connected())
        has_connection_choice = self.connection_combo.count() > 0
        has_project = self._selected_project_row() is not None
        has_container = self._selected_container() is not None

        self.connect_button.setEnabled(is_connected or has_connection_choice)
        self.detect_button.setEnabled(is_connected)
        self.refresh_button.setEnabled(is_connected)
        self.auto_refresh_button.setEnabled(is_connected)
        self.installer_button.setEnabled(is_connected)
        self.compose_button.setEnabled(is_connected)

        self.project_up_button.setEnabled(is_connected and has_project)
        self.project_down_button.setEnabled(is_connected and has_project)
        self.project_restart_button.setEnabled(is_connected and has_project)
        self.project_logs_button.setEnabled(is_connected and has_project)
        self.project_edit_button.setEnabled(is_connected and has_project)
        self.clear_filter_button.setEnabled(is_connected and bool(self._selected_project))

        self.start_button.setEnabled(is_connected and has_container)
        self.stop_button.setEnabled(is_connected and has_container)
        self.restart_button.setEnabled(is_connected and has_container)
        self.remove_button.setEnabled(is_connected and has_container)
        self.logs_button.setEnabled(is_connected and has_container)
        self.terminal_button.setEnabled(is_connected and has_container)

    def _auto_refresh(self) -> None:
        if not self._connection or not self._connection.is_connected():
            self._refresh_timer.stop()
            self.auto_refresh_button.setChecked(False)
            return
        try:
            self._refresh_all()
        except Exception as exc:
            self._logger.debug("自动刷新 Docker 信息失败: %s", exc)

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        self._disconnect()
        super().closeEvent(event)
