#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
远程文本文件编辑对话框。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout


class TextFileDialog(QDialog):
    """轻量文本编辑对话框。"""

    def __init__(self, file_path: str, text: str = "", parent: Optional[QDialog] = None):
        super().__init__(parent)
        self.setWindowTitle(file_path)
        self.resize(900, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.path_label = QLabel(file_path)
        layout.addWidget(self.path_label)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(text)
        self.editor.setFont(QFont("Monospace", 10))
        layout.addWidget(self.editor)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton(self.tr("取消"))
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        self.save_button = QPushButton(self.tr("保存"))
        self.save_button.clicked.connect(self.accept)
        self.save_button.setDefault(True)
        button_layout.addWidget(self.save_button)

        layout.addLayout(button_layout)

    def text(self) -> str:
        """获取编辑后的文本。"""
        return self.editor.toPlainText()
