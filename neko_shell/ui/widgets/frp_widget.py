#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FRP 管理组件。
"""

from __future__ import annotations

import os
import subprocess
import yaml
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neko_shell.core.frp_manager import get_frp_manager
from neko_shell.core import frp_templates

from neko_shell.core.connection import ConnectionFactory
from neko_shell.utils import ConfigManager, get_default_config_dir, get_logger
from neko_shell.ui.ui_errors import show_operation_error


class FRPWidget(QWidget):
    """基础 FRP 管理工作区。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._logger = get_logger("FRPWidget")
        self._config_manager: Optional[ConfigManager] = None
        self._connection = None
        self._local_frpc_process: Optional[subprocess.Popen] = None
        self._local_frpc_log_handle = None
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(3000)
        self._status_timer.timeout.connect(self._refresh_status)
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
        layout.addLayout(header)

        form = QFormLayout()
        self.token_edit = QLineEdit()
        form.addRow(self.tr("Token"), self.token_edit)

        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItem("TCP", "tcp")
        self.proxy_type_combo.addItem("HTTP", "http")
        self.proxy_type_combo.addItem("UDP", "udp")
        self.proxy_type_combo.currentIndexChanged.connect(self._sync_port_label)
        form.addRow(self.tr("代理类型"), self.proxy_type_combo)

        self.local_port_spin = QSpinBox()
        self.local_port_spin.setRange(1, 65535)
        self.local_port_spin.setValue(8080)
        form.addRow(self.tr("本地服务端口"), self.local_port_spin)

        self.remote_port_label = QLabel(self.tr("远程端口"))
        self.remote_port_spin = QSpinBox()
        self.remote_port_spin.setRange(1, 65535)
        self.remote_port_spin.setValue(9000)
        form.addRow(self.remote_port_label, self.remote_port_spin)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        self.ensure_client_button = QPushButton(self.tr("下载客户端"))
        self.ensure_client_button.clicked.connect(self._ensure_client)
        action_row.addWidget(self.ensure_client_button)
        self.deploy_server_button = QPushButton(self.tr("部署服务端"))
        self.deploy_server_button.clicked.connect(self._deploy_server)
        action_row.addWidget(self.deploy_server_button)
        self.start_button = QPushButton(self.tr("启动"))
        self.start_button.clicked.connect(self._start_services)
        action_row.addWidget(self.start_button)
        self.stop_button = QPushButton(self.tr("停止"))
        self.stop_button.clicked.connect(self._stop_services)
        action_row.addWidget(self.stop_button)
        self.save_button = QPushButton(self.tr("保存配置"))
        self.save_button.clicked.connect(self._save_current_config)
        action_row.addWidget(self.save_button)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.status_label = QLabel(self.tr("未连接"))
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, 1)

        self._sync_port_label()
        self._refresh_status()
        self._update_action_states()

    def set_config_manager(self, manager: ConfigManager) -> None:
        self._config_manager = manager
        self._reload_connections()
        self._load_saved_config()
        self._update_action_states()

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
        previous_data = self.connection_combo.currentData()
        previous_id = previous_data.get("id") if isinstance(previous_data, dict) else None
        self._reload_connections()
        if previous_id or self.connection_combo.currentIndex() >= 0:
            return
        self._load_saved_config()
        self._update_action_states()

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
            self._status_timer.start()
            self._refresh_status()
            self._update_action_states()
        except Exception as exc:
            self._connection = None
            self._refresh_status()
            self._update_action_states()
            context = ""
            if isinstance(conn_data, dict):
                context = (
                    f"{conn_data.get('name', '')}\n"
                    f"{conn_data.get('username', '')}@{conn_data.get('host', '')}:{conn_data.get('port', '')}"
                ).strip()
            show_operation_error(self, self.tr("连接失败"), self.tr("连接 SSH"), exc, context=context)

    def _disconnect(self) -> None:
        self._status_timer.stop()
        if self._connection:
            try:
                self._connection.disconnect()
            except Exception as exc:
                self._logger.debug("断开 FRP SSH 连接失败: %s", exc)
        self._connection = None
        self.connect_button.setText(self.tr("连接"))
        self._refresh_status()
        self._update_action_states()

    def _append_log(self, message: str) -> None:
        self.log_view.append(message)

    def _update_progress(self, downloaded: int, total: int) -> None:
        """更新下载进度。"""
        if total <= 0:
            self.progress_bar.setValue(0)
            return
        self.progress_bar.setValue(min(100, int(downloaded * 100 / total)))

    def _require_connection(self) -> None:
        if not self._connection or not self._connection.is_connected():
            raise RuntimeError(self.tr("请先连接 SSH"))

    def _sync_port_label(self) -> None:
        if self.proxy_type_combo.currentData() == "http":
            self.remote_port_label.setText(self.tr("HTTP 端口"))
        else:
            self.remote_port_label.setText(self.tr("远程端口"))

    def _ensure_client(self) -> bool:
        manager = get_frp_manager()
        self.progress_bar.setValue(0)
        self._append_log(self.tr("正在准备本地 frpc..."))
        success = manager.ensure_frpc(
            progress_callback=self._update_progress,
            status_callback=self._append_log,
        )
        if success:
            self.progress_bar.setValue(100)
            self._append_log(self.tr(f"本地 frpc 已就绪: {manager.frpc_path}"))
        return success

    def _deploy_server(self) -> bool:
        self._require_connection()
        manager = get_frp_manager()
        self.progress_bar.setValue(0)
        self._append_log(self.tr("正在部署远程 frps..."))
        sftp = self._connection.open_sftp()
        success = manager.ensure_frps_on_server(
            self._connection,
            sftp,
            progress_callback=self._update_progress,
            status_callback=self._append_log,
        )
        if success:
            self.progress_bar.setValue(100)
            self._append_log(self.tr("远程 frps 已就绪"))
        return success

    def _frpc_config_path(self) -> str:
        base_dir = self._config_manager.config_dir if self._config_manager else get_default_config_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        return str(base_dir / "frpc.toml")

    def _config_path(self) -> str:
        """FRP 配置持久化文件路径。"""
        base_dir = self._config_manager.config_dir if self._config_manager else get_default_config_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        return str(base_dir / "frp.yaml")

    def _load_saved_config(self) -> None:
        """加载已保存的 FRP 配置。"""
        try:
            config_path = self._config_path()
            if not os.path.exists(config_path):
                return
            with open(config_path, "r", encoding="utf-8") as file_handle:
                data = yaml.safe_load(file_handle) or {}

            connection_id = data.get("connection_id")
            index = self.connection_combo.findData(
                next(
                    (
                        item
                        for item in [self.connection_combo.itemData(i) for i in range(self.connection_combo.count())]
                        if isinstance(item, dict) and item.get("id") == connection_id
                    ),
                    None,
                )
            )
            if index >= 0:
                self.connection_combo.setCurrentIndex(index)

            self.token_edit.setText(data.get("token", ""))
            proxy_index = self.proxy_type_combo.findData(data.get("proxy_type", "tcp"))
            if proxy_index >= 0:
                self.proxy_type_combo.setCurrentIndex(proxy_index)
            self.local_port_spin.setValue(int(data.get("local_port", 8080)))
            self.remote_port_spin.setValue(int(data.get("remote_port", 9000)))
            self._sync_port_label()
        except Exception as exc:
            self._logger.debug("加载 FRP 配置失败: %s", exc)

    def _save_current_config(self) -> None:
        """保存当前 FRP 配置。"""
        try:
            conn_data = self.connection_combo.currentData() or {}
            payload = {
                "connection_id": conn_data.get("id"),
                "token": self.token_edit.text().strip(),
                "proxy_type": self.proxy_type_combo.currentData(),
                "local_port": self.local_port_spin.value(),
                "remote_port": self.remote_port_spin.value(),
            }
            with open(self._config_path(), "w", encoding="utf-8") as file_handle:
                yaml.safe_dump(payload, file_handle, allow_unicode=True, sort_keys=False)
            self._append_log(self.tr("FRP 配置已保存"))
        except Exception as exc:
            show_operation_error(
                self,
                self.tr("保存失败"),
                self.tr("保存 FRP 配置"),
                exc,
                context=self._config_path(),
            )

    def _local_frpc_running(self) -> bool:
        """检查本地 frpc 是否在运行。"""
        return self._local_frpc_process is not None and self._local_frpc_process.poll() is None

    def _remote_frps_running(self) -> bool:
        """检查远程 frps 是否在运行。"""
        if not self._connection or not self._connection.is_connected():
            return False
        try:
            return bool(self._connection.exec("pgrep -x frps || true", pty=False).strip())
        except Exception:
            return False

    def _refresh_status(self) -> None:
        """刷新本地/远端 FRP 状态。"""
        ssh_status = self.tr("SSH: 已连接") if self._connection and self._connection.is_connected() else self.tr("SSH: 未连接")
        local_status = self.tr("本地 frpc: 运行中") if self._local_frpc_running() else self.tr("本地 frpc: 已停止")
        if self._connection and self._connection.is_connected():
            remote_status = self.tr("远端 frps: 运行中") if self._remote_frps_running() else self.tr("远端 frps: 已停止")
        else:
            remote_status = self.tr("远端 frps: 未知")
        self.status_label.setText(f"{ssh_status} | {local_status} | {remote_status}")
        self._update_action_states()

    def _update_action_states(self) -> None:
        """根据当前连接和服务状态刷新按钮可用性。"""
        is_connected = bool(self._connection and self._connection.is_connected())
        has_connection_choice = self.connection_combo.count() > 0
        has_local_frpc = self._local_frpc_running()

        self.connection_combo.setEnabled(not is_connected and has_connection_choice)
        self.connect_button.setEnabled(is_connected or has_connection_choice)
        self.ensure_client_button.setEnabled(True)
        self.deploy_server_button.setEnabled(is_connected)
        self.start_button.setEnabled(is_connected)
        self.stop_button.setEnabled(is_connected or has_local_frpc)
        self.save_button.setEnabled(True)

    def _start_services(self) -> None:
        try:
            self._require_connection()
            if not self.token_edit.text().strip():
                raise ValueError(self.tr("Token 不能为空"))
            self._save_current_config()
            if not self._ensure_client():
                raise RuntimeError(self.tr("frpc 准备失败"))
            if not self._deploy_server():
                raise RuntimeError(self.tr("frps 部署失败"))

            token = self.token_edit.text().strip()
            proxy_type = self.proxy_type_combo.currentData()
            local_port = self.local_port_spin.value()
            remote_port = self.remote_port_spin.value()

            self._connection.exec("killall -9 frps 2>/dev/null; pkill -9 frps 2>/dev/null; true", pty=False)
            frps_config = frp_templates.frps(token, proxy_type, remote_port if proxy_type == "http" else None)
            self._connection.exec(f"cat > $HOME/frp/frps.toml << 'EOF'\n{frps_config}\nEOF", pty=False)
            self._connection.exec("cd $HOME/frp && nohup ./frps -c frps.toml > frps.log 2>&1 &", pty=False)
            if not self._connection.exec("pgrep -x frps || true", pty=False).strip():
                raise RuntimeError(self.tr("远程 frps 启动失败"))

            frpc_config = frp_templates.frpc(self._connection.host, token, proxy_type, local_port, remote_port)
            frpc_config_path = self._frpc_config_path()
            with open(frpc_config_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(frpc_config)

            self._stop_local_frpc_best_effort()
            log_dir = get_frp_manager().frpc_path.parent
            log_dir.mkdir(parents=True, exist_ok=True)
            self._local_frpc_log_handle = open(log_dir / "frpc.log", "a", encoding="utf-8")
            self._local_frpc_process = subprocess.Popen(
                [str(get_frp_manager().frpc_path), "-c", frpc_config_path],
                stdout=self._local_frpc_log_handle,
                stderr=subprocess.STDOUT,
            )
            self._status_timer.start()
            self._refresh_status()
            self._append_log(self.tr("FRP 已启动"))
            self._update_action_states()
        except Exception as exc:
            self._refresh_status()
            self._update_action_states()
            show_operation_error(
                self,
                self.tr("启动失败"),
                self.tr("启动 FRP"),
                exc,
                hint=self.tr("请确认 SSH 连接可用、Token 正确，并检查日志输出。"),
            )

    def _stop_local_frpc_best_effort(self) -> None:
        if self._local_frpc_process and self._local_frpc_process.poll() is None:
            try:
                self._local_frpc_process.terminate()
                self._local_frpc_process.wait(timeout=5)
            except Exception:
                try:
                    self._local_frpc_process.kill()
                except Exception:
                    pass
        self._local_frpc_process = None
        if self._local_frpc_log_handle is not None:
            try:
                self._local_frpc_log_handle.close()
            except Exception:
                pass
            self._local_frpc_log_handle = None

        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/f", "/im", "frpc.exe"], capture_output=True)
            else:
                subprocess.run(["pkill", "-9", "frpc"], capture_output=True)
        except Exception:
            pass
        self._update_action_states()

    def _stop_services(self) -> None:
        try:
            self._stop_local_frpc_best_effort()
            if self._connection and self._connection.is_connected():
                self._connection.exec("killall -9 frps 2>/dev/null; pkill -9 frps 2>/dev/null; true", pty=False)
            self._refresh_status()
            self._append_log(self.tr("FRP 已停止"))
            self._update_action_states()
        except Exception as exc:
            self._refresh_status()
            self._update_action_states()
            show_operation_error(self, self.tr("停止失败"), self.tr("停止 FRP"), exc)

    def closeEvent(self, event) -> None:
        self._status_timer.stop()
        self._stop_local_frpc_best_effort()
        self._disconnect()
        super().closeEvent(event)
