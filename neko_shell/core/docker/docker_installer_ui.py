#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轻量 Docker 安装器 UI。

说明：
- 该组件通过 SSH 在远端执行命令，不对本机安装 Docker
- 安装动作具有侵入性，默认需要用户确认
- 当前实现以 Debian/Ubuntu 常见的一键脚本为主，其他发行版可先用检测信息判断
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class DockerInstallerWidget(QWidget):
    """远端 Docker 安装辅助组件。"""

    def __init__(self, ssh, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._ssh = ssh
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        tips = QLabel(
            self.tr(
                "该功能会在远端服务器上执行安装命令。\n"
                "建议先确保你具备 sudo 权限，并了解目标系统发行版。"
            )
        )
        tips.setWordWrap(True)
        layout.addWidget(tips)

        row = QHBoxLayout()
        self.detect_btn = QPushButton(self.tr("检测 Docker"))
        self.detect_btn.clicked.connect(self._detect)
        row.addWidget(self.detect_btn)

        self.install_btn = QPushButton(self.tr("安装 Docker"))
        self.install_btn.clicked.connect(self._install)
        row.addWidget(self.install_btn)
        row.addStretch()
        layout.addLayout(row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(360)
        layout.addWidget(self.output, 1)

    def _append(self, text: str) -> None:
        self.output.append(text.rstrip("\n"))

    def _require_ssh(self) -> None:
        if not self._ssh or not getattr(self._ssh, "is_connected", lambda: False)():
            raise RuntimeError(self.tr("请先连接 SSH"))

    def _detect(self) -> None:
        try:
            self._require_ssh()
            self._append(self.tr("检测系统信息..."))
            os_release = self._ssh.exec("cat /etc/os-release 2>/dev/null || true", pty=False) or ""
            self._append(os_release.strip())

            self._append(self.tr("检测 Docker..."))
            version = self._ssh.exec("docker --version 2>&1 || true", pty=False) or ""
            self._append(version.strip() or self.tr("未检测到 docker 命令"))
        except Exception as exc:
            QMessageBox.critical(self, self.tr("检测失败"), str(exc))

    def _install(self) -> None:
        try:
            self._require_ssh()
            reply = QMessageBox.question(
                self,
                self.tr("确认安装"),
                self.tr(
                    "将尝试在远端执行 `curl -fsSL https://get.docker.com | sh`。\n"
                    "该操作会修改系统软件源与服务配置，确定继续吗？"
                ),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            self._append(self.tr("开始安装..."))
            # 优先使用 curl，否则尝试 wget
            cmd = (
                "set -e; "
                "if command -v curl >/dev/null 2>&1; then "
                "  curl -fsSL https://get.docker.com | sh; "
                "elif command -v wget >/dev/null 2>&1; then "
                "  wget -qO- https://get.docker.com | sh; "
                "else "
                "  echo '缺少 curl/wget，无法执行安装脚本'; exit 1; "
                "fi"
            )
            out = self._ssh.exec(cmd, pty=True) or ""
            self._append(out.strip())
            self._append(self.tr("安装命令已执行，建议再次点击“检测 Docker”确认结果。"))
        except Exception as exc:
            QMessageBox.critical(self, self.tr("安装失败"), str(exc))

