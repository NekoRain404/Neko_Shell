#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速打开对话框。

聚合连接、文件入口、工作区模板和常用页面，提供统一搜索入口。
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class QuickOpenDialog(QDialog):
    """统一快速打开面板。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._entries: list[dict[str, Any]] = []
        self._visible_entries: list[dict[str, Any]] = []
        self.search_edit: QLineEdit
        self.result_list: QListWidget
        self.summary_label: QLabel
        self.detail_label: QLabel
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建对话框界面。"""
        self.setWindowTitle(self.tr("快速打开"))
        self.setModal(True)
        self.resize(760, 560)
        self.setMinimumSize(620, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(self.tr("快速打开"), self)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(
            self.tr("搜索连接、文件入口、工作区模板和常用页面。按回车立即执行。"),
            self,
        )
        subtitle.setStyleSheet("color: palette(mid);")
        layout.addWidget(subtitle)

        self.search_edit = QLineEdit(self)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(
            self.tr("搜索名称、主机、分组、标签、模板或动作")
        )
        self.search_edit.textChanged.connect(lambda _text: self._refresh_results())
        self.search_edit.returnPressed.connect(lambda: self._accept_current_item())
        layout.addWidget(self.search_edit)

        self.summary_label = QLabel(self.tr("0 个结果"), self)
        self.summary_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.summary_label)

        self.result_list = QListWidget(self)
        self.result_list.itemActivated.connect(lambda _item: self._accept_current_item())
        self.result_list.currentItemChanged.connect(
            lambda current, previous: self._update_detail_label(current, previous)
        )
        layout.addWidget(self.result_list, 1)

        self.detail_label = QLabel(self.tr("请选择一个条目。"), self)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.detail_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(lambda: self._accept_current_item())
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_entries(self, entries: list[dict[str, Any]]) -> None:
        """设置候选条目。"""
        self._entries = [dict(entry) for entry in entries if isinstance(entry, dict)]
        self._refresh_results()

    def selected_entry(self) -> Optional[dict[str, Any]]:
        """返回当前选择的条目。"""
        item = self.result_list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        if not isinstance(index, int) or index < 0 or index >= len(self._visible_entries):
            return None
        return dict(self._visible_entries[index])

    def _refresh_results(self) -> None:
        """根据关键字刷新结果列表。"""
        keyword = self.search_edit.text().strip().casefold()
        self._visible_entries = []
        for entry in self._entries:
            searchable = str(entry.get("searchable_text") or "").casefold()
            if keyword and keyword not in searchable:
                continue
            self._visible_entries.append(entry)

        self.result_list.clear()
        for index, entry in enumerate(self._visible_entries):
            title = str(entry.get("title") or self.tr("未命名条目"))
            subtitle = str(entry.get("subtitle") or "").strip()
            item = QListWidgetItem(title, self.result_list)
            icon = entry.get("icon")
            if icon is not None:
                item.setIcon(icon)
            if subtitle:
                item.setToolTip(subtitle)
                item.setText(f"{title}\n{subtitle}")
            item.setData(Qt.UserRole, index)

        self.summary_label.setText(self.tr(f"{len(self._visible_entries)} 个结果"))
        if self.result_list.count():
            self.result_list.setCurrentRow(0)
        else:
            self.detail_label.setText(self.tr("没有匹配结果，请调整搜索条件。"))

    def _update_detail_label(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem] = None,
    ) -> None:
        """更新底部详情说明。"""
        if current is None:
            self.detail_label.setText(self.tr("没有匹配结果，请调整搜索条件。"))
            return
        entry = self.selected_entry()
        if not entry:
            self.detail_label.setText(self.tr("请选择一个条目。"))
            return
        self.detail_label.setText(str(entry.get("detail") or entry.get("subtitle") or ""))

    def _accept_current_item(self, *_args: object) -> None:
        """接受当前选择。"""
        if self.selected_entry() is None:
            return
        self.accept()
