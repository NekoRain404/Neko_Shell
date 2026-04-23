#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端编排发送对话框。

用于录入多行命令，并将片段/宏快速组织成可批量发送的命令列表。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class ComposeCommandDialog(QDialog):
    """终端多行编排发送对话框。"""

    FAVORITE_GROUP_LABEL = "收藏"

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        initial_text: str = "",
        title_text: Optional[str] = None,
        summary_text: Optional[str] = None,
        snippet_groups: Optional[dict[str, list[str]]] = None,
        favorite_snippets: Optional[list[str]] = None,
        macros: Optional[dict[str, list[str]]] = None,
        template_choices: Optional[list[dict[str, object]]] = None,
        current_template_label: Optional[str] = None,
        target_scope_choices: Optional[list[tuple[str, str]]] = None,
        current_target_scope: Optional[str] = None,
        target_type_choices: Optional[list[tuple[str, str]]] = None,
        current_target_type: Optional[str] = None,
        target_group_choices: Optional[list[tuple[str, str]]] = None,
        current_target_group: Optional[str] = None,
        target_preview_text: Optional[str] = None,
        target_preview_map: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(parent)
        self.editor: QPlainTextEdit
        self.skip_blank_lines_check: QCheckBox
        self.summary_label: QLabel
        self.stats_label: QLabel
        self.template_combo: Optional[QComboBox]
        self.template_preview: Optional[QPlainTextEdit]
        self.target_scope_combo: Optional[QComboBox]
        self.target_type_combo: Optional[QComboBox]
        self.target_group_combo: Optional[QComboBox]
        self.target_preview_label: Optional[QLabel]
        self.snippet_group_combo: QComboBox
        self.snippet_list: QListWidget
        self.macro_list: QListWidget
        self.macro_preview: QPlainTextEdit
        self._target_scope_choices = list(target_scope_choices or [])
        self._current_target_scope = current_target_scope
        self._target_type_choices = list(target_type_choices or [])
        self._current_target_type = current_target_type
        self._target_group_choices = list(target_group_choices or [])
        self._current_target_group = current_target_group
        self._target_preview_text = target_preview_text or ""
        self._target_preview_map = dict(target_preview_map or {})
        self._template_choices = [
            dict(template)
            for template in (template_choices or [])
            if isinstance(template, dict) and template.get("label")
        ]
        self._current_template_label = current_template_label

        self._snippet_groups = {
            (group_name or "").strip(): [
                command.strip()
                for command in (commands or [])
                if isinstance(command, str) and command.strip()
            ]
            for group_name, commands in (snippet_groups or {}).items()
            if isinstance(group_name, str) and group_name.strip()
        }
        self._favorite_snippets = [
            command.strip()
            for command in (favorite_snippets or [])
            if isinstance(command, str) and command.strip()
        ]
        self._macros = {
            (macro_name or "").strip(): [
                command.strip()
                for command in (commands or [])
                if isinstance(command, str) and command.strip()
            ]
            for macro_name, commands in (macros or {}).items()
            if isinstance(macro_name, str) and macro_name.strip()
        }

        self._setup_ui(initial_text, title_text=title_text, summary_text=summary_text)
        self._refresh_snippet_groups()
        self._refresh_macro_list()
        self._refresh_target_controls()
        self._update_stats()

    def _setup_ui(
        self,
        initial_text: str,
        *,
        title_text: Optional[str],
        summary_text: Optional[str],
    ) -> None:
        """构建对话框界面。"""
        self.setWindowTitle(title_text or self.tr("编排发送"))
        self.setModal(True)
        self.resize(860, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.summary_label = QLabel(
            summary_text or self.tr("左侧可插入片段或命令宏，右侧用于整理最终发送内容。"),
            self,
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.template_combo = None
        self.template_preview = None
        if self._template_choices:
            template_panel = QWidget(self)
            template_layout = QVBoxLayout(template_panel)
            template_layout.setContentsMargins(0, 0, 0, 0)
            template_layout.setSpacing(6)

            template_title = QLabel(self.tr("任务模板"), template_panel)
            template_title.setStyleSheet("font-weight: 700;")
            template_layout.addWidget(template_title)

            template_row = QHBoxLayout()
            template_row.setSpacing(8)
            template_row.addWidget(QLabel(self.tr("模板"), template_panel))
            self.template_combo = QComboBox(template_panel)
            self.template_combo.currentIndexChanged.connect(self._refresh_template_preview)
            template_row.addWidget(self.template_combo, 1)
            apply_template_button = QPushButton(self.tr("应用模板"), template_panel)
            apply_template_button.clicked.connect(self._apply_selected_template)
            template_row.addWidget(apply_template_button)
            template_layout.addLayout(template_row)

            self.template_preview = QPlainTextEdit(template_panel)
            self.template_preview.setReadOnly(True)
            self.template_preview.setMaximumHeight(120)
            template_layout.addWidget(self.template_preview)
            layout.addWidget(template_panel)

        self.target_scope_combo = None
        self.target_type_combo = None
        self.target_group_combo = None
        self.target_preview_label = None
        if self._target_scope_choices or self._target_type_choices or self._target_group_choices:
            target_panel = QWidget(self)
            target_layout = QVBoxLayout(target_panel)
            target_layout.setContentsMargins(0, 0, 0, 0)
            target_layout.setSpacing(6)

            target_title = QLabel(self.tr("发送目标"), target_panel)
            target_title.setStyleSheet("font-weight: 700;")
            target_layout.addWidget(target_title)

            target_row = QHBoxLayout()
            target_row.setSpacing(8)
            if self._target_scope_choices:
                target_row.addWidget(QLabel(self.tr("范围"), target_panel))
                self.target_scope_combo = QComboBox(target_panel)
                self.target_scope_combo.currentIndexChanged.connect(self._refresh_target_preview)
                target_row.addWidget(self.target_scope_combo)
            if self._target_type_choices:
                target_row.addWidget(QLabel(self.tr("类型"), target_panel))
                self.target_type_combo = QComboBox(target_panel)
                self.target_type_combo.currentIndexChanged.connect(self._refresh_target_preview)
                target_row.addWidget(self.target_type_combo)
            if self._target_group_choices:
                target_row.addWidget(QLabel(self.tr("分组"), target_panel))
                self.target_group_combo = QComboBox(target_panel)
                self.target_group_combo.currentIndexChanged.connect(self._refresh_target_preview)
                target_row.addWidget(self.target_group_combo)
            target_row.addStretch(1)
            target_layout.addLayout(target_row)

            self.target_preview_label = QLabel(target_panel)
            self.target_preview_label.setWordWrap(True)
            self.target_preview_label.setStyleSheet("color: palette(mid);")
            target_layout.addWidget(self.target_preview_label)
            layout.addWidget(target_panel)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        library_panel = QWidget(splitter)
        library_layout = QVBoxLayout(library_panel)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(10)

        snippet_title = QLabel(self.tr("命令片段"), library_panel)
        snippet_title.setStyleSheet("font-weight: 700;")
        library_layout.addWidget(snippet_title)

        self.snippet_group_combo = QComboBox(library_panel)
        self.snippet_group_combo.currentIndexChanged.connect(
            self._refresh_snippet_list
        )
        library_layout.addWidget(self.snippet_group_combo)

        self.snippet_list = QListWidget(library_panel)
        self.snippet_list.itemDoubleClicked.connect(
            lambda _item: self._insert_selected_snippets()
        )
        library_layout.addWidget(self.snippet_list, 1)

        snippet_button_row = QHBoxLayout()
        snippet_button_row.setSpacing(8)
        insert_selected_button = QPushButton(self.tr("插入选中命令"), library_panel)
        insert_selected_button.clicked.connect(self._insert_selected_snippets)
        snippet_button_row.addWidget(insert_selected_button)
        insert_group_button = QPushButton(self.tr("插入整组"), library_panel)
        insert_group_button.clicked.connect(self._insert_current_group)
        snippet_button_row.addWidget(insert_group_button)
        library_layout.addLayout(snippet_button_row)

        macro_title = QLabel(self.tr("命令宏"), library_panel)
        macro_title.setStyleSheet("font-weight: 700;")
        library_layout.addWidget(macro_title)

        self.macro_list = QListWidget(library_panel)
        self.macro_list.currentItemChanged.connect(self._refresh_macro_preview)
        self.macro_list.itemDoubleClicked.connect(
            lambda _item: self._insert_selected_macro()
        )
        library_layout.addWidget(self.macro_list, 1)

        self.macro_preview = QPlainTextEdit(library_panel)
        self.macro_preview.setReadOnly(True)
        self.macro_preview.setPlaceholderText(self.tr("选择宏后可在此预览命令列表"))
        self.macro_preview.setMaximumHeight(140)
        library_layout.addWidget(self.macro_preview)

        insert_macro_button = QPushButton(self.tr("插入选中宏"), library_panel)
        insert_macro_button.clicked.connect(self._insert_selected_macro)
        library_layout.addWidget(insert_macro_button)

        editor_panel = QWidget(splitter)
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(10)

        editor_title = QLabel(self.tr("待发送命令"), editor_panel)
        editor_title.setStyleSheet("font-weight: 700;")
        editor_layout.addWidget(editor_title)

        self.editor = QPlainTextEdit(editor_panel)
        self.editor.setPlaceholderText(
            self.tr("例如:\nwhoami\nhostname\nuptime\nfree -h")
        )
        self.editor.setPlainText(initial_text)
        self.editor.textChanged.connect(self._update_stats)
        editor_layout.addWidget(self.editor, 1)

        self.skip_blank_lines_check = QCheckBox(self.tr("忽略空行"), editor_panel)
        self.skip_blank_lines_check.setChecked(True)
        self.skip_blank_lines_check.toggled.connect(self._update_stats)
        editor_layout.addWidget(self.skip_blank_lines_check)

        self.stats_label = QLabel("", editor_panel)
        self.stats_label.setStyleSheet("color: palette(mid);")
        editor_layout.addWidget(self.stats_label)

        splitter.addWidget(library_panel)
        splitter.addWidget(editor_panel)
        splitter.setSizes([300, 520])

        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        button_box.button(QDialogButtonBox.Ok).setText(self.tr("发送"))
        button_box.button(QDialogButtonBox.Cancel).setText(self.tr("取消"))
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _refresh_snippet_groups(self) -> None:
        """刷新片段分组下拉框。"""
        current_group = self.snippet_group_combo.currentText().strip()
        group_names = list(self._snippet_groups.keys())
        if self._favorite_snippets:
            group_names.insert(0, self.FAVORITE_GROUP_LABEL)

        self.snippet_group_combo.blockSignals(True)
        self.snippet_group_combo.clear()
        self.snippet_group_combo.addItems(group_names)
        if current_group and current_group in group_names:
            self.snippet_group_combo.setCurrentText(current_group)
        self.snippet_group_combo.blockSignals(False)
        self._refresh_snippet_list()

    def _current_group_commands(self) -> list[str]:
        """返回当前分组对应的命令列表。"""
        group_name = self.snippet_group_combo.currentText().strip()
        if not group_name:
            return []
        if group_name == self.FAVORITE_GROUP_LABEL:
            return list(self._favorite_snippets)
        return list(self._snippet_groups.get(group_name, []))

    def _refresh_snippet_list(self) -> None:
        """刷新片段列表。"""
        commands = self._current_group_commands()
        self.snippet_list.clear()
        for command in commands:
            self.snippet_list.addItem(command)

    def _refresh_macro_list(self) -> None:
        """刷新宏列表。"""
        macro_names = list(self._macros.keys())
        self.macro_list.clear()
        for macro_name in macro_names:
            item = QListWidgetItem(macro_name, self.macro_list)
            item.setData(Qt.UserRole, list(self._macros.get(macro_name, [])))
        if macro_names:
            self.macro_list.setCurrentRow(0)
        else:
            self.macro_preview.clear()

    def _refresh_target_controls(self) -> None:
        """刷新目标控制项。"""
        if self.template_combo is not None:
            self.template_combo.blockSignals(True)
            self.template_combo.clear()
            for template in self._template_choices:
                self.template_combo.addItem(str(template.get("label", "")), dict(template))
            if self._current_template_label:
                index = self.template_combo.findText(self._current_template_label)
                if index >= 0:
                    self.template_combo.setCurrentIndex(index)
            self.template_combo.blockSignals(False)
            self._refresh_template_preview()

        if self.target_scope_combo is not None:
            self.target_scope_combo.blockSignals(True)
            self.target_scope_combo.clear()
            for label, value in self._target_scope_choices:
                self.target_scope_combo.addItem(label, value)
            if self._current_target_scope is not None:
                index = self.target_scope_combo.findData(self._current_target_scope)
                if index >= 0:
                    self.target_scope_combo.setCurrentIndex(index)
            self.target_scope_combo.blockSignals(False)

        if self.target_type_combo is not None:
            self.target_type_combo.blockSignals(True)
            self.target_type_combo.clear()
            for label, value in self._target_type_choices:
                self.target_type_combo.addItem(label, value)
            if self._current_target_type is not None:
                index = self.target_type_combo.findData(self._current_target_type)
                if index >= 0:
                    self.target_type_combo.setCurrentIndex(index)
            self.target_type_combo.blockSignals(False)

        if self.target_group_combo is not None:
            self.target_group_combo.blockSignals(True)
            self.target_group_combo.clear()
            for label, value in self._target_group_choices:
                self.target_group_combo.addItem(label, value)
            if self._current_target_group is not None:
                index = self.target_group_combo.findData(self._current_target_group)
                if index >= 0:
                    self.target_group_combo.setCurrentIndex(index)
            self.target_group_combo.blockSignals(False)

        self._refresh_target_preview()

    def _refresh_target_preview(self) -> None:
        """刷新目标预览。"""
        if self.target_preview_label is None:
            return
        preview_key = self._target_preview_key()
        preview_text = self._target_preview_map.get(preview_key, self._target_preview_text)
        self.target_preview_label.setText(
            preview_text or self.tr("可按范围和终端类型限制本次批量发送。")
        )

    def _refresh_template_preview(self) -> None:
        """刷新模板预览。"""
        if self.template_preview is None:
            return
        template = self.selected_template()
        if not template:
            self.template_preview.clear()
            return
        summary = str(template.get("summary", "") or "").strip()
        commands = template.get("commands", [])
        if not isinstance(commands, list):
            commands = []
        command_block = "\n".join(
            command.strip()
            for command in commands
            if isinstance(command, str) and command.strip()
        )
        self.template_preview.setPlainText(
            "\n\n".join(block for block in [summary, command_block] if block)
        )

    def _apply_selected_template(self) -> None:
        """把当前选择的模板应用到编辑区。"""
        template = self.selected_template()
        if not template:
            return
        commands = template.get("commands", [])
        if not isinstance(commands, list):
            return
        normalized = [
            command.strip()
            for command in commands
            if isinstance(command, str) and command.strip()
        ]
        self.editor.setPlainText("\n".join(normalized))
        self._update_stats()

    def _target_preview_key(self) -> str:
        """返回当前目标预览键。"""
        scope = self.selected_target_scope() or ""
        target_type = self.selected_target_type() or ""
        target_group = self.selected_target_group() or ""
        return f"{scope}::{target_type}::{target_group}"

    def _refresh_macro_preview(self) -> None:
        """刷新宏预览文本。"""
        item = self.macro_list.currentItem()
        commands = item.data(Qt.UserRole) if item else []
        if not isinstance(commands, list):
            commands = []
        self.macro_preview.setPlainText("\n".join(commands))

    def _append_commands(self, commands: list[str]) -> None:
        """将命令追加到编辑区。"""
        normalized = [command.strip() for command in commands if isinstance(command, str) and command.strip()]
        if not normalized:
            return

        existing = self.editor.toPlainText().rstrip("\n")
        new_block = "\n".join(normalized)
        if existing:
            self.editor.setPlainText(f"{existing}\n{new_block}")
        else:
            self.editor.setPlainText(new_block)
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus(Qt.OtherFocusReason)
        self._update_stats()

    def _insert_selected_snippets(self) -> None:
        """插入当前选中的命令片段。"""
        commands = [
            item.text().strip()
            for item in self.snippet_list.selectedItems()
            if item.text().strip()
        ]
        self._append_commands(commands)

    def _insert_current_group(self) -> None:
        """插入当前分组中的全部命令。"""
        self._append_commands(self._current_group_commands())

    def _insert_selected_macro(self) -> None:
        """插入当前选中的命令宏。"""
        item = self.macro_list.currentItem()
        if item is None:
            return
        commands = item.data(Qt.UserRole)
        if not isinstance(commands, list):
            return
        self._append_commands(commands)

    def _effective_commands(self) -> list[str]:
        """返回按当前选项过滤后的有效命令。"""
        lines = self.editor.toPlainText().splitlines()
        if self.skip_blank_lines_check.isChecked():
            return [line.strip() for line in lines if line.strip()]
        return [line.rstrip() for line in lines]

    def _update_stats(self) -> None:
        """刷新命令统计信息。"""
        total_lines = len(self.editor.toPlainText().splitlines())
        effective_lines = len(self._effective_commands())
        self.stats_label.setText(
            self.tr(f"共 {total_lines} 行，实际将发送 {effective_lines} 条命令")
        )

    def commands(self) -> list[str]:
        """返回规整后的命令列表。"""
        return self._effective_commands()

    def selected_target_scope(self) -> Optional[str]:
        """返回当前选中的目标范围。"""
        if self.target_scope_combo is None:
            return None
        value = self.target_scope_combo.currentData()
        return value if isinstance(value, str) else None

    def selected_target_type(self) -> Optional[str]:
        """返回当前选中的目标类型。"""
        if self.target_type_combo is None:
            return None
        value = self.target_type_combo.currentData()
        return value if isinstance(value, str) else None

    def selected_target_group(self) -> Optional[str]:
        """返回当前选中的目标分组。"""
        if self.target_group_combo is None:
            return None
        value = self.target_group_combo.currentData()
        return value if isinstance(value, str) else None

    def selected_template(self) -> Optional[dict[str, object]]:
        """返回当前选中的模板。"""
        if self.template_combo is None:
            return None
        value = self.template_combo.currentData()
        return dict(value) if isinstance(value, dict) else None

    def selected_template_label(self) -> Optional[str]:
        """返回当前选中的模板名称。"""
        template = self.selected_template()
        if not template:
            return None
        label = str(template.get("label", "") or "").strip()
        return label or None
