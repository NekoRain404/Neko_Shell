#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件浏览器组件

提供远程文件浏览和管理功能。
"""

import posixpath
import os
from collections import deque
from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeView,
    QAbstractItemView,
    QToolBar,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QApplication,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QFileDialog,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
    QProgressBar,
    QHeaderView,
    QFrame,
    QSplitter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPlainTextEdit,
)
from PySide6.QtCore import Qt, Signal, QModelIndex, QItemSelectionModel, QTimer, QEvent
from PySide6.QtGui import QAction, QIcon, QStandardItemModel, QStandardItem

from typing import Callable, Optional, List
from pathlib import Path

from neko_shell.core.connection import BaseConnection, ConnectionType
from neko_shell.models.connection import FTPFileItem
from neko_shell.ui.icons import icon
from neko_shell.utils import get_logger

from ..dialogs.text_file_dialog import TextFileDialog


class TransferCanceled(Exception):
    """用户主动取消传输任务。"""


class ConflictResolutionCanceled(Exception):
    """用户在冲突处理对话框中取消。"""


@dataclass
class TransferTask:
    """传输任务。"""

    task_id: str
    operation: str
    display_name: str
    title: str
    label: str
    runner: Callable[[Callable[[int, int], bool]], None]
    success_payload: str
    attempt: int = 0
    max_retries: int = 2
    status: str = "queued"
    last_error: str = ""
    progress_percent: int = 0
    batch_id: int = 0
    batch_label: str = ""


class FilePropertiesDialog(QDialog):
    """文件属性对话框。"""

    def __init__(
        self,
        remote_path: str,
        item: FTPFileItem,
        *,
        allow_chmod: bool,
        allow_chown: bool,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._allow_chmod = allow_chmod
        self._allow_chown = allow_chown
        self.setWindowTitle(self.tr("文件属性"))
        self.setModal(True)
        self.resize(520, 320)
        self._initial_permission = self._default_permission_value(item.permissions)
        self._initial_owner = (item.owner or "").strip()
        self._initial_group = (item.group or "").strip()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        layout.addLayout(form)

        self.name_label = QLabel(item.name or "-")
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.tr("名称"), self.name_label)

        self.path_label = QLabel(remote_path or "-")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        form.addRow(self.tr("路径"), self.path_label)

        self.type_label = QLabel(self.tr("目录") if item.is_dir else self.tr("文件"))
        form.addRow(self.tr("类型"), self.type_label)

        self.size_label = QLabel(self.tr("<DIR>") if item.is_dir else self._format_size(item.size))
        form.addRow(self.tr("大小"), self.size_label)

        self.modify_time_label = QLabel(item.modify_time or "-")
        self.modify_time_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.tr("修改时间"), self.modify_time_label)

        self.owner_label = QLabel(item.owner or "-")
        self.owner_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.tr("所有者"), self.owner_label)

        self.group_label = QLabel(item.group or "-")
        self.group_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.tr("属组"), self.group_label)

        self.permission_input = QLineEdit(self._initial_permission)
        self.permission_input.setPlaceholderText(self.tr("八进制权限，例如 755"))
        self.permission_input.setEnabled(allow_chmod)
        form.addRow(self.tr("权限"), self.permission_input)

        self.owner_input = QLineEdit(self._initial_owner)
        self.owner_input.setPlaceholderText(self.tr("数字 UID，例如 1000"))
        self.owner_input.setEnabled(allow_chown)
        form.addRow(self.tr("编辑所有者"), self.owner_input)

        self.group_input = QLineEdit(self._initial_group)
        self.group_input.setPlaceholderText(self.tr("数字 GID，例如 1000"))
        self.group_input.setEnabled(allow_chown)
        form.addRow(self.tr("编辑属组"), self.group_input)

        self.permission_hint = QLabel(self._hint_text())
        self.permission_hint.setWordWrap(True)
        layout.addWidget(self.permission_hint)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Close)
        if allow_chmod:
            self.apply_button = self.button_box.addButton(
                self.tr("应用权限"),
                QDialogButtonBox.AcceptRole,
            )
        else:
            self.apply_button = None
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)

    @staticmethod
    def _format_size(size: int) -> str:
        """格式化大小。"""
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(max(size, 0))
        unit = units[0]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                break
            value /= 1024
        if unit == "B":
            return f"{int(value)} {unit}"
        return f"{value:.1f} {unit}"

    @staticmethod
    def _default_permission_value(permissions: Optional[str]) -> str:
        """从现有权限字符串推导默认输入值。"""
        if not permissions:
            return ""
        normalized = permissions.strip()
        if normalized.startswith("0o"):
            normalized = normalized[2:]
        if normalized.isdigit() and all(char in "01234567" for char in normalized):
            return normalized
        if len(normalized) >= 10 and normalized[0] in {"d", "-"}:
            try:
                return oct(FileBrowserWidget._permission_text_to_mode(normalized))[2:]
            except ValueError:
                return normalized
        return normalized

    def permission_mode(self) -> str:
        """返回用户填写的权限值。"""
        return self.permission_input.text().strip()

    def owner_value(self) -> str:
        """返回用户填写的所有者。"""
        return self.owner_input.text().strip()

    def group_value(self) -> str:
        """返回用户填写的属组。"""
        return self.group_input.text().strip()

    def initial_permission_mode(self) -> str:
        """返回初始权限值。"""
        return self._initial_permission

    def initial_owner_value(self) -> str:
        """返回初始所有者值。"""
        return self._initial_owner

    def initial_group_value(self) -> str:
        """返回初始属组值。"""
        return self._initial_group

    def _hint_text(self) -> str:
        """返回属性编辑提示文案。"""
        hints = []
        if self._allow_chmod:
            hints.append(self.tr("支持八进制权限输入，例如 644、755。"))
        if self._allow_chown:
            hints.append(self.tr("属主/属组当前仅支持输入数字 UID/GID。"))
        if not hints:
            hints.append(self.tr("当前连接仅支持查看属性，不支持直接修改权限或属主属组。"))
        return " ".join(hints)


class TransferBatchHistoryDialog(QDialog):
    """传输批次历史与诊断对话框。"""

    def __init__(
        self,
        batch_entries: list[dict[str, object]],
        diagnostics_text: str,
        retry_failed_callback: Optional[Callable[[int], int]] = None,
        retry_incomplete_callback: Optional[Callable[[int], int]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._batch_entries = list(batch_entries)
        self._current_report = ""
        self._retry_failed_callback = retry_failed_callback
        self._retry_incomplete_callback = retry_incomplete_callback
        self.setWindowTitle(self.tr("传输批次历史"))
        self.resize(900, 560)

        layout = QVBoxLayout(self)

        self.diagnostics_label = QLabel(diagnostics_text or self.tr("暂无批次统计"))
        self.diagnostics_label.setWordWrap(True)
        self.diagnostics_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.diagnostics_label)

        content_splitter = QSplitter(Qt.Horizontal)
        self.batch_list = QListWidget()
        self.batch_list.setMinimumWidth(280)
        content_splitter.addWidget(self.batch_list)

        self.detail_edit = QPlainTextEdit()
        self.detail_edit.setReadOnly(True)
        content_splitter.addWidget(self.detail_edit)
        content_splitter.setSizes([320, 560])
        layout.addWidget(content_splitter, 1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Close)
        self.copy_summary_button = self.button_box.addButton(
            self.tr("复制总览"),
            QDialogButtonBox.ActionRole,
        )
        self.export_summary_button = self.button_box.addButton(
            self.tr("导出总览"),
            QDialogButtonBox.ActionRole,
        )
        self.copy_button = self.button_box.addButton(
            self.tr("复制报告"),
            QDialogButtonBox.ActionRole,
        )
        self.retry_failed_button = self.button_box.addButton(
            self.tr("重试失败项"),
            QDialogButtonBox.ActionRole,
        )
        self.retry_incomplete_button = self.button_box.addButton(
            self.tr("重试未完成项"),
            QDialogButtonBox.ActionRole,
        )
        self.export_button = self.button_box.addButton(
            self.tr("导出报告"),
            QDialogButtonBox.ActionRole,
        )
        self.button_box.rejected.connect(self.reject)
        self.copy_summary_button.clicked.connect(self._copy_summary)
        self.export_summary_button.clicked.connect(self._export_summary)
        self.copy_button.clicked.connect(self._copy_report)
        self.retry_failed_button.clicked.connect(self._retry_failed)
        self.retry_incomplete_button.clicked.connect(self._retry_incomplete)
        self.export_button.clicked.connect(self._export_report)
        layout.addWidget(self.button_box)

        self.batch_list.currentRowChanged.connect(self._on_batch_changed)
        self._populate_batches()

    def _populate_batches(self) -> None:
        """填充批次列表。"""
        self.batch_list.clear()
        for entry in self._batch_entries:
            self.batch_list.addItem(str(entry.get("title") or self.tr("未知批次")))
        if self._batch_entries:
            self.batch_list.setCurrentRow(0)
        else:
            self.detail_edit.setPlainText(self.tr("暂无批次记录"))
            self.copy_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.retry_failed_button.setEnabled(False)
            self.retry_incomplete_button.setEnabled(False)

    def _copy_summary(self) -> None:
        """复制总览摘要。"""
        summary = self.diagnostics_label.text().strip()
        if summary:
            QApplication.clipboard().setText(summary)

    def _export_summary(self) -> None:
        """导出总览与全部批次报告。"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出批次总览"),
            "transfer-batch-summary.txt",
            self.tr("文本文件 (*.txt)"),
        )
        if not file_path:
            return
        sections = [self.diagnostics_label.text().strip() or self.tr("暂无批次统计")]
        for entry in self._batch_entries:
            report = str(entry.get("report") or "").strip()
            if report:
                sections.append(report)
        Path(file_path).write_text("\n\n".join(sections), encoding="utf-8")

    def _on_batch_changed(self, row: int) -> None:
        """切换当前批次详情。"""
        if row < 0 or row >= len(self._batch_entries):
            self._current_report = ""
            self.detail_edit.clear()
            self.copy_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.retry_failed_button.setEnabled(False)
            self.retry_incomplete_button.setEnabled(False)
            return
        entry = self._batch_entries[row]
        self._current_report = str(entry.get("report") or "")
        self.detail_edit.setPlainText(self._current_report)
        has_report = bool(self._current_report.strip())
        self.copy_button.setEnabled(has_report)
        self.export_button.setEnabled(has_report)
        self.retry_failed_button.setEnabled(
            bool(entry.get("failed_count")) and self._retry_failed_callback is not None
        )
        self.retry_incomplete_button.setEnabled(
            bool(entry.get("incomplete_count")) and self._retry_incomplete_callback is not None
        )

    def _copy_report(self) -> None:
        """复制当前批次报告。"""
        if not self._current_report.strip():
            return
        QApplication.clipboard().setText(self._current_report)

    def _export_report(self) -> None:
        """导出当前批次报告。"""
        if not self._current_report.strip():
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出批次报告"),
            "transfer-batch-report.txt",
            self.tr("文本文件 (*.txt)"),
        )
        if not file_path:
            return
        Path(file_path).write_text(self._current_report, encoding="utf-8")

    def _selected_batch_id(self) -> int:
        """返回当前选中批次 ID。"""
        row = self.batch_list.currentRow()
        if row < 0 or row >= len(self._batch_entries):
            return 0
        return int(self._batch_entries[row].get("batch_id") or 0)

    def _retry_failed(self) -> None:
        """重试当前批次失败项。"""
        batch_id = self._selected_batch_id()
        if not batch_id or self._retry_failed_callback is None:
            return
        count = self._retry_failed_callback(batch_id)
        if count > 0:
            QMessageBox.information(
                self,
                self.tr("批次恢复"),
                self.tr(f"已加入 {count} 个失败项重试任务"),
            )

    def _retry_incomplete(self) -> None:
        """重试当前批次未完成项。"""
        batch_id = self._selected_batch_id()
        if not batch_id or self._retry_incomplete_callback is None:
            return
        count = self._retry_incomplete_callback(batch_id)
        if count > 0:
            QMessageBox.information(
                self,
                self.tr("批次恢复"),
                self.tr(f"已加入 {count} 个未完成项重试任务"),
            )


class FileBrowserWidget(QWidget):
    """
    文件浏览器组件

    提供：
    - 文件列表显示
    - 目录导航
    - 文件上传/下载
    - 文件操作（重命名、删除等）

    Signals:
        file_uploaded: 文件上传完成
        file_downloaded: 文件下载完成
        directory_changed: 目录改变
        terminal_requested: 请求在终端中打开目录
    """

    # 信号
    file_uploaded = Signal(str)  # file_path
    file_downloaded = Signal(str)  # file_path
    directory_changed = Signal(str)  # dir_path
    terminal_requested = Signal(str)  # remote_dir_path
    FILE_COLUMNS = ("name", "type", "size", "modify_time", "permissions", "owner")
    TASK_ID_ROLE = Qt.UserRole
    TASK_STATUS_ROLE = Qt.UserRole + 1
    TASK_PROGRESS_ROLE = Qt.UserRole + 2
    TASK_ERROR_ROLE = Qt.UserRole + 3
    TASK_ATTEMPT_ROLE = Qt.UserRole + 4

    STATUS_QUEUED = "queued"
    STATUS_RETRY_WAIT = "retry_wait"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    CONFLICT_ASK = "ask"
    CONFLICT_OVERWRITE = "overwrite"
    CONFLICT_SKIP = "skip"
    CONFLICT_RENAME = "rename"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._logger = get_logger("FileBrowserWidget")
        self._connection: Optional[BaseConnection] = None
        self._current_path = "/"
        self._transfer_queue: deque[TransferTask] = deque()
        self._queue_items: dict[str, QListWidgetItem] = {}
        self._task_registry: dict[str, TransferTask] = {}
        self._active_transfer: Optional[TransferTask] = None
        self._active_progress_dialog: Optional[QProgressDialog] = None
        self._transfer_processing_scheduled = False
        self._next_batch_id = 1
        self._batch_registry: dict[int, dict[str, object]] = {}
        self._batch_order: list[int] = []
        self._all_items: List[FTPFileItem] = []
        self._current_items: List[FTPFileItem] = []

        self._setup_ui()
        self._setup_connections()
        self._update_action_states()
        self._update_transfer_controls()

    @property
    def connection(self) -> Optional[BaseConnection]:
        """获取当前绑定的连接。"""
        return self._connection

    def _setup_ui(self) -> None:
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 工具栏
        toolbar = QToolBar()
        layout.addWidget(toolbar)

        # 返回上级
        self.up_action = QAction(self.tr("上级"), self)
        self.up_action.setIcon(QIcon.fromTheme("go-up"))
        self.up_action.triggered.connect(self._go_up)
        toolbar.addAction(self.up_action)

        # 刷新
        self.refresh_action = QAction(self.tr("刷新"), self)
        self.refresh_action.setIcon(QIcon.fromTheme("view-refresh"))
        self.refresh_action.triggered.connect(self.refresh)
        toolbar.addAction(self.refresh_action)

        # 主目录
        self.home_action = QAction(self.tr("主目录"), self)
        self.home_action.setIcon(QIcon.fromTheme("go-home"))
        self.home_action.triggered.connect(self._go_home)
        toolbar.addAction(self.home_action)

        self.copy_current_path_action = QAction(self.tr("复制当前路径"), self)
        self.copy_current_path_action.setIcon(QIcon.fromTheme("edit-copy"))
        self.copy_current_path_action.triggered.connect(self._copy_current_path)
        toolbar.addAction(self.copy_current_path_action)

        self.open_terminal_here_action = QAction(self.tr("在终端打开"), self)
        self.open_terminal_here_action.setIcon(QIcon.fromTheme("utilities-terminal"))
        self.open_terminal_here_action.triggered.connect(self._request_terminal_for_current_path)
        toolbar.addAction(self.open_terminal_here_action)

        toolbar.addSeparator()

        # 新建文件夹
        self.mkdir_action = QAction(self.tr("新建文件夹"), self)
        self.mkdir_action.setIcon(QIcon.fromTheme("folder-new"))
        self.mkdir_action.triggered.connect(self._create_folder)
        toolbar.addAction(self.mkdir_action)

        self.create_file_action = QAction(self.tr("新建文件"), self)
        self.create_file_action.setIcon(QIcon.fromTheme("document-new"))
        self.create_file_action.triggered.connect(self._create_file)
        toolbar.addAction(self.create_file_action)

        # 上传
        self.upload_action = QAction(self.tr("上传"), self)
        self.upload_action.setIcon(QIcon.fromTheme("document-send"))
        self.upload_action.triggered.connect(self._upload_file)
        toolbar.addAction(self.upload_action)

        self.upload_directory_action = QAction(self.tr("上传目录"), self)
        self.upload_directory_action.setIcon(QIcon.fromTheme("folder-open"))
        self.upload_directory_action.triggered.connect(self._upload_directory)
        toolbar.addAction(self.upload_directory_action)

        self.resume_check = QCheckBox(self.tr("断点续传"))
        self.resume_check.setChecked(True)
        toolbar.addWidget(self.resume_check)

        toolbar.addWidget(QLabel(self.tr("冲突:")))
        self.conflict_strategy_combo = QComboBox()
        self.conflict_strategy_combo.addItem(self.tr("询问"), self.CONFLICT_ASK)
        self.conflict_strategy_combo.addItem(self.tr("覆盖"), self.CONFLICT_OVERWRITE)
        self.conflict_strategy_combo.addItem(self.tr("跳过"), self.CONFLICT_SKIP)
        self.conflict_strategy_combo.addItem(self.tr("自动重命名"), self.CONFLICT_RENAME)
        toolbar.addWidget(self.conflict_strategy_combo)

        toolbar.addSeparator()

        # 视图切换
        self.view_combo = QComboBox()
        self.view_combo.addItems([self.tr("列表"), self.tr("图标")])
        toolbar.addWidget(self.view_combo)

        # 路径栏
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel(self.tr("路径:")))

        self.path_edit = QLineEdit()
        self.path_edit.returnPressed.connect(self._navigate_to_path)
        path_layout.addWidget(self.path_edit)

        self.go_btn = QPushButton(self.tr("转到"))
        self.go_btn.clicked.connect(self._navigate_to_path)
        path_layout.addWidget(self.go_btn)

        layout.addLayout(path_layout)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel(self.tr("筛选:")))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(self.tr("按名称筛选文件或目录"))
        filter_layout.addWidget(self.filter_edit, 1)
        filter_layout.addWidget(QLabel(self.tr("排序:")))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(
            [
                self.tr("原始顺序"),
                self.tr("名称"),
                self.tr("类型"),
                self.tr("大小"),
                self.tr("修改时间"),
            ]
        )
        filter_layout.addWidget(self.sort_combo)
        self.sort_order_combo = QComboBox()
        self.sort_order_combo.addItems([self.tr("升序"), self.tr("降序")])
        filter_layout.addWidget(self.sort_order_combo)
        self.clear_filter_btn = QPushButton(self.tr("清空"))
        filter_layout.addWidget(self.clear_filter_btn)
        layout.addLayout(filter_layout)

        # 文件列表
        self.file_model = QStandardItemModel()
        self.file_model.setHorizontalHeaderLabels(self._file_headers())

        self.file_list = QTreeView()
        self.file_list.setModel(self.file_model)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.setRootIsDecorated(False)
        self.file_list.setItemsExpandable(False)
        self.file_list.setUniformRowHeights(True)
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setWordWrap(False)
        self.file_list.viewport().setAcceptDrops(True)
        self.file_list.doubleClicked.connect(self._on_item_double_clicked)
        header = self.file_list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        queue_card = QFrame()
        queue_card.setObjectName("transferQueueCard")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(12, 12, 12, 12)
        queue_layout.setSpacing(8)
        queue_header = QHBoxLayout()
        self.queue_title = QLabel(self.tr("传输队列"))
        self.queue_title.setObjectName("sidebarTitle")
        queue_header.addWidget(self.queue_title)
        self.cancel_transfer_btn = QPushButton(self.tr("取消当前"))
        self.cancel_transfer_btn.clicked.connect(self._cancel_active_transfer)
        queue_header.addWidget(self.cancel_transfer_btn)

        self.retry_failed_btn = QPushButton(self.tr("重试失败"))
        self.retry_failed_btn.clicked.connect(self._retry_failed_transfers)
        queue_header.addWidget(self.retry_failed_btn)

        self.copy_failed_btn = QPushButton(self.tr("复制失败项"))
        self.copy_failed_btn.clicked.connect(self._copy_failed_transfer_items)
        queue_header.addWidget(self.copy_failed_btn)

        self.history_btn = QPushButton(self.tr("批次历史"))
        self.history_btn.clicked.connect(self._show_batch_history)
        queue_header.addWidget(self.history_btn)

        self.clear_pending_btn = QPushButton(self.tr("清空队列"))
        self.clear_pending_btn.clicked.connect(self._clear_pending_transfers)
        queue_header.addWidget(self.clear_pending_btn)

        self.clear_finished_btn = QPushButton(self.tr("清理已完成"))
        self.clear_finished_btn.clicked.connect(self._clear_finished_transfer_items)
        queue_header.addWidget(self.clear_finished_btn)
        queue_header.addStretch()
        queue_layout.addLayout(queue_header)

        self.transfer_queue_list = QListWidget()
        self.transfer_queue_list.setMinimumHeight(180)
        self.transfer_queue_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.transfer_queue_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.transfer_queue_list.setAlternatingRowColors(True)
        queue_layout.addWidget(self.transfer_queue_list)

        self.queue_summary_label = QLabel(self.tr("队列摘要: 空"))
        queue_layout.addWidget(self.queue_summary_label)

        self.batch_summary_label = QLabel(self.tr("批次摘要: 无"))
        self.batch_summary_label.setWordWrap(True)
        queue_layout.addWidget(self.batch_summary_label)

        self.queue_detail_label = QLabel(
            self.tr("选择一条队列任务，可查看详细状态、错误信息和批次上下文。")
        )
        self.queue_detail_label.setWordWrap(True)
        self.queue_detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        queue_layout.addWidget(self.queue_detail_label)

        progress_row = QHBoxLayout()
        self.queue_progress_label = QLabel(self.tr("当前任务: 无"))
        progress_row.addWidget(self.queue_progress_label)
        self.queue_progress_bar = QProgressBar()
        self.queue_progress_bar.setRange(0, 100)
        self.queue_progress_bar.setValue(0)
        progress_row.addWidget(self.queue_progress_bar, 1)
        queue_layout.addLayout(progress_row)

        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)
        sidebar_layout.addWidget(queue_card, 1)

        sidebar_container = QWidget()
        sidebar_container.setLayout(sidebar_layout)

        self.browser_splitter = QSplitter(Qt.Horizontal)
        self.browser_splitter.addWidget(self.file_list)
        self.browser_splitter.addWidget(sidebar_container)
        self.browser_splitter.setCollapsible(0, False)
        self.browser_splitter.setCollapsible(1, False)
        self.browser_splitter.setSizes([860, 240])

        layout.addWidget(self.browser_splitter, 1)

        # 状态栏
        self.status_label = QLabel(self.tr("就绪"))
        layout.addWidget(self.status_label)
        self.setStyleSheet("""
            QFrame#transferQueueCard {
                border: 1px solid rgba(110, 132, 74, 0.18);
                border-radius: 14px;
                background: rgba(255, 255, 255, 0.45);
            }
            QLabel#sidebarTitle {
                font-size: 14px;
                font-weight: 700;
            }
            """)
        self.setAcceptDrops(True)

    def _setup_connections(self) -> None:
        """设置信号连接"""
        self.file_list.customContextMenuRequested.connect(self._show_context_menu)
        self.file_list.viewport().installEventFilter(self)
        selection_model = self.file_list.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._on_selection_changed)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self.sort_order_combo.currentIndexChanged.connect(
            lambda _index: self._apply_filter(self.filter_edit.text())
        )
        self.clear_filter_btn.clicked.connect(self.filter_edit.clear)
        self.transfer_queue_list.itemSelectionChanged.connect(self._refresh_queue_detail)
        self.transfer_queue_list.currentItemChanged.connect(
            lambda _current, _previous: self._refresh_queue_detail()
        )
        self.transfer_queue_list.customContextMenuRequested.connect(
            self._show_transfer_queue_context_menu
        )

    def _on_selection_changed(self, *_args) -> None:
        """统一处理文件选择变化。"""
        self._update_action_states()

    def _selected_name_items(self) -> List[QStandardItem]:
        """获取当前选中的名称列项目，不弹提示。"""
        selection_model = self.file_list.selectionModel()
        if selection_model is None:
            return []
        return [
            self.file_model.itemFromIndex(index)
            for index in selection_model.selectedRows(0)
            if index.isValid()
        ]

    def _file_headers(self) -> List[str]:
        """返回文件列表表头。"""
        return [
            self.tr("名称"),
            self.tr("类型"),
            self.tr("大小"),
            self.tr("修改时间"),
            self.tr("权限"),
            self.tr("所有者"),
        ]

    def _has_connection_capability(self, *names: str) -> bool:
        """判断当前连接是否具备指定能力。"""
        if not self._connection:
            return False
        return all(hasattr(self._connection, name) for name in names)

    def _update_action_states(self) -> None:
        """根据连接和当前选择刷新操作可用性。"""
        selected_items = self._selected_name_items()
        selected_files = [item for item in selected_items if not item.data(Qt.UserRole)]
        selected_dirs = [item for item in selected_items if item.data(Qt.UserRole)]

        is_connected = self._connection is not None
        has_selection = bool(selected_items)
        single_selection = len(selected_items) == 1
        single_file = len(selected_files) == 1 and not selected_dirs and single_selection
        can_delete = False
        if selected_files and not self._has_connection_capability("delete_file"):
            can_delete = False
        elif selected_dirs and not self._has_connection_capability(
            "list_dir", "rmdir", "delete_file"
        ):
            can_delete = False
        else:
            can_delete = has_selection

        self.up_action.setEnabled(is_connected and self._current_path != "/")
        self.refresh_action.setEnabled(is_connected)
        self.home_action.setEnabled(is_connected)
        self.mkdir_action.setEnabled(self._has_connection_capability("mkdir"))
        self.create_file_action.setEnabled(self._has_connection_capability("create_file"))
        self.upload_action.setEnabled(self._has_connection_capability("upload_from_path"))
        self.upload_directory_action.setEnabled(
            self._has_connection_capability("upload_from_path", "mkdir")
        )
        self.copy_current_path_action.setEnabled(is_connected)
        self.open_terminal_here_action.setEnabled(is_connected and self._supports_terminal_link())

        self.resume_check.setEnabled(
            self._has_connection_capability("upload_from_path")
            or self._has_connection_capability("download_to_path")
        )
        self.conflict_strategy_combo.setEnabled(
            self._has_connection_capability("upload_from_path")
            or self._has_connection_capability("download_to_path")
        )
        self.path_edit.setEnabled(is_connected)
        self.go_btn.setEnabled(is_connected)
        self.filter_edit.setEnabled(is_connected)
        self.sort_combo.setEnabled(is_connected)
        self.sort_order_combo.setEnabled(is_connected and self.sort_combo.currentIndex() != 0)
        self.clear_filter_btn.setEnabled(is_connected and bool(self.filter_edit.text().strip()))
        self.file_list.setEnabled(is_connected)

        self._context_action_states = {
            "open_in_terminal": single_selection and self._supports_terminal_link(),
            "properties": single_selection,
            "edit": single_file and self._has_connection_capability("read_text", "write_text"),
            "download": bool(selected_files)
            and self._has_connection_capability("download_to_path"),
            "rename": single_selection and self._has_connection_capability("rename"),
            "copy": has_selection and self._has_connection_capability("copy_paths"),
            "move": has_selection and self._has_connection_capability("move_paths"),
            "chmod": has_selection and self._has_connection_capability("chmod"),
            "compress": has_selection and self._has_connection_capability("create_archive"),
            "extract": bool(selected_files) and self._has_connection_capability("extract_archive"),
            "delete": can_delete,
        }

    def _update_transfer_controls(self) -> None:
        """根据传输队列状态刷新队列操作按钮。"""
        statuses = [
            self._queue_item_status(self.transfer_queue_list.item(index))
            for index in range(self.transfer_queue_list.count())
            if self.transfer_queue_list.item(index) is not None
        ]
        has_failed = self.STATUS_FAILED in statuses
        has_finished = any(
            status in {self.STATUS_COMPLETED, self.STATUS_FAILED, self.STATUS_CANCELED}
            for status in statuses
        )

        self.cancel_transfer_btn.setEnabled(self._active_transfer is not None)
        self.retry_failed_btn.setEnabled(has_failed)
        self.copy_failed_btn.setEnabled(has_failed)
        self.history_btn.setEnabled(bool(self._batch_registry))
        self.clear_pending_btn.setEnabled(bool(self._transfer_queue))
        self.clear_finished_btn.setEnabled(has_finished)
        self._refresh_queue_summary()
        self._refresh_queue_detail()

    def _refresh_queue_summary(self) -> None:
        """刷新传输队列摘要。"""
        counts = {
            self.STATUS_QUEUED: 0,
            self.STATUS_RETRY_WAIT: 0,
            self.STATUS_RUNNING: 0,
            self.STATUS_COMPLETED: 0,
            self.STATUS_FAILED: 0,
            self.STATUS_CANCELED: 0,
        }
        for index in range(self.transfer_queue_list.count()):
            item = self.transfer_queue_list.item(index)
            if item is None:
                continue
            status = self._queue_item_status(item)
            if status in counts:
                counts[status] += 1
        summary = self.tr(
            "队列摘要: 排队 {queued} / 重试 {retry} / 执行 {running} / 完成 {done} / 失败 {failed} / 取消 {canceled}"
        ).format(
            queued=counts[self.STATUS_QUEUED],
            retry=counts[self.STATUS_RETRY_WAIT],
            running=counts[self.STATUS_RUNNING],
            done=counts[self.STATUS_COMPLETED],
            failed=counts[self.STATUS_FAILED],
            canceled=counts[self.STATUS_CANCELED],
        )
        self.queue_summary_label.setText(summary)
        self.batch_summary_label.setText(self._latest_batch_summary_text())

    def _selected_queue_tasks(
        self,
        *,
        statuses: Optional[set[str]] = None,
    ) -> list[TransferTask]:
        """返回当前选中的队列任务，可按状态过滤。"""
        tasks: list[TransferTask] = []
        seen: set[str] = set()
        for item in self.transfer_queue_list.selectedItems():
            task_id = str(item.data(self.TASK_ID_ROLE) or "").strip()
            if not task_id or task_id in seen:
                continue
            task = self._task_registry.get(task_id)
            if task is None:
                continue
            if statuses is not None and task.status not in statuses:
                continue
            seen.add(task_id)
            tasks.append(task)
        return tasks

    def _queue_task_detail_text(self, tasks: list[TransferTask]) -> str:
        """生成当前选中队列任务的详情说明。"""
        if not tasks:
            if isinstance(self._active_transfer, TransferTask):
                tasks = [self._active_transfer]
            elif self.transfer_queue_list.count() > 0:
                return self.tr("选择一条队列任务，可查看详细状态、错误信息和批次上下文。")
            else:
                return self.tr("当前暂无传输任务。")

        if len(tasks) == 1:
            task = tasks[0]
            lines = [
                self.tr(f"任务: {task.operation} {task.display_name}"),
                self.tr(
                    f"状态: {self._status_label(task.status, error=task.last_error, percent=task.progress_percent)}"
                ),
            ]
            if task.batch_label:
                lines.append(self.tr(f"批次: {task.batch_label}"))
            if task.attempt:
                lines.append(self.tr(f"重试: 第 {task.attempt} 次 / 最多 {task.max_retries} 次"))
            if task.last_error:
                lines.append(self.tr(f"错误: {task.last_error}"))
            if task.success_payload:
                lines.append(self.tr(f"目标: {task.success_payload}"))
            return "\n".join(lines)

        failed_count = sum(1 for task in tasks if task.status == self.STATUS_FAILED)
        running_count = sum(1 for task in tasks if task.status == self.STATUS_RUNNING)
        queued_count = sum(
            1 for task in tasks if task.status in {self.STATUS_QUEUED, self.STATUS_RETRY_WAIT}
        )
        completed_count = sum(1 for task in tasks if task.status == self.STATUS_COMPLETED)
        canceled_count = sum(1 for task in tasks if task.status == self.STATUS_CANCELED)
        lines = [
            self.tr(f"已选 {len(tasks)} 条任务"),
            self.tr(
                "状态汇总: 排队 {queued} / 执行 {running} / 完成 {completed} / 失败 {failed} / 取消 {canceled}"
            ).format(
                queued=queued_count,
                running=running_count,
                completed=completed_count,
                failed=failed_count,
                canceled=canceled_count,
            ),
        ]
        sample_names = [task.display_name for task in tasks[:3]]
        if sample_names:
            lines.append(self.tr(f"示例: {'、'.join(sample_names)}"))
        if len(tasks) > 3:
            lines.append(self.tr(f"其余 {len(tasks) - 3} 条可通过右键菜单批量处理。"))
        return "\n".join(lines)

    def _refresh_queue_detail(self) -> None:
        """刷新队列详情文案。"""
        self.queue_detail_label.setText(self._queue_task_detail_text(self._selected_queue_tasks()))

    def _allocate_transfer_batch(self, operation: str, total_tasks: int) -> tuple[int, str]:
        """创建新的传输批次标识。"""
        batch_id = self._next_batch_id
        self._next_batch_id += 1
        batch_label = self.tr(f"{operation}批次 #{batch_id:03d}")
        self._batch_registry[batch_id] = {
            "operation": operation,
            "label": batch_label,
            "total_tasks": total_tasks,
            "tasks": {},
        }
        self._batch_order.append(batch_id)
        return batch_id, batch_label

    def _attach_batch_to_tasks(self, tasks: List[TransferTask], operation: str) -> int:
        """为一组传输任务绑定批次信息。"""
        if not tasks:
            return 0
        batch_id, batch_label = self._allocate_transfer_batch(operation, len(tasks))
        for task in tasks:
            task.batch_id = batch_id
            task.batch_label = batch_label
            self._sync_batch_history_task(task)
        return batch_id

    @staticmethod
    def _batch_task_snapshot(task: TransferTask) -> dict[str, object]:
        """构建批次任务快照。"""
        return {
            "task_id": task.task_id,
            "operation": task.operation,
            "display_name": task.display_name,
            "title": task.title,
            "label": task.label,
            "runner": task.runner,
            "success_payload": task.success_payload,
            "status": task.status,
            "attempt": task.attempt,
            "max_retries": task.max_retries,
            "last_error": task.last_error,
            "progress_percent": task.progress_percent,
        }

    def _sync_batch_history_task(self, task: TransferTask) -> None:
        """将任务状态同步到批次历史。"""
        if not task.batch_id:
            return
        metadata = self._batch_registry.get(task.batch_id)
        if metadata is None:
            return
        task_map = metadata.setdefault("tasks", {})
        if isinstance(task_map, dict):
            task_map[task.task_id] = self._batch_task_snapshot(task)

    def _batch_counts(self, batch_id: int) -> Optional[dict[str, int]]:
        """统计指定批次的任务状态。"""
        metadata = self._batch_registry.get(batch_id)
        if metadata is None:
            return None
        counts = {
            self.STATUS_QUEUED: 0,
            self.STATUS_RETRY_WAIT: 0,
            self.STATUS_RUNNING: 0,
            self.STATUS_COMPLETED: 0,
            self.STATUS_FAILED: 0,
            self.STATUS_CANCELED: 0,
        }
        task_map = metadata.get("tasks")
        if not isinstance(task_map, dict) or not task_map:
            return None
        has_task = False
        for task in task_map.values():
            if not isinstance(task, dict):
                continue
            has_task = True
            status = str(task.get("status") or "")
            if status in counts:
                counts[status] += 1
        if not has_task:
            return None
        counts["total"] = int(metadata.get("total_tasks", 0) or 0)
        return counts

    def _batch_state_label(self, counts: dict[str, int]) -> str:
        """返回批次综合状态文案。"""
        total = counts.get("total", 0)
        failed = counts.get(self.STATUS_FAILED, 0)
        canceled = counts.get(self.STATUS_CANCELED, 0)
        running = counts.get(self.STATUS_RUNNING, 0)
        queued = counts.get(self.STATUS_QUEUED, 0) + counts.get(self.STATUS_RETRY_WAIT, 0)
        completed = counts.get(self.STATUS_COMPLETED, 0)
        if failed > 0:
            return self.tr("部分失败")
        if running > 0 or queued > 0:
            return self.tr("进行中")
        if total > 0 and completed == total:
            return self.tr("已完成")
        if total > 0 and canceled == total:
            return self.tr("已取消")
        if canceled > 0:
            return self.tr("部分取消")
        return self.tr("混合状态")

    def _batch_task_entries(self, batch_id: int) -> list[dict[str, object]]:
        """返回批次任务快照列表。"""
        metadata = self._batch_registry.get(batch_id, {})
        task_map = metadata.get("tasks")
        if not isinstance(task_map, dict):
            return []
        return [task for task in task_map.values() if isinstance(task, dict)]

    def _batch_report_text(self, batch_id: int) -> str:
        """生成批次文本报告。"""
        metadata = self._batch_registry.get(batch_id, {})
        counts = self._batch_counts(batch_id)
        if counts is None:
            return self.tr("暂无批次记录")

        status_text = self._batch_state_label(counts)
        total = max(1, counts.get("total", 0))
        success_rate = (counts.get(self.STATUS_COMPLETED, 0) * 100.0) / total
        lines = [
            str(metadata.get("label") or self.tr("未知批次")),
            self.tr(f"操作: {metadata.get('operation') or self.tr('未知')}"),
            self.tr(f"状态: {status_text}"),
            self.tr(f"成功率: {success_rate:.1f}%"),
            "",
            self.tr(f"总计: {counts.get('total', 0)}"),
            self.tr(f"排队: {counts.get(self.STATUS_QUEUED, 0)}"),
            self.tr(f"等待重试: {counts.get(self.STATUS_RETRY_WAIT, 0)}"),
            self.tr(f"执行中: {counts.get(self.STATUS_RUNNING, 0)}"),
            self.tr(f"完成: {counts.get(self.STATUS_COMPLETED, 0)}"),
            self.tr(f"失败: {counts.get(self.STATUS_FAILED, 0)}"),
            self.tr(f"取消: {counts.get(self.STATUS_CANCELED, 0)}"),
        ]

        task_entries = self._batch_task_entries(batch_id)
        failed_entries = [
            entry for entry in task_entries if entry.get("status") == self.STATUS_FAILED
        ]
        pending_entries = [
            entry
            for entry in task_entries
            if entry.get("status")
            in {self.STATUS_QUEUED, self.STATUS_RETRY_WAIT, self.STATUS_RUNNING}
        ]
        canceled_entries = [
            entry for entry in task_entries if entry.get("status") == self.STATUS_CANCELED
        ]

        if failed_entries:
            lines.extend(["", self.tr("失败项:")])
            for entry in failed_entries:
                detail = str(entry.get("last_error") or self.tr("未知错误"))
                lines.append(
                    self.tr(f"- {entry.get('operation')}: {entry.get('display_name')} :: {detail}")
                )

        if pending_entries:
            lines.extend(["", self.tr("待处理项:")])
            for entry in pending_entries:
                status = self._status_label(
                    str(entry.get("status") or ""),
                    error=str(entry.get("last_error") or ""),
                    percent=int(entry.get("progress_percent") or 0),
                )
                lines.append(
                    self.tr(f"- {entry.get('operation')}: {entry.get('display_name')} [{status}]")
                )

        if canceled_entries:
            lines.extend(["", self.tr("已取消项:")])
            for entry in canceled_entries:
                lines.append(self.tr(f"- {entry.get('operation')}: {entry.get('display_name')}"))
        return "\n".join(lines)

    def _transfer_diagnostics_text(self) -> str:
        """生成跨批次传输诊断摘要。"""
        if not self._batch_registry:
            return self.tr("暂无批次统计")

        total_batches = len(self._batch_registry)
        task_total = 0
        completed = 0
        failed = 0
        canceled = 0
        active_batches = 0
        failed_batches = 0
        error_counts: dict[str, int] = {}

        for batch_id in self._batch_order:
            counts = self._batch_counts(batch_id)
            if counts is None:
                continue
            task_total += counts.get("total", 0)
            completed += counts.get(self.STATUS_COMPLETED, 0)
            failed += counts.get(self.STATUS_FAILED, 0)
            canceled += counts.get(self.STATUS_CANCELED, 0)
            if counts.get(self.STATUS_FAILED, 0) > 0:
                failed_batches += 1
            if counts.get(self.STATUS_RUNNING, 0) > 0 or (
                counts.get(self.STATUS_QUEUED, 0) + counts.get(self.STATUS_RETRY_WAIT, 0) > 0
            ):
                active_batches += 1

            for entry in self._batch_task_entries(batch_id):
                error_text = str(entry.get("last_error") or "").strip()
                if not error_text:
                    continue
                error_counts[error_text] = error_counts.get(error_text, 0) + 1

        parts = [
            self.tr(
                f"批次总数 {total_batches} · 活跃批次 {active_batches} · 失败批次 {failed_batches}"
            ),
            self.tr(f"任务总数 {task_total} · 完成 {completed} · 失败 {failed} · 取消 {canceled}"),
        ]
        if error_counts:
            ranked = sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))[:3]
            hotspot_text = " / ".join(f"{message} ×{count}" for message, count in ranked)
            parts.append(self.tr(f"错误热点: {hotspot_text}"))
        else:
            parts.append(self.tr("错误热点: 暂无"))
        return " | ".join(parts)

    def _batch_history_entries(self) -> list[dict[str, object]]:
        """返回批次历史条目。"""
        entries: list[dict[str, object]] = []
        for batch_id in reversed(self._batch_order):
            counts = self._batch_counts(batch_id)
            if counts is None:
                continue
            metadata = self._batch_registry.get(batch_id, {})
            title = self.tr("{label} · {status} · 完成 {done}/{total} · 失败 {failed}").format(
                label=str(metadata.get("label") or self.tr("未知批次")),
                status=self._batch_state_label(counts),
                done=counts.get(self.STATUS_COMPLETED, 0),
                total=counts.get("total", 0),
                failed=counts.get(self.STATUS_FAILED, 0),
            )
            entries.append(
                {
                    "batch_id": batch_id,
                    "title": title,
                    "report": self._batch_report_text(batch_id),
                    "failed_count": counts.get(self.STATUS_FAILED, 0),
                    "incomplete_count": (
                        counts.get(self.STATUS_QUEUED, 0)
                        + counts.get(self.STATUS_RETRY_WAIT, 0)
                        + counts.get(self.STATUS_RUNNING, 0)
                        + counts.get(self.STATUS_CANCELED, 0)
                    ),
                }
            )
        return entries

    def _create_batch_history_dialog(self) -> TransferBatchHistoryDialog:
        """创建批次历史对话框。"""
        return TransferBatchHistoryDialog(
            self._batch_history_entries(),
            self._transfer_diagnostics_text(),
            retry_failed_callback=self._retry_failed_history_batch,
            retry_incomplete_callback=self._retry_incomplete_history_batch,
            parent=self,
        )

    def _show_batch_history(self) -> None:
        """显示批次历史与诊断对话框。"""
        dialog = self._create_batch_history_dialog()
        dialog.exec()

    def _latest_batch_summary_text(self) -> str:
        """返回最近一个仍可见批次的摘要文本。"""
        for batch_id in reversed(self._batch_order):
            counts = self._batch_counts(batch_id)
            if counts is None:
                continue
            metadata = self._batch_registry.get(batch_id, {})
            return self.tr(
                "批次摘要: {label} · 总计 {total} / 排队 {queued} / 执行 {running} / "
                "完成 {done} / 失败 {failed} / 取消 {canceled}"
            ).format(
                label=str(metadata.get("label", "") or self.tr("未知批次")),
                total=counts["total"],
                queued=counts[self.STATUS_QUEUED] + counts[self.STATUS_RETRY_WAIT],
                running=counts[self.STATUS_RUNNING],
                done=counts[self.STATUS_COMPLETED],
                failed=counts[self.STATUS_FAILED],
                canceled=counts[self.STATUS_CANCELED],
            )
        return self.tr("批次摘要: 无")

    def _status_label(self, status: str, error: str = "", percent: int = 0) -> str:
        """返回内部状态对应的展示文案。"""
        labels = {
            self.STATUS_QUEUED: self.tr("排队中"),
            self.STATUS_RETRY_WAIT: self.tr("等待重试"),
            self.STATUS_RUNNING: self.tr("执行中"),
            self.STATUS_COMPLETED: self.tr("已完成"),
            self.STATUS_FAILED: self.tr("失败"),
            self.STATUS_CANCELED: self.tr("已取消"),
        }
        label = labels.get(status, self.tr("未知状态"))
        if status == self.STATUS_RUNNING and percent > 0:
            return f"{label} {percent}%"
        if status == self.STATUS_FAILED and error:
            return f"{label} - {error}"
        return label

    def _task_text(self, task: TransferTask) -> str:
        """构造队列展示文本。"""
        status_text = self._status_label(
            task.status, error=task.last_error, percent=task.progress_percent
        )
        if task.attempt:
            status_text = f"{status_text} ({self.tr('重试')}{task.attempt}/{task.max_retries})"
        batch_segment = f"{task.batch_label} · " if task.batch_label else ""
        return self.tr(f"[{status_text}] {batch_segment}{task.operation}: {task.display_name}")

    def _queue_item_status(self, item: Optional[QListWidgetItem]) -> str:
        """读取队列项的结构化状态。"""
        if item is None:
            return ""
        return str(item.data(self.TASK_STATUS_ROLE) or "")

    def _sync_task_item(self, task: TransferTask) -> None:
        """同步任务与列表项的结构化状态和展示文本。"""
        item = self._queue_items.get(task.task_id)
        if item is None:
            return
        item.setData(self.TASK_ID_ROLE, task.task_id)
        item.setData(self.TASK_STATUS_ROLE, task.status)
        item.setData(self.TASK_PROGRESS_ROLE, task.progress_percent)
        item.setData(self.TASK_ERROR_ROLE, task.last_error)
        item.setData(self.TASK_ATTEMPT_ROLE, task.attempt)
        item.setText(self._task_text(task))

    def _set_task_status(
        self,
        task: TransferTask,
        status: str,
        percent: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """更新队列任务状态。"""
        task.status = status
        if percent is not None:
            task.progress_percent = percent
        elif status != self.STATUS_RUNNING:
            task.progress_percent = 0
        if error is not None:
            task.last_error = error
        elif status != self.STATUS_FAILED:
            task.last_error = ""
        self._sync_task_item(task)
        self._sync_batch_history_task(task)

    def _schedule_transfer_processing(self) -> None:
        """在需要时异步调度下一个传输任务。"""
        if (
            self._active_transfer is not None
            or not self._transfer_queue
            or self._transfer_processing_scheduled
        ):
            return
        self._transfer_processing_scheduled = True
        QTimer.singleShot(0, self._process_next_transfer_task)

    def _enqueue_transfer_tasks(self, tasks: List[TransferTask]) -> int:
        """批量加入传输队列。"""
        if not tasks:
            return 0
        for task in tasks:
            task.status = self.STATUS_QUEUED
            task.last_error = ""
            task.progress_percent = 0
            self._transfer_queue.append(task)
            self._task_registry[task.task_id] = task
            item = QListWidgetItem()
            self.transfer_queue_list.addItem(item)
            self._queue_items[task.task_id] = item
            self._sync_task_item(task)
        self.status_label.setText(self.tr(f"队列中任务数: {len(self._transfer_queue)}"))
        self._update_transfer_controls()
        self._schedule_transfer_processing()
        return len(tasks)

    def _enqueue_transfer_task(self, task: TransferTask) -> None:
        """加入传输队列。"""
        self._enqueue_transfer_tasks([task])

    def _mark_task_failed(self, task: TransferTask, error: Exception) -> None:
        """标记任务失败。"""
        error_text = str(error)
        if task.attempt < task.max_retries:
            task.attempt += 1
            self._set_task_status(task, self.STATUS_RETRY_WAIT, error=error_text)
            self._logger.warning(
                "传输任务失败，准备重试(%s/%s) [%s]: %s",
                task.attempt,
                task.max_retries,
                task.display_name,
                error,
            )
            self._transfer_queue.appendleft(task)
            self._update_transfer_controls()
            return

        self._set_task_status(task, self.STATUS_FAILED, error=error_text)
        self._logger.error("传输任务失败 [%s]: %s", task.display_name, error)
        self._update_transfer_controls()

    def _mark_task_completed(self, task: TransferTask) -> None:
        """标记任务完成。"""
        self._set_task_status(task, self.STATUS_COMPLETED)
        self._update_transfer_controls()

    def _mark_task_canceled(self, task: TransferTask) -> None:
        """标记任务取消（不重试）。"""
        self._set_task_status(task, self.STATUS_CANCELED)
        self._logger.info("传输任务已取消 [%s]", task.display_name)
        self._update_transfer_controls()

    def _update_active_progress(self, task: TransferTask, transferred: int, total: int) -> None:
        if total > 0:
            percent = int(min(100, max(0, (transferred * 100) // total)))
        else:
            percent = 0
        self._set_task_status(task, self.STATUS_RUNNING, percent=percent)
        self.queue_progress_label.setText(
            self.tr(f"当前任务: {task.operation} {task.display_name}")
        )
        self.queue_progress_bar.setValue(percent)

    def _process_next_transfer_task(self) -> None:
        """顺序处理队列中的传输任务。"""
        self._transfer_processing_scheduled = False
        if self._active_transfer is not None:
            return
        if not self._transfer_queue:
            self.status_label.setText(self.tr("就绪"))
            self.queue_progress_label.setText(self.tr("当前任务: 无"))
            self.queue_progress_bar.setValue(0)
            return

        task = self._transfer_queue.popleft()
        self._active_transfer = task
        self._set_task_status(task, self.STATUS_RUNNING)
        self.status_label.setText(self.tr(f"执行任务: {task.operation} {task.display_name}"))
        self.queue_progress_label.setText(
            self.tr(f"当前任务: {task.operation} {task.display_name}")
        )
        self.queue_progress_bar.setValue(0)
        self._update_transfer_controls()

        try:
            self._run_transfer_with_progress(
                task.title,
                task.label,
                task.runner,
                on_progress=lambda transferred, total: self._update_active_progress(
                    task, transferred, total
                ),
            )
        except TransferCanceled:
            self._mark_task_canceled(task)
        except Exception as exc:
            self._mark_task_failed(task, exc)
        else:
            self._mark_task_completed(task)
            if task.operation == self.tr("上传"):
                self.file_uploaded.emit(task.success_payload)
            elif task.operation == self.tr("下载"):
                self.file_downloaded.emit(task.success_payload)
            self.refresh()
        finally:
            self._active_transfer = None
            if self._transfer_queue:
                self._schedule_transfer_processing()
            else:
                self.status_label.setText(self.tr("就绪"))
                self.queue_progress_label.setText(self.tr("当前任务: 无"))
                self.queue_progress_bar.setValue(0)
            self._update_transfer_controls()

    def _clear_finished_transfer_items(self) -> None:
        """清理已完成或失败的传输队列项。"""
        removable_rows = []
        for row in range(self.transfer_queue_list.count()):
            item = self.transfer_queue_list.item(row)
            status = self._queue_item_status(item)
            if status in {self.STATUS_COMPLETED, self.STATUS_FAILED, self.STATUS_CANCELED}:
                removable_rows.append(row)

        for row in reversed(removable_rows):
            item = self.transfer_queue_list.takeItem(row)
            if item is not None:
                task_id = item.data(self.TASK_ID_ROLE)
                self._queue_items.pop(task_id, None)
                self._task_registry.pop(task_id, None)
        self._update_transfer_controls()

    def _copy_failed_transfer_items(self) -> None:
        """复制当前队列中的失败项摘要。"""
        failed_lines = self._transfer_error_lines(
            [task for task in self._task_registry.values() if task.status == self.STATUS_FAILED]
        )
        if not failed_lines:
            return
        QApplication.clipboard().setText("\n".join(failed_lines))
        self.status_label.setText(self.tr(f"已复制 {len(failed_lines)} 条失败项"))

    def _cancel_active_transfer(self) -> None:
        """取消当前任务。"""
        dialog = self._active_progress_dialog
        if dialog is not None:
            dialog.cancel()

    def _clear_pending_transfers(self) -> None:
        """清空尚未执行的队列。"""
        self._transfer_queue.clear()
        for row in range(self.transfer_queue_list.count()):
            item = self.transfer_queue_list.item(row)
            if item is None:
                continue
            status = self._queue_item_status(item)
            if status not in {self.STATUS_QUEUED, self.STATUS_RETRY_WAIT}:
                continue
            task_id = item.data(self.TASK_ID_ROLE)
            task = self._task_registry.get(task_id)
            if task is not None:
                self._set_task_status(task, self.STATUS_CANCELED)
        self._update_transfer_controls()

    def _retry_failed_transfers(self) -> None:
        """将失败的任务重新加入队列。"""
        failed_tasks = [
            task for task in self._task_registry.values() if task.status == self.STATUS_FAILED
        ]
        self._retry_transfer_tasks(failed_tasks, batch_name=self.tr("失败重试"))

    def _retry_transfer_tasks(self, tasks: list[TransferTask], *, batch_name: str) -> int:
        """克隆指定任务并重新加入队列。"""
        cloned_tasks = []
        for origin in tasks:
            cloned = TransferTask(
                task_id=str(uuid4()),
                operation=origin.operation,
                display_name=origin.display_name,
                title=origin.title,
                label=origin.label,
                runner=origin.runner,
                success_payload=origin.success_payload,
                attempt=0,
                max_retries=origin.max_retries,
            )
            cloned_tasks.append(cloned)
        self._attach_batch_to_tasks(cloned_tasks, batch_name)
        enqueued = self._enqueue_transfer_tasks(cloned_tasks)
        self._update_transfer_controls()
        return enqueued

    @staticmethod
    def _transfer_error_lines(tasks: list[TransferTask]) -> list[str]:
        """将任务列表格式化为可复制的错误摘要。"""
        lines: list[str] = []
        for task in tasks:
            prefix = f"{task.batch_label} · " if task.batch_label else ""
            line = f"{prefix}{task.operation}: {task.display_name}"
            if task.last_error:
                line = f"{line} :: {task.last_error}"
            lines.append(line)
        return lines

    def _retry_selected_failed_transfers(self) -> int:
        """仅重试当前选中的失败任务。"""
        selected_failed = self._selected_queue_tasks(statuses={self.STATUS_FAILED})
        enqueued = self._retry_transfer_tasks(
            selected_failed,
            batch_name=self.tr("选中失败重试"),
        )
        if enqueued > 0:
            self.status_label.setText(self.tr(f"已加入 {enqueued} 个选中失败重试任务"))
        return enqueued

    def _copy_selected_queue_errors(self) -> int:
        """复制当前选中任务中的错误信息。"""
        selected_failed = self._selected_queue_tasks(statuses={self.STATUS_FAILED})
        lines = self._transfer_error_lines(selected_failed)
        if not lines:
            return 0
        QApplication.clipboard().setText("\n".join(lines))
        self.status_label.setText(self.tr(f"已复制 {len(lines)} 条选中错误"))
        return len(lines)

    @staticmethod
    def _clone_transfer_task(
        snapshot: dict[str, object],
        *,
        label_prefix: Optional[str] = None,
    ) -> Optional[TransferTask]:
        """根据历史快照克隆传输任务。"""
        runner = snapshot.get("runner")
        if not callable(runner):
            return None
        operation = str(snapshot.get("operation") or "")
        display_name = str(snapshot.get("display_name") or "")
        title = str(snapshot.get("title") or f"{operation}文件")
        label = str(snapshot.get("label") or f"{operation}中")
        if label_prefix:
            label = f"{label_prefix}{display_name}"
        return TransferTask(
            task_id=str(uuid4()),
            operation=operation,
            display_name=display_name,
            title=title,
            label=label,
            runner=runner,
            success_payload=str(snapshot.get("success_payload") or display_name),
            attempt=0,
            max_retries=int(snapshot.get("max_retries") or 2),
        )

    def _retry_history_batch(self, batch_id: int, statuses: set[str], batch_name: str) -> int:
        """按状态从批次历史中重试任务。"""
        snapshots = [
            entry
            for entry in self._batch_task_entries(batch_id)
            if str(entry.get("status") or "") in statuses
        ]
        tasks: list[TransferTask] = []
        for snapshot in snapshots:
            cloned = self._clone_transfer_task(
                snapshot,
                label_prefix=self.tr("历史恢复: "),
            )
            if cloned is not None:
                tasks.append(cloned)
        self._attach_batch_to_tasks(tasks, batch_name)
        return self._enqueue_transfer_tasks(tasks)

    def _build_transfer_queue_context_menu(self) -> QMenu:
        """构造传输队列右键菜单。"""
        menu = QMenu(self)

        selected_failed_tasks = self._selected_queue_tasks(statuses={self.STATUS_FAILED})
        retry_selected_action = QAction(self.tr("重试选中失败项"), self)
        retry_selected_action.setEnabled(bool(selected_failed_tasks))
        retry_selected_action.triggered.connect(self._retry_selected_failed_transfers)
        menu.addAction(retry_selected_action)

        copy_selected_action = QAction(self.tr("复制选中错误"), self)
        copy_selected_action.setEnabled(bool(selected_failed_tasks))
        copy_selected_action.triggered.connect(self._copy_selected_queue_errors)
        menu.addAction(copy_selected_action)

        menu.addSeparator()

        history_action = QAction(self.tr("打开批次历史"), self)
        history_action.setEnabled(bool(self._batch_registry))
        history_action.triggered.connect(self._show_batch_history)
        menu.addAction(history_action)

        copy_all_failed_action = QAction(self.tr("复制全部失败项"), self)
        copy_all_failed_action.setEnabled(self.copy_failed_btn.isEnabled())
        copy_all_failed_action.triggered.connect(self._copy_failed_transfer_items)
        menu.addAction(copy_all_failed_action)

        return menu

    def _show_transfer_queue_context_menu(self, pos) -> None:
        """显示传输队列右键菜单。"""
        item = self.transfer_queue_list.itemAt(pos)
        if item is not None and not item.isSelected():
            self.transfer_queue_list.clearSelection()
            item.setSelected(True)
            self.transfer_queue_list.setCurrentItem(item)
        menu = self._build_transfer_queue_context_menu()
        menu.exec(self.transfer_queue_list.viewport().mapToGlobal(pos))

    def _retry_failed_history_batch(self, batch_id: int) -> int:
        """从历史批次重试失败项。"""
        return self._retry_history_batch(
            batch_id,
            {self.STATUS_FAILED},
            self.tr("历史失败重试"),
        )

    def _retry_incomplete_history_batch(self, batch_id: int) -> int:
        """从历史批次重试未完成项。"""
        return self._retry_history_batch(
            batch_id,
            {
                self.STATUS_QUEUED,
                self.STATUS_RETRY_WAIT,
                self.STATUS_RUNNING,
                self.STATUS_CANCELED,
            },
            self.tr("历史未完成重试"),
        )

    def set_connection(self, connection: BaseConnection) -> None:
        """
        设置关联的连接

        Args:
            connection: 连接实例
        """
        self._connection = connection
        self._current_path = getattr(connection, "current_dir", self._current_path)
        self.refresh()
        self._update_action_states()

    def refresh(self) -> None:
        """刷新当前目录"""
        if not self._connection:
            self._all_items = []
            self._current_items = []
            self.file_model.clear()
            self.file_model.setHorizontalHeaderLabels(self._file_headers())
            self.status_label.setText(self.tr("未连接"))
            self._update_action_states()
            return

        try:
            self.status_label.setText(self.tr("正在加载..."))
            items: List[FTPFileItem] = []

            # 获取文件列表
            if hasattr(self._connection, "list_dir"):
                items = self._connection.list_dir(self._current_path)
                self._update_file_list(items)

            self.path_edit.setText(self._current_path)
            self.directory_changed.emit(self._current_path)
            self._update_action_states()

        except Exception as e:
            self._logger.error(f"刷新目录失败: {e}")
            self.status_label.setText(self.tr(f"错误: {e}"))
            self._update_action_states()

    def _update_file_list(self, items: List[FTPFileItem]) -> None:
        """
        更新文件列表

        Args:
            items: 文件项列表
        """
        self._all_items = list(items)
        self._apply_filter(self.filter_edit.text(), preserve_selection=False)

    def _populate_file_list(self, items: List[FTPFileItem]) -> None:
        """根据给定项目填充列表。"""
        self.file_model.clear()
        self.file_model.setHorizontalHeaderLabels(self._file_headers())
        self._current_items = list(items)

        for item in items:
            # 名称
            name_item = QStandardItem(item.name)
            name_item.setData(item.is_dir, Qt.UserRole)
            name_item.setToolTip(self._join_remote_path(self._current_path, item.name))
            name_item.setIcon(self._item_icon(item))

            type_item = QStandardItem(self.tr("目录") if item.is_dir else self.tr("文件"))

            # 大小
            size_str = self._format_size(item.size) if not item.is_dir else "<DIR>"
            size_item = QStandardItem(size_str)

            # 修改时间
            time_item = QStandardItem(item.modify_time or "")

            # 权限
            perm_item = QStandardItem(item.permissions or "")

            owner_parts = [part for part in (item.owner, item.group) if part]
            owner_item = QStandardItem(":".join(owner_parts))

            self.file_model.appendRow(
                [name_item, type_item, size_item, time_item, perm_item, owner_item]
            )

    def _apply_filter(self, text: str, preserve_selection: bool = True) -> None:
        """按名称过滤当前目录项目。"""
        selected_names = set()
        if preserve_selection:
            selected_names = {item.text() for item in self._selected_name_items()}

        keyword = (text or "").strip().lower()
        if keyword:
            filtered = [item for item in self._all_items if keyword in item.name.lower()]
        else:
            filtered = list(self._all_items)

        filtered = self._sorted_items(filtered)
        self._populate_file_list(filtered)
        self._restore_selection_by_name(selected_names)
        self._refresh_browser_status()
        self._update_action_states()

    def _on_sort_changed(self) -> None:
        """排序类型变化时刷新排序控件和列表。"""
        self.sort_order_combo.setEnabled(
            self.sort_combo.currentIndex() != 0 and self._connection is not None
        )
        self._apply_filter(self.filter_edit.text())

    def _sorted_items(self, items: List[FTPFileItem]) -> List[FTPFileItem]:
        """按当前选择返回排序后的项目列表。"""
        mode = self.sort_combo.currentText()
        if mode == self.tr("原始顺序"):
            return list(items)

        reverse = self.sort_order_combo.currentText() == self.tr("降序")
        if mode == self.tr("名称"):
            key = lambda item: (not item.is_dir, item.name.lower())
        elif mode == self.tr("类型"):
            key = lambda item: (
                0 if item.is_dir else 1,
                Path(item.name).suffix.lower(),
                item.name.lower(),
            )
        elif mode == self.tr("大小"):
            key = lambda item: (0 if item.is_dir else 1, item.size, item.name.lower())
        elif mode == self.tr("修改时间"):
            key = lambda item: (item.modify_time or "", item.name.lower())
        else:
            return list(items)
        return sorted(items, key=key, reverse=reverse)

    def eventFilter(self, watched, event) -> bool:
        """接管文件列表视口的拖拽上传事件。"""
        if watched is self.file_list.viewport():
            if event.type() == QEvent.DragEnter:
                self.dragEnterEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.DragMove:
                self.dragMoveEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Drop:
                self.dropEvent(event)
                return event.isAccepted()
        return super().eventFilter(watched, event)

    def _mime_has_local_paths(self, mime_data) -> bool:
        """判断拖拽数据中是否包含本地文件或目录。"""
        if mime_data is None or not mime_data.hasUrls():
            return False
        return any(url.isLocalFile() and url.toLocalFile() for url in mime_data.urls())

    def _extract_local_paths_from_mime_data(self, mime_data) -> List[str]:
        """从拖拽数据中提取本地路径。"""
        if not self._mime_has_local_paths(mime_data):
            return []
        seen: set[str] = set()
        paths: List[str] = []
        for url in mime_data.urls():
            local_path = url.toLocalFile() if url.isLocalFile() else ""
            if not local_path or local_path in seen:
                continue
            seen.add(local_path)
            paths.append(local_path)
        return paths

    def dragEnterEvent(self, event) -> None:
        """允许本地文件或目录拖入。"""
        if self._mime_has_local_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        """持续允许有效拖拽目标。"""
        if self._mime_has_local_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        """处理拖拽上传。"""
        paths = self._extract_local_paths_from_mime_data(event.mimeData())
        if not paths:
            event.ignore()
            return
        enqueued = self._enqueue_upload_paths(paths)
        if enqueued:
            self.status_label.setText(self.tr(f"已通过拖拽加入 {enqueued} 个上传任务"))
            event.acceptProposedAction()
            return
        event.ignore()

    def _restore_selection_by_name(self, selected_names: set[str]) -> None:
        """按名称恢复过滤后的选中状态。"""
        if not selected_names:
            return
        selection_model = self.file_list.selectionModel()
        if selection_model is None:
            return
        for row, item in enumerate(self._current_items):
            if item.name in selected_names:
                selection_model.select(
                    self.file_model.index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows,
                )

    def _refresh_browser_status(self) -> None:
        """刷新底部状态文本。"""
        total = len(self._all_items)
        visible = len(self._current_items)
        parts = []
        if self.filter_edit.text().strip():
            parts.append(self.tr(f"显示 {visible} / 共 {total} 项"))
        else:
            parts.append(self.tr(f"共 {total} 项"))
        if self.sort_combo.currentIndex() != 0:
            parts.append(
                self.tr(
                    f"排序: {self.sort_combo.currentText()} {self.sort_order_combo.currentText()}"
                )
            )
        self.status_label.setText(self.tr("就绪 · ") + " · ".join(parts))

    def _update_selection_details(self, items: Optional[List[FTPFileItem]] = None) -> None:
        """详情面板已移除，选择变化不再维护重复展示。"""
        _ = items
        return

    def _item_icon(self, item: FTPFileItem) -> QIcon:
        """返回文件项图标。"""
        if item.is_dir:
            directory_icon = QIcon.fromTheme("folder")
            return directory_icon if not directory_icon.isNull() else icon("sftp")
        suffix = Path(item.name).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
            themed_icon = QIcon.fromTheme("image-x-generic")
        elif suffix in {".zip", ".gz", ".bz2", ".xz", ".rar", ".7z", ".tar"}:
            themed_icon = QIcon.fromTheme("package-x-generic")
        elif suffix in {
            ".py",
            ".sh",
            ".js",
            ".ts",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".md",
        }:
            themed_icon = QIcon.fromTheme("text-x-script")
            if themed_icon.isNull():
                themed_icon = QIcon.fromTheme("text-x-generic")
        else:
            themed_icon = QIcon.fromTheme("text-x-generic")
        return themed_icon if not themed_icon.isNull() else icon("ftp")

    def _cell_text(self, row: int, column: int) -> str:
        """读取指定单元格文本。"""
        item = self.file_model.item(row, column)
        if item is None:
            return "—"
        text = item.text().strip()
        return text or "—"

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def _go_up(self) -> None:
        """返回上级目录"""
        if self._current_path != "/":
            parent = posixpath.dirname(self._current_path.rstrip("/")) or "/"
            self._current_path = parent
            self.refresh()

    def _go_home(self) -> None:
        """返回主目录"""
        self._current_path = "/"
        self.refresh()

    def _connection_type_key(self) -> str:
        """返回当前连接类型的小写键。"""
        connection_type = getattr(getattr(self._connection, "config", None), "connection_type", "")
        if isinstance(connection_type, ConnectionType):
            return connection_type.value.lower()
        return str(connection_type or "").strip().lower()

    def _supports_terminal_link(self) -> bool:
        """判断当前文件连接是否支持与终端联动。"""
        return self._connection_type_key() in {"ssh", "sftp"}

    def _navigate_to_path(self) -> None:
        """导航到指定路径"""
        path = self.path_edit.text().strip()
        if path:
            self._current_path = path
            self.refresh()

    def _copy_current_path(self) -> None:
        """复制当前目录路径。"""
        QApplication.clipboard().setText(self._current_path)
        self.status_label.setText(self.tr(f"已复制当前路径: {self._current_path}"))

    def _open_selected_item(self) -> None:
        """快速打开当前选中项目。"""
        items = self._get_selected_name_items()
        if len(items) != 1:
            return
        index = self.file_model.indexFromItem(items[0])
        if index.isValid():
            self._on_item_double_clicked(index)

    def _copy_selected_name(self) -> None:
        """复制选中项名称。"""
        items = self._get_selected_name_items()
        if len(items) != 1:
            return
        QApplication.clipboard().setText(items[0].text())
        self.status_label.setText(self.tr(f"已复制文件名: {items[0].text()}"))

    def _copy_selected_path(self) -> None:
        """复制选中项完整路径。"""
        items = self._get_selected_name_items()
        if len(items) != 1:
            return
        remote_path = self._build_selected_remote_path(items[0])
        QApplication.clipboard().setText(remote_path)
        self.status_label.setText(self.tr(f"已复制路径: {remote_path}"))

    def _target_directory_for_terminal(self, item: Optional[QStandardItem] = None) -> str:
        """根据当前选择解析应发送到终端的目录。"""
        if item is None:
            return self._current_path
        remote_path = self._build_selected_remote_path(item)
        if bool(item.data(Qt.UserRole)):
            return remote_path
        return posixpath.dirname(remote_path.rstrip("/")) or "/"

    def _emit_terminal_request(self, remote_dir: str) -> None:
        """向主窗口请求在终端中打开指定目录。"""
        if not self._supports_terminal_link():
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前连接类型不支持终端联动"),
            )
            return
        normalized_dir = remote_dir.strip() or "/"
        self.terminal_requested.emit(normalized_dir)
        self.status_label.setText(self.tr(f"已请求在终端打开: {normalized_dir}"))

    def _request_terminal_for_current_path(self) -> None:
        """在终端中打开当前目录。"""
        self._emit_terminal_request(self._current_path)

    def _request_terminal_for_selection(self) -> None:
        """在终端中打开所选项目所在目录。"""
        items = self._get_selected_name_items()
        if len(items) != 1:
            return
        self._emit_terminal_request(self._target_directory_for_terminal(items[0]))

    def _create_folder(self) -> None:
        """创建文件夹"""
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, self.tr("新建文件夹"), self.tr("文件夹名称:"))

        if ok and name:
            try:
                if hasattr(self._connection, "mkdir"):
                    self._connection.mkdir(self._join_remote_path(self._current_path, name))
                    self.refresh()
            except Exception as e:
                QMessageBox.critical(self, self.tr("错误"), str(e))

    def _build_upload_tasks(
        self,
        file_paths: List[str],
        errors: Optional[List[str]] = None,
        reserved_remote_paths: Optional[set[str]] = None,
    ) -> List[TransferTask]:
        """根据本地文件路径构建批量上传任务。"""
        tasks = []
        reserved_paths = reserved_remote_paths if reserved_remote_paths is not None else set()
        total = len(file_paths)
        for index, file_path in enumerate(file_paths, start=1):
            local_name = Path(file_path).name
            remote_path = self._join_remote_path(self._current_path, local_name)
            resolved_remote_path = self._resolve_remote_conflict_path(
                remote_path,
                self.tr("上传"),
                errors=errors,
                reserved_paths=reserved_paths,
            )
            if not resolved_remote_path:
                continue
            reserved_paths.add(resolved_remote_path)
            display_name = local_name
            if resolved_remote_path != remote_path:
                display_name = f"{local_name} -> {posixpath.basename(resolved_remote_path)}"
            tasks.append(
                TransferTask(
                    task_id=str(uuid4()),
                    operation=self.tr("上传"),
                    display_name=display_name,
                    title=self.tr("上传文件"),
                    label=self.tr(f"正在上传 ({index}/{total}): {display_name}"),
                    runner=lambda progress, local_path=file_path, target_path=resolved_remote_path: (
                        self._run_upload_task(local_path, target_path, progress)
                    ),
                    success_payload=file_path,
                )
            )
        return tasks

    def _build_directory_upload_tasks(
        self,
        directory_paths: List[str],
        errors: Optional[List[str]] = None,
        reserved_remote_paths: Optional[set[str]] = None,
    ) -> List[TransferTask]:
        """根据本地目录递归构建上传任务。"""
        tasks = []
        directory_entries: List[tuple[str, str, str]] = []
        file_entries: List[tuple[str, str, str]] = []
        reserved_paths = reserved_remote_paths if reserved_remote_paths is not None else set()

        for directory_path in directory_paths:
            local_root = Path(directory_path)
            remote_root = self._resolve_remote_conflict_path(
                self._join_remote_path(self._current_path, local_root.name),
                self.tr("上传目录"),
                errors=errors,
                reserved_paths=reserved_paths,
            )
            if not remote_root:
                continue
            reserved_paths.add(remote_root)
            for current_dir, subdirs, filenames in os.walk(local_root):
                subdirs.sort()
                filenames.sort()
                current_path = Path(current_dir)
                relative_dir = current_path.relative_to(local_root)
                remote_dir = remote_root
                if str(relative_dir) != ".":
                    remote_dir = self._join_remote_path(
                        remote_root,
                        relative_dir.as_posix(),
                    )
                if not subdirs and not filenames:
                    directory_entries.append(
                        (
                            str(current_path),
                            remote_dir,
                            current_path.name,
                        )
                    )
                for filename in filenames:
                    local_file = current_path / filename
                    remote_file = self._join_remote_path(remote_dir, filename)
                    display_name = (
                        f"{local_root.name}/{local_file.relative_to(local_root).as_posix()}"
                    )
                    file_entries.append((str(local_file), remote_file, display_name))

        total = len(directory_entries) + len(file_entries)
        index = 0
        for local_dir, remote_dir, display_name in directory_entries:
            index += 1
            tasks.append(
                TransferTask(
                    task_id=str(uuid4()),
                    operation=self.tr("上传目录"),
                    display_name=display_name,
                    title=self.tr("上传目录"),
                    label=self.tr(f"正在创建目录 ({index}/{total}): {display_name}"),
                    runner=lambda progress, target_path=remote_dir: (
                        self._run_create_directory_task(target_path, progress)
                    ),
                    success_payload=local_dir,
                )
            )
        for local_file, remote_file, display_name in file_entries:
            index += 1
            resolved_remote_path = self._resolve_remote_conflict_path(
                remote_file,
                self.tr("上传"),
                errors=errors,
                reserved_paths=reserved_paths,
            )
            if not resolved_remote_path:
                continue
            reserved_paths.add(resolved_remote_path)
            final_display_name = display_name
            if resolved_remote_path != remote_file:
                final_display_name = f"{display_name} -> {posixpath.basename(resolved_remote_path)}"
            tasks.append(
                TransferTask(
                    task_id=str(uuid4()),
                    operation=self.tr("上传"),
                    display_name=final_display_name,
                    title=self.tr("上传目录"),
                    label=self.tr(f"正在上传 ({index}/{total}): {final_display_name}"),
                    runner=lambda progress, source_path=local_file, target_path=resolved_remote_path: (
                        self._run_upload_task(source_path, target_path, progress)
                    ),
                    success_payload=local_file,
                )
            )
        return tasks

    def _enqueue_upload_paths(self, paths: List[str]) -> int:
        """统一处理文件与目录上传入口。"""
        if not self._connection or not hasattr(self._connection, "upload_from_path"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持上传"))
            return 0

        file_paths: List[str] = []
        directory_paths: List[str] = []
        errors: List[str] = []
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists():
                errors.append(self.tr(f"路径不存在: {raw_path}"))
                continue
            if path.is_file():
                file_paths.append(str(path))
            elif path.is_dir():
                directory_paths.append(str(path))
            else:
                errors.append(self.tr(f"不支持的路径类型: {raw_path}"))

        reserved_remote_paths: set[str] = set()
        try:
            tasks = self._build_upload_tasks(
                file_paths,
                errors=errors,
                reserved_remote_paths=reserved_remote_paths,
            )
            if directory_paths:
                if not self._has_connection_capability("mkdir"):
                    errors.append(self.tr("当前连接不支持目录上传"))
                else:
                    tasks.extend(
                        self._build_directory_upload_tasks(
                            directory_paths,
                            errors=errors,
                            reserved_remote_paths=reserved_remote_paths,
                        )
                    )
        except ConflictResolutionCanceled:
            self.status_label.setText(self.tr("上传已取消"))
            return 0

        self._attach_batch_to_tasks(tasks, self.tr("上传"))
        enqueued = self._enqueue_transfer_tasks(tasks)
        self._show_batch_result(self.tr("上传"), errors)
        return enqueued

    def _enqueue_upload_files(self, file_paths: List[str]) -> int:
        """将多个本地文件统一加入上传队列。"""
        return self._enqueue_upload_paths(file_paths)

    def _select_and_upload_files(self) -> None:
        """选择本地文件并加入上传队列。"""
        file_paths, _ = QFileDialog.getOpenFileNames(self, self.tr("选择文件"))
        if not file_paths:
            return
        if not self._connection or not hasattr(self._connection, "upload_from_path"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持上传"))
            return
        enqueued = self._enqueue_upload_files(file_paths)
        if enqueued:
            self.status_label.setText(self.tr(f"已加入 {enqueued} 个上传任务"))

    def _upload_directory(self) -> None:
        """选择目录并递归加入上传队列。"""
        directory = QFileDialog.getExistingDirectory(self, self.tr("选择目录"))
        if not directory:
            return
        if not self._connection or not hasattr(self._connection, "upload_from_path"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持上传"))
            return
        if not self._has_connection_capability("mkdir"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持目录上传"))
            return
        enqueued = self._enqueue_upload_paths([directory])
        if enqueued:
            self.status_label.setText(self.tr(f"已加入 {enqueued} 个目录上传任务"))

    def _upload_file(self) -> None:
        """上传文件。"""
        self._select_and_upload_files()

    def _on_item_double_clicked(self, index: QModelIndex) -> None:
        """双击项目"""
        item = self.file_model.item(index.row(), 0)
        if item is None:
            return
        is_dir = item.data(Qt.UserRole)

        if is_dir:
            name = item.text()
            self._current_path = self._join_remote_path(self._current_path, name)
            self.refresh()
        else:
            self._edit_item(item)

    def _show_context_menu(self, pos) -> None:
        """显示右键菜单"""
        index = self.file_list.indexAt(pos)
        if not index.isValid():
            menu = self._build_background_context_menu()
            menu.exec(self.file_list.viewport().mapToGlobal(pos))
            return

        self.file_list.setCurrentIndex(index)
        selection_model = self.file_list.selectionModel()
        if selection_model is not None:
            if not selection_model.isSelected(index):
                selection_model.select(
                    index,
                    QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
                )

        menu = self._build_context_menu()
        menu.exec(self.file_list.viewport().mapToGlobal(pos))

    def _build_background_context_menu(self) -> QMenu:
        """构造空白区域右键菜单。"""
        menu = QMenu(self)

        refresh_action = QAction(self.tr("刷新目录"), self)
        refresh_action.triggered.connect(self.refresh)
        refresh_action.setEnabled(self._connection is not None)
        menu.addAction(refresh_action)

        copy_current_path_action = QAction(self.tr("复制当前路径"), self)
        copy_current_path_action.triggered.connect(self._copy_current_path)
        copy_current_path_action.setEnabled(self._connection is not None)
        menu.addAction(copy_current_path_action)

        open_terminal_action = QAction(self.tr("在终端打开当前目录"), self)
        open_terminal_action.triggered.connect(self._request_terminal_for_current_path)
        open_terminal_action.setEnabled(
            self._connection is not None and self._supports_terminal_link()
        )
        menu.addAction(open_terminal_action)

        menu.addSeparator()

        mkdir_action = QAction(self.tr("新建文件夹"), self)
        mkdir_action.triggered.connect(self._create_folder)
        mkdir_action.setEnabled(self.mkdir_action.isEnabled())
        menu.addAction(mkdir_action)

        create_file_action = QAction(self.tr("新建文件"), self)
        create_file_action.triggered.connect(self._create_file)
        create_file_action.setEnabled(self.create_file_action.isEnabled())
        menu.addAction(create_file_action)

        upload_action = QAction(self.tr("上传"), self)
        upload_action.triggered.connect(self._upload_file)
        upload_action.setEnabled(self.upload_action.isEnabled())
        menu.addAction(upload_action)

        upload_directory_action = QAction(self.tr("上传目录"), self)
        upload_directory_action.triggered.connect(self._upload_directory)
        upload_directory_action.setEnabled(self.upload_directory_action.isEnabled())
        menu.addAction(upload_directory_action)

        return menu

    def _build_context_menu(self) -> QMenu:
        """构造当前选择对应的右键菜单，便于测试和复用。"""
        menu = QMenu(self)
        single_selection = len(self._selected_name_items()) == 1

        open_action = QAction(self.tr("打开"), self)
        open_action.triggered.connect(self._open_selected_item)
        open_action.setEnabled(single_selection)
        menu.addAction(open_action)

        copy_name_action = QAction(self.tr("复制文件名"), self)
        copy_name_action.triggered.connect(self._copy_selected_name)
        copy_name_action.setEnabled(single_selection)
        menu.addAction(copy_name_action)

        copy_path_action = QAction(self.tr("复制路径"), self)
        copy_path_action.triggered.connect(self._copy_selected_path)
        copy_path_action.setEnabled(single_selection)
        menu.addAction(copy_path_action)

        open_terminal_action = QAction(self.tr("在终端中打开"), self)
        open_terminal_action.triggered.connect(self._request_terminal_for_selection)
        open_terminal_action.setEnabled(self._context_action_states.get("open_in_terminal", False))
        menu.addAction(open_terminal_action)

        refresh_action = QAction(self.tr("刷新目录"), self)
        refresh_action.triggered.connect(self.refresh)
        refresh_action.setEnabled(self._connection is not None)
        menu.addAction(refresh_action)

        menu.addSeparator()

        properties_action = QAction(self.tr("属性"), self)
        properties_action.triggered.connect(self._show_properties_selected)
        properties_action.setEnabled(self._context_action_states.get("properties", False))
        menu.addAction(properties_action)

        edit_action = QAction(self.tr("编辑"), self)
        edit_action.triggered.connect(self._edit_selected)
        edit_action.setEnabled(self._context_action_states.get("edit", False))
        menu.addAction(edit_action)

        menu.addSeparator()

        download_action = QAction(self.tr("下载"), self)
        download_action.triggered.connect(self._download_selected)
        download_action.setEnabled(self._context_action_states.get("download", False))
        menu.addAction(download_action)

        rename_action = QAction(self.tr("重命名"), self)
        rename_action.triggered.connect(self._rename_selected)
        rename_action.setEnabled(self._context_action_states.get("rename", False))
        menu.addAction(rename_action)

        copy_action = QAction(self.tr("复制到"), self)
        copy_action.triggered.connect(self._copy_selected)
        copy_action.setEnabled(self._context_action_states.get("copy", False))
        menu.addAction(copy_action)

        move_action = QAction(self.tr("移动到"), self)
        move_action.triggered.connect(self._move_selected)
        move_action.setEnabled(self._context_action_states.get("move", False))
        menu.addAction(move_action)

        permission_action = QAction(self.tr("修改权限"), self)
        permission_action.triggered.connect(self._chmod_selected)
        permission_action.setEnabled(self._context_action_states.get("chmod", False))
        menu.addAction(permission_action)

        menu.addSeparator()

        compress_action = QAction(self.tr("压缩"), self)
        compress_action.triggered.connect(self._compress_selected)
        compress_action.setEnabled(self._context_action_states.get("compress", False))
        menu.addAction(compress_action)

        extract_action = QAction(self.tr("解压"), self)
        extract_action.triggered.connect(self._extract_selected)
        extract_action.setEnabled(self._context_action_states.get("extract", False))
        menu.addAction(extract_action)

        menu.addSeparator()

        delete_action = QAction(self.tr("删除"), self)
        delete_action.triggered.connect(self._delete_selected)
        delete_action.setEnabled(self._context_action_states.get("delete", False))
        menu.addAction(delete_action)
        return menu

    def _download_selected(self) -> None:
        """下载选中文件"""
        items = self._get_selected_name_items()
        if not items:
            return

        directory_items = [item for item in items if item.data(Qt.UserRole)]
        files = [item for item in items if not item.data(Qt.UserRole)]

        if not self._connection or not hasattr(self._connection, "download_to_path"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持下载"))
            return
        if directory_items and not self._has_connection_capability("list_dir"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持目录下载"))
            return

        target_dir: Optional[str] = None
        explicit_local_paths: dict[str, str] = {}
        single_file_only = len(files) == 1 and not directory_items
        if single_file_only:
            local_path, _ = QFileDialog.getSaveFileName(self, self.tr("保存文件"), files[0].text())
            if not local_path:
                return
            explicit_local_paths[files[0].text()] = local_path
        else:
            target_dir = QFileDialog.getExistingDirectory(self, self.tr("选择保存目录"))
            if not target_dir:
                return

        tasks = []
        errors: List[str] = []
        total = len(files)
        reserved_local_paths: set[str] = set()
        try:
            if directory_items:
                tasks.extend(
                    self._build_directory_download_tasks(
                        directory_items,
                        str(target_dir),
                        errors=errors,
                        reserved_local_paths=reserved_local_paths,
                    )
                )
            for index, item in enumerate(files, start=1):
                remote_path = self._build_selected_remote_path(item)
                local_path = explicit_local_paths.get(item.text()) or str(
                    Path(target_dir) / item.text()
                )
                resolved_local_path = self._resolve_local_conflict_path(
                    local_path,
                    self.tr("下载"),
                    errors=errors,
                    reserved_paths=reserved_local_paths,
                )
                if not resolved_local_path:
                    continue
                reserved_local_paths.add(resolved_local_path)
                display_name = item.text()
                if resolved_local_path != local_path:
                    display_name = f"{item.text()} -> {Path(resolved_local_path).name}"
                tasks.append(
                    TransferTask(
                        task_id=str(uuid4()),
                        operation=self.tr("下载"),
                        display_name=display_name,
                        title=self.tr("下载文件"),
                        label=self.tr(f"正在下载 ({index}/{max(total, 1)}): {display_name}"),
                        runner=lambda progress, source_path=remote_path, target_path=resolved_local_path: (
                            self._run_download_task(source_path, target_path, progress)
                        ),
                        success_payload=resolved_local_path,
                    )
                )
        except ConflictResolutionCanceled:
            self.status_label.setText(self.tr("下载已取消"))
            return
        self._attach_batch_to_tasks(tasks, self.tr("下载"))
        enqueued = self._enqueue_transfer_tasks(tasks)
        if enqueued:
            self.status_label.setText(self.tr(f"已加入 {enqueued} 个下载任务"))
        self._show_batch_result(self.tr("下载"), errors)

    def _edit_selected(self) -> None:
        """编辑选中的文本文件。"""
        items = self._get_selected_name_items()
        if not items:
            return
        if len(items) != 1:
            QMessageBox.information(self, self.tr("提示"), self.tr("编辑一次只能处理一个文件"))
            return
        item = items[0]
        if item.data(Qt.UserRole):
            QMessageBox.information(self, self.tr("提示"), self.tr("目录不能直接编辑"))
            return
        self._edit_item(item)

    def _rename_selected(self) -> None:
        """重命名选中文件"""
        items = self._get_selected_name_items()
        if not items:
            return
        if len(items) != 1:
            QMessageBox.information(self, self.tr("提示"), self.tr("重命名一次只能处理一个项目"))
            return
        item = items[0]

        old_path = self._build_selected_remote_path(item)
        new_name, ok = QInputDialog.getText(
            self,
            self.tr("重命名"),
            self.tr("新名称:"),
            text=item.text(),
        )
        if not ok or not new_name.strip():
            return

        if not self._connection or not hasattr(self._connection, "rename"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持重命名"))
            return

        new_path = self._join_remote_path(posixpath.dirname(old_path), new_name.strip())

        try:
            self._connection.rename(old_path, new_path)
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, self.tr("错误"), str(e))

    def _prompt_target_directory(self, title: str) -> Optional[str]:
        """弹出目标目录输入框。"""
        target_dir, ok = QInputDialog.getText(
            self,
            title,
            self.tr("目标目录:"),
            text=self._current_path,
        )
        if not ok:
            return None
        normalized = target_dir.strip()
        if not normalized:
            QMessageBox.warning(self, self.tr("错误"), self.tr("目标目录不能为空"))
            return None
        return normalized

    def _copy_selected(self) -> None:
        """批量复制选中项目。"""
        items = self._get_selected_name_items()
        if not items:
            return
        if not self._connection or not hasattr(self._connection, "copy_paths"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持批量复制"))
            return

        target_dir = self._prompt_target_directory(self.tr("复制到"))
        if target_dir is None:
            return

        source_paths = [self._build_selected_remote_path(item) for item in items]
        try:
            self._connection.copy_paths(source_paths, target_dir)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, self.tr("错误"), str(exc))

    def _move_selected(self) -> None:
        """批量移动选中项目。"""
        items = self._get_selected_name_items()
        if not items:
            return
        if not self._connection or not hasattr(self._connection, "move_paths"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持批量移动"))
            return

        target_dir = self._prompt_target_directory(self.tr("移动到"))
        if target_dir is None:
            return

        source_paths = [self._build_selected_remote_path(item) for item in items]
        try:
            self._connection.move_paths(source_paths, target_dir)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, self.tr("错误"), str(exc))

    def _chmod_selected(self) -> None:
        """修改选中项目权限。"""
        items = self._get_selected_name_items()
        if not items:
            return
        if not self._connection or not hasattr(self._connection, "chmod"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持修改权限"))
            return

        mode, ok = QInputDialog.getText(
            self,
            self.tr("修改权限"),
            self.tr("权限值（八进制，例如 755）:"),
            text="755",
        )
        if not ok or not mode.strip():
            return

        errors = []
        for item in items:
            try:
                self._connection.chmod(self._build_selected_remote_path(item), mode.strip())
            except Exception as exc:
                errors.append(f"{item.text()}: {exc}")

        self.refresh()
        self._show_batch_result(self.tr("修改权限"), errors)

    @staticmethod
    def _permission_text_to_mode(permissions: str) -> int:
        """将 drwxr-xr-x 形式权限转换为八进制。"""
        normalized = (permissions or "").strip()
        if len(normalized) < 10:
            raise ValueError("权限字符串格式无效")
        mode = 0
        triplets = (normalized[1:4], normalized[4:7], normalized[7:10])
        for index, triplet in enumerate(triplets):
            digit = 0
            if triplet[0] == "r":
                digit += 4
            if triplet[1] == "w":
                digit += 2
            if triplet[2] in {"x", "s", "t"}:
                digit += 1
            mode |= digit << (3 - index - 1) * 3
        return mode

    def _item_details_from_cache(self, name: str) -> Optional[FTPFileItem]:
        """从当前缓存中按名称查找文件项详情。"""
        for item in self._all_items:
            if item.name == name:
                return item
        return None

    def _resolve_item_details(self, item: QStandardItem) -> FTPFileItem:
        """解析选中项的详细属性。"""
        remote_path = self._build_selected_remote_path(item)
        if self._connection and hasattr(self._connection, "get_file_info"):
            details = self._connection.get_file_info(remote_path)
            if isinstance(details, FTPFileItem):
                return details

        cached = self._item_details_from_cache(item.text())
        if cached is not None:
            return cached

        return FTPFileItem(
            name=item.text(),
            is_dir=bool(item.data(Qt.UserRole)),
        )

    def _create_properties_dialog(self, item: QStandardItem) -> FilePropertiesDialog:
        """创建属性对话框。"""
        details = self._resolve_item_details(item)
        remote_path = self._build_selected_remote_path(item)
        return FilePropertiesDialog(
            remote_path,
            details,
            allow_chmod=self._has_connection_capability("chmod"),
            allow_chown=self._has_connection_capability("chown"),
            parent=self,
        )

    def _show_properties_selected(self) -> None:
        """显示选中项属性。"""
        items = self._get_selected_name_items()
        if not items:
            return
        if len(items) != 1:
            QMessageBox.information(self, self.tr("提示"), self.tr("属性一次只能查看一个项目"))
            return

        item = items[0]
        try:
            dialog = self._create_properties_dialog(item)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("错误"), str(exc))
            return

        if not dialog.exec():
            return

        try:
            remote_path = self._build_selected_remote_path(item)
            applied_changes: list[str] = []

            new_mode = dialog.permission_mode()
            if (
                self._has_connection_capability("chmod")
                and new_mode
                and new_mode != dialog.initial_permission_mode()
            ):
                self._connection.chmod(remote_path, new_mode)
                applied_changes.append(self.tr(f"权限 {new_mode}"))

            new_owner = dialog.owner_value()
            new_group = dialog.group_value()
            if self._has_connection_capability("chown") and (
                new_owner != dialog.initial_owner_value()
                or new_group != dialog.initial_group_value()
            ):
                self._connection.chown(
                    remote_path,
                    owner=new_owner or None,
                    group=new_group or None,
                )
                change_text = self.tr(f"属主/属组 {new_owner or '-'}:{new_group or '-'}")
                applied_changes.append(change_text)

            if applied_changes:
                self.refresh()
                self.status_label.setText(
                    self.tr(f"已更新属性: {item.text()} · {' / '.join(applied_changes)}")
                )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("错误"), str(exc))

    def _compress_selected(self) -> None:
        """压缩选中的远程文件或目录。"""
        items = self._get_selected_name_items()
        if not items:
            return
        if not self._connection or not hasattr(self._connection, "create_archive"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持压缩"))
            return

        default_name = "archive.tar.gz"
        if len(items) == 1:
            default_name = f"{items[0].text().rstrip('/')}.tar.gz"

        archive_name, ok = QInputDialog.getText(
            self,
            self.tr("压缩"),
            self.tr("压缩包名称:"),
            text=default_name,
        )
        if not ok or not archive_name.strip():
            return

        archive_path = self._join_remote_path(self._current_path, archive_name.strip())
        source_paths = [self._build_selected_remote_path(item) for item in items]
        try:
            self._connection.create_archive(source_paths, archive_path)
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, self.tr("错误"), str(exc))

    def _extract_selected(self) -> None:
        """解压选中的远程压缩包。"""
        items = self._get_selected_name_items()
        if not items:
            return
        if not self._connection or not hasattr(self._connection, "extract_archive"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持解压"))
            return

        files = [item for item in items if not item.data(Qt.UserRole)]
        skipped_dirs = [item.text() for item in items if item.data(Qt.UserRole)]
        errors = []
        if skipped_dirs:
            errors.append(self.tr(f"已跳过目录: {', '.join(skipped_dirs)}"))

        for item in files:
            try:
                self._connection.extract_archive(
                    self._build_selected_remote_path(item), self._current_path
                )
            except Exception as exc:
                errors.append(f"{item.text()}: {exc}")

        self.refresh()
        self._show_batch_result(self.tr("解压"), errors)

    def _delete_selected(self) -> None:
        """删除选中文件"""
        items = self._get_selected_name_items()
        if not items:
            return

        reply = QMessageBox.question(
            self,
            self.tr("确认删除"),
            self.tr(f"确定删除选中的 {len(items)} 个项目吗？"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        errors = []
        try:
            for item in items:
                target_path = self._build_selected_remote_path(item)
                is_dir = bool(item.data(Qt.UserRole))
                try:
                    if is_dir:
                        self._delete_remote_directory(target_path)
                    elif hasattr(self._connection, "delete_file"):
                        self._connection.delete_file(target_path)
                    else:
                        QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持删除"))
                        return
                except Exception as e:
                    errors.append(f"{item.text()}: {e}")
            self.refresh()
            self._show_batch_result(self.tr("删除"), errors)
        except Exception as e:
            QMessageBox.critical(self, self.tr("错误"), str(e))

    def _delete_remote_directory(self, path: str) -> None:
        """递归删除远程目录。"""
        if not self._connection:
            raise RuntimeError(self.tr("当前没有活动连接"))
        if not hasattr(self._connection, "list_dir") or not hasattr(self._connection, "rmdir"):
            raise RuntimeError(self.tr("当前连接不支持目录删除"))

        for entry in self._connection.list_dir(path):
            child_path = self._join_remote_path(path, entry.name)
            if entry.is_dir:
                self._delete_remote_directory(child_path)
            else:
                if not hasattr(self._connection, "delete_file"):
                    raise RuntimeError(self.tr("当前连接不支持文件删除"))
                self._connection.delete_file(child_path)

        self._connection.rmdir(path)

    def _create_file(self) -> None:
        """创建空文件。"""
        name, ok = QInputDialog.getText(
            self,
            self.tr("新建文件"),
            self.tr("文件名:"),
        )
        if not ok or not name.strip():
            return
        if not self._connection or not hasattr(self._connection, "create_file"):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持创建文件"))
            return
        try:
            self._connection.create_file(self._join_remote_path(self._current_path, name.strip()))
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, self.tr("错误"), str(exc))

    def _get_selected_name_items(self) -> List[QStandardItem]:
        """获取当前选中的名称列项目。"""
        items = self._selected_name_items()
        if not items:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择文件"))
        return items

    def _build_selected_remote_path(self, item: QStandardItem) -> str:
        """构造选中项对应的远程路径。"""
        return self._join_remote_path(self._current_path, item.text())

    def _run_transfer_with_progress(
        self,
        title: str,
        label: str,
        transfer_func: Callable[[Callable[[int, int], bool]], None],
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """执行带进度反馈的传输任务。"""
        dialog = QProgressDialog(label, self.tr("取消"), 0, 100, self)
        dialog.setWindowTitle(title)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.show()
        self._active_progress_dialog = dialog

        def progress_callback(transferred: int, total: int) -> bool:
            if total > 0:
                capped_total = min(total, 2_147_483_647)
                capped_value = min(transferred, capped_total)
                dialog.setMaximum(capped_total)
                dialog.setValue(capped_value)
            else:
                dialog.setMaximum(0)
            QApplication.processEvents()
            if on_progress:
                on_progress(transferred, total)
            return not dialog.wasCanceled()

        try:
            transfer_func(progress_callback)
            if dialog.wasCanceled():
                raise TransferCanceled(self.tr("用户取消"))
            if dialog.maximum() > 0:
                dialog.setValue(dialog.maximum())
        except Exception as exc:
            # 某些连接实现会在 progress_callback 返回 False 时抛异常；这里统一映射为“已取消”，避免被当作失败重试。
            if dialog.wasCanceled():
                raise TransferCanceled(self.tr("用户取消")) from exc
            raise
        finally:
            self._active_progress_dialog = None
            dialog.close()

    def _show_batch_result(self, operation: str, errors: List[str]) -> None:
        """显示批量操作结果。"""
        if not errors:
            return
        QMessageBox.warning(
            self,
            self.tr(f"{operation}结果"),
            "\n".join(errors),
        )

    def _edit_item(self, item: QStandardItem) -> None:
        """打开远程文本文件编辑对话框。"""
        if (
            not self._connection
            or not hasattr(self._connection, "read_text")
            or not hasattr(self._connection, "write_text")
        ):
            QMessageBox.warning(self, self.tr("错误"), self.tr("当前连接不支持在线编辑文件"))
            return

        remote_path = self._build_selected_remote_path(item)
        try:
            content = self._connection.read_text(remote_path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("错误"), str(exc))
            return

        dialog = TextFileDialog(remote_path, content, self)
        if not dialog.exec():
            return

        try:
            self._connection.write_text(remote_path, dialog.text())
        except Exception as exc:
            QMessageBox.critical(self, self.tr("错误"), str(exc))

    def _run_upload_task(
        self, local_path: str, remote_path: str, progress: Callable[[int, int], bool]
    ) -> None:
        """执行单个上传任务（支持断点续传开关，兼容不同连接签名）。"""
        resume = bool(getattr(self, "resume_check", None) and self.resume_check.isChecked())
        self._ensure_remote_directory(posixpath.dirname(remote_path))
        try:
            self._connection.upload_from_path(local_path, remote_path, progress, resume=resume)
        except TypeError:
            self._connection.upload_from_path(local_path, remote_path, progress)

    def _run_create_directory_task(
        self, remote_path: str, progress: Callable[[int, int], bool]
    ) -> None:
        """执行创建远程目录任务。"""
        self._ensure_remote_directory(remote_path, strict=True)
        progress(1, 1)

    def _run_create_local_directory_task(
        self, local_path: str, progress: Callable[[int, int], bool]
    ) -> None:
        """执行本地目录创建任务。"""
        Path(local_path).mkdir(parents=True, exist_ok=True)
        progress(1, 1)

    def _run_download_task(
        self, remote_path: str, local_path: str, progress: Callable[[int, int], bool]
    ) -> None:
        """执行单个下载任务（支持断点续传开关，兼容不同连接签名）。"""
        resume = bool(getattr(self, "resume_check", None) and self.resume_check.isChecked())
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection.download_to_path(remote_path, local_path, progress, resume=resume)
        except TypeError:
            self._connection.download_to_path(remote_path, local_path, progress)

    def _current_conflict_strategy(self) -> str:
        """返回当前选择的冲突处理策略。"""
        return (
            str(
                getattr(self, "conflict_strategy_combo", None).currentData()
                if getattr(self, "conflict_strategy_combo", None) is not None
                else self.CONFLICT_ASK
            )
            or self.CONFLICT_ASK
        )

    def _prompt_conflict_strategy(self, operation: str, target_path: str) -> Optional[str]:
        """在“询问”模式下请求用户选择冲突处理策略。"""
        choices = [
            self.tr("覆盖"),
            self.tr("跳过"),
            self.tr("自动重命名"),
        ]
        choice, ok = QInputDialog.getItem(
            self,
            self.tr(f"{operation}冲突"),
            self.tr(f"目标已存在，请选择处理方式:\n{target_path}"),
            choices,
            0,
            False,
        )
        if not ok:
            raise ConflictResolutionCanceled(f"{operation}: {target_path}")
        mapping = {
            self.tr("覆盖"): self.CONFLICT_OVERWRITE,
            self.tr("跳过"): self.CONFLICT_SKIP,
            self.tr("自动重命名"): self.CONFLICT_RENAME,
        }
        return mapping.get(choice)

    def _remote_path_exists(self, remote_path: str) -> bool:
        """检查远程路径是否存在。"""
        if not self._connection:
            return False
        if hasattr(self._connection, "exists"):
            try:
                return bool(self._connection.exists(remote_path))
            except Exception:
                return False
        return False

    @staticmethod
    def _local_path_exists(local_path: str) -> bool:
        """检查本地路径是否存在。"""
        return Path(local_path).exists()

    @staticmethod
    def _next_available_path(
        path_value: str,
        exists_callback: Callable[[str], bool],
        *,
        remote: bool,
        reserved_paths: Optional[set[str]] = None,
    ) -> str:
        """生成下一个可用的重命名路径。"""
        if remote:
            parent = posixpath.dirname(path_value)
            filename = posixpath.basename(path_value)
        else:
            path = Path(path_value)
            parent = str(path.parent)
            filename = path.name

        base, suffix = os.path.splitext(filename)
        counter = 1
        while True:
            candidate_name = f"{base} ({counter}){suffix}"
            if remote:
                candidate_path = (
                    posixpath.join(parent, candidate_name)
                    if parent and parent != "/"
                    else f"/{candidate_name}"
                )
            else:
                candidate_path = str(Path(parent) / candidate_name)
            if not exists_callback(candidate_path) and (
                reserved_paths is None or candidate_path not in reserved_paths
            ):
                return candidate_path
            counter += 1

    def _resolve_remote_conflict_path(
        self,
        remote_path: str,
        operation: str,
        *,
        errors: Optional[List[str]] = None,
        reserved_paths: Optional[set[str]] = None,
    ) -> Optional[str]:
        """解析远程目标路径冲突。"""
        if not self._remote_path_exists(remote_path) and (
            reserved_paths is None or remote_path not in reserved_paths
        ):
            return remote_path

        strategy = self._current_conflict_strategy()
        if strategy == self.CONFLICT_ASK:
            strategy = self._prompt_conflict_strategy(operation, remote_path)
        if strategy == self.CONFLICT_OVERWRITE:
            return remote_path
        if strategy == self.CONFLICT_SKIP or strategy is None:
            if errors is not None:
                errors.append(self.tr(f"已跳过冲突项: {remote_path}"))
            return None
        if strategy == self.CONFLICT_RENAME:
            return self._next_available_path(
                remote_path,
                self._remote_path_exists,
                remote=True,
                reserved_paths=reserved_paths,
            )
        return remote_path

    def _resolve_local_conflict_path(
        self,
        local_path: str,
        operation: str,
        *,
        errors: Optional[List[str]] = None,
        reserved_paths: Optional[set[str]] = None,
    ) -> Optional[str]:
        """解析本地目标路径冲突。"""
        if not self._local_path_exists(local_path) and (
            reserved_paths is None or local_path not in reserved_paths
        ):
            return local_path

        strategy = self._current_conflict_strategy()
        if strategy == self.CONFLICT_ASK:
            strategy = self._prompt_conflict_strategy(operation, local_path)
        if strategy == self.CONFLICT_OVERWRITE:
            return local_path
        if strategy == self.CONFLICT_SKIP or strategy is None:
            if errors is not None:
                errors.append(self.tr(f"已跳过冲突项: {local_path}"))
            return None
        if strategy == self.CONFLICT_RENAME:
            return self._next_available_path(
                local_path,
                self._local_path_exists,
                remote=False,
                reserved_paths=reserved_paths,
            )
        return local_path

    def _ensure_remote_directory(self, remote_path: str, *, strict: bool = False) -> None:
        """确保远程目录存在，目录已存在时忽略异常。"""
        if not remote_path or remote_path in {".", "/"}:
            return
        if not self._connection or not hasattr(self._connection, "mkdir"):
            return

        normalized = posixpath.normpath(remote_path)
        current = ""
        for part in [segment for segment in normalized.split("/") if segment]:
            current = f"{current}/{part}" if current else f"/{part}"
            try:
                self._connection.mkdir(current)
            except Exception as exc:
                if self._remote_path_exists(current):
                    continue
                if strict:
                    raise exc

    def _build_directory_download_tasks(
        self,
        directory_items: List[QStandardItem],
        target_dir: str,
        *,
        errors: Optional[List[str]] = None,
        reserved_local_paths: Optional[set[str]] = None,
    ) -> List[TransferTask]:
        """根据远程目录递归构建下载任务。"""
        if not self._connection or not hasattr(self._connection, "list_dir"):
            raise RuntimeError(self.tr("当前连接不支持目录下载"))

        tasks: List[TransferTask] = []
        reserved_paths = reserved_local_paths if reserved_local_paths is not None else set()
        directory_entries: List[tuple[str, str, str]] = []
        file_entries: List[tuple[str, str, str]] = []

        for item in directory_items:
            remote_root = self._build_selected_remote_path(item)
            local_root = str(Path(target_dir) / item.text())
            resolved_local_root = self._resolve_local_conflict_path(
                local_root,
                self.tr("下载目录"),
                errors=errors,
                reserved_paths=reserved_paths,
            )
            if not resolved_local_root:
                continue
            reserved_paths.add(resolved_local_root)
            root_name = Path(resolved_local_root).name
            stack = [(remote_root, Path(resolved_local_root), root_name)]

            while stack:
                current_remote, current_local, display_name = stack.pop()
                entries = self._connection.list_dir(current_remote)
                child_dirs = [entry for entry in entries if entry.is_dir]
                child_files = [entry for entry in entries if not entry.is_dir]
                if not child_dirs and not child_files:
                    directory_entries.append((current_remote, str(current_local), display_name))
                    continue

                directory_entries.append((current_remote, str(current_local), display_name))
                for child_dir in sorted(
                    child_dirs, key=lambda entry: entry.name.lower(), reverse=True
                ):
                    remote_child = self._join_remote_path(current_remote, child_dir.name)
                    local_child = current_local / child_dir.name
                    stack.append(
                        (
                            remote_child,
                            local_child,
                            f"{display_name}/{child_dir.name}",
                        )
                    )
                for child_file in sorted(child_files, key=lambda entry: entry.name.lower()):
                    remote_file = self._join_remote_path(current_remote, child_file.name)
                    local_file = str(current_local / child_file.name)
                    resolved_local_file = self._resolve_local_conflict_path(
                        local_file,
                        self.tr("下载"),
                        errors=errors,
                        reserved_paths=reserved_paths,
                    )
                    if not resolved_local_file:
                        continue
                    reserved_paths.add(resolved_local_file)
                    display_file = f"{display_name}/{child_file.name}"
                    if resolved_local_file != local_file:
                        display_file = f"{display_file} -> {Path(resolved_local_file).name}"
                    file_entries.append((remote_file, resolved_local_file, display_file))

        total = len(directory_entries) + len(file_entries)
        index = 0
        for _remote_dir, local_dir, display_name in directory_entries:
            index += 1
            tasks.append(
                TransferTask(
                    task_id=str(uuid4()),
                    operation=self.tr("下载目录"),
                    display_name=display_name,
                    title=self.tr("下载目录"),
                    label=self.tr(f"正在创建本地目录 ({index}/{total}): {display_name}"),
                    runner=lambda progress, target_path=local_dir: (
                        self._run_create_local_directory_task(target_path, progress)
                    ),
                    success_payload=local_dir,
                )
            )
        for remote_file, local_file, display_name in file_entries:
            index += 1
            tasks.append(
                TransferTask(
                    task_id=str(uuid4()),
                    operation=self.tr("下载"),
                    display_name=display_name,
                    title=self.tr("下载目录"),
                    label=self.tr(f"正在下载 ({index}/{total}): {display_name}"),
                    runner=lambda progress, source_path=remote_file, target_path=local_file: (
                        self._run_download_task(source_path, target_path, progress)
                    ),
                    success_payload=local_file,
                )
            )
        return tasks

    @staticmethod
    def _join_remote_path(base_path: str, name: str) -> str:
        """拼接远程 POSIX 路径。"""
        if not base_path or base_path == "/":
            return f"/{name}".replace("//", "/")
        return posixpath.join(base_path, name)
