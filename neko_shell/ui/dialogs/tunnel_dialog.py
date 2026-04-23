#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH 隧道配置对话框。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from neko_shell.models import TunnelConfig


class TunnelDialog(QDialog):
    """新增或编辑 SSH 隧道配置。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("SSH 隧道"))
        self.resize(460, 320)
        self._tunnel_id: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)

        self.name_edit = QLineEdit()
        form.addRow(self.tr("名称"), self.name_edit)

        self.connection_combo = QComboBox()
        form.addRow(self.tr("SSH 连接"), self.connection_combo)

        self.tunnel_type_combo = QComboBox()
        self.tunnel_type_combo.addItem(self.tr("本地"), "local")
        self.tunnel_type_combo.addItem(self.tr("远程"), "remote")
        self.tunnel_type_combo.addItem(self.tr("动态"), "dynamic")
        self.tunnel_type_combo.currentIndexChanged.connect(self._sync_type_visibility)
        form.addRow(self.tr("隧道类型"), self.tunnel_type_combo)

        local_layout = QHBoxLayout()
        self.local_host_edit = QLineEdit("127.0.0.1")
        self.local_port_spin = QSpinBox()
        self.local_port_spin.setRange(1, 65535)
        self.local_port_spin.setValue(1080)
        local_layout.addWidget(self.local_host_edit)
        local_layout.addWidget(QLabel(":"))
        local_layout.addWidget(self.local_port_spin)
        form.addRow(self.tr("本地绑定"), local_layout)

        remote_layout = QHBoxLayout()
        self.remote_host_edit = QLineEdit("127.0.0.1")
        self.remote_port_spin = QSpinBox()
        self.remote_port_spin.setRange(1, 65535)
        self.remote_port_spin.setValue(80)
        remote_layout.addWidget(self.remote_host_edit)
        remote_layout.addWidget(QLabel(":"))
        remote_layout.addWidget(self.remote_port_spin)
        self._remote_label = QLabel(self.tr("远程目标"))
        self._remote_layout = remote_layout
        form.addRow(self._remote_label, remote_layout)

        self.browser_url_edit = QLineEdit()
        self.browser_url_edit.setPlaceholderText("http://127.0.0.1:8080")
        form.addRow(self.tr("打开地址"), self.browser_url_edit)

        layout.addLayout(form)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._sync_type_visibility()

    def set_connections(self, connections: list[dict]) -> None:
        """设置可选 SSH 连接列表。"""
        self.connection_combo.clear()
        for connection in connections:
            self.connection_combo.addItem(connection.get("name", "未命名"), connection.get("id"))

    def set_config(self, config: TunnelConfig) -> None:
        """回填已有配置。"""
        self._tunnel_id = config.id
        self.name_edit.setText(config.name)
        self.browser_url_edit.setText(config.browser_url)
        self.local_host_edit.setText(config.local_host)
        self.local_port_spin.setValue(config.local_port)
        self.remote_host_edit.setText(config.remote_host)
        self.remote_port_spin.setValue(config.remote_port or 80)

        index = self.connection_combo.findData(config.connection_id)
        if index >= 0:
            self.connection_combo.setCurrentIndex(index)

        tunnel_index = self.tunnel_type_combo.findData(config.tunnel_type)
        if tunnel_index >= 0:
            self.tunnel_type_combo.setCurrentIndex(tunnel_index)
        self._sync_type_visibility()

    def get_config(self) -> TunnelConfig:
        """构建隧道配置对象。"""
        return TunnelConfig(
            id=self._tunnel_id or "",
            name=self.name_edit.text().strip(),
            connection_id=self.connection_combo.currentData(),
            tunnel_type=self.tunnel_type_combo.currentData(),
            local_host=self.local_host_edit.text().strip() or "127.0.0.1",
            local_port=self.local_port_spin.value(),
            remote_host=self.remote_host_edit.text().strip() or "127.0.0.1",
            remote_port=None if self.tunnel_type_combo.currentData() == "dynamic" else self.remote_port_spin.value(),
            browser_url=self.browser_url_edit.text().strip(),
        )

    def _sync_type_visibility(self) -> None:
        """动态模式下隐藏远程目标字段。"""
        is_dynamic = self.tunnel_type_combo.currentData() == "dynamic"
        self._remote_label.setVisible(not is_dynamic)
        for index in range(self._remote_layout.count()):
            widget = self._remote_layout.itemAt(index).widget()
            if widget is not None:
                widget.setVisible(not is_dynamic)
