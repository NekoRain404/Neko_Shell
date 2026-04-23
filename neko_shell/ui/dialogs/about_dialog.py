#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关于对话框。"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from neko_shell.release import (
    APP_NAME,
    APP_AUTHOR,
    APP_SUMMARY,
    ISSUES_URL,
    LICENSE_NAME,
    REPOSITORY_URL,
    build_about_overview_html,
    build_credits_html,
    build_feedback_overview_html,
    build_issue_feedback_template,
    build_license_overview_html,
    build_preview_acceptance_checklist,
    collect_runtime_diagnostic_report,
    collect_runtime_summary,
    export_preview_acceptance_checklist,
    export_issue_feedback_template,
    export_runtime_diagnostic_report,
    export_support_bundle,
    get_default_acceptance_checklist_export_path,
    format_version_display,
    get_default_diagnostic_export_path,
    get_default_issue_template_export_path,
    get_default_support_bundle_export_path,
)
from neko_shell.utils.paths import get_runtime_root


class AboutDialog(QDialog):
    """Neko_Shell 关于对话框。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tabs: QTabWidget
        self.about_browser: QTextBrowser
        self.runtime_browser: QTextBrowser
        self.license_browser: QTextBrowser
        self.credits_browser: QTextBrowser
        self.runtime_status_label: QLabel
        self._runtime_summary_text = ""
        self._setup_ui()

    @staticmethod
    def _resolve_runtime_context() -> tuple[Optional[Path], Optional[object]]:
        """解析当前应用上下文。"""
        app = QApplication.instance()
        if app is None:
            return None, None
        config_manager = getattr(app, "_config_manager", None)
        config_dir = (
            getattr(config_manager, "config_dir", None) if config_manager is not None else None
        )
        app_config = None
        if config_manager is not None:
            try:
                app_config = config_manager.app_config
            except Exception:
                app_config = None
        return (Path(config_dir) if config_dir is not None else None), app_config

    def _refresh_runtime_summary(self) -> None:
        """刷新运行摘要内容。"""
        config_dir, app_config = self._resolve_runtime_context()
        report = collect_runtime_diagnostic_report(config_dir=config_dir, app_config=app_config)
        self._runtime_summary_text = report.to_text()
        self.runtime_browser.setHtml(report.to_html())
        self.runtime_status_label.setText(
            self.tr("运行自检通过") if report.ok else self.tr("运行自检存在问题")
        )

    def _copy_runtime_summary(self) -> None:
        """复制运行摘要。"""
        if not self._runtime_summary_text:
            self._refresh_runtime_summary()
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._runtime_summary_text)
            self.runtime_status_label.setText(self.tr("诊断信息已复制到剪贴板"))

    def _copy_issue_template(self) -> None:
        """复制问题反馈模板。"""
        config_dir, app_config = self._resolve_runtime_context()
        report = collect_runtime_diagnostic_report(config_dir=config_dir, app_config=app_config)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(build_issue_feedback_template(report))
            self.runtime_status_label.setText(self.tr("问题反馈模板已复制到剪贴板"))

    def _copy_acceptance_checklist(self) -> None:
        """复制预览版验收清单。"""
        config_dir, app_config = self._resolve_runtime_context()
        report = collect_runtime_diagnostic_report(config_dir=config_dir, app_config=app_config)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(build_preview_acceptance_checklist(report))
            self.runtime_status_label.setText(self.tr("验收清单已复制到剪贴板"))

    def _export_issue_template(self) -> None:
        """导出问题反馈模板。"""
        config_dir, app_config = self._resolve_runtime_context()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出问题反馈模板"),
            str(get_default_issue_template_export_path(datetime.now())),
            self.tr("Markdown 文件 (*.md);;所有文件 (*)"),
        )
        if not file_path:
            return
        try:
            export_issue_feedback_template(
                Path(file_path),
                config_dir=config_dir,
                app_config=app_config,
            )
            self.runtime_status_label.setText(self.tr(f"问题反馈模板已导出: {file_path}"))
        except OSError as exc:
            QMessageBox.warning(self, self.tr("导出失败"), str(exc))
            self.runtime_status_label.setText(self.tr(f"导出失败: {exc}"))

    def _export_acceptance_checklist(self) -> None:
        """导出预览版验收清单。"""
        config_dir, app_config = self._resolve_runtime_context()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出预览版验收清单"),
            str(get_default_acceptance_checklist_export_path(datetime.now())),
            self.tr("Markdown 文件 (*.md);;所有文件 (*)"),
        )
        if not file_path:
            return
        try:
            export_preview_acceptance_checklist(
                Path(file_path),
                config_dir=config_dir,
                app_config=app_config,
            )
            self.runtime_status_label.setText(self.tr(f"验收清单已导出: {file_path}"))
        except OSError as exc:
            QMessageBox.warning(self, self.tr("导出失败"), str(exc))
            self.runtime_status_label.setText(self.tr(f"导出失败: {exc}"))

    def _export_support_bundle(self) -> None:
        """导出预览版支持包。"""
        config_dir, app_config = self._resolve_runtime_context()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出预览版支持包"),
            str(get_default_support_bundle_export_path(datetime.now())),
            self.tr("ZIP 文件 (*.zip);;所有文件 (*)"),
        )
        if not file_path:
            return
        try:
            export_support_bundle(
                Path(file_path),
                config_dir=config_dir,
                app_config=app_config,
            )
            self.runtime_status_label.setText(self.tr(f"预览版支持包已导出: {file_path}"))
        except OSError as exc:
            QMessageBox.warning(self, self.tr("导出失败"), str(exc))
            self.runtime_status_label.setText(self.tr(f"导出失败: {exc}"))

    def _export_runtime_summary(self) -> None:
        """导出诊断信息。"""
        config_dir, app_config = self._resolve_runtime_context()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出诊断信息"),
            str(get_default_diagnostic_export_path(datetime.now())),
            self.tr("文本文件 (*.txt);;所有文件 (*)"),
        )
        if file_path:
            try:
                export_runtime_diagnostic_report(
                    Path(file_path),
                    config_dir=config_dir,
                    app_config=app_config,
                )
                self.runtime_status_label.setText(self.tr(f"诊断信息已导出: {file_path}"))
            except OSError as exc:
                QMessageBox.warning(self, self.tr("导出失败"), str(exc))
                self.runtime_status_label.setText(self.tr(f"导出失败: {exc}"))

    def _open_runtime_root(self) -> None:
        """打开运行目录。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_runtime_root())))

    def _open_logs_dir(self) -> None:
        """打开日志目录。"""
        config_dir, app_config = self._resolve_runtime_context()
        target = Path(
            collect_runtime_summary(
                config_dir=config_dir,
                app_config=app_config,
            ).log_dir
        )
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(target if target.exists() else target.parent))
        )

    def _open_config_dir(self) -> None:
        """打开配置目录。"""
        config_dir, app_config = self._resolve_runtime_context()
        target = config_dir or Path(
            collect_runtime_summary(
                config_dir=config_dir,
                app_config=app_config,
            ).config_dir
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_issues_page(self) -> None:
        """打开问题反馈页面。"""
        QDesktopServices.openUrl(QUrl(ISSUES_URL))

    def _setup_ui(self) -> None:
        """构建界面。"""
        self.setWindowTitle(self.tr(f"关于 {APP_NAME}"))
        self.setMinimumSize(640, 520)
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QFrame(self)
        header.setObjectName("aboutHeader")
        header.setStyleSheet("""
            QFrame#aboutHeader {
                border: 1px solid palette(mid);
                border-radius: 12px;
                background: palette(base);
            }
            """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 18, 18, 18)
        header_layout.setSpacing(16)

        badge = QLabel("N", header)
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(72, 72)
        badge.setStyleSheet("""
            QLabel {
                font-size: 30px;
                font-weight: 700;
                border-radius: 16px;
                color: palette(base);
                background-color: #2f6feb;
            }
            """)
        header_layout.addWidget(badge)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)

        name_label = QLabel(APP_NAME, header)
        name_label.setStyleSheet("font-size: 24px; font-weight: 700;")
        title_layout.addWidget(name_label)

        summary_label = QLabel(
            self.tr(APP_SUMMARY),
            header,
        )
        summary_label.setWordWrap(True)
        summary_label.setStyleSheet("color: palette(mid);")
        title_layout.addWidget(summary_label)

        meta_label = QLabel(
            self.tr("版本: {version}    作者: {author}").format(
                version=format_version_display(),
                author=APP_AUTHOR,
            ),
            header,
        )
        meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title_layout.addWidget(meta_label)

        legal_label = QLabel(
            self.tr(f"许可证: {LICENSE_NAME}    无担保发布"),
            header,
        )
        legal_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title_layout.addWidget(legal_label)

        header_layout.addLayout(title_layout, 1)
        layout.addWidget(header)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        about_page = QWidget(self)
        about_layout = QVBoxLayout(about_page)
        about_layout.setContentsMargins(0, 0, 0, 0)
        about_layout.setSpacing(8)

        self.about_browser = self._create_browser(
            build_about_overview_html() + build_feedback_overview_html()
        )
        about_layout.addWidget(self.about_browser)

        runtime_controls = QVBoxLayout()
        runtime_controls.setSpacing(8)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(8)
        copy_button = QPushButton(self.tr("复制诊断信息"), about_page)
        copy_button.clicked.connect(self._copy_runtime_summary)
        primary_row.addWidget(copy_button)

        acceptance_button = QPushButton(self.tr("复制验收清单"), about_page)
        acceptance_button.clicked.connect(self._copy_acceptance_checklist)
        primary_row.addWidget(acceptance_button)

        issue_template_button = QPushButton(self.tr("复制反馈模板"), about_page)
        issue_template_button.clicked.connect(self._copy_issue_template)
        primary_row.addWidget(issue_template_button)

        refresh_button = QPushButton(self.tr("刷新运行摘要"), about_page)
        refresh_button.clicked.connect(self._refresh_runtime_summary)
        primary_row.addWidget(refresh_button)
        primary_row.addStretch(1)
        runtime_controls.addLayout(primary_row)

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        export_button = QPushButton(self.tr("导出诊断报告"), about_page)
        export_button.clicked.connect(self._export_runtime_summary)
        export_row.addWidget(export_button)

        export_acceptance_button = QPushButton(self.tr("导出验收清单"), about_page)
        export_acceptance_button.clicked.connect(self._export_acceptance_checklist)
        export_row.addWidget(export_acceptance_button)

        export_issue_template_button = QPushButton(self.tr("导出反馈模板"), about_page)
        export_issue_template_button.clicked.connect(self._export_issue_template)
        export_row.addWidget(export_issue_template_button)

        export_support_bundle_button = QPushButton(self.tr("导出支持包"), about_page)
        export_support_bundle_button.clicked.connect(self._export_support_bundle)
        export_row.addWidget(export_support_bundle_button)

        export_row.addStretch(1)
        runtime_controls.addLayout(export_row)

        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(8)
        open_runtime_button = QPushButton(self.tr("打开运行目录"), about_page)
        open_runtime_button.clicked.connect(self._open_runtime_root)
        secondary_row.addWidget(open_runtime_button)

        open_config_button = QPushButton(self.tr("打开配置目录"), about_page)
        open_config_button.clicked.connect(self._open_config_dir)
        secondary_row.addWidget(open_config_button)

        open_logs_button = QPushButton(self.tr("打开日志目录"), about_page)
        open_logs_button.clicked.connect(self._open_logs_dir)
        secondary_row.addWidget(open_logs_button)

        issues_button = QPushButton(self.tr("问题反馈"), about_page)
        issues_button.clicked.connect(self._open_issues_page)
        secondary_row.addWidget(issues_button)
        secondary_row.addStretch(1)
        runtime_controls.addLayout(secondary_row)

        self.runtime_status_label = QLabel(
            self.tr("反馈预览版问题前，建议先复制反馈模板并附带诊断报告"),
            about_page,
        )
        self.runtime_status_label.setStyleSheet("color: palette(mid);")
        runtime_controls.addWidget(self.runtime_status_label)
        about_layout.addLayout(runtime_controls)

        self.runtime_browser = self._create_browser("")
        about_layout.addWidget(self.runtime_browser, 1)
        self._refresh_runtime_summary()
        self.tabs.addTab(about_page, self.tr("关于"))

        self.license_browser = self._create_browser(build_license_overview_html())
        self.tabs.addTab(self.license_browser, self.tr("许可证"))

        self.credits_browser = self._create_browser(build_credits_html())
        self.tabs.addTab(self.credits_browser, self.tr("致谢"))

        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(12)

        repo_label = QLabel(
            f'<a href="{REPOSITORY_URL}">github.com/neko-shell/Neko_Shell</a>',
            self,
        )
        repo_label.setOpenExternalLinks(True)
        repo_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        footer_layout.addWidget(repo_label)
        footer_layout.addStretch(1)

        button_box = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        footer_layout.addWidget(button_box)

        layout.addLayout(footer_layout)

    def _create_browser(self, html: str) -> QTextBrowser:
        """创建只读富文本浏览器。"""
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setReadOnly(True)
        browser.setHtml(html)
        return browser
