#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快捷命令中心对话框。

聚合收藏命令、片段与宏，支持搜索、预览、立即执行、编排发送与复制。
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class CommandCenterDialog(QDialog):
    """快捷命令中心。"""

    MODE_NONE = "none"
    MODE_EXECUTE = "execute"
    MODE_COMPOSE = "compose"
    MODE_COPY = "copy"
    MODE_FAVORITE = "favorite"
    MODE_MACRO = "macro"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        initial_query: str = "",
    ) -> None:
        super().__init__(parent)
        self._entries: list[dict[str, Any]] = []
        self._visible_entries: list[dict[str, Any]] = []
        self._selected_mode = self.MODE_NONE
        self.search_edit: QLineEdit
        self.summary_label: QLabel
        self.result_list: QListWidget
        self.detail_label: QLabel
        self.preview_edit: QPlainTextEdit
        self.execute_button: QPushButton
        self.compose_button: QPushButton
        self.copy_button: QPushButton
        self.favorite_button: QPushButton
        self.macro_button: QPushButton
        self._setup_ui(initial_query)

    def _setup_ui(self, initial_query: str) -> None:
        """构建对话框界面。"""
        self.setWindowTitle(self.tr("快捷命令中心"))
        self.setModal(True)
        self.resize(860, 600)
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(self.tr("快捷命令中心"), self)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(
            self.tr("搜索收藏命令、片段和命令宏。可立即执行、转入编排发送，或直接复制。"),
            self,
        )
        subtitle.setStyleSheet("color: palette(mid);")
        layout.addWidget(subtitle)

        self.search_edit = QLineEdit(self)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(self.tr("搜索命令、分组、宏名或来源"))
        self.search_edit.setText(initial_query)
        self.search_edit.textChanged.connect(lambda _text: self._refresh_results())
        self.search_edit.returnPressed.connect(lambda: self._accept_with_mode(self.MODE_EXECUTE))
        layout.addWidget(self.search_edit)

        self.summary_label = QLabel(self.tr("0 个结果"), self)
        self.summary_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.summary_label)

        body = QHBoxLayout()
        body.setSpacing(10)
        layout.addLayout(body, 1)

        self.result_list = QListWidget(self)
        self.result_list.itemActivated.connect(
            lambda _item: self._accept_with_mode(self.MODE_EXECUTE)
        )
        self.result_list.currentItemChanged.connect(
            lambda current, previous: self._update_detail(current, previous)
        )
        body.addWidget(self.result_list, 4)

        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        body.addWidget(right_panel, 5)

        self.detail_label = QLabel(self.tr("请选择一项命令。"), right_panel)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: palette(mid);")
        right_layout.addWidget(self.detail_label)

        preview_title = QLabel(self.tr("命令预览"), right_panel)
        preview_title.setStyleSheet("font-weight: 700;")
        right_layout.addWidget(preview_title)

        self.preview_edit = QPlainTextEdit(right_panel)
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setPlaceholderText(self.tr("选择命令后可在此预览内容"))
        right_layout.addWidget(self.preview_edit, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.execute_button = QPushButton(self.tr("立即执行"), right_panel)
        self.execute_button.clicked.connect(lambda: self._accept_with_mode(self.MODE_EXECUTE))
        button_row.addWidget(self.execute_button)

        self.compose_button = QPushButton(self.tr("编排发送"), right_panel)
        self.compose_button.clicked.connect(lambda: self._accept_with_mode(self.MODE_COMPOSE))
        button_row.addWidget(self.compose_button)

        self.copy_button = QPushButton(self.tr("复制命令"), right_panel)
        self.copy_button.clicked.connect(lambda: self._accept_with_mode(self.MODE_COPY))
        button_row.addWidget(self.copy_button)
        self.favorite_button = QPushButton(self.tr("加入收藏"), right_panel)
        self.favorite_button.clicked.connect(lambda: self._accept_with_mode(self.MODE_FAVORITE))
        button_row.addWidget(self.favorite_button)

        self.macro_button = QPushButton(self.tr("保存为宏"), right_panel)
        self.macro_button.clicked.connect(lambda: self._accept_with_mode(self.MODE_MACRO))
        button_row.addWidget(self.macro_button)

        cancel_button = QPushButton(self.tr("取消"), right_panel)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        right_layout.addLayout(button_row)

    def set_entries(self, entries: list[dict[str, Any]]) -> None:
        """设置候选条目。"""
        self._entries = [dict(entry) for entry in entries if isinstance(entry, dict)]
        self._refresh_results()

    def selected_entry(self) -> Optional[dict[str, Any]]:
        """返回当前选中条目。"""
        item = self.result_list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        if not isinstance(index, int) or index < 0 or index >= len(self._visible_entries):
            return None
        return dict(self._visible_entries[index])

    def selected_mode(self) -> str:
        """返回本次选择的动作模式。"""
        return self._selected_mode

    def _refresh_results(self) -> None:
        """根据关键字刷新结果。"""
        keyword = self.search_edit.text().strip().casefold()
        self._visible_entries = []
        for entry in self._entries:
            searchable = str(entry.get("searchable_text") or "").casefold()
            if keyword and keyword not in searchable:
                continue
            self._visible_entries.append(entry)

        self.result_list.clear()
        for index, entry in enumerate(self._visible_entries):
            title = str(entry.get("title") or self.tr("未命名命令"))
            subtitle = str(entry.get("subtitle") or "").strip()
            item = QListWidgetItem(title, self.result_list)
            icon = entry.get("icon")
            if icon is not None:
                item.setIcon(icon)
            if subtitle:
                item.setText(f"{title}\n{subtitle}")
                item.setToolTip(subtitle)
            item.setData(Qt.UserRole, index)

        self.summary_label.setText(self.tr(f"{len(self._visible_entries)} 个结果"))
        has_items = bool(self.result_list.count())
        self.execute_button.setEnabled(has_items)
        self.compose_button.setEnabled(has_items)
        self.copy_button.setEnabled(has_items)
        self.favorite_button.setEnabled(has_items)
        self.macro_button.setEnabled(has_items)
        if has_items:
            self.result_list.setCurrentRow(0)
        else:
            self.preview_edit.clear()
            self.detail_label.setText(self.tr("没有匹配结果，请调整搜索条件。"))

    def _update_detail(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem] = None,
    ) -> None:
        """更新详情和预览。"""
        if current is None:
            self.detail_label.setText(self.tr("没有匹配结果，请调整搜索条件。"))
            self.preview_edit.clear()
            return
        entry = self.selected_entry()
        if not entry:
            self.detail_label.setText(self.tr("请选择一项命令。"))
            self.preview_edit.clear()
            return
        self.detail_label.setText(str(entry.get("detail") or entry.get("subtitle") or ""))
        commands = [
            str(command).strip()
            for command in (entry.get("commands") or [])
            if str(command).strip()
        ]
        self.preview_edit.setPlainText("\n".join(commands))

    def _accept_with_mode(self, mode: str) -> None:
        """按指定模式接受当前条目。"""
        if self.selected_entry() is None:
            return
        self._selected_mode = mode
        self.accept()
