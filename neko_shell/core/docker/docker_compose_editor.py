#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轻量 Docker Compose 编辑器。

目标：
- 不依赖旧的顶层包与额外第三方库（如 pygments）
- 通过 SSH + SFTP 读写远端 compose 文件
- 支持一键校验 `docker compose config`
"""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class DockerComposeEditor(QWidget):
    """远端 docker-compose 文件编辑器。"""

    def __init__(self, ssh, compose_path: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._ssh = ssh
        self._compose_path = compose_path or ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.tr("Docker Compose 编辑器"))
        layout = QVBoxLayout(self)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel(self.tr("Compose 路径")))
        self.path_edit = QLineEdit(self._compose_path)
        self.path_edit.setPlaceholderText("/srv/app/docker-compose.yml")
        path_row.addWidget(self.path_edit, 1)
        self.load_btn = QPushButton(self.tr("加载"))
        self.load_btn.clicked.connect(self._load)
        path_row.addWidget(self.load_btn)
        self.save_btn = QPushButton(self.tr("保存"))
        self.save_btn.clicked.connect(self._save)
        path_row.addWidget(self.save_btn)
        self.validate_btn = QPushButton(self.tr("校验"))
        self.validate_btn.clicked.connect(self._validate)
        path_row.addWidget(self.validate_btn)
        layout.addLayout(path_row)

        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        self.editor.setFont(font)
        layout.addWidget(self.editor, 1)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(160)
        self.output.setFont(font)
        layout.addWidget(self.output)

    def _compose_path_value(self) -> str:
        value = self.path_edit.text().strip()
        return value

    def _append_output(self, text: str) -> None:
        self.output.append(text.rstrip("\n"))

    def _require_ssh(self) -> None:
        if not self._ssh or not getattr(self._ssh, "is_connected", lambda: False)():
            raise RuntimeError(self.tr("请先连接 SSH"))

    def _normalize_remote_path(self, path: str) -> str:
        # 仅做最小规范化，避免把 Windows 路径误当成远端路径。
        return str(PurePosixPath(path))

    def _load(self) -> None:
        try:
            self._require_ssh()
            remote_path = self._compose_path_value()
            if not remote_path:
                QMessageBox.information(self, self.tr("提示"), self.tr("请先填写 compose 文件路径"))
                return
            remote_path = self._normalize_remote_path(remote_path)
            sftp = self._ssh.open_sftp()
            with sftp.open(remote_path, "r") as fh:
                content = fh.read().decode("utf-8", errors="replace")
            self.editor.setPlainText(content)
            self._append_output(self.tr(f"已加载: {remote_path}"))
        except Exception as exc:
            QMessageBox.critical(self, self.tr("加载失败"), str(exc))

    def _save(self) -> None:
        try:
            self._require_ssh()
            remote_path = self._compose_path_value()
            if not remote_path:
                QMessageBox.information(self, self.tr("提示"), self.tr("请先填写 compose 文件路径"))
                return
            remote_path = self._normalize_remote_path(remote_path)
            content = self.editor.toPlainText()
            sftp = self._ssh.open_sftp()
            with sftp.open(remote_path, "w") as fh:
                fh.write(content.encode("utf-8"))
            self._append_output(self.tr(f"已保存: {remote_path}"))
        except Exception as exc:
            QMessageBox.critical(self, self.tr("保存失败"), str(exc))

    def _validate(self) -> None:
        try:
            self._require_ssh()
            remote_path = self._compose_path_value()
            if not remote_path:
                QMessageBox.information(self, self.tr("提示"), self.tr("请先填写 compose 文件路径"))
                return
            remote_path = self._normalize_remote_path(remote_path)
            cmd = f"docker compose --file {shlex.quote(remote_path)} config 2>&1 || true"
            out = self._ssh.exec(cmd, pty=False)
            self._append_output(self.tr("校验输出:"))
            self._append_output(out or "")
        except Exception as exc:
            QMessageBox.critical(self, self.tr("校验失败"), str(exc))

