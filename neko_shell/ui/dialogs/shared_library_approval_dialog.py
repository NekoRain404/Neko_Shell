#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享中心待审队列对话框。

用于查看、筛选和处理共享包审批记录。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from neko_shell.utils import ConfigManager


class SharedLibraryApprovalDialog(QDialog):
    """共享中心待审队列管理对话框。"""

    approvals_changed = Signal(int, str)
    sync_completed = Signal(object)
    policy_changed = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_manager: Optional[ConfigManager] = None
        self._records: list[dict[str, Any]] = []
        self._filtered_records: list[dict[str, Any]] = []
        self.summary_label: QLabel
        self.status_label: QLabel
        self.record_list: QListWidget
        self.detail_browser: QTextBrowser
        self.decision_filter_combo: QComboBox
        self.source_filter_combo: QComboBox
        self.package_type_filter_combo: QComboBox
        self.search_edit: QLineEdit
        self.approve_selected_button: QPushButton
        self.reject_selected_button: QPushButton
        self.reset_selected_button: QPushButton
        self.approve_filtered_button: QPushButton
        self.reject_filtered_button: QPushButton
        self.trust_source_button: QPushButton
        self.trust_signer_button: QPushButton
        self.revoke_signer_button: QPushButton
        self.allow_package_type_button: QPushButton
        self.grant_rotation_exception_button: QPushButton
        self.remove_rotation_exception_button: QPushButton
        self.refresh_button: QPushButton
        self.sync_button: QPushButton
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.tr("共享待审队列"))
        self.resize(980, 640)
        self.setMinimumSize(860, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(self.tr("共享包审批队列"), self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        description = QLabel(
            self.tr(
                "在这里处理共享仓库中因来源未信任、签名者未受信任、包类型未加入自动拉取或签名轮换策略命中而被拦截的共享包。批准后的记录将在下一次同步时自动导入。"
            ),
            self,
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: palette(mid);")
        layout.addWidget(description)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel(self.tr("决策"), self))
        self.decision_filter_combo = QComboBox(self)
        self.decision_filter_combo.addItem(self.tr("全部"), "all")
        self.decision_filter_combo.addItem(self.tr("待审"), "pending")
        self.decision_filter_combo.addItem(self.tr("已批准"), "approved")
        self.decision_filter_combo.addItem(self.tr("已拒绝"), "rejected")
        self.decision_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.decision_filter_combo)

        filter_row.addWidget(QLabel(self.tr("来源"), self))
        self.source_filter_combo = QComboBox(self)
        self.source_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.source_filter_combo)

        filter_row.addWidget(QLabel(self.tr("包类型"), self))
        self.package_type_filter_combo = QComboBox(self)
        self.package_type_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.package_type_filter_combo)

        filter_row.addWidget(QLabel(self.tr("搜索"), self))
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText(self.tr("名称 / 来源 / 原因 / 版本"))
        self.search_edit.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_edit, 1)

        layout.addLayout(filter_row)

        self.summary_label = QLabel(self.tr("当前没有共享审批记录"), self)
        self.summary_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.summary_label)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        self.record_list = QListWidget(splitter)
        self.record_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.record_list.currentRowChanged.connect(self._render_current_record)
        self.record_list.itemSelectionChanged.connect(self._update_action_states)
        self.record_list.setMinimumWidth(320)
        splitter.addWidget(self.record_list)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.approve_selected_button = QPushButton(self.tr("批准选中"), right_panel)
        self.approve_selected_button.clicked.connect(
            lambda: self._apply_decision_to_selected("approved")
        )
        action_row.addWidget(self.approve_selected_button)

        self.reject_selected_button = QPushButton(self.tr("拒绝选中"), right_panel)
        self.reject_selected_button.clicked.connect(
            lambda: self._apply_decision_to_selected("rejected")
        )
        action_row.addWidget(self.reject_selected_button)

        self.reset_selected_button = QPushButton(self.tr("恢复待审"), right_panel)
        self.reset_selected_button.clicked.connect(
            lambda: self._apply_decision_to_selected("pending")
        )
        action_row.addWidget(self.reset_selected_button)

        self.approve_filtered_button = QPushButton(self.tr("批准筛选结果"), right_panel)
        self.approve_filtered_button.clicked.connect(
            lambda: self._apply_decision_to_filtered("approved")
        )
        action_row.addWidget(self.approve_filtered_button)

        self.reject_filtered_button = QPushButton(self.tr("拒绝筛选结果"), right_panel)
        self.reject_filtered_button.clicked.connect(
            lambda: self._apply_decision_to_filtered("rejected")
        )
        action_row.addWidget(self.reject_filtered_button)

        self.sync_button = QPushButton(self.tr("同步已放行共享包"), right_panel)
        self.sync_button.clicked.connect(self._sync_approved_records)
        action_row.addWidget(self.sync_button)

        policy_row = QHBoxLayout()
        policy_row.setSpacing(8)
        self.trust_source_button = QPushButton(self.tr("信任当前来源"), right_panel)
        self.trust_source_button.clicked.connect(self._trust_current_source)
        policy_row.addWidget(self.trust_source_button)

        self.trust_signer_button = QPushButton(self.tr("信任当前签名者"), right_panel)
        self.trust_signer_button.clicked.connect(self._trust_current_signer)
        policy_row.addWidget(self.trust_signer_button)

        self.revoke_signer_button = QPushButton(self.tr("撤销当前签名者"), right_panel)
        self.revoke_signer_button.clicked.connect(self._revoke_current_signer)
        policy_row.addWidget(self.revoke_signer_button)

        self.allow_package_type_button = QPushButton(self.tr("允许当前类型自动拉取"), right_panel)
        self.allow_package_type_button.clicked.connect(self._allow_current_package_type)
        policy_row.addWidget(self.allow_package_type_button)

        self.grant_rotation_exception_button = QPushButton(self.tr("批准并例外放行"), right_panel)
        self.grant_rotation_exception_button.clicked.connect(self._grant_current_rotation_exception)
        policy_row.addWidget(self.grant_rotation_exception_button)

        self.remove_rotation_exception_button = QPushButton(self.tr("移除轮换例外"), right_panel)
        self.remove_rotation_exception_button.clicked.connect(
            self._remove_current_rotation_exception
        )
        policy_row.addWidget(self.remove_rotation_exception_button)

        self.refresh_button = QPushButton(self.tr("刷新"), right_panel)
        self.refresh_button.clicked.connect(self.reload_records)
        policy_row.addWidget(self.refresh_button)
        policy_row.addStretch(1)
        action_row.addStretch(1)
        right_layout.addLayout(action_row)
        right_layout.addLayout(policy_row)

        self.detail_browser = QTextBrowser(right_panel)
        self.detail_browser.setOpenExternalLinks(False)
        self.detail_browser.setReadOnly(True)
        right_layout.addWidget(self.detail_browser, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([360, 620])

        self.status_label = QLabel(self.tr("未绑定配置管理器"), self)
        self.status_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.status_label)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._rebuild_filter_options([])
        self._update_action_states()

    @staticmethod
    def _package_type_label(package_type: str) -> str:
        if package_type == "workspace_templates":
            return "工作区模板"
        if package_type == "connection_filter_presets":
            return "筛选预设"
        return package_type or "未知类型"

    @staticmethod
    def _decision_label(decision: str) -> str:
        if decision == "approved":
            return "已批准"
        if decision == "rejected":
            return "已拒绝"
        return "待审"

    @staticmethod
    def _reason_label(reason: str) -> str:
        if reason.startswith("team_rule_block:"):
            rule_name = reason.split(":", 1)[1].strip()
            return f"命中团队阻断规则: {rule_name or '未命名规则'}"
        if reason.startswith("team_rule:"):
            rule_name = reason.split(":", 1)[1].strip()
            return f"命中团队审批规则: {rule_name or '未命名规则'}"
        if reason == "untrusted_source":
            return "来源未受信任"
        if reason == "blocked_package_type":
            return "包类型未加入自动拉取"
        if reason == "untrusted_signer":
            return "签名者未受信任"
        if reason == "expired_signer_policy":
            return "签名者信任策略已过期"
        if reason == "rotation_due_signer":
            return "签名者轮换临近截止"
        if reason == "rotation_overdue_signer":
            return "签名者轮换已超期"
        if reason == "revoked_signer":
            return "签名者已撤销"
        if reason == "invalid_integrity":
            return "完整性校验失败"
        if reason == "invalid_signature":
            return "签名校验失败"
        return reason or "未说明原因"

    @staticmethod
    def _policy_status_label(status: str) -> str:
        if status == "active":
            return "有效"
        if status == "expiring":
            return "临近到期"
        if status == "expired":
            return "已过期"
        if status == "invalid":
            return "配置无效"
        return "未设置"

    @staticmethod
    def _rotation_status_label(status: str) -> str:
        if status == "scheduled":
            return "已计划"
        if status == "due":
            return "临近截止"
        if status == "overdue":
            return "已超期"
        if status == "invalid":
            return "配置无效"
        return "未设置"

    def set_config_manager(self, manager: ConfigManager) -> None:
        """绑定配置管理器并加载审批记录。"""
        self._config_manager = manager
        self.reload_records()

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def reload_records(self) -> None:
        """重新加载审批记录。"""
        if not self._config_manager:
            self._records = []
            self._filtered_records = []
            self.record_list.clear()
            self.detail_browser.clear()
            self.summary_label.setText(self.tr("当前没有共享审批记录"))
            self._set_status(self.tr("未绑定配置管理器"))
            self._rebuild_filter_options([])
            self._update_action_states()
            return

        selected_ids = {
            str(item.data(Qt.ItemDataRole.UserRole) or "")
            for item in self.record_list.selectedItems()
            if str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        }
        self._records = self._config_manager.load_shared_library_approval_records()
        self._rebuild_filter_options(self._records)
        self._apply_filters(selected_ids=selected_ids)
        self._set_status(self.tr(f"已加载 {len(self._records)} 条共享审批记录"))

    def _rebuild_filter_options(self, records: list[dict[str, Any]]) -> None:
        """根据当前记录重建筛选项。"""
        current_source = (
            self.source_filter_combo.currentData() if hasattr(self, "source_filter_combo") else None
        )
        current_package_type = (
            self.package_type_filter_combo.currentData()
            if hasattr(self, "package_type_filter_combo")
            else None
        )

        sources = sorted(
            {
                str(record.get("source_app") or "").strip()
                for record in records
                if str(record.get("source_app") or "").strip()
            },
            key=str.casefold,
        )
        package_types = sorted(
            {
                str(record.get("package_type") or "").strip()
                for record in records
                if str(record.get("package_type") or "").strip()
            },
            key=str.casefold,
        )

        self.source_filter_combo.blockSignals(True)
        self.package_type_filter_combo.blockSignals(True)

        self.source_filter_combo.clear()
        self.source_filter_combo.addItem(self.tr("全部来源"), "all")
        for source in sources:
            self.source_filter_combo.addItem(source, source)
        source_index = self.source_filter_combo.findData(current_source)
        self.source_filter_combo.setCurrentIndex(max(source_index, 0))

        self.package_type_filter_combo.clear()
        self.package_type_filter_combo.addItem(self.tr("全部包类型"), "all")
        for package_type in package_types:
            self.package_type_filter_combo.addItem(
                self.tr(self._package_type_label(package_type)),
                package_type,
            )
        package_type_index = self.package_type_filter_combo.findData(current_package_type)
        self.package_type_filter_combo.setCurrentIndex(max(package_type_index, 0))

        self.source_filter_combo.blockSignals(False)
        self.package_type_filter_combo.blockSignals(False)

    def _apply_filters(self, *_args: Any, selected_ids: Optional[set[str]] = None) -> None:
        """应用筛选并刷新列表。"""
        decision_filter = str(self.decision_filter_combo.currentData() or "all")
        source_filter = str(self.source_filter_combo.currentData() or "all")
        package_type_filter = str(self.package_type_filter_combo.currentData() or "all")
        query = self.search_edit.text().strip().casefold()

        filtered: list[dict[str, Any]] = []
        for record in self._records:
            decision = str(record.get("decision") or "pending")
            source_app = str(record.get("source_app") or "").strip()
            package_type = str(record.get("package_type") or "").strip()
            haystack = " ".join(
                [
                    str(record.get("name") or ""),
                    source_app,
                    package_type,
                    str(record.get("package_version") or ""),
                    str(record.get("signature_signer") or ""),
                    str(record.get("signature_fingerprint") or ""),
                    str(record.get("policy_expires_at") or ""),
                    str(record.get("policy_status") or ""),
                    str(record.get("rotation_due_at") or ""),
                    str(record.get("rotation_status") or ""),
                    str(record.get("required_signature_count") or ""),
                    str(record.get("verified_signature_count") or ""),
                    " ".join(
                        str(item).strip()
                        for item in record.get("matched_team_approval_levels") or []
                        if str(item).strip()
                    ),
                    " ".join(
                        self._reason_label(str(reason)) for reason in record.get("reasons") or []
                    ),
                ]
            ).casefold()
            if decision_filter != "all" and decision != decision_filter:
                continue
            if source_filter != "all" and source_app != source_filter:
                continue
            if package_type_filter != "all" and package_type != package_type_filter:
                continue
            if query and query not in haystack:
                continue
            filtered.append(record)

        self._filtered_records = filtered
        self.record_list.blockSignals(True)
        self.record_list.clear()
        selected_ids = selected_ids or set()
        first_selected_row: Optional[int] = None
        for row, record in enumerate(filtered):
            decision = self._decision_label(str(record.get("decision") or "pending"))
            name = str(record.get("name") or "未命名共享包")
            package_type = self._package_type_label(str(record.get("package_type") or ""))
            source_app = str(record.get("source_app") or "Neko_Shell")
            item = QListWidgetItem(
                self.tr(
                    f"{decision} · {name} · {package_type} · {source_app} · "
                    f"v{int(record.get('package_version') or 1)}"
                ),
                self.record_list,
            )
            record_id = str(record.get("id") or "")
            item.setData(Qt.ItemDataRole.UserRole, record_id)
            item.setToolTip(self._record_tooltip(record))
            if record_id in selected_ids:
                item.setSelected(True)
                if first_selected_row is None:
                    first_selected_row = row

        if self.record_list.count():
            self.record_list.setCurrentRow(
                first_selected_row if first_selected_row is not None else 0
            )
        else:
            self.detail_browser.setPlainText(self.tr("当前筛选条件下没有共享审批记录"))
        self.record_list.blockSignals(False)
        self._update_summary()
        self._update_action_states()
        self._render_current_record(self.record_list.currentRow())

    def _update_summary(self) -> None:
        pending_count = sum(
            1 for record in self._filtered_records if record.get("decision") == "pending"
        )
        approved_count = sum(
            1 for record in self._filtered_records if record.get("decision") == "approved"
        )
        rejected_count = sum(
            1 for record in self._filtered_records if record.get("decision") == "rejected"
        )
        self.summary_label.setText(
            self.tr(
                f"当前筛选结果 {len(self._filtered_records)} 项 · 待审 {pending_count} 项 · "
                f"已批准 {approved_count} 项 · 已拒绝 {rejected_count} 项"
            )
        )

    def _record_tooltip(self, record: dict[str, Any]) -> str:
        reasons = ", ".join(
            self._reason_label(str(reason)) for reason in (record.get("reasons") or [])
        )
        return self.tr(
            f"{record.get('name', '未命名共享包')} · "
            f"{self._package_type_label(str(record.get('package_type') or ''))} · "
            f"来源 {record.get('source_app', 'Neko_Shell')}"
            + (f" · 原因 {reasons}" if reasons else "")
        )

    def _current_record(self) -> Optional[dict[str, Any]]:
        row = self.record_list.currentRow()
        if row < 0 or row >= len(self._filtered_records):
            return None
        return dict(self._filtered_records[row])

    def _selected_records(self) -> list[dict[str, Any]]:
        selected_ids = {
            str(item.data(Qt.ItemDataRole.UserRole) or "")
            for item in self.record_list.selectedItems()
            if str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        }
        return [
            dict(record)
            for record in self._filtered_records
            if str(record.get("id") or "") in selected_ids
        ]

    def _render_current_record(self, row: int) -> None:
        if row < 0 or row >= len(self._filtered_records):
            if not self._filtered_records:
                self.detail_browser.setPlainText(self.tr("当前筛选条件下没有共享审批记录"))
            else:
                self.detail_browser.setPlainText(self.tr("请选择一条共享审批记录"))
            return

        record = self._filtered_records[row]
        reasons = [
            self._reason_label(str(reason))
            for reason in record.get("reasons") or []
            if str(reason).strip()
        ]
        lines = [
            self.tr(f"名称: {record.get('name', '未命名共享包')}"),
            self.tr(f"决策: {self._decision_label(str(record.get('decision') or 'pending'))}"),
            self.tr(f"包类型: {self._package_type_label(str(record.get('package_type') or ''))}"),
            self.tr(f"来源应用: {record.get('source_app', 'Neko_Shell')}"),
            self.tr(f"共享版本: v{int(record.get('package_version') or 1)}"),
        ]
        sync_dir = str(record.get("sync_dir") or "").strip()
        if sync_dir:
            lines.append(self.tr(f"来源仓库: {sync_dir}"))
        requested_at = str(record.get("requested_at") or "").strip()
        if requested_at:
            lines.append(self.tr(f"进入队列: {requested_at}"))
        decided_at = str(record.get("decided_at") or "").strip()
        if decided_at:
            lines.append(self.tr(f"决策时间: {decided_at}"))
        if reasons:
            lines.append(self.tr(f"原因: {', '.join(reasons)}"))
        matched_team_rules = [
            str(item).strip()
            for item in record.get("matched_team_approval_rules") or []
            if str(item).strip()
        ]
        if matched_team_rules:
            lines.append(self.tr(f"命中团队规则: {', '.join(matched_team_rules)}"))
        matched_team_levels = [
            str(item).strip()
            for item in record.get("matched_team_approval_levels") or []
            if str(item).strip()
        ]
        if matched_team_levels:
            lines.append(self.tr(f"审批级别: {', '.join(matched_team_levels)}"))
        verified_signature_count = max(int(record.get("verified_signature_count") or 0), 0)
        if verified_signature_count:
            lines.append(self.tr(f"有效签名数: {verified_signature_count}"))
        required_signature_count = max(int(record.get("required_signature_count") or 0), 0)
        if required_signature_count:
            lines.append(self.tr(f"规则要求最小签名数: {required_signature_count}"))
        source_app = str(record.get("source_app") or "").strip()
        if source_app:
            lines.append(
                self.tr(
                    "来源策略: "
                    + (
                        "已受信任"
                        if source_app
                        in (
                            self._config_manager.app_config.shared_library_trusted_source_apps
                            if self._config_manager
                            else []
                        )
                        else "未受信任"
                    )
                )
            )
        signature_signer = str(record.get("signature_signer") or "").strip()
        signature_fingerprint = str(record.get("signature_fingerprint") or "").strip().lower()
        if signature_signer:
            lines.append(self.tr(f"签名者: {signature_signer}"))
        signer_display_name = str(record.get("signer_display_name") or "").strip()
        if signer_display_name:
            lines.append(self.tr(f"签名者别名: {signer_display_name}"))
        signer_note = str(record.get("signer_note") or "").strip()
        if signer_note:
            lines.append(self.tr(f"签名备注: {signer_note}"))
        signer_group_label = str(record.get("signer_group_label") or "").strip()
        if signer_group_label:
            lines.append(self.tr(f"签名分组: {signer_group_label}"))
        if signature_fingerprint:
            lines.append(self.tr(f"签名指纹: {signature_fingerprint}"))
            trusted_signers = (
                self._config_manager.app_config.shared_library_trusted_signer_fingerprints
                if self._config_manager
                else []
            )
            revoked_signers = (
                self._config_manager.app_config.shared_library_revoked_signer_fingerprints
                if self._config_manager
                else []
            )
            lines.append(
                self.tr(
                    "签名者策略: "
                    + (
                        "已撤销"
                        if signature_fingerprint in revoked_signers
                        else (
                            "策略已过期"
                            if str(record.get("policy_status") or "") == "expired"
                            else (
                                "已受信任"
                                if signature_fingerprint in trusted_signers
                                else "未受信任"
                            )
                        )
                    )
                )
            )
        verified_signature_signers = [
            str(item).strip()
            for item in record.get("verified_signature_signers") or []
            if str(item).strip()
        ]
        if verified_signature_signers:
            lines.append(self.tr(f"已验签签名者: {', '.join(verified_signature_signers)}"))
        policy_expires_at = str(record.get("policy_expires_at") or "").strip()
        if policy_expires_at:
            lines.append(self.tr(f"策略有效期: {policy_expires_at}"))
        policy_status = str(record.get("policy_status") or "").strip()
        if policy_status and policy_status != "none":
            lines.append(self.tr(f"策略状态: {self._policy_status_label(policy_status)}"))
        rotation_due_at = str(record.get("rotation_due_at") or "").strip()
        if rotation_due_at:
            lines.append(self.tr(f"轮换截止: {rotation_due_at}"))
        rotation_status = str(record.get("rotation_status") or "").strip()
        if rotation_status and rotation_status != "none":
            lines.append(self.tr(f"轮换状态: {self._rotation_status_label(rotation_status)}"))
        current_exception = None
        if self._config_manager and signature_fingerprint and rotation_status in {"due", "overdue"}:
            current_exception = self._config_manager.get_shared_library_rotation_exception_record(
                signature_fingerprint,
                package_type=str(record.get("package_type") or "").strip() or None,
                rotation_status=rotation_status,
                include_expired=True,
            )
        if current_exception:
            exception_status = str(current_exception.get("status") or "").strip()
            lines.append(
                self.tr("轮换例外: " + ("生效中" if exception_status == "active" else "已失效"))
            )
            source_approval_name = str(current_exception.get("source_approval_name") or "").strip()
            if source_approval_name:
                lines.append(self.tr(f"例外来源审批: {source_approval_name}"))
            exception_expires_at = str(current_exception.get("expires_at") or "").strip()
            if exception_expires_at:
                lines.append(self.tr(f"例外截止: {exception_expires_at}"))
            exception_note = str(current_exception.get("note") or "").strip()
            if exception_note:
                lines.append(self.tr(f"例外备注: {exception_note}"))
        revoked_reason = str(record.get("revoked_reason") or "").strip()
        if revoked_reason:
            lines.append(self.tr(f"撤销原因: {revoked_reason}"))
        revoked_at = str(record.get("revoked_at") or "").strip()
        if revoked_at:
            lines.append(self.tr(f"撤销时间: {revoked_at}"))
        revoked_note = str(record.get("revoked_note") or "").strip()
        if revoked_note:
            lines.append(self.tr(f"撤销备注: {revoked_note}"))
        package_type = str(record.get("package_type") or "").strip()
        if package_type:
            lines.append(
                self.tr(
                    "包类型策略: "
                    + (
                        "自动拉取已允许"
                        if package_type
                        in (
                            self._config_manager.app_config.shared_library_auto_pull_allowed_package_types
                            if self._config_manager
                            else []
                        )
                        else "自动拉取未允许"
                    )
                )
            )
        content_hash = str(record.get("content_hash") or "").strip()
        if content_hash:
            lines.append(self.tr(f"内容摘要: {content_hash[:24]}"))
        self.detail_browser.setPlainText("\n".join(lines))

    def _update_action_states(self) -> None:
        has_selection = bool(self._selected_records())
        has_filtered_records = bool(self._filtered_records)
        has_pending_filtered = any(
            record.get("decision") == "pending" for record in self._filtered_records
        )
        if not self._config_manager:
            has_pending_filtered = False
            has_filtered_records = False
            has_selection = False
        current_record = self._current_record()
        trusted_sources = (
            list(self._config_manager.app_config.shared_library_trusted_source_apps or [])
            if self._config_manager
            else []
        )
        allowed_types = (
            list(
                self._config_manager.app_config.shared_library_auto_pull_allowed_package_types or []
            )
            if self._config_manager
            else []
        )
        trusted_signers = (
            list(self._config_manager.app_config.shared_library_trusted_signer_fingerprints or [])
            if self._config_manager
            else []
        )
        revoked_signers = (
            list(self._config_manager.app_config.shared_library_revoked_signer_fingerprints or [])
            if self._config_manager
            else []
        )
        can_trust_source = bool(
            self._config_manager
            and current_record
            and str(current_record.get("source_app") or "").strip()
            and str(current_record.get("source_app") or "").strip() not in trusted_sources
        )
        current_fingerprint = (
            str(current_record.get("signature_fingerprint") or "").strip().lower()
            if current_record
            else ""
        )
        can_trust_signer = bool(
            self._config_manager
            and current_record
            and current_fingerprint
            and current_fingerprint not in revoked_signers
            and current_fingerprint not in trusted_signers
        )
        can_revoke_signer = bool(
            self._config_manager
            and current_record
            and current_fingerprint
            and current_fingerprint not in revoked_signers
        )
        can_allow_package_type = bool(
            self._config_manager
            and current_record
            and str(current_record.get("package_type") or "").strip()
            and str(current_record.get("package_type") or "").strip() not in allowed_types
        )
        current_rotation_status = (
            str(current_record.get("rotation_status") or "").strip() if current_record else ""
        )
        current_rotation_exception = (
            self._config_manager.get_shared_library_rotation_exception_record(
                current_fingerprint,
                package_type=str(current_record.get("package_type") or "").strip() or None,
                rotation_status=current_rotation_status,
                include_expired=True,
            )
            if self._config_manager
            and current_record
            and current_fingerprint
            and current_rotation_status in {"due", "overdue"}
            else None
        )
        can_grant_rotation_exception = bool(
            self._config_manager
            and current_record
            and current_fingerprint
            and current_rotation_status in {"due", "overdue"}
            and (
                current_rotation_exception is None
                or str(current_rotation_exception.get("status") or "").strip() != "active"
            )
        )
        can_remove_rotation_exception = bool(
            self._config_manager
            and current_rotation_exception is not None
            and str(current_rotation_exception.get("status") or "").strip() == "active"
        )
        self.approve_selected_button.setEnabled(has_selection)
        self.reject_selected_button.setEnabled(has_selection)
        self.reset_selected_button.setEnabled(has_selection)
        self.approve_filtered_button.setEnabled(has_pending_filtered)
        self.reject_filtered_button.setEnabled(has_pending_filtered)
        self.trust_source_button.setEnabled(can_trust_source)
        self.trust_signer_button.setEnabled(can_trust_signer)
        self.revoke_signer_button.setEnabled(can_revoke_signer)
        self.allow_package_type_button.setEnabled(can_allow_package_type)
        self.grant_rotation_exception_button.setEnabled(can_grant_rotation_exception)
        self.remove_rotation_exception_button.setEnabled(can_remove_rotation_exception)
        self.refresh_button.setEnabled(self._config_manager is not None)
        self.sync_button.setEnabled(self._config_manager is not None and has_filtered_records)

    def _trust_current_source(self) -> None:
        """将当前记录的来源加入受信任列表。"""
        current_record = self._current_record()
        if not self._config_manager or not current_record:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择共享审批记录"))
            return
        source_app = str(current_record.get("source_app") or "").strip()
        if not source_app:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前记录没有可用的来源应用"))
            return
        trusted_sources = self._config_manager.trust_shared_library_source_app(source_app)
        self._update_action_states()
        self.policy_changed.emit(
            {
                "kind": "trusted_source",
                "value": source_app,
                "trusted_source_apps": trusted_sources,
            }
        )
        self._render_current_record(self.record_list.currentRow())
        self._set_status(self.tr(f"已信任来源 {source_app}，可重新同步共享仓库"))

    def _trust_current_signer(self) -> None:
        """将当前记录的签名者加入受信任列表。"""
        current_record = self._current_record()
        if not self._config_manager or not current_record:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择共享审批记录"))
            return
        fingerprint = str(current_record.get("signature_fingerprint") or "").strip().lower()
        if not fingerprint:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前记录没有可用的签名指纹"))
            return
        trusted_signers = self._config_manager.trust_shared_library_signer_fingerprint(fingerprint)
        self._update_action_states()
        self.policy_changed.emit(
            {
                "kind": "trusted_signer",
                "value": fingerprint,
                "signature_signer": str(current_record.get("signature_signer") or "").strip()
                or None,
                "signer_display_name": str(current_record.get("signer_display_name") or "").strip()
                or None,
                "trusted_signer_fingerprints": trusted_signers,
            }
        )
        self._render_current_record(self.record_list.currentRow())
        self._set_status(self.tr(f"已信任签名者 {fingerprint[:12]}，可重新同步共享仓库"))

    def _revoke_current_signer(self) -> None:
        """将当前记录的签名者加入撤销列表。"""
        current_record = self._current_record()
        if not self._config_manager or not current_record:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择共享审批记录"))
            return
        fingerprint = str(current_record.get("signature_fingerprint") or "").strip().lower()
        if not fingerprint:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前记录没有可用的签名指纹"))
            return
        revoked_signers = self._config_manager.revoke_shared_library_signer_fingerprint(
            fingerprint,
            reason=self.tr("审批面板手动撤销"),
        )
        revoked_record = (
            self._config_manager.get_shared_library_revoked_signer_record(fingerprint) or {}
        )
        self._update_action_states()
        self.policy_changed.emit(
            {
                "kind": "revoked_signer",
                "value": fingerprint,
                "signature_signer": str(current_record.get("signature_signer") or "").strip()
                or None,
                "signer_display_name": str(current_record.get("signer_display_name") or "").strip()
                or None,
                "revoked_reason": str(revoked_record.get("reason") or "").strip() or None,
                "revoked_at": str(revoked_record.get("revoked_at") or "").strip() or None,
                "revoked_signer_fingerprints": revoked_signers,
            }
        )
        self._render_current_record(self.record_list.currentRow())
        self._set_status(self.tr(f"已撤销签名者 {fingerprint[:12]}，后续同步将直接阻断"))

    def _allow_current_package_type(self) -> None:
        """允许当前记录的包类型自动拉取。"""
        current_record = self._current_record()
        if not self._config_manager or not current_record:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择共享审批记录"))
            return
        package_type = str(current_record.get("package_type") or "").strip()
        if not package_type:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前记录没有可用的包类型"))
            return
        allowed_types = self._config_manager.allow_shared_library_auto_pull_package_type(
            package_type
        )
        self._update_action_states()
        self.policy_changed.emit(
            {
                "kind": "allowed_package_type",
                "value": package_type,
                "allowed_package_types": allowed_types,
            }
        )
        self._render_current_record(self.record_list.currentRow())
        self._set_status(self.tr(f"已允许 {self._package_type_label(package_type)} 自动拉取"))

    def _grant_current_rotation_exception(self) -> None:
        """为当前记录授予轮换例外，并默认批准当前审批单。"""
        current_record = self._current_record()
        if not self._config_manager or not current_record:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择共享审批记录"))
            return
        fingerprint = str(current_record.get("signature_fingerprint") or "").strip().lower()
        rotation_status = str(current_record.get("rotation_status") or "").strip().lower()
        package_type = str(current_record.get("package_type") or "").strip()
        if not fingerprint or rotation_status not in {"due", "overdue"}:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前记录没有可用的轮换签名者上下文，无法授予例外授权"),
            )
            return

        default_days = 7 if rotation_status == "due" else 3
        days, accepted = QInputDialog.getInt(
            self,
            self.tr("轮换例外时长"),
            self.tr("请输入例外授权持续天数:"),
            default_days,
            1,
            365,
        )
        if not accepted:
            return
        note, note_ok = QInputDialog.getText(
            self,
            self.tr("轮换例外备注"),
            self.tr("请输入例外备注:"),
            text=self.tr("审批面板临时放行"),
        )
        if not note_ok:
            return
        expires_at = (
            (datetime.now(timezone.utc) + timedelta(days=int(days)))
            .replace(microsecond=0)
            .isoformat()
        )
        record = self._config_manager.upsert_shared_library_rotation_exception_record(
            fingerprint,
            package_types=[package_type] if package_type else [],
            rotation_states=[rotation_status],
            expires_at=expires_at,
            note=note.strip() or None,
            source_approval_id=str(current_record.get("id") or "").strip() or None,
            source_approval_name=str(current_record.get("name") or "").strip() or None,
        )
        decision_updated = False
        if str(current_record.get("decision") or "pending") != "approved":
            self._config_manager.upsert_shared_library_approval_decision(
                current_record,
                decision="approved",
                sync_dir=current_record.get("sync_dir"),
                reasons=[
                    str(reason)
                    for reason in current_record.get("reasons") or []
                    if str(reason).strip()
                ],
            )
            self.approvals_changed.emit(1, "approved")
            decision_updated = True
        self.reload_records()
        self.policy_changed.emit(
            {
                "kind": "rotation_exception_granted",
                "value": fingerprint,
                "signature_signer": str(current_record.get("signature_signer") or "").strip()
                or None,
                "signer_display_name": str(current_record.get("signer_display_name") or "").strip()
                or None,
                "package_type": package_type or None,
                "rotation_status": rotation_status,
                "expires_at": str(record.get("expires_at") or "").strip() or None,
                "note": str(record.get("note") or "").strip() or None,
            }
        )
        status_message = self.tr(f"已为签名者 {fingerprint[:12]} 授予轮换例外 {int(days)} 天")
        if decision_updated:
            status_message += self.tr("，并已自动批准当前审批记录")
        self._set_status(status_message)

    def _remove_current_rotation_exception(self) -> None:
        """移除当前记录对应的轮换例外。"""
        current_record = self._current_record()
        if not self._config_manager or not current_record:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择共享审批记录"))
            return
        fingerprint = str(current_record.get("signature_fingerprint") or "").strip().lower()
        rotation_status = str(current_record.get("rotation_status") or "").strip().lower()
        package_type = str(current_record.get("package_type") or "").strip()
        if not fingerprint or rotation_status not in {"due", "overdue"}:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前记录没有可用的轮换例外上下文"),
            )
            return
        removed = self._config_manager.remove_shared_library_rotation_exception_record(
            fingerprint,
            package_types=[package_type] if package_type else [],
            rotation_states=[rotation_status],
        )
        if not removed:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前没有可移除的生效轮换例外"))
            return
        self.reload_records()
        self.policy_changed.emit(
            {
                "kind": "rotation_exception_removed",
                "value": fingerprint,
                "signature_signer": str(current_record.get("signature_signer") or "").strip()
                or None,
                "signer_display_name": str(current_record.get("signer_display_name") or "").strip()
                or None,
                "package_type": package_type or None,
                "rotation_status": rotation_status,
            }
        )
        self._set_status(self.tr(f"已移除签名者 {fingerprint[:12]} 的轮换例外授权"))

    def _apply_decision_to_selected(self, decision: str) -> None:
        selected_records = self._selected_records()
        if not selected_records:
            QMessageBox.information(self, self.tr("提示"), self.tr("请先选择共享审批记录"))
            return
        self._apply_decision(selected_records, decision)

    def _apply_decision_to_filtered(self, decision: str) -> None:
        target_records = [
            record for record in self._filtered_records if record.get("decision") == "pending"
        ]
        if not target_records:
            QMessageBox.information(self, self.tr("提示"), self.tr("当前筛选结果中没有待审记录"))
            return
        self._apply_decision(target_records, decision)

    def _apply_decision(self, records: list[dict[str, Any]], decision: str) -> None:
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        updated_count = 0
        for record in records:
            self._config_manager.upsert_shared_library_approval_decision(
                record,
                decision=decision,
                sync_dir=record.get("sync_dir"),
                reasons=[
                    str(reason) for reason in record.get("reasons") or [] if str(reason).strip()
                ],
            )
            updated_count += 1

        decision_label = self._decision_label(decision)
        self.reload_records()
        self.approvals_changed.emit(updated_count, decision)
        self._set_status(self.tr(f"已更新 {updated_count} 条共享审批记录: {decision_label}"))

    def _sync_approved_records(self) -> None:
        """同步当前已放行的共享记录。"""
        if not self._config_manager:
            QMessageBox.warning(self, self.tr("错误"), self.tr("配置管理器未初始化"))
            return

        app_config = self._config_manager.app_config
        sync_dir = str(app_config.shared_library_sync_dir or "").strip()
        if not sync_dir:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前未配置共享仓库目录，无法同步已放行共享包"),
            )
            return

        try:
            result = self._config_manager.pull_shared_library_from_directory(
                sync_dir,
                trusted_source_apps=app_config.shared_library_trusted_source_apps,
                trusted_signer_fingerprints=app_config.shared_library_trusted_signer_fingerprints,
                revoked_signer_fingerprints=app_config.shared_library_revoked_signer_fingerprints,
                allowed_package_types=app_config.shared_library_auto_pull_allowed_package_types,
                queue_pending_approvals=True,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("同步失败"), str(exc))
            return

        if int(result.get("index_version") or 0):
            self._config_manager.update_shared_library_cached_index_version(
                sync_dir,
                int(result.get("index_version") or 0),
            )
        self.reload_records()
        self.sync_completed.emit(result)
        self._set_status(
            self.tr(
                f"已同步共享仓库: 导入 {int(result.get('imported_count') or 0)} 项，"
                f"待审 {int(result.get('pending_approval_count') or 0)} 项，"
                f"完整性异常 {int(result.get('integrity_blocked_count') or 0)} 项"
            )
            + (
                self.tr(f" · 已撤销签名者 {int(result.get('revoked_signer_count') or 0)} 项")
                if int(result.get("revoked_signer_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 未受信任签名者 {int(result.get('untrusted_signer_count') or 0)} 项")
                if int(result.get("untrusted_signer_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 签名异常 {int(result.get('signature_blocked_count') or 0)} 项")
                if int(result.get("signature_blocked_count") or 0)
                else ""
            )
            + (
                self.tr(f" · 未签名 {int(result.get('signature_unverified_count') or 0)} 项")
                if int(result.get("signature_unverified_count") or 0)
                else ""
            )
        )
