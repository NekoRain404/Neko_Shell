#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享中心完整性异常对话框。

用于查看共享仓库中被校验规则拦截或缺少校验信息的共享包。
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
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
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from neko_shell.utils import ConfigManager


class SharedLibraryIntegrityDialog(QDialog):
    """共享中心校验异常查看对话框。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_manager: Optional[ConfigManager] = None
        self._sync_dir = ""
        self._trusted_source_apps: list[str] = []
        self._trusted_signer_fingerprints: list[str] = []
        self._revoked_signer_fingerprints: list[str] = []
        self._allowed_package_types: list[str] = []
        self._rotation_due_policy = "warn"
        self._rotation_overdue_policy = "approval"
        self._last_result: dict[str, Any] = {}
        self._records: list[dict[str, Any]] = []
        self._filtered_records: list[dict[str, Any]] = []
        self.summary_label: QLabel
        self.status_label: QLabel
        self.record_list: QListWidget
        self.detail_browser: QTextBrowser
        self.status_filter_combo: QComboBox
        self.source_filter_combo: QComboBox
        self.package_type_filter_combo: QComboBox
        self.search_edit: QLineEdit
        self.refresh_button: QPushButton
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(self.tr("共享校验异常"))
        self.resize(1020, 660)
        self.setMinimumSize(900, 580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(self.tr("共享包校验检查"), self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        description = QLabel(
            self.tr(
                "这里展示共享仓库中因摘要异常、签名异常、文件缺失、文件不可读而被拦截的共享包，以及缺少摘要或签名的未校验记录。"
            ),
            self,
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: palette(mid);")
        layout.addWidget(description)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel(self.tr("状态"), self))
        self.status_filter_combo = QComboBox(self)
        self.status_filter_combo.addItem(self.tr("全部"), "all")
        self.status_filter_combo.addItem(self.tr("摘要不匹配"), "invalid")
        self.status_filter_combo.addItem(self.tr("文件缺失"), "missing_file")
        self.status_filter_combo.addItem(self.tr("文件不可读"), "unreadable")
        self.status_filter_combo.addItem(self.tr("未校验摘要"), "missing")
        self.status_filter_combo.addItem(self.tr("签名异常"), "invalid_signature")
        self.status_filter_combo.addItem(self.tr("已撤销签名者"), "revoked_signature")
        self.status_filter_combo.addItem(self.tr("未签名"), "missing_signature")
        self.status_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.status_filter_combo)

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
        self.search_edit.setPlaceholderText(self.tr("名称 / 来源 / 状态 / 摘要"))
        self.search_edit.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_edit, 1)

        self.refresh_button = QPushButton(self.tr("刷新"), self)
        self.refresh_button.clicked.connect(self.reload_records)
        filter_row.addWidget(self.refresh_button)
        layout.addLayout(filter_row)

        self.summary_label = QLabel(self.tr("当前没有共享校验异常记录"), self)
        self.summary_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.summary_label)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        self.record_list = QListWidget(splitter)
        self.record_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.record_list.currentRowChanged.connect(self._render_current_record)
        self.record_list.setMinimumWidth(340)
        splitter.addWidget(self.record_list)

        right_panel = QWidget(splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.detail_browser = QTextBrowser(right_panel)
        self.detail_browser.setOpenExternalLinks(False)
        self.detail_browser.setReadOnly(True)
        right_layout.addWidget(self.detail_browser, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([380, 640])

        self.status_label = QLabel(self.tr("未绑定配置管理器"), self)
        self.status_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.status_label)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._rebuild_filter_options([])

    @staticmethod
    def _package_type_label(package_type: str) -> str:
        if package_type == "workspace_templates":
            return "工作区模板"
        if package_type == "connection_filter_presets":
            return "筛选预设"
        return package_type or "未知类型"

    @staticmethod
    def _integrity_status_label(status: str) -> str:
        if status == "invalid":
            return "摘要不匹配"
        if status == "missing_file":
            return "文件缺失"
        if status == "unreadable":
            return "文件不可读"
        if status == "missing":
            return "未校验摘要"
        if status == "verified":
            return "已校验"
        return status or "未知状态"

    @staticmethod
    def _verification_issue_label(issue_code: str, integrity_status: str) -> str:
        if issue_code == "invalid_signature":
            return "签名异常"
        if issue_code == "revoked_signature":
            return "已撤销签名者"
        if issue_code == "rotation_due_signer":
            return "签名者轮换临近截止"
        if issue_code == "rotation_overdue_signer":
            return "签名者轮换已超期"
        if issue_code == "missing_signature":
            return "未签名"
        if issue_code == "unsupported_signature":
            return "签名不可校验"
        if issue_code == "missing_content_hash":
            return "未校验摘要"
        return SharedLibraryIntegrityDialog._integrity_status_label(integrity_status)

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

    def set_context(
        self,
        manager: ConfigManager,
        sync_dir: str,
        *,
        trusted_source_apps: Optional[list[str]] = None,
        trusted_signer_fingerprints: Optional[list[str]] = None,
        revoked_signer_fingerprints: Optional[list[str]] = None,
        allowed_package_types: Optional[list[str]] = None,
        rotation_due_policy: Optional[str] = None,
        rotation_overdue_policy: Optional[str] = None,
    ) -> None:
        """绑定上下文并加载完整性状态。"""
        self._config_manager = manager
        self._sync_dir = str(sync_dir or "").strip()
        self._trusted_source_apps = [
            str(item) for item in trusted_source_apps or [] if str(item).strip()
        ]
        self._trusted_signer_fingerprints = [
            str(item) for item in trusted_signer_fingerprints or [] if str(item).strip()
        ]
        self._revoked_signer_fingerprints = [
            str(item) for item in revoked_signer_fingerprints or [] if str(item).strip()
        ]
        self._allowed_package_types = [
            str(item) for item in allowed_package_types or [] if str(item).strip()
        ]
        self._rotation_due_policy = str(rotation_due_policy or "warn").strip() or "warn"
        self._rotation_overdue_policy = (
            str(rotation_overdue_policy or "approval").strip() or "approval"
        )
        self.reload_records()

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def reload_records(self) -> None:
        """重新加载共享完整性记录。"""
        if not self._config_manager:
            self._last_result = {}
            self._records = []
            self._filtered_records = []
            self.record_list.clear()
            self.detail_browser.clear()
            self.summary_label.setText(self.tr("当前没有共享校验异常记录"))
            self._set_status(self.tr("未绑定配置管理器"))
            self._rebuild_filter_options([])
            return

        if not self._sync_dir:
            self._last_result = {}
            self._records = []
            self._filtered_records = []
            self.record_list.clear()
            self.detail_browser.clear()
            self.summary_label.setText(self.tr("当前没有共享校验异常记录"))
            self._set_status(self.tr("未设置共享仓库目录"))
            self._rebuild_filter_options([])
            return

        try:
            result = self._config_manager.inspect_shared_library_pull_integrity(
                self._sync_dir,
                trusted_source_apps=self._trusted_source_apps,
                trusted_signer_fingerprints=self._trusted_signer_fingerprints,
                revoked_signer_fingerprints=self._revoked_signer_fingerprints,
                allowed_package_types=self._allowed_package_types,
                rotation_due_policy=self._rotation_due_policy,
                rotation_overdue_policy=self._rotation_overdue_policy,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("加载失败"), str(exc))
            self._last_result = {}
            self._records = []
            self._filtered_records = []
            self.record_list.clear()
            self.detail_browser.clear()
            self.summary_label.setText(self.tr("当前没有共享校验异常记录"))
            self._set_status(self.tr("加载共享校验记录失败"))
            self._rebuild_filter_options([])
            return

        self._last_result = dict(result)
        blocked_records = [
            {**dict(record), "_issue_bucket": "blocked"}
            for record in result.get("blocked_records") or []
        ]
        unverified_records = [
            {**dict(record), "_issue_bucket": "unverified"}
            for record in result.get("unverified_records") or []
        ]
        self._records = sorted(
            blocked_records + unverified_records,
            key=lambda record: (
                0 if str(record.get("_issue_bucket") or "") == "blocked" else 1,
                self._integrity_status_label(str(record.get("integrity_status") or "")),
                str(record.get("source_app") or "").casefold(),
                str(record.get("name") or "").casefold(),
            ),
        )
        self._rebuild_filter_options(self._records)
        self._apply_filters()
        self._set_status(
            self.tr(
                f"已加载 {len(self._records)} 条共享校验记录 · "
                f"异常 {int(result.get('blocked_count') or 0)} 项 · "
                f"未校验 {int(result.get('unverified_count') or 0)} 项 · "
                f"撤销命中 {int(result.get('revoked_signer_count') or 0)} 项"
            )
        )

    def _rebuild_filter_options(self, records: list[dict[str, Any]]) -> None:
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

    def _apply_filters(self, *_args: Any) -> None:
        status_filter = str(self.status_filter_combo.currentData() or "all")
        source_filter = str(self.source_filter_combo.currentData() or "all")
        package_type_filter = str(self.package_type_filter_combo.currentData() or "all")
        query = self.search_edit.text().strip().casefold()

        filtered: list[dict[str, Any]] = []
        for record in self._records:
            integrity_status = str(record.get("integrity_status") or "")
            issue_code = str(record.get("verification_issue_code") or "").strip()
            source_app = str(record.get("source_app") or "").strip()
            package_type = str(record.get("package_type") or "").strip()
            haystack = " ".join(
                [
                    str(record.get("name") or ""),
                    source_app,
                    package_type,
                    self._verification_issue_label(issue_code, integrity_status),
                    str(record.get("declared_content_hash") or ""),
                    str(record.get("actual_content_hash") or ""),
                    str(record.get("signature_signer") or ""),
                    str(record.get("signer_display_name") or ""),
                    str(record.get("signer_note") or ""),
                    str(record.get("signature_fingerprint") or ""),
                    str(record.get("policy_expires_at") or ""),
                    str(record.get("policy_status") or ""),
                    str(record.get("rotation_due_at") or ""),
                    str(record.get("rotation_status") or ""),
                    str(record.get("revoked_reason") or ""),
                    str(record.get("revoked_note") or ""),
                ]
            ).casefold()
            if (
                status_filter != "all"
                and issue_code != status_filter
                and integrity_status != status_filter
            ):
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
        for record in filtered:
            name = str(record.get("name") or "未命名共享包")
            issue_label = self._verification_issue_label(
                str(record.get("verification_issue_code") or ""),
                str(record.get("integrity_status") or ""),
            )
            package_type = self._package_type_label(str(record.get("package_type") or ""))
            source_app = str(record.get("source_app") or "Neko_Shell")
            item = QListWidgetItem(
                self.tr(f"{issue_label} · {name} · {package_type} · {source_app}"),
                self.record_list,
            )
            item.setToolTip(self._record_tooltip(record))
            item.setData(
                Qt.ItemDataRole.UserRole,
                str(record.get("id") or record.get("file_path") or name),
            )

        if self.record_list.count():
            self.record_list.setCurrentRow(0)
        else:
            self.detail_browser.setPlainText(self.tr("当前筛选条件下没有共享校验记录"))
        self.record_list.blockSignals(False)
        self._update_summary()
        self._render_current_record(self.record_list.currentRow())

    def _update_summary(self) -> None:
        blocked_count = sum(
            1
            for record in self._filtered_records
            if str(record.get("_issue_bucket") or "") == "blocked"
        )
        unverified_count = sum(
            1
            for record in self._filtered_records
            if str(record.get("_issue_bucket") or "") == "unverified"
        )
        revoked_count = sum(
            1
            for record in self._filtered_records
            if str(record.get("verification_issue_code") or "") == "revoked_signature"
        )
        self.summary_label.setText(
            self.tr(
                f"当前筛选结果 {len(self._filtered_records)} 项 · "
                f"校验异常 {blocked_count} 项 · "
                f"待补充校验 {unverified_count} 项 · "
                f"撤销签名者 {revoked_count} 项"
            )
        )

    def _record_tooltip(self, record: dict[str, Any]) -> str:
        return self.tr(
            f"{record.get('name', '未命名共享包')} · "
            f"{self._package_type_label(str(record.get('package_type') or ''))} · "
            f"来源 {record.get('source_app', 'Neko_Shell')} · "
            f"状态 {self._verification_issue_label(str(record.get('verification_issue_code') or ''), str(record.get('integrity_status') or ''))}"
        )

    def _render_current_record(self, row: int) -> None:
        if row < 0 or row >= len(self._filtered_records):
            if not self._filtered_records:
                self.detail_browser.setPlainText(self.tr("当前筛选条件下没有共享校验记录"))
            else:
                self.detail_browser.setPlainText(self.tr("请选择一条共享校验记录"))
            return

        record = self._filtered_records[row]
        lines = [
            self.tr(f"名称: {record.get('name', '未命名共享包')}"),
            self.tr(
                f"状态: {self._verification_issue_label(str(record.get('verification_issue_code') or ''), str(record.get('integrity_status') or ''))}"
            ),
            self.tr(f"包类型: {self._package_type_label(str(record.get('package_type') or ''))}"),
            self.tr(f"来源应用: {record.get('source_app', 'Neko_Shell')}"),
            self.tr(f"共享版本: v{int(record.get('package_version') or 1)}"),
            self.tr(
                f"处理建议: {'阻止导入' if str(record.get('_issue_bucket') or '') == 'blocked' else '允许查看但建议补齐摘要'}"
            ),
        ]
        sync_dir = self._sync_dir.strip()
        if sync_dir:
            lines.append(self.tr(f"来源仓库: {sync_dir}"))
        relative_path = str(record.get("relative_path") or "").strip()
        if relative_path:
            lines.append(self.tr(f"相对路径: {relative_path}"))
        file_path = str(record.get("file_path") or "").strip()
        if file_path:
            lines.append(self.tr(f"文件路径: {file_path}"))
        exported_at = str(record.get("exported_at") or "").strip()
        if exported_at:
            lines.append(self.tr(f"导出时间: {exported_at}"))
        declared_hash = str(record.get("declared_content_hash") or "").strip()
        if declared_hash:
            lines.append(self.tr(f"声明摘要: {declared_hash}"))
        else:
            lines.append(self.tr("声明摘要: 缺失"))
        actual_hash = str(record.get("actual_content_hash") or "").strip()
        if actual_hash:
            lines.append(self.tr(f"实际摘要: {actual_hash}"))
        elif str(record.get("integrity_status") or "") != "missing":
            lines.append(self.tr("实际摘要: 无法读取"))
        signature_signer = str(record.get("signature_signer") or "").strip()
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
        signature_fingerprint = str(record.get("signature_fingerprint") or "").strip()
        if signature_fingerprint:
            lines.append(self.tr(f"签名指纹: {signature_fingerprint}"))
            if signature_fingerprint in self._revoked_signer_fingerprints:
                lines.append(self.tr("签名者策略: 已撤销"))
            elif str(record.get("policy_status") or "") == "expired":
                lines.append(self.tr("签名者策略: 策略已过期"))
            elif signature_fingerprint in self._trusted_signer_fingerprints:
                lines.append(self.tr("签名者策略: 已受信任"))
            else:
                lines.append(self.tr("签名者策略: 未受信任"))
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
        signature_algorithm = str(record.get("signature_algorithm") or "").strip()
        if signature_algorithm:
            lines.append(self.tr(f"签名算法: {signature_algorithm}"))
        revoked_reason = str(record.get("revoked_reason") or "").strip()
        if revoked_reason:
            lines.append(self.tr(f"撤销原因: {revoked_reason}"))
        revoked_at = str(record.get("revoked_at") or "").strip()
        if revoked_at:
            lines.append(self.tr(f"撤销时间: {revoked_at}"))
        revoked_note = str(record.get("revoked_note") or "").strip()
        if revoked_note:
            lines.append(self.tr(f"撤销备注: {revoked_note}"))
        description = str(record.get("description") or "").strip()
        if description:
            lines.append(self.tr(f"说明: {description}"))
        sample_names = [
            str(item).strip() for item in record.get("sample_names") or [] if str(item).strip()
        ]
        if sample_names:
            lines.append(self.tr(f"样例项: {', '.join(sample_names[:8])}"))
        self.detail_browser.setPlainText("\n".join(lines))
