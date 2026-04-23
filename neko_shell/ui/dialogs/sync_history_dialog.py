#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步输入结果历史对话框。

用于查看最近的批量发送记录与失败信息。
"""

from __future__ import annotations

from collections import Counter
import json
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class SyncHistoryDialog(QDialog):
    """同步输入结果历史对话框。"""

    replay_requested = Signal(object)
    retry_failed_requested = Signal(object)
    retry_nonzero_requested = Signal(object)
    retry_pending_requested = Signal(object)
    recommended_retry_requested = Signal(object, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.history_list: QListWidget
        self.detail_browser: QTextBrowser
        self.empty_label: QLabel
        self.summary_label: QLabel
        self.insight_label: QLabel
        self.batch_metric_label: QLabel
        self.failed_metric_label: QLabel
        self.command_metric_label: QLabel
        self.target_metric_label: QLabel
        self.delivery_metric_label: QLabel
        self.task_metric_label: QLabel
        self.echoed_metric_label: QLabel
        self.reported_metric_label: QLabel
        self.nonzero_metric_label: QLabel
        self.retry_batch_metric_label: QLabel
        self.improved_metric_label: QLabel
        self.pending_batch_metric_label: QLabel
        self.scope_filter_combo: QComboBox
        self.task_filter_combo: QComboBox
        self.result_filter_combo: QComboBox
        self.status_filter_combo: QComboBox
        self.search_edit: QLineEdit
        self.copy_overview_button: QPushButton
        self.copy_summary_button: QPushButton
        self.copy_recommendation_button: QPushButton
        self.apply_recommendation_button: QPushButton
        self.copy_commands_button: QPushButton
        self.copy_target_results_button: QPushButton
        self.copy_failed_targets_button: QPushButton
        self.reuse_record_button: QPushButton
        self.retry_failed_button: QPushButton
        self.retry_nonzero_button: QPushButton
        self.retry_pending_button: QPushButton
        self.export_report_button: QPushButton
        self.export_json_button: QPushButton
        self._records: list[object] = []
        self._filtered_records: list[object] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.tr("发送结果"))
        self.resize(860, 560)
        self.setMinimumSize(760, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(self.tr("同步输入与编排发送记录"), self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        summary = QLabel(
            self.tr(
                "查看批量发送的投递范围、命令摘要、目标终端与失败信息。该面板展示的是发送结果，不代表远端命令执行输出。"
            ),
            self,
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("color: palette(mid);")
        layout.addWidget(summary)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel(self.tr("范围"), self))
        self.scope_filter_combo = QComboBox(self)
        self.scope_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.scope_filter_combo)

        filter_row.addWidget(QLabel(self.tr("任务"), self))
        self.task_filter_combo = QComboBox(self)
        self.task_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.task_filter_combo)

        filter_row.addWidget(QLabel(self.tr("结果"), self))
        self.result_filter_combo = QComboBox(self)
        self.result_filter_combo.addItem(self.tr("全部"), "all")
        self.result_filter_combo.addItem(self.tr("仅失败"), "failed")
        self.result_filter_combo.addItem(self.tr("仅成功"), "success")
        self.result_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.result_filter_combo)

        filter_row.addWidget(QLabel(self.tr("状态"), self))
        self.status_filter_combo = QComboBox(self)
        self.status_filter_combo.addItem(self.tr("全部状态"), "all")
        self.status_filter_combo.addItem(self.tr("等待回显"), "waiting")
        self.status_filter_combo.addItem(self.tr("采集中"), "capturing")
        self.status_filter_combo.addItem(self.tr("已回显"), "echoed")
        self.status_filter_combo.addItem(self.tr("部分失败"), "partial_failed")
        self.status_filter_combo.addItem(self.tr("失败"), "failed")
        self.status_filter_combo.addItem(self.tr("未投递"), "undelivered")
        self.status_filter_combo.addItem(self.tr("成功"), "success")
        self.status_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.status_filter_combo)

        filter_row.addWidget(QLabel(self.tr("搜索"), self))
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText(self.tr("命令 / 终端 / 批次 / 状态"))
        self.search_edit.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_edit, 1)

        layout.addLayout(filter_row)

        self.summary_label = QLabel(self.tr("当前没有发送记录"), self)
        self.summary_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.summary_label)

        self.insight_label = QLabel(self.tr("当前筛选条件下没有复盘洞察"), self)
        self.insight_label.setWordWrap(True)
        self.insight_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.insight_label)

        metric_row = QGridLayout()
        metric_row.setHorizontalSpacing(8)
        metric_row.setVerticalSpacing(8)
        self.batch_metric_label = self._build_metric_label(self.tr("批次"), "0")
        self.failed_metric_label = self._build_metric_label(self.tr("失败批次"), "0")
        self.command_metric_label = self._build_metric_label(self.tr("命令总量"), "0")
        self.target_metric_label = self._build_metric_label(self.tr("目标终端"), "0")
        self.delivery_metric_label = self._build_metric_label(self.tr("实际投递"), "0")
        self.task_metric_label = self._build_metric_label(self.tr("任务批次"), "0")
        self.echoed_metric_label = self._build_metric_label(self.tr("已回显终端"), "0")
        self.reported_metric_label = self._build_metric_label(self.tr("已回执终端"), "0")
        self.nonzero_metric_label = self._build_metric_label(self.tr("非零退出"), "0")
        self.retry_batch_metric_label = self._build_metric_label(self.tr("重试批次"), "0")
        self.improved_metric_label = self._build_metric_label(self.tr("改善重试"), "0")
        self.pending_batch_metric_label = self._build_metric_label(self.tr("待回执批次"), "0")
        metric_row.addWidget(self.batch_metric_label, 0, 0)
        metric_row.addWidget(self.failed_metric_label, 0, 1)
        metric_row.addWidget(self.command_metric_label, 0, 2)
        metric_row.addWidget(self.target_metric_label, 0, 3)
        metric_row.addWidget(self.delivery_metric_label, 1, 0)
        metric_row.addWidget(self.task_metric_label, 1, 1)
        metric_row.addWidget(self.echoed_metric_label, 1, 2)
        metric_row.addWidget(self.reported_metric_label, 1, 3)
        metric_row.addWidget(self.nonzero_metric_label, 2, 0)
        metric_row.addWidget(self.retry_batch_metric_label, 2, 1)
        metric_row.addWidget(self.improved_metric_label, 2, 2)
        metric_row.addWidget(self.pending_batch_metric_label, 2, 3)
        metric_row.setColumnStretch(3, 1)
        layout.addLayout(metric_row)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        self.history_list = QListWidget(splitter)
        self.history_list.currentRowChanged.connect(self._render_selected_record)
        self.history_list.setMinimumWidth(280)
        splitter.addWidget(self.history_list)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.empty_label = QLabel(self.tr("当前还没有发送记录"), right_panel)
        self.empty_label.setStyleSheet("color: palette(mid);")
        right_layout.addWidget(self.empty_label)

        detail_actions = QHBoxLayout()
        detail_actions.setSpacing(8)
        self.copy_overview_button = QPushButton(self.tr("复制筛选洞察"), right_panel)
        self.copy_overview_button.clicked.connect(self._copy_filtered_overview)
        detail_actions.addWidget(self.copy_overview_button)
        self.copy_summary_button = QPushButton(self.tr("复制批次摘要"), right_panel)
        self.copy_summary_button.clicked.connect(self._copy_selected_summary)
        detail_actions.addWidget(self.copy_summary_button)
        self.copy_recommendation_button = QPushButton(self.tr("复制处置计划"), right_panel)
        self.copy_recommendation_button.clicked.connect(self._copy_selected_recommendation)
        detail_actions.addWidget(self.copy_recommendation_button)
        self.apply_recommendation_button = QPushButton(self.tr("按建议执行"), right_panel)
        self.apply_recommendation_button.clicked.connect(
            self._request_apply_selected_recommendation
        )
        detail_actions.addWidget(self.apply_recommendation_button)
        self.copy_commands_button = QPushButton(self.tr("复制命令"), right_panel)
        self.copy_commands_button.clicked.connect(self._copy_selected_commands)
        detail_actions.addWidget(self.copy_commands_button)
        self.copy_target_results_button = QPushButton(
            self.tr("复制终端结果"),
            right_panel,
        )
        self.copy_target_results_button.clicked.connect(self._copy_target_results)
        detail_actions.addWidget(self.copy_target_results_button)
        self.copy_failed_targets_button = QPushButton(
            self.tr("复制失败终端"),
            right_panel,
        )
        self.copy_failed_targets_button.clicked.connect(self._copy_failed_targets)
        detail_actions.addWidget(self.copy_failed_targets_button)
        self.reuse_record_button = QPushButton(self.tr("复用为新任务"), right_panel)
        self.reuse_record_button.clicked.connect(self._request_replay_selected_record)
        detail_actions.addWidget(self.reuse_record_button)
        self.retry_failed_button = QPushButton(self.tr("重试失败终端"), right_panel)
        self.retry_failed_button.clicked.connect(self._request_retry_failed_selected_record)
        detail_actions.addWidget(self.retry_failed_button)
        self.retry_nonzero_button = QPushButton(self.tr("重试非零退出"), right_panel)
        self.retry_nonzero_button.clicked.connect(self._request_retry_nonzero_selected_record)
        detail_actions.addWidget(self.retry_nonzero_button)
        self.retry_pending_button = QPushButton(self.tr("重试待回执终端"), right_panel)
        self.retry_pending_button.clicked.connect(self._request_retry_pending_selected_record)
        detail_actions.addWidget(self.retry_pending_button)
        self.export_report_button = QPushButton(self.tr("导出报告"), right_panel)
        self.export_report_button.clicked.connect(self._export_selected_report)
        detail_actions.addWidget(self.export_report_button)
        self.export_json_button = QPushButton(self.tr("导出 JSON"), right_panel)
        self.export_json_button.clicked.connect(self._export_selected_json)
        detail_actions.addWidget(self.export_json_button)
        detail_actions.addStretch(1)
        right_layout.addLayout(detail_actions)

        self.detail_browser = QTextBrowser(right_panel)
        self.detail_browser.setReadOnly(True)
        self.detail_browser.setOpenExternalLinks(True)
        right_layout.addWidget(self.detail_browser, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([320, 520])

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)

        close_button = QPushButton(self.tr("关闭"), self)
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)

        button_box = QDialogButtonBox(parent=self)
        button_box.setVisible(False)
        layout.addWidget(button_box)
        layout.addLayout(footer)
        self._update_detail_action_state(None)

    def _build_metric_label(self, title: str, value: str) -> QLabel:
        """构建统计指标标签。"""
        label = QLabel(f"{title}: {value}", self)
        label.setObjectName("syncHistoryMetric")
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumWidth(120)
        label.setStyleSheet("""
            QLabel#syncHistoryMetric {
                border: 1px solid palette(mid);
                border-radius: 10px;
                padding: 8px 12px;
                background: palette(base);
                font-weight: 600;
            }
            """)
        return label

    @staticmethod
    def _string_list(value: object) -> list[str]:
        """把对象规整为字符串列表。"""
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item]

    def _successful_targets(self, record: object) -> list[str]:
        """返回本批次成功投递的目标终端。"""
        target_names = self._string_list(getattr(record, "target_names", []))
        failed_targets = set(self._string_list(getattr(record, "failed_targets", [])))
        return [name for name in target_names if name not in failed_targets]

    def _target_result_entries(self, record: object) -> list[dict[str, object]]:
        """返回规整后的终端结果摘要列表。"""
        raw_entries = getattr(record, "target_result_entries", [])
        if not isinstance(raw_entries, list):
            return []
        normalized: list[dict[str, object]] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            target_name = str(entry.get("target_name", "") or "").strip()
            if not target_name:
                continue
            normalized.append(
                {
                    "target_name": target_name,
                    "target_connection_id": str(
                        entry.get("target_connection_id", "") or ""
                    ).strip(),
                    "target_type_key": str(entry.get("target_type_key", "") or "").strip(),
                    "result_excerpt": str(entry.get("result_excerpt", "") or "").strip(),
                    "result_excerpt_updated_at": entry.get("result_excerpt_updated_at", None),
                    "result_sample_count": int(entry.get("result_sample_count", 0) or 0),
                    "delivery_state": str(entry.get("delivery_state", "sent") or "sent"),
                    "stdout_excerpt": str(entry.get("stdout_excerpt", "") or "").strip(),
                    "stdout_sample_count": int(entry.get("stdout_sample_count", 0) or 0),
                    "stderr_excerpt": str(entry.get("stderr_excerpt", "") or "").strip(),
                    "stderr_sample_count": int(entry.get("stderr_sample_count", 0) or 0),
                    "last_output_kind": str(entry.get("last_output_kind", "") or "").strip(),
                    "exit_code": self._normalize_exit_code(entry.get("exit_code", None)),
                    "exit_code_updated_at": entry.get("exit_code_updated_at", None),
                }
            )
        return normalized

    @staticmethod
    def _normalize_exit_code(value: object) -> Optional[int]:
        """把退出码规整为整数。"""
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _expected_delivery_count(self, record: object) -> int:
        """返回理论投递次数。"""
        command_count = int(getattr(record, "command_count", 0) or 0)
        target_count = int(getattr(record, "target_count", 0) or 0)
        return command_count * target_count

    def _delivery_count(self, record: object) -> int:
        """返回实际投递次数。"""
        return int(getattr(record, "delivery_count", 0) or 0)

    def _delivery_ratio_text(self, record: object) -> str:
        """返回投递完成率文案。"""
        expected = self._expected_delivery_count(record)
        delivered = self._delivery_count(record)
        if expected <= 0:
            return self.tr("0%")
        return self.tr(f"{(delivered / expected) * 100:.0f}%")

    @staticmethod
    def _format_top_items(items: list[tuple[str, int]]) -> str:
        """格式化热点条目。"""
        if not items:
            return "无"
        return "，".join(f"{name}({count})" for name, count in items)

    def _captured_target_count(self, record: object) -> int:
        """返回已有结果摘要的终端数量。"""
        count = 0
        for entry in self._target_result_entries(record):
            if (
                str(entry.get("delivery_state", "") or "") == "captured"
                or str(entry.get("result_excerpt", "") or "").strip()
            ):
                count += 1
        return count

    def _reported_target_count(self, record: object) -> int:
        """返回已记录退出码的终端数量。"""
        count = 0
        for entry in self._target_result_entries(record):
            if self._normalize_exit_code(entry.get("exit_code", None)) is not None:
                count += 1
        return count

    def _nonzero_exit_target_count(self, record: object) -> int:
        """返回退出码非零的终端数量。"""
        count = 0
        failed_targets = set(self._string_list(getattr(record, "failed_targets", [])))
        for entry in self._target_result_entries(record):
            if entry.get("target_name") in failed_targets:
                continue
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            if isinstance(exit_code, int) and exit_code != 0:
                count += 1
        return count

    def _retryable_failed_target_count(self, record: object) -> int:
        """返回可重试失败终端数量。"""
        failed_targets = set(self._string_list(getattr(record, "failed_targets", [])))
        count = 0
        for entry in self._target_result_entries(record):
            target_name = str(entry.get("target_name", "") or "").strip()
            state = str(entry.get("delivery_state", "") or "").strip()
            if target_name in failed_targets or state == "failed":
                count += 1
        return count

    def _zero_exit_target_count(self, record: object) -> int:
        """返回退出码为零的终端数量。"""
        count = 0
        failed_targets = set(self._string_list(getattr(record, "failed_targets", [])))
        for entry in self._target_result_entries(record):
            if entry.get("target_name") in failed_targets:
                continue
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            if exit_code == 0:
                count += 1
        return count

    def _stderr_target_count(self, record: object) -> int:
        """返回有错误输出摘要的终端数量。"""
        count = 0
        for entry in self._target_result_entries(record):
            if str(entry.get("stderr_excerpt", "") or "").strip():
                count += 1
        return count

    def _pending_receipt_target_count(self, record: object) -> int:
        """返回仍未记录退出码的终端数量。"""
        target_count = int(getattr(record, "target_count", 0) or 0)
        return max(target_count - self._reported_target_count(record), 0)

    def _retryable_pending_target_count(self, record: object) -> int:
        """返回可重试待回执终端数量。"""
        failed_targets = set(self._string_list(getattr(record, "failed_targets", [])))
        count = 0
        for entry in self._target_result_entries(record):
            target_name = str(entry.get("target_name", "") or "").strip()
            state = str(entry.get("delivery_state", "") or "").strip()
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            connection_id = str(entry.get("target_connection_id", "") or "").strip()
            if (
                connection_id
                and target_name not in failed_targets
                and state != "failed"
                and exit_code is None
            ):
                count += 1
        return count

    @staticmethod
    def _normalize_batch_id(value: object) -> Optional[int]:
        """把批次号规整为整数。"""
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _target_entry_identity(entry: dict[str, object]) -> str:
        """返回终端条目的稳定标识。"""
        connection_id = str(entry.get("target_connection_id", "") or "").strip()
        if connection_id:
            return f"id:{connection_id}"
        target_name = str(entry.get("target_name", "") or "").strip()
        if target_name:
            return f"name:{target_name}"
        return ""

    def _find_record_by_batch_id(self, batch_id: object) -> Optional[object]:
        """按批次号查找历史记录。"""
        normalized_batch_id = self._normalize_batch_id(batch_id)
        if normalized_batch_id is None:
            return None
        for candidate in self._records:
            if (
                self._normalize_batch_id(getattr(candidate, "batch_id", None))
                == normalized_batch_id
            ):
                return candidate
        return None

    def _comparison_entry_metrics(
        self,
        entries: list[dict[str, object]],
        failed_targets: set[str],
    ) -> dict[str, int]:
        """统计可比终端条目的关键执行指标。"""
        metrics = {
            "target_count": len(entries),
            "failed_targets": 0,
            "captured_targets": 0,
            "reported_targets": 0,
            "zero_exit_targets": 0,
            "nonzero_exit_targets": 0,
            "pending_receipts": 0,
        }
        for entry in entries:
            target_name = str(entry.get("target_name", "") or "").strip()
            delivery_state = str(entry.get("delivery_state", "") or "").strip()
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            is_failed = target_name in failed_targets or delivery_state == "failed"
            if is_failed:
                metrics["failed_targets"] += 1
            if delivery_state == "captured" or str(entry.get("result_excerpt", "") or "").strip():
                metrics["captured_targets"] += 1
            if exit_code is not None:
                metrics["reported_targets"] += 1
                if not is_failed:
                    if exit_code == 0:
                        metrics["zero_exit_targets"] += 1
                    else:
                        metrics["nonzero_exit_targets"] += 1
            elif not is_failed:
                metrics["pending_receipts"] += 1
        return metrics

    @staticmethod
    def _comparison_status(
        origin_metrics: dict[str, int],
        current_metrics: dict[str, int],
    ) -> tuple[str, str]:
        """根据对比指标返回状态键与文案。"""
        problem_keys = ("failed_targets", "nonzero_exit_targets", "pending_receipts")
        visibility_keys = ("reported_targets", "captured_targets")
        problem_improved = any(current_metrics[key] < origin_metrics[key] for key in problem_keys)
        problem_regressed = any(current_metrics[key] > origin_metrics[key] for key in problem_keys)
        visibility_improved = any(
            current_metrics[key] > origin_metrics[key] for key in visibility_keys
        )
        visibility_regressed = any(
            current_metrics[key] < origin_metrics[key] for key in visibility_keys
        )
        if not any(
            (
                problem_improved,
                problem_regressed,
                visibility_improved,
                visibility_regressed,
            )
        ):
            return "stable", "持平"
        if problem_regressed or visibility_regressed:
            if problem_improved or visibility_improved:
                return "mixed", "混合"
            return "regressed", "回退"
        return "improved", "已改善"

    @staticmethod
    def _signed_delta_text(value: int) -> str:
        """返回带符号的差值文本。"""
        return "0" if value == 0 else f"{value:+d}"

    def _comparison_summary_text(self, comparison: dict[str, object]) -> str:
        """返回对比摘要文案。"""
        if not bool(comparison.get("available")):
            reason = str(comparison.get("reason", "") or "")
            if reason == "missing_origin":
                return self.tr("未找到源批次记录")
            if reason == "no_comparable_targets":
                return self.tr("已找到源批次，但当前记录缺少可比目标")
            return self.tr("当前批次没有源批次对比信息")

        improved_parts: list[str] = []
        regressed_parts: list[str] = []
        delta = comparison.get("delta", {})
        if not isinstance(delta, dict):
            delta = {}

        reduction_labels = (
            ("failed_targets", "失败减少"),
            ("nonzero_exit_targets", "非零退出减少"),
            ("pending_receipts", "待回执减少"),
        )
        gain_labels = (
            ("reported_targets", "新增回执"),
            ("captured_targets", "新增回显"),
        )
        increase_labels = (
            ("failed_targets", "失败增加"),
            ("nonzero_exit_targets", "非零退出增加"),
            ("pending_receipts", "待回执增加"),
        )
        loss_labels = (
            ("reported_targets", "回执减少"),
            ("captured_targets", "回显减少"),
        )

        for key, label in reduction_labels:
            value = int(delta.get(key, 0) or 0)
            if value < 0:
                improved_parts.append(f"{self.tr(label)} {abs(value)}")
        for key, label in gain_labels:
            value = int(delta.get(key, 0) or 0)
            if value > 0:
                improved_parts.append(f"{self.tr(label)} {value}")
        for key, label in increase_labels:
            value = int(delta.get(key, 0) or 0)
            if value > 0:
                regressed_parts.append(f"{self.tr(label)} {value}")
        for key, label in loss_labels:
            value = int(delta.get(key, 0) or 0)
            if value < 0:
                regressed_parts.append(f"{self.tr(label)} {abs(value)}")

        if not improved_parts and not regressed_parts:
            return self.tr("与源批次持平")
        summary_parts: list[str] = []
        if improved_parts:
            summary_parts.append(self.tr(f"改善: {'，'.join(improved_parts)}"))
        if regressed_parts:
            summary_parts.append(self.tr(f"回退: {'，'.join(regressed_parts)}"))
        return "；".join(summary_parts)

    def _origin_comparison_payload(self, record: object) -> Optional[dict[str, object]]:
        """构建当前记录与源批次的对比载荷。"""
        origin_batch_id = self._normalize_batch_id(getattr(record, "origin_batch_id", None))
        if origin_batch_id is None:
            return None

        payload: dict[str, object] = {
            "origin_batch_id": origin_batch_id,
            "origin_batch_label": self._origin_batch_label(origin_batch_id),
            "available": False,
            "reason": "missing_origin",
        }
        origin_record = self._find_record_by_batch_id(origin_batch_id)
        if origin_record is None:
            payload["summary"] = self._comparison_summary_text(payload)
            return payload

        origin_entries = self._target_result_entries(origin_record)
        origin_entry_map: dict[str, dict[str, object]] = {}
        for entry in origin_entries:
            identity = self._target_entry_identity(entry)
            if identity and identity not in origin_entry_map:
                origin_entry_map[identity] = entry

        current_entries = self._target_result_entries(record)
        matched_pairs: list[tuple[dict[str, object], dict[str, object]]] = []
        for entry in current_entries:
            identity = self._target_entry_identity(entry)
            if identity and identity in origin_entry_map:
                matched_pairs.append((entry, origin_entry_map[identity]))

        payload["origin_status"] = self._record_status_text(origin_record)
        payload["current_status"] = self._record_status_text(record)
        if not matched_pairs:
            payload["reason"] = "no_comparable_targets"
            payload["summary"] = self._comparison_summary_text(payload)
            return payload

        current_failed_targets = set(self._string_list(getattr(record, "failed_targets", [])))
        origin_failed_targets = set(self._string_list(getattr(origin_record, "failed_targets", [])))
        current_pair_entries = [entry for entry, _origin in matched_pairs]
        origin_pair_entries = [origin for _entry, origin in matched_pairs]
        current_metrics = self._comparison_entry_metrics(
            current_pair_entries,
            current_failed_targets,
        )
        origin_metrics = self._comparison_entry_metrics(
            origin_pair_entries,
            origin_failed_targets,
        )
        delta = {key: current_metrics[key] - origin_metrics.get(key, 0) for key in current_metrics}
        status_key, status_label = self._comparison_status(origin_metrics, current_metrics)
        payload.update(
            {
                "available": True,
                "reason": "",
                "status_key": status_key,
                "status_label": status_label,
                "comparable_target_count": len(matched_pairs),
                "matched_target_names": [
                    str(entry.get("target_name", "") or "").strip()
                    for entry in current_pair_entries
                    if str(entry.get("target_name", "") or "").strip()
                ],
                "origin_metrics": origin_metrics,
                "current_metrics": current_metrics,
                "delta": delta,
            }
        )
        payload["summary"] = self._comparison_summary_text(payload)
        return payload

    def _record_problem_target_names(self, record: object) -> list[str]:
        """返回当前批次的问题终端列表。"""
        problem_names: list[str] = []
        seen: set[str] = set()
        for name in self._string_list(getattr(record, "failed_targets", [])):
            if name not in seen:
                seen.add(name)
                problem_names.append(name)
        failed_target_set = set(seen)
        for entry in self._target_result_entries(record):
            target_name = str(entry.get("target_name", "") or "").strip()
            if not target_name or target_name in seen:
                continue
            delivery_state = str(entry.get("delivery_state", "") or "").strip()
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            is_problem = (
                target_name in failed_target_set
                or delivery_state == "failed"
                or (isinstance(exit_code, int) and exit_code != 0)
                or exit_code is None
            )
            if is_problem:
                seen.add(target_name)
                problem_names.append(target_name)
        return problem_names

    def _task_health_entry(self, task_title: str, records: list[object]) -> dict[str, object]:
        """返回任务级成功率统计。"""
        total_batches = len(records)
        healthy_batches = 0
        problem_batches = 0
        pending_batches = 0
        for record in records:
            status_key = self._record_status_key(record)
            if status_key in {"success", "echoed"}:
                healthy_batches += 1
            elif status_key in {"failed", "partial_failed"}:
                problem_batches += 1
            else:
                pending_batches += 1
        success_rate = (healthy_batches / total_batches) if total_batches > 0 else 0.0
        return {
            "task_title": task_title,
            "total_batches": total_batches,
            "healthy_batches": healthy_batches,
            "problem_batches": problem_batches,
            "pending_batches": pending_batches,
            "success_rate": success_rate,
        }

    def _format_task_health_items(self, items: list[dict[str, object]]) -> str:
        """格式化任务成功率条目。"""
        if not items:
            return "无"
        parts: list[str] = []
        for item in items:
            parts.append(
                self.tr(
                    f"{str(item.get('task_title', '') or '')} "
                    f"{float(item.get('success_rate', 0.0) or 0.0) * 100:.0f}%"
                    f"({int(item.get('healthy_batches', 0) or 0)}/{int(item.get('total_batches', 0) or 0)})"
                )
            )
        return "，".join(parts)

    def _classify_failure_reason(self, record: object, entry: dict[str, object]) -> str:
        """按终端结果归类失败原因。"""
        target_name = str(entry.get("target_name", "") or "").strip()
        delivery_state = str(entry.get("delivery_state", "") or "").strip().lower()
        exit_code = self._normalize_exit_code(entry.get("exit_code", None))
        failed_targets = set(self._string_list(getattr(record, "failed_targets", [])))
        text = " ".join(
            [
                str(entry.get("stderr_excerpt", "") or ""),
                str(entry.get("stdout_excerpt", "") or ""),
                str(entry.get("result_excerpt", "") or ""),
            ]
        ).lower()

        if target_name in failed_targets or delivery_state == "failed":
            if "permission denied" in text or "denied" in text or "auth" in text:
                return "认证或权限失败"
            if "timeout" in text or "timed out" in text or "超时" in text:
                return "投递超时"
            if (
                "refused" in text
                or "unreachable" in text
                or "connection" in text
                or "network" in text
                or "reset by peer" in text
            ):
                return "网络连接失败"
            return "投递失败"
        if exit_code is None:
            return "待回执"
        if exit_code == 0:
            return ""
        if "permission denied" in text or "operation not permitted" in text or "sudo" in text:
            return "权限不足"
        if "timeout" in text or "timed out" in text or "超时" in text:
            return "执行超时"
        if (
            "command not found" in text
            or "not found" in text
            or "no such file" in text
            or "no such directory" in text
        ):
            return "命令或路径错误"
        if (
            "refused" in text
            or "unreachable" in text
            or "connection" in text
            or "network" in text
            or "temporary failure in name resolution" in text
        ):
            return "网络连接异常"
        if "no space left" in text or "disk full" in text or "quota exceeded" in text:
            return "磁盘空间不足"
        if "yaml" in text or "json" in text or "parse" in text or "syntax" in text:
            return "配置或语法错误"
        if "service" in text or "systemctl" in text or "failed" in text or "error" in text:
            return "服务或脚本异常"
        return "非零退出"

    def _record_problem_groups(self, record: object) -> dict[str, object]:
        """返回批次内的问题终端分组。"""
        explicit_failed_targets = self._string_list(getattr(record, "failed_targets", []))
        failed_target_set = set(explicit_failed_targets)
        failed_targets: list[str] = []
        pending_targets: list[str] = []
        nonzero_targets: list[str] = []
        reason_targets: dict[str, list[str]] = {}
        seen_by_group: dict[str, set[str]] = {
            "failed": set(),
            "pending": set(),
            "nonzero": set(),
        }

        for entry in self._target_result_entries(record):
            target_name = str(entry.get("target_name", "") or "").strip()
            if not target_name:
                continue
            delivery_state = str(entry.get("delivery_state", "") or "").strip().lower()
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            reason = self._classify_failure_reason(record, entry)
            if reason:
                reason_targets.setdefault(reason, [])
                if target_name not in reason_targets[reason]:
                    reason_targets[reason].append(target_name)
            if target_name in failed_target_set or delivery_state == "failed":
                if target_name not in seen_by_group["failed"]:
                    seen_by_group["failed"].add(target_name)
                    failed_targets.append(target_name)
                continue
            if exit_code is None:
                if target_name not in seen_by_group["pending"]:
                    seen_by_group["pending"].add(target_name)
                    pending_targets.append(target_name)
                continue
            if exit_code != 0 and target_name not in seen_by_group["nonzero"]:
                seen_by_group["nonzero"].add(target_name)
                nonzero_targets.append(target_name)

        for target_name in explicit_failed_targets:
            if target_name not in seen_by_group["failed"]:
                seen_by_group["failed"].add(target_name)
                failed_targets.append(target_name)
            reason_targets.setdefault("投递失败", [])
            if target_name not in reason_targets["投递失败"]:
                reason_targets["投递失败"].append(target_name)

        reason_items = [
            {
                "reason": reason,
                "count": len(targets),
                "targets": list(targets),
            }
            for reason, targets in sorted(
                reason_targets.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )
        ]
        return {
            "failed_targets": failed_targets,
            "pending_targets": pending_targets,
            "nonzero_targets": nonzero_targets,
            "reason_items": reason_items,
        }

    def _joined_target_names(self, names: list[str], limit: int = 6) -> str:
        """把终端名称列表格式化为紧凑文本。"""
        if not names:
            return self.tr("无")
        visible = names[:limit]
        suffix = ""
        if len(names) > limit:
            suffix = self.tr(f" 等 {len(names)} 个")
        return ", ".join(visible) + suffix

    def _available_retry_labels(self, record: object) -> list[str]:
        """返回当前批次可执行的重试动作。"""
        labels: list[str] = []
        if self._retryable_pending_target_count(record) > 0:
            labels.append(self.tr("待回执重试"))
        if self._retryable_failed_target_count(record) > 0:
            labels.append(self.tr("失败终端重试"))
        if self._nonzero_exit_target_count(record) > 0:
            labels.append(self.tr("非零退出重试"))
        return labels

    def _preferred_retry_mode(self, record: object) -> str:
        """返回当前批次最推荐执行的重试模式。"""
        if self._retryable_pending_target_count(record) > 0:
            return "pending"
        if self._retryable_failed_target_count(record) > 0:
            return "failed"
        if self._nonzero_exit_target_count(record) > 0:
            return "nonzero"
        return ""

    def _preferred_retry_label(self, record: object) -> str:
        """返回当前批次最推荐执行的重试文案。"""
        return self._retry_mode_label(self._preferred_retry_mode(record))

    def _record_recommendation_payload(self, record: object) -> dict[str, object]:
        """返回批次级建议处置计划。"""
        problem_groups = self._record_problem_groups(record)
        failed_targets = list(problem_groups.get("failed_targets", []))
        pending_targets = list(problem_groups.get("pending_targets", []))
        nonzero_targets = list(problem_groups.get("nonzero_targets", []))
        reason_items = list(problem_groups.get("reason_items", []))
        comparison = self._origin_comparison_payload(record)
        comparison_status = ""
        if isinstance(comparison, dict) and bool(comparison.get("available")):
            comparison_status = str(comparison.get("status_key", "") or "").strip()
        available_retries = self._available_retry_labels(record)

        priority = self.tr("低")
        focus = self.tr("建议归档为稳定样本")
        actions: list[str] = []
        if pending_targets:
            priority = self.tr("高")
            focus = self.tr("优先处理待回执终端，避免批次长期悬空")
            actions.append(
                self.tr(
                    f"先对待回执终端 {self._joined_target_names(pending_targets)} 执行待回执重试，并核对网络、超时与采集链路。"
                )
            )
        if failed_targets:
            if priority != self.tr("高"):
                priority = self.tr("高")
                focus = self.tr("优先处理投递失败终端，恢复可达性")
            actions.append(
                self.tr(
                    f"对失败终端 {self._joined_target_names(failed_targets)} 先检查认证、权限和连接状态，再执行失败终端重试。"
                )
            )
        if nonzero_targets:
            if priority == self.tr("低"):
                priority = self.tr("中")
                focus = self.tr("聚焦非零退出终端，排查命令与环境差异")
            actions.append(
                self.tr(
                    f"针对非零退出终端 {self._joined_target_names(nonzero_targets)} 复核 stderr / 退出码，再执行非零退出重试。"
                )
            )

        if reason_items:
            top_reason = reason_items[0]
            if isinstance(top_reason, dict):
                actions.append(
                    self.tr(
                        f"围绕高频原因“{str(top_reason.get('reason', '') or '')}”优先编写专项排查步骤，覆盖 {int(top_reason.get('count', 0) or 0)} 个终端。"
                    )
                )

        if comparison_status == "regressed":
            actions.append(
                self.tr("当前批次相较源批次出现回退，建议先对差异终端做定向复盘，再扩大重试范围。")
            )
        elif comparison_status == "mixed":
            actions.append(
                self.tr("当前批次同时存在改善与回退，建议先锁定新增问题终端，避免误判整体恢复。")
            )
        elif comparison_status == "improved" and (
            pending_targets or failed_targets or nonzero_targets
        ):
            actions.append(
                self.tr("当前批次相较源批次已有改善，可优先续跑遗留问题终端，不必全量重放。")
            )

        if not actions:
            actions.append(self.tr("当前批次未发现明显异常，可保留为稳定基线并继续观察后续批次。"))

        total_problem_targets = len(failed_targets) + len(pending_targets) + len(nonzero_targets)
        return {
            "priority": priority,
            "focus": focus,
            "problem_target_total": total_problem_targets,
            "failed_targets": failed_targets,
            "pending_targets": pending_targets,
            "nonzero_targets": nonzero_targets,
            "failure_reasons": reason_items,
            "available_retries": available_retries,
            "recommended_actions": actions,
        }

    def _record_recommendation_lines(self, record: object) -> list[str]:
        """返回批次级建议处置计划文本。"""
        payload = self._record_recommendation_payload(record)
        reason_items = payload.get("failure_reasons", [])
        if not isinstance(reason_items, list):
            reason_items = []
        reason_text = "；".join(
            self.tr(
                f"{str(item.get('reason', '') or '')}: {self._joined_target_names(list(item.get('targets', [])), limit=4)}"
            )
            for item in reason_items
            if isinstance(item, dict) and str(item.get("reason", "") or "").strip()
        )
        action_text = "；".join(
            str(item)
            for item in payload.get("recommended_actions", [])
            if isinstance(item, str) and item
        )
        retry_text = "、".join(
            str(item)
            for item in payload.get("available_retries", [])
            if isinstance(item, str) and item
        )
        return [
            self.tr(f"处置优先级: {str(payload.get('priority', self.tr('低')) or self.tr('低'))}"),
            self.tr(f"处置焦点: {str(payload.get('focus', self.tr('无')) or self.tr('无'))}"),
            self.tr(f"问题终端总数: {int(payload.get('problem_target_total', 0) or 0)}"),
            self.tr(
                f"待回执终端: {self._joined_target_names(list(payload.get('pending_targets', [])))}"
            ),
            self.tr(
                f"失败终端: {self._joined_target_names(list(payload.get('failed_targets', [])))}"
            ),
            self.tr(
                f"非零退出终端: {self._joined_target_names(list(payload.get('nonzero_targets', [])))}"
            ),
            self.tr(f"推荐执行: {self._preferred_retry_label(record) or self.tr('无')}"),
            self.tr(f"失败原因分组: {reason_text or self.tr('无')}"),
            self.tr(f"可执行重试: {retry_text or self.tr('无')}"),
            self.tr(f"建议动作: {action_text or self.tr('无')}"),
        ]

    def _record_lineage_batch_ids(self, record: object) -> list[int]:
        """返回当前批次的谱系链路。"""
        lineage: list[int] = []
        visited: set[int] = set()
        current_record: Optional[object] = record
        max_depth = 12
        while current_record is not None and max_depth > 0:
            current_batch_id = self._normalize_batch_id(getattr(current_record, "batch_id", None))
            if current_batch_id is None or current_batch_id in visited:
                break
            visited.add(current_batch_id)
            lineage.append(current_batch_id)
            origin_batch_id = self._normalize_batch_id(
                getattr(current_record, "origin_batch_id", None)
            )
            if origin_batch_id is None:
                break
            current_record = self._find_record_by_batch_id(origin_batch_id)
            max_depth -= 1
        lineage.reverse()
        return lineage

    def _record_lineage_text(self, record: object) -> str:
        """返回当前批次的谱系文本。"""
        lineage = self._record_lineage_batch_ids(record)
        if not lineage:
            current_batch_id = self._normalize_batch_id(getattr(record, "batch_id", None))
            return (
                self._origin_batch_label(current_batch_id)
                if current_batch_id is not None
                else self.tr("无")
            )
        return " -> ".join(self._origin_batch_label(batch_id) for batch_id in lineage)

    def _filtered_overview_payload(self) -> dict[str, object]:
        """返回当前筛选结果的复盘洞察。"""
        batch_count = len(self._filtered_records)
        retry_batch_count = 0
        improved_retry_count = 0
        regressed_retry_count = 0
        mixed_retry_count = 0
        stable_retry_count = 0
        pending_batch_count = 0
        task_counter: Counter[str] = Counter()
        source_counter: Counter[str] = Counter()
        target_counter: Counter[str] = Counter()
        failure_reason_counter: Counter[str] = Counter()
        task_records_map: dict[str, list[object]] = {}

        for record in self._filtered_records:
            if self._pending_receipt_target_count(record) > 0:
                pending_batch_count += 1
            task_title = str(getattr(record, "task_preset_title", "") or "").strip()
            if task_title:
                task_counter[task_title] += 1
                task_records_map.setdefault(task_title, []).append(record)
            source_label = str(getattr(record, "source_label", "") or "").strip()
            if source_label:
                source_counter[source_label] += 1
            target_counter.update(self._record_problem_target_names(record))
            for entry in self._target_result_entries(record):
                reason = self._classify_failure_reason(record, entry)
                if reason:
                    failure_reason_counter[reason] += 1

            has_lineage = self._normalize_batch_id(
                getattr(record, "origin_batch_id", None)
            ) is not None or bool(str(getattr(record, "retry_mode", "") or "").strip())
            if not has_lineage:
                continue
            retry_batch_count += 1
            comparison = self._origin_comparison_payload(record)
            status_key = ""
            if isinstance(comparison, dict) and bool(comparison.get("available")):
                status_key = str(comparison.get("status_key", "") or "").strip()
            if status_key == "improved":
                improved_retry_count += 1
            elif status_key == "regressed":
                regressed_retry_count += 1
            elif status_key == "mixed":
                mixed_retry_count += 1
            elif status_key == "stable":
                stable_retry_count += 1

        task_health_items = [
            self._task_health_entry(task_title, records)
            for task_title, records in task_records_map.items()
        ]
        weakest_tasks = sorted(
            task_health_items,
            key=lambda item: (
                float(item.get("success_rate", 0.0) or 0.0),
                -int(item.get("total_batches", 0) or 0),
                str(item.get("task_title", "") or ""),
            ),
        )[:3]

        recommended_actions: list[str] = []
        if pending_batch_count > 0:
            recommended_actions.append(
                self.tr(f"优先清理待回执批次 {pending_batch_count} 批，避免历史回执持续悬空。")
            )
        if regressed_retry_count > 0:
            recommended_actions.append(
                self.tr(
                    f"优先复盘回退重试 {regressed_retry_count} 批，确认新一轮重试是否扩大影响。"
                )
            )
        if weakest_tasks:
            weakest = weakest_tasks[0]
            recommended_actions.append(
                self.tr(
                    f"重点检查任务“{str(weakest.get('task_title', '') or '')}”，当前成功率 "
                    f"{float(weakest.get('success_rate', 0.0) or 0.0) * 100:.0f}% 。"
                )
            )
        top_reasons = failure_reason_counter.most_common(3)
        if top_reasons:
            recommended_actions.append(
                self.tr(
                    f"针对高频原因 {self._format_top_items(top_reasons)} 准备专项排查或重试模板。"
                )
            )
        top_problem_targets = target_counter.most_common(3)
        if top_problem_targets:
            recommended_actions.append(
                self.tr(f"优先处理问题终端 {self._format_top_items(top_problem_targets)}。")
            )

        return {
            "batch_count": batch_count,
            "retry_batch_count": retry_batch_count,
            "improved_retry_count": improved_retry_count,
            "regressed_retry_count": regressed_retry_count,
            "mixed_retry_count": mixed_retry_count,
            "stable_retry_count": stable_retry_count,
            "pending_batch_count": pending_batch_count,
            "top_tasks": task_counter.most_common(3),
            "top_sources": source_counter.most_common(3),
            "problem_targets": target_counter.most_common(5),
            "task_health": task_health_items,
            "weakest_tasks": weakest_tasks,
            "failure_reasons": failure_reason_counter.most_common(5),
            "recommended_actions": recommended_actions,
        }

    def _filtered_overview_lines(self) -> list[str]:
        """返回当前筛选结果的复盘文本。"""
        payload = self._filtered_overview_payload()
        if int(payload.get("batch_count", 0) or 0) <= 0:
            return [self.tr("当前筛选条件下没有复盘洞察")]
        recommended_actions = payload.get("recommended_actions", [])
        if not isinstance(recommended_actions, list):
            recommended_actions = []
        return [
            self.tr(
                f"筛选复盘: 共 {int(payload.get('batch_count', 0) or 0)} 批，"
                f"其中重试批次 {int(payload.get('retry_batch_count', 0) or 0)} 批，"
                f"改善 {int(payload.get('improved_retry_count', 0) or 0)} 批，"
                f"回退 {int(payload.get('regressed_retry_count', 0) or 0)} 批，"
                f"混合 {int(payload.get('mixed_retry_count', 0) or 0)} 批，"
                f"持平 {int(payload.get('stable_retry_count', 0) or 0)} 批。"
            ),
            self.tr(f"待回执批次: {int(payload.get('pending_batch_count', 0) or 0)}"),
            self.tr(f"任务热点: {self._format_top_items(payload.get('top_tasks', []))}"),
            self.tr(
                f"任务成功率: {self._format_task_health_items(payload.get('weakest_tasks', []))}"
            ),
            self.tr(f"来源分布: {self._format_top_items(payload.get('top_sources', []))}"),
            self.tr(f"问题热点终端: {self._format_top_items(payload.get('problem_targets', []))}"),
            self.tr(f"失败原因聚类: {self._format_top_items(payload.get('failure_reasons', []))}"),
            self.tr(
                f"建议计划: {'；'.join(str(item) for item in recommended_actions if isinstance(item, str) and item) or self.tr('无')}"
            ),
        ]

    def _comparison_summary_lines(self, record: object) -> list[str]:
        """返回源批次对比摘要文本。"""
        comparison = self._origin_comparison_payload(record)
        if comparison is None:
            return []
        if not bool(comparison.get("available")):
            return [
                f"{self.tr('源批次对比')}: {comparison.get('summary', self.tr('无'))}",
            ]

        origin_metrics = comparison.get("origin_metrics", {})
        current_metrics = comparison.get("current_metrics", {})
        delta = comparison.get("delta", {})
        if not isinstance(origin_metrics, dict) or not isinstance(current_metrics, dict):
            return []
        if not isinstance(delta, dict):
            delta = {}
        origin_problem_total = (
            int(origin_metrics.get("failed_targets", 0) or 0)
            + int(origin_metrics.get("nonzero_exit_targets", 0) or 0)
            + int(origin_metrics.get("pending_receipts", 0) or 0)
        )
        current_problem_total = (
            int(current_metrics.get("failed_targets", 0) or 0)
            + int(current_metrics.get("nonzero_exit_targets", 0) or 0)
            + int(current_metrics.get("pending_receipts", 0) or 0)
        )
        return [
            self.tr(
                f"源批次对比: {comparison.get('status_label', self.tr('无'))} · "
                f"对比目标 {int(comparison.get('comparable_target_count', 0) or 0)} 个 · "
                f"源批次 {comparison.get('origin_batch_label', self.tr('无'))}"
            ),
            self.tr(
                f"问题终端变化: {origin_problem_total} -> {current_problem_total} "
                f"({self._signed_delta_text(current_problem_total - origin_problem_total)})"
            ),
            self.tr(
                f"失败终端变化: {int(origin_metrics.get('failed_targets', 0) or 0)} -> "
                f"{int(current_metrics.get('failed_targets', 0) or 0)}"
            ),
            self.tr(
                f"非零退出变化: {int(origin_metrics.get('nonzero_exit_targets', 0) or 0)} -> "
                f"{int(current_metrics.get('nonzero_exit_targets', 0) or 0)}"
            ),
            self.tr(
                f"待回执变化: {int(origin_metrics.get('pending_receipts', 0) or 0)} -> "
                f"{int(current_metrics.get('pending_receipts', 0) or 0)}"
            ),
            self.tr(
                f"回执覆盖变化: {int(origin_metrics.get('reported_targets', 0) or 0)} -> "
                f"{int(current_metrics.get('reported_targets', 0) or 0)} "
                f"({self._signed_delta_text(int(delta.get('reported_targets', 0) or 0))})"
            ),
            self.tr(
                f"回显覆盖变化: {int(origin_metrics.get('captured_targets', 0) or 0)} -> "
                f"{int(current_metrics.get('captured_targets', 0) or 0)} "
                f"({self._signed_delta_text(int(delta.get('captured_targets', 0) or 0))})"
            ),
            f"{self.tr('改善摘要')}: {comparison.get('summary', self.tr('无'))}",
        ]

    @staticmethod
    def _retry_mode_label(value: object) -> str:
        """返回重试模式文案。"""
        mapping = {
            "failed": "失败终端重试",
            "nonzero": "非零退出重试",
            "pending": "待回执重试",
        }
        return mapping.get(str(value or "").strip(), "无")

    @staticmethod
    def _origin_batch_label(value: object) -> str:
        """返回源批次标签。"""
        if value in (None, ""):
            return "无"
        try:
            return f"#{int(value):03d}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _output_kind_text(value: object) -> str:
        """返回输出流文案。"""
        mapping = {
            "stdout": "标准输出",
            "stderr": "错误输出",
            "mixed": "混合输出",
            "output": "普通输出",
        }
        return mapping.get(str(value or "").strip(), "无")

    def _execution_summary_lines(self, record: object) -> list[str]:
        """返回批次级执行汇总文本。"""
        return [
            f"{self.tr('已回执终端')}: {self._reported_target_count(record)} / {getattr(record, 'target_count', 0)}",
            f"{self.tr('成功退出终端')}: {self._zero_exit_target_count(record)}",
            f"{self.tr('非零退出终端')}: {self._nonzero_exit_target_count(record)}",
            f"{self.tr('可重试失败终端')}: {self._retryable_failed_target_count(record)}",
            f"{self.tr('可重试待回执终端')}: {self._retryable_pending_target_count(record)}",
            f"{self.tr('错误输出终端')}: {self._stderr_target_count(record)}",
            f"{self.tr('待回执终端')}: {self._pending_receipt_target_count(record)}",
        ]

    def _record_status_text(self, record: object) -> str:
        """返回批次状态文案。"""
        status_key = self._record_status_key(record)
        status_text_map = {
            "failed": self.tr("失败"),
            "partial_failed": self.tr("部分失败"),
            "undelivered": self.tr("未投递"),
            "waiting": self.tr("等待回显"),
            "capturing": self.tr("采集中"),
            "echoed": self.tr("已回显"),
            "success": self.tr("成功"),
        }
        return status_text_map.get(status_key, self.tr("成功"))

    def _record_status_key(self, record: object) -> str:
        """返回批次状态键。"""
        failed_targets = self._string_list(getattr(record, "failed_targets", []))
        delivered = self._delivery_count(record)
        expected = self._expected_delivery_count(record)
        target_count = int(getattr(record, "target_count", 0) or 0)
        source_kind = str(getattr(record, "source_kind", "") or "")
        task_title = getattr(record, "task_preset_title", None)
        captured_target_count = self._captured_target_count(record)
        successful_target_count = max(target_count - len(failed_targets), 0)
        exit_report_count = 0
        nonzero_exit_count = 0
        failed_target_set = set(failed_targets)
        for entry in self._target_result_entries(record):
            if str(entry.get("target_name", "") or "") in failed_target_set:
                continue
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            if exit_code is None:
                continue
            exit_report_count += 1
            if exit_code != 0:
                nonzero_exit_count += 1
        if failed_targets:
            if len(failed_targets) >= target_count > 0:
                return "failed"
            return "partial_failed"
        if nonzero_exit_count:
            if successful_target_count > 0 and exit_report_count >= successful_target_count:
                if nonzero_exit_count >= successful_target_count:
                    return "failed"
            return "partial_failed"
        if delivered <= 0 and expected > 0:
            return "undelivered"
        if source_kind == "task_preset" or (isinstance(task_title, str) and task_title.strip()):
            if captured_target_count <= 0:
                return "waiting"
            if captured_target_count < successful_target_count:
                return "capturing"
            if successful_target_count > 0:
                return "echoed"
        return "success"

    def _target_results_summary_text(self, record: object) -> str:
        """返回按终端分组的结果摘要文本。"""
        blocks: list[str] = []
        for entry in self._target_result_entries(record):
            excerpt = str(entry.get("result_excerpt", "") or "").strip() or self.tr("无")
            updated_at = entry.get("result_excerpt_updated_at", None) or self.tr("无")
            sample_count = int(entry.get("result_sample_count", 0) or 0)
            state = str(entry.get("delivery_state", "sent") or "sent")
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            exit_code_text = str(exit_code) if exit_code is not None else self.tr("未记录")
            exit_code_updated_at = entry.get("exit_code_updated_at", None) or self.tr("无")
            stdout_excerpt = str(entry.get("stdout_excerpt", "") or "").strip() or self.tr("无")
            stderr_excerpt = str(entry.get("stderr_excerpt", "") or "").strip() or self.tr("无")
            blocks.append(
                "\n".join(
                    [
                        f"{self.tr('终端')}: {entry['target_name']}",
                        f"{self.tr('状态')}: {state}",
                        f"{self.tr('输出流')}: {self._output_kind_text(entry.get('last_output_kind', ''))}",
                        f"{self.tr('退出码')}: {exit_code_text}",
                        f"{self.tr('回执时间')}: {exit_code_updated_at}",
                        f"{self.tr('片段数')}: {sample_count}",
                        f"{self.tr('更新时间')}: {updated_at}",
                        f"{self.tr('摘要')}: {excerpt}",
                        f"{self.tr('标准输出摘要')}: {stdout_excerpt}",
                        f"{self.tr('错误输出摘要')}: {stderr_excerpt}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _record_summary_text(self, record: object) -> str:
        """返回用于复制的批次摘要。"""
        failed_targets = self._string_list(getattr(record, "failed_targets", []))
        successful_targets = self._successful_targets(record)
        task_title = getattr(record, "task_preset_title", None)
        template_label = getattr(record, "task_template_label", None)
        target_filter_label = getattr(record, "target_filter_label", None)
        target_group_label = getattr(record, "target_group_label", None)
        origin_batch_id = getattr(record, "origin_batch_id", None)
        lineage_text = self._record_lineage_text(record)
        retry_mode = getattr(record, "retry_mode", None)
        archive_tags = self._string_list(getattr(record, "archive_tags", []))
        result_excerpt = getattr(record, "result_excerpt", "") or self.tr("无")
        result_updated_at = getattr(record, "result_excerpt_updated_at", None) or self.tr("无")
        target_result_lines = []
        for entry in self._target_result_entries(record):
            excerpt = str(entry.get("result_excerpt", "") or "").strip() or self.tr("无")
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            exit_segment = self.tr(f" exit={exit_code}") if exit_code is not None else ""
            target_result_lines.append(
                f"{entry['target_name']} [{entry.get('delivery_state', 'sent')}{exit_segment}] {excerpt}"
            )
        return "\n".join(
            [
                f"{self.tr('批次')}: #{getattr(record, 'batch_id', 0):03d}",
                f"{self.tr('时间')}: {getattr(record, 'timestamp', '--:--:--')}",
                f"{self.tr('来源')}: {getattr(record, 'source_label', self.tr('未知'))}",
                f"{self.tr('任务预设')}: {task_title or self.tr('无')}",
                f"{self.tr('任务模板')}: {template_label or self.tr('无')}",
                f"{self.tr('范围')}: {getattr(record, 'scope_label', self.tr('未知'))}",
                f"{self.tr('目标筛选')}: {target_filter_label or self.tr('无')}",
                f"{self.tr('目标分组')}: {target_group_label or self.tr('无')}",
                f"{self.tr('源批次')}: {self.tr(self._origin_batch_label(origin_batch_id))}",
                f"{self.tr('批次链路')}: {lineage_text}",
                f"{self.tr('重试类型')}: {self.tr(self._retry_mode_label(retry_mode)) if retry_mode else self.tr('无')}",
                f"{self.tr('状态')}: {self._record_status_text(record)}",
                f"{self.tr('命令条数')}: {getattr(record, 'command_count', 0)}",
                f"{self.tr('目标终端')}: {getattr(record, 'target_count', 0)}",
                f"{self.tr('理论投递')}: {self._expected_delivery_count(record)}",
                f"{self.tr('实际投递')}: {self._delivery_count(record)}",
                f"{self.tr('投递完成率')}: {self._delivery_ratio_text(record)}",
                *self._execution_summary_lines(record),
                *self._comparison_summary_lines(record),
                f"{self.tr('精确目标数量')}: {len(self._string_list(getattr(record, 'target_connection_ids', [])))}",
                f"{self.tr('归档标签')}: {', '.join(archive_tags) or self.tr('无')}",
                f"{self.tr('最近结果时间')}: {result_updated_at}",
                f"{self.tr('最近结果摘要')}: {result_excerpt}",
                f"{self.tr('终端结果摘要')}: {' | '.join(target_result_lines) or self.tr('无')}",
                f"{self.tr('成功终端')}: {', '.join(successful_targets) or self.tr('无')}",
                f"{self.tr('失败终端')}: {', '.join(failed_targets) or self.tr('无')}",
            ]
        )

    def _set_clipboard_text(self, text: str) -> None:
        """复制文本到剪贴板。"""
        QApplication.clipboard().setText(text)

    def _selected_record(self) -> Optional[object]:
        """返回当前选中的记录。"""
        row = self.history_list.currentRow()
        if row < 0 or row >= len(self._filtered_records):
            return None
        return self._filtered_records[row]

    def _copy_selected_summary(self) -> None:
        """复制当前批次摘要。"""
        record = self._selected_record()
        if record is None:
            return
        self._set_clipboard_text(self._record_summary_text(record))

    def _copy_selected_recommendation(self) -> None:
        """复制当前批次的建议处置计划。"""
        record = self._selected_record()
        if record is None:
            return
        self._set_clipboard_text(
            "\n".join([self.tr("建议处置计划:")] + self._record_recommendation_lines(record))
        )

    def _request_apply_selected_recommendation(self) -> None:
        """请求执行当前批次推荐动作。"""
        record = self._selected_record()
        if record is None:
            return
        retry_mode = self._preferred_retry_mode(record)
        if not retry_mode:
            return
        self.recommended_retry_requested.emit(record, retry_mode)

    def _copy_filtered_overview(self) -> None:
        """复制当前筛选结果的复盘洞察。"""
        if not self._filtered_records:
            return
        self._set_clipboard_text("\n".join(self._filtered_overview_lines()))

    def _copy_selected_commands(self) -> None:
        """复制当前批次命令列表。"""
        record = self._selected_record()
        if record is None:
            return
        commands = self._string_list(getattr(record, "commands", []))
        self._set_clipboard_text("\n".join(commands))

    def _copy_target_results(self) -> None:
        """复制当前批次按终端分组的结果摘要。"""
        record = self._selected_record()
        if record is None:
            return
        self._set_clipboard_text(self._target_results_summary_text(record))

    def _copy_failed_targets(self) -> None:
        """复制当前批次失败终端。"""
        record = self._selected_record()
        if record is None:
            return
        failed_targets = self._string_list(getattr(record, "failed_targets", []))
        self._set_clipboard_text("\n".join(failed_targets))

    def _request_replay_selected_record(self) -> None:
        """请求将当前批次复用为新任务。"""
        record = self._selected_record()
        if record is None:
            return
        if not self._string_list(getattr(record, "commands", [])):
            return
        self.replay_requested.emit(record)

    def _request_retry_failed_selected_record(self) -> None:
        """请求重试当前批次中的失败终端。"""
        record = self._selected_record()
        if record is None:
            return
        if self._retryable_failed_target_count(record) <= 0:
            return
        self.retry_failed_requested.emit(record)

    def _request_retry_nonzero_selected_record(self) -> None:
        """请求重试当前批次中的非零退出终端。"""
        record = self._selected_record()
        if record is None:
            return
        if self._nonzero_exit_target_count(record) <= 0:
            return
        self.retry_nonzero_requested.emit(record)

    def _request_retry_pending_selected_record(self) -> None:
        """请求重试当前批次中的待回执终端。"""
        record = self._selected_record()
        if record is None:
            return
        if self._retryable_pending_target_count(record) <= 0:
            return
        self.retry_pending_requested.emit(record)

    def _export_report_text(self, record: object) -> str:
        """导出批次报告文本。"""
        commands = self._string_list(getattr(record, "commands", []))
        command_block = "\n".join(commands) if commands else self.tr("无")
        target_results_block = self._target_results_summary_text(record) or self.tr("无")
        return "\n\n".join(
            [
                self._record_summary_text(record),
                f"{self.tr('筛选洞察')}:\n" + "\n".join(self._filtered_overview_lines()),
                f"{self.tr('执行汇总')}:\n" + "\n".join(self._execution_summary_lines(record)),
                f"{self.tr('建议处置计划')}:\n"
                + "\n".join(self._record_recommendation_lines(record)),
                f"{self.tr('命令列表')}:\n{command_block}",
                f"{self.tr('终端结果详情')}:\n{target_results_block}",
            ]
        )

    def _record_json_payload(self, record: object) -> dict[str, object]:
        """返回结构化 JSON 导出内容。"""
        comparison = self._origin_comparison_payload(record)
        return {
            "batch_id": int(getattr(record, "batch_id", 0) or 0),
            "timestamp": str(getattr(record, "timestamp", "--:--:--") or "--:--:--"),
            "source_label": str(
                getattr(record, "source_label", self.tr("未知")) or self.tr("未知")
            ),
            "source_kind": str(getattr(record, "source_kind", "") or ""),
            "origin_batch_id": getattr(record, "origin_batch_id", None),
            "lineage": {
                "batch_ids": self._record_lineage_batch_ids(record),
                "text": self._record_lineage_text(record),
            },
            "retry_mode": getattr(record, "retry_mode", None),
            "retry_mode_label": self._retry_mode_label(getattr(record, "retry_mode", None)),
            "scope_label": str(getattr(record, "scope_label", self.tr("未知")) or self.tr("未知")),
            "scope_key": getattr(record, "scope_key", None),
            "task_preset_title": getattr(record, "task_preset_title", None),
            "task_preset_key": getattr(record, "task_preset_key", None),
            "task_template_label": getattr(record, "task_template_label", None),
            "target_type_key": getattr(record, "target_type_key", None),
            "target_filter_label": getattr(record, "target_filter_label", None),
            "target_group_key": getattr(record, "target_group_key", None),
            "target_group_label": getattr(record, "target_group_label", None),
            "status": self._record_status_text(record),
            "command_count": int(getattr(record, "command_count", 0) or 0),
            "delivery_count": self._delivery_count(record),
            "expected_delivery_count": self._expected_delivery_count(record),
            "target_count": int(getattr(record, "target_count", 0) or 0),
            "target_names": self._string_list(getattr(record, "target_names", [])),
            "target_connection_ids": self._string_list(
                getattr(record, "target_connection_ids", [])
            ),
            "commands": self._string_list(getattr(record, "commands", [])),
            "failed_targets": self._string_list(getattr(record, "failed_targets", [])),
            "archive_tags": self._string_list(getattr(record, "archive_tags", [])),
            "result_excerpt": str(getattr(record, "result_excerpt", "") or ""),
            "result_excerpt_updated_at": getattr(record, "result_excerpt_updated_at", None),
            "result_sample_count": int(getattr(record, "result_sample_count", 0) or 0),
            "execution_summary": {
                "reported_targets": self._reported_target_count(record),
                "zero_exit_targets": self._zero_exit_target_count(record),
                "nonzero_exit_targets": self._nonzero_exit_target_count(record),
                "stderr_targets": self._stderr_target_count(record),
                "pending_receipts": self._pending_receipt_target_count(record),
                "captured_targets": self._captured_target_count(record),
                "retryable_failed_targets": self._retryable_failed_target_count(record),
                "retryable_pending_targets": self._retryable_pending_target_count(record),
            },
            "comparison": comparison,
            "filtered_overview_context": self._filtered_overview_payload(),
            "record_recommendation": self._record_recommendation_payload(record),
            "target_result_entries": self._target_result_entries(record),
        }

    def _export_selected_report(self) -> None:
        """导出当前选中批次的文本报告。"""
        record = self._selected_record()
        if record is None:
            return
        batch_id = int(getattr(record, "batch_id", 0) or 0)
        default_name = self.tr(f"发送结果-批次{batch_id:03d}.txt")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出批次报告"),
            default_name,
            self.tr("文本文件 (*.txt);;所有文件 (*)"),
        )
        if not file_path:
            return
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(self._export_report_text(record))

    def _export_selected_json(self) -> None:
        """导出当前选中批次的 JSON 报告。"""
        record = self._selected_record()
        if record is None:
            return
        batch_id = int(getattr(record, "batch_id", 0) or 0)
        default_name = self.tr(f"发送结果-批次{batch_id:03d}.json")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出 JSON 报告"),
            default_name,
            self.tr("JSON 文件 (*.json);;所有文件 (*)"),
        )
        if not file_path:
            return
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(
                self._record_json_payload(record),
                handle,
                ensure_ascii=False,
                indent=2,
            )

    def _update_detail_action_state(self, record: Optional[object]) -> None:
        """刷新详情操作按钮状态。"""
        has_record = record is not None
        self.copy_overview_button.setEnabled(bool(self._filtered_records))
        self.copy_summary_button.setEnabled(has_record)
        self.copy_recommendation_button.setEnabled(has_record)
        preferred_retry_mode = self._preferred_retry_mode(record) if has_record else ""
        self.apply_recommendation_button.setEnabled(bool(preferred_retry_mode))
        self.apply_recommendation_button.setText(
            self.tr("按建议执行")
            if not preferred_retry_mode
            else self.tr(f"执行推荐: {self._retry_mode_label(preferred_retry_mode)}")
        )
        self.copy_commands_button.setEnabled(
            has_record and bool(self._string_list(getattr(record, "commands", [])))
        )
        self.copy_target_results_button.setEnabled(
            has_record and bool(self._target_result_entries(record))
        )
        self.copy_failed_targets_button.setEnabled(
            has_record and bool(self._string_list(getattr(record, "failed_targets", [])))
        )
        self.reuse_record_button.setEnabled(
            has_record and bool(self._string_list(getattr(record, "commands", [])))
        )
        self.retry_failed_button.setEnabled(
            has_record and self._retryable_failed_target_count(record) > 0
        )
        self.retry_nonzero_button.setEnabled(
            has_record and self._nonzero_exit_target_count(record) > 0
        )
        self.retry_pending_button.setEnabled(
            has_record and self._retryable_pending_target_count(record) > 0
        )
        self.export_report_button.setEnabled(has_record)
        self.export_json_button.setEnabled(has_record)

    def set_records(self, records: list[object]) -> None:
        """刷新显示记录。"""
        self._records = list(records)
        self._refresh_scope_filters()
        self._refresh_task_filters()
        self._apply_filters()

    def _refresh_scope_filters(self) -> None:
        """刷新范围筛选选项。"""
        current_value = self.scope_filter_combo.currentData()
        scopes = []
        seen: set[str] = set()
        for record in self._records:
            scope_label = getattr(record, "scope_label", "")
            if not isinstance(scope_label, str) or not scope_label or scope_label in seen:
                continue
            scopes.append(scope_label)
            seen.add(scope_label)

        self.scope_filter_combo.blockSignals(True)
        self.scope_filter_combo.clear()
        self.scope_filter_combo.addItem(self.tr("全部范围"), "all")
        for scope_label in scopes:
            self.scope_filter_combo.addItem(scope_label, scope_label)
        if current_value:
            index = self.scope_filter_combo.findData(current_value)
            if index >= 0:
                self.scope_filter_combo.setCurrentIndex(index)
        self.scope_filter_combo.blockSignals(False)

    def _refresh_task_filters(self) -> None:
        """刷新任务筛选选项。"""
        current_value = self.task_filter_combo.currentData()
        task_titles = []
        seen: set[str] = set()
        for record in self._records:
            task_title = getattr(record, "task_preset_title", None)
            if not isinstance(task_title, str) or not task_title or task_title in seen:
                continue
            task_titles.append(task_title)
            seen.add(task_title)

        self.task_filter_combo.blockSignals(True)
        self.task_filter_combo.clear()
        self.task_filter_combo.addItem(self.tr("全部任务"), "all")
        self.task_filter_combo.addItem(self.tr("仅任务预设"), "__task_only__")
        for task_title in task_titles:
            self.task_filter_combo.addItem(task_title, task_title)
        if current_value:
            index = self.task_filter_combo.findData(current_value)
            if index >= 0:
                self.task_filter_combo.setCurrentIndex(index)
        self.task_filter_combo.blockSignals(False)

    def _apply_filters(self) -> None:
        """按范围、结果和搜索关键字过滤记录。"""
        scope_value = self.scope_filter_combo.currentData()
        task_value = self.task_filter_combo.currentData()
        result_value = self.result_filter_combo.currentData()
        status_value = self.status_filter_combo.currentData()
        query = self.search_edit.text().strip().lower()

        filtered: list[object] = []
        for record in self._records:
            scope_label = getattr(record, "scope_label", "")
            failed_targets = getattr(record, "failed_targets", [])
            source_label = getattr(record, "source_label", "")
            task_title = getattr(record, "task_preset_title", "")
            template_label = getattr(record, "task_template_label", "")
            archive_tags = getattr(record, "archive_tags", [])
            result_excerpt = getattr(record, "result_excerpt", "")
            target_result_entries = self._target_result_entries(record)
            batch_id = getattr(record, "batch_id", 0)
            commands = getattr(record, "commands", [])
            target_names = getattr(record, "target_names", [])
            target_filter_label = getattr(record, "target_filter_label", "")
            target_group_label = getattr(record, "target_group_label", "")
            origin_batch_id = getattr(record, "origin_batch_id", "")
            retry_mode = getattr(record, "retry_mode", "")
            comparison = self._origin_comparison_payload(record)
            lineage_text = self._record_lineage_text(record)
            status_key = self._record_status_key(record)
            status_text = self._record_status_text(record)
            is_failed_record = status_key in {"failed", "partial_failed"}
            is_success_record = status_key in {"success", "echoed"}

            if scope_value not in (None, "all") and scope_label != scope_value:
                continue
            if task_value == "__task_only__" and not task_title:
                continue
            if task_value not in (None, "all", "__task_only__") and task_title != task_value:
                continue
            if result_value == "failed" and not is_failed_record:
                continue
            if result_value == "success" and not is_success_record:
                continue
            if status_value not in (None, "all") and status_key != status_value:
                continue
            if query:
                haystack = " ".join(
                    [
                        str(batch_id),
                        str(source_label),
                        str(task_title),
                        str(template_label),
                        str(scope_label),
                        str(target_filter_label),
                        str(target_group_label),
                        str(origin_batch_id),
                        str(lineage_text),
                        str(retry_mode),
                        self._retry_mode_label(retry_mode),
                        (
                            str(comparison.get("status_label", ""))
                            if isinstance(comparison, dict)
                            else ""
                        ),
                        str(comparison.get("summary", "")) if isinstance(comparison, dict) else "",
                        " ".join(commands) if isinstance(commands, list) else "",
                        " ".join(target_names) if isinstance(target_names, list) else "",
                        " ".join(failed_targets) if isinstance(failed_targets, list) else "",
                        " ".join(archive_tags) if isinstance(archive_tags, list) else "",
                        status_text,
                        str(result_excerpt),
                        " ".join(
                            " ".join(
                                [
                                    str(entry.get("target_name", "") or ""),
                                    str(entry.get("result_excerpt", "") or ""),
                                    str(entry.get("stdout_excerpt", "") or ""),
                                    str(entry.get("stderr_excerpt", "") or ""),
                                    str(entry.get("exit_code", "") or ""),
                                ]
                            )
                            for entry in target_result_entries
                            if isinstance(entry, dict)
                        ),
                    ]
                ).lower()
                if query not in haystack:
                    continue
            filtered.append(record)

        self._filtered_records = filtered
        self.history_list.clear()
        self._update_metrics()

        for record in self._filtered_records:
            commands = getattr(record, "commands", [])
            preview = " / ".join(commands[:2]) if commands else self.tr("无命令")
            failure_badge = self._record_status_text(record)
            delivery_ratio = self._delivery_ratio_text(record)
            task_title = getattr(record, "task_preset_title", "")
            task_segment = (
                self.tr(f"  ·  任务 {task_title}")
                if isinstance(task_title, str) and task_title
                else ""
            )
            origin_batch_id = getattr(record, "origin_batch_id", None)
            retry_mode = getattr(record, "retry_mode", None)
            comparison = self._origin_comparison_payload(record)
            lineage_segment = ""
            if origin_batch_id not in (None, ""):
                lineage_segment = self.tr(
                    f"  ·  源批次 {self._origin_batch_label(origin_batch_id)}"
                )
            if retry_mode:
                lineage_segment += self.tr(f"  ·  {self._retry_mode_label(retry_mode)}")
            comparison_segment = ""
            if isinstance(comparison, dict) and comparison.get("available"):
                comparison_segment = self.tr(
                    f"  ·  对比 {comparison.get('status_label', self.tr('无'))}"
                )
            item = QListWidgetItem(
                self.tr(
                    f"#{getattr(record, 'batch_id', 0):03d}  {getattr(record, 'timestamp', '--:--:--')}  ·  "
                    f"{getattr(record, 'source_label', self.tr('发送'))}  ·  "
                    f"{getattr(record, 'command_count', 0)} 条  ·  "
                    f"{getattr(record, 'target_count', 0)} 个终端{task_segment}{lineage_segment}{comparison_segment}  ·  {failure_badge}  ·  {delivery_ratio}\n{preview}"
                ),
                self.history_list,
            )
            item.setData(Qt.UserRole, record)

        has_records = bool(self._filtered_records)
        self.empty_label.setVisible(not has_records)
        self.detail_browser.setVisible(has_records)
        self.summary_label.setText(
            self.tr(f"共 {len(self._records)} 批，当前筛出 {len(self._filtered_records)} 批")
        )
        self.insight_label.setText("\n".join(self._filtered_overview_lines()))

        if has_records:
            self.history_list.setCurrentRow(0)
        else:
            self._update_detail_action_state(None)
            self.detail_browser.setHtml(f"<p>{self.tr('当前筛选条件下没有发送记录')}</p>")

    def _update_metrics(self) -> None:
        """刷新批次级统计汇总。"""
        batch_count = len(self._filtered_records)
        failed_batch_count = sum(
            1
            for record in self._filtered_records
            if self._record_status_key(record) in {"failed", "partial_failed"}
        )
        task_batch_count = sum(
            1
            for record in self._filtered_records
            if isinstance(getattr(record, "task_preset_title", None), str)
            and getattr(record, "task_preset_title", None)
        )
        command_total = sum(
            int(getattr(record, "command_count", 0) or 0) for record in self._filtered_records
        )
        target_total = sum(
            int(getattr(record, "target_count", 0) or 0) for record in self._filtered_records
        )
        delivery_total = sum(self._delivery_count(record) for record in self._filtered_records)
        echoed_total = sum(self._captured_target_count(record) for record in self._filtered_records)
        reported_total = sum(
            self._reported_target_count(record) for record in self._filtered_records
        )
        nonzero_total = sum(
            self._nonzero_exit_target_count(record) for record in self._filtered_records
        )
        overview = self._filtered_overview_payload()
        self.batch_metric_label.setText(self.tr(f"批次: {batch_count}"))
        self.failed_metric_label.setText(self.tr(f"失败批次: {failed_batch_count}"))
        self.command_metric_label.setText(self.tr(f"命令总量: {command_total}"))
        self.target_metric_label.setText(self.tr(f"目标终端: {target_total}"))
        self.delivery_metric_label.setText(self.tr(f"实际投递: {delivery_total}"))
        self.task_metric_label.setText(self.tr(f"任务批次: {task_batch_count}"))
        self.echoed_metric_label.setText(self.tr(f"已回显终端: {echoed_total}"))
        self.reported_metric_label.setText(self.tr(f"已回执终端: {reported_total}"))
        self.nonzero_metric_label.setText(self.tr(f"非零退出: {nonzero_total}"))
        self.retry_batch_metric_label.setText(
            self.tr(f"重试批次: {int(overview.get('retry_batch_count', 0) or 0)}")
        )
        self.improved_metric_label.setText(
            self.tr(f"改善重试: {int(overview.get('improved_retry_count', 0) or 0)}")
        )
        self.pending_batch_metric_label.setText(
            self.tr(f"待回执批次: {int(overview.get('pending_batch_count', 0) or 0)}")
        )

    def _render_selected_record(self, row: int) -> None:
        """渲染当前选中的记录详情。"""
        if row < 0 or row >= len(self._filtered_records):
            self._update_detail_action_state(None)
            self.detail_browser.setHtml(f"<p>{self.tr('请选择一条发送记录')}</p>")
            return

        record = self._filtered_records[row]
        commands = self._string_list(getattr(record, "commands", []))
        target_names = self._string_list(getattr(record, "target_names", []))
        failed_targets = self._string_list(getattr(record, "failed_targets", []))
        successful_targets = self._successful_targets(record)
        expected_delivery_count = self._expected_delivery_count(record)
        delivery_count = self._delivery_count(record)
        status_text = self._record_status_text(record)
        delivery_ratio = self._delivery_ratio_text(record)
        task_title = getattr(record, "task_preset_title", None)
        template_label = getattr(record, "task_template_label", None)
        target_filter_label = getattr(record, "target_filter_label", None)
        target_group_label = getattr(record, "target_group_label", None)
        origin_batch_id = getattr(record, "origin_batch_id", None)
        retry_mode = getattr(record, "retry_mode", None)
        lineage_text = self._record_lineage_text(record)
        archive_tags = self._string_list(getattr(record, "archive_tags", []))
        result_excerpt = getattr(record, "result_excerpt", "") or self.tr("无")
        result_updated_at = getattr(record, "result_excerpt_updated_at", None) or self.tr("无")
        target_result_entries = self._target_result_entries(record)
        comparison_lines = self._comparison_summary_lines(record)
        overview_lines = self._filtered_overview_lines()
        recommendation_lines = self._record_recommendation_lines(record)
        self._update_detail_action_state(record)

        commands_html = "<br>".join(commands) if commands else self.tr("无")
        targets_html = "<br>".join(target_names) if target_names else self.tr("无")
        success_html = "<br>".join(successful_targets) if successful_targets else self.tr("无")
        failed_html = "<br>".join(failed_targets) if failed_targets else self.tr("无")
        tags_html = "<br>".join(archive_tags) if archive_tags else self.tr("无")
        result_html = result_excerpt.replace("\n", "<br>")
        execution_summary_html = "<br>".join(self._execution_summary_lines(record))
        comparison_html = (
            "<p>" + "<br>".join(comparison_lines) + "</p>"
            if comparison_lines
            else f"<p>{self.tr('无')}</p>"
        )
        overview_html = (
            "<p>" + "<br>".join(overview_lines) + "</p>"
            if overview_lines
            else f"<p>{self.tr('无')}</p>"
        )
        recommendation_html = (
            "<p>" + "<br>".join(recommendation_lines) + "</p>"
            if recommendation_lines
            else f"<p>{self.tr('无')}</p>"
        )
        target_result_html_parts = []
        for entry in target_result_entries:
            excerpt = str(entry.get("result_excerpt", "") or "").strip() or self.tr("无")
            updated_at = entry.get("result_excerpt_updated_at", None) or self.tr("无")
            sample_count = int(entry.get("result_sample_count", 0) or 0)
            state = str(entry.get("delivery_state", "sent") or "sent")
            exit_code = self._normalize_exit_code(entry.get("exit_code", None))
            exit_code_text = str(exit_code) if exit_code is not None else self.tr("未记录")
            exit_code_updated_at = entry.get("exit_code_updated_at", None) or self.tr("无")
            stdout_excerpt = str(entry.get("stdout_excerpt", "") or "").strip() or self.tr("无")
            stderr_excerpt = str(entry.get("stderr_excerpt", "") or "").strip() or self.tr("无")
            target_result_html_parts.append(
                "<p>"
                f"<b>{entry['target_name']}</b> · {self.tr('状态')}: {state} · "
                f"{self.tr('输出流')}: {self._output_kind_text(entry.get('last_output_kind', ''))} · "
                f"{self.tr('退出码')}: {exit_code_text} · "
                f"{self.tr('片段数')}: {sample_count} · {self.tr('更新时间')}: {updated_at}<br>"
                f"{self.tr('回执时间')}: {exit_code_updated_at}<br>"
                f"{self.tr('摘要')}: {excerpt.replace(chr(10), '<br>')}<br>"
                f"{self.tr('标准输出摘要')}: {stdout_excerpt.replace(chr(10), '<br>')}<br>"
                f"{self.tr('错误输出摘要')}: {stderr_excerpt.replace(chr(10), '<br>')}"
                "</p>"
            )
        target_result_html = (
            "".join(target_result_html_parts)
            if target_result_html_parts
            else f"<p>{self.tr('无')}</p>"
        )

        self.detail_browser.setHtml(f"""
            <h3>{self.tr('批次详情')}</h3>
            <p><b>{self.tr('批次')}:</b> #{getattr(record, 'batch_id', 0):03d}</p>
            <p><b>{self.tr('时间')}:</b> {getattr(record, 'timestamp', '--:--:--')}</p>
            <p><b>{self.tr('来源')}:</b> {getattr(record, 'source_label', self.tr('未知'))}</p>
            <p><b>{self.tr('任务预设')}:</b> {task_title or self.tr('无')}</p>
            <p><b>{self.tr('任务模板')}:</b> {template_label or self.tr('无')}</p>
            <p><b>{self.tr('范围')}:</b> {getattr(record, 'scope_label', self.tr('未知'))}</p>
            <p><b>{self.tr('目标筛选')}:</b> {target_filter_label or self.tr('无')}</p>
            <p><b>{self.tr('目标分组')}:</b> {target_group_label or self.tr('无')}</p>
            <p><b>{self.tr('源批次')}:</b> {self.tr(self._origin_batch_label(origin_batch_id))}</p>
            <p><b>{self.tr('批次链路')}:</b> {lineage_text}</p>
            <p><b>{self.tr('重试类型')}:</b> {self.tr(self._retry_mode_label(retry_mode)) if retry_mode else self.tr('无')}</p>
            <p><b>{self.tr('状态')}:</b> {status_text}</p>
            <p><b>{self.tr('已回显终端')}:</b> {self._captured_target_count(record)} / {getattr(record, 'target_count', 0)}</p>
            <p><b>{self.tr('已回执终端')}:</b> {self._reported_target_count(record)} / {getattr(record, 'target_count', 0)}</p>
            <p><b>{self.tr('非零退出终端')}:</b> {self._nonzero_exit_target_count(record)}</p>
            <p><b>{self.tr('可重试失败终端')}:</b> {self._retryable_failed_target_count(record)}</p>
            <p><b>{self.tr('可重试待回执终端')}:</b> {self._retryable_pending_target_count(record)}</p>
            <p><b>{self.tr('精确目标数量')}:</b> {len(self._string_list(getattr(record, 'target_connection_ids', [])))}</p>
            <p><b>{self.tr('命令条数')}:</b> {getattr(record, 'command_count', 0)}</p>
            <p><b>{self.tr('目标终端')}:</b> {getattr(record, 'target_count', 0)}</p>
            <p><b>{self.tr('理论投递')}:</b> {expected_delivery_count}</p>
            <p><b>{self.tr('实际投递')}:</b> {delivery_count}</p>
            <p><b>{self.tr('投递完成率')}:</b> {delivery_ratio}</p>
            <p><b>{self.tr('失败数')}:</b> {len(failed_targets)}</p>
            <h4>{self.tr('执行汇总')}</h4>
            <p>{execution_summary_html}</p>
            <h4>{self.tr('源批次对比')}</h4>
            {comparison_html}
            <h4>{self.tr('当前筛选洞察')}</h4>
            {overview_html}
            <h4>{self.tr('建议处置计划')}</h4>
            {recommendation_html}
            <h4>{self.tr('归档标签')}</h4>
            <p>{tags_html}</p>
            <h4>{self.tr('最近结果摘要')}</h4>
            <p><b>{self.tr('更新时间')}:</b> {result_updated_at}</p>
            <p>{result_html}</p>
            <h4>{self.tr('按终端结果汇总')}</h4>
            {target_result_html}
            <h4>{self.tr('成功终端')}</h4>
            <p>{success_html}</p>
            <h4>{self.tr('命令')}</h4>
            <p>{commands_html}</p>
            <h4>{self.tr('目标终端列表')}</h4>
            <p>{targets_html}</p>
            <h4>{self.tr('失败终端')}</h4>
            <p>{failed_html}</p>
            <p><i>{self.tr('提示：这里展示的是发送/投递结果与已采集到的执行回执，部分终端可能只有摘要而没有完整 stdout/stderr。')}</i></p>
            """)
