#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
帮助对话框。

使用选项卡承载用户手册、关于与许可证信息。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from neko_shell.release import (
    APP_NAME,
    ISSUES_URL,
    REPOSITORY_URL,
    build_about_overview_html,
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
    get_default_diagnostic_export_path,
    get_default_issue_template_export_path,
    get_default_support_bundle_export_path,
)
from neko_shell.utils.paths import get_runtime_root


class HelpDialog(QDialog):
    """Neko_Shell 帮助对话框。"""

    TAB_GUIDE = 0
    TAB_ABOUT = 1
    TAB_LICENSE = 2

    def __init__(self, parent: Optional[QWidget] = None, initial_tab: int = TAB_GUIDE):
        super().__init__(parent)
        self.tabs: QTabWidget
        self.guide_toc_list: QListWidget
        self.guide_search_edit: QLineEdit
        self.guide_search_status: QLabel
        self.guide_meta_label: QLabel
        self.guide_browser: QTextBrowser
        self.about_browser: QTextBrowser
        self.about_runtime_browser: QTextBrowser
        self.about_runtime_status: QLabel
        self.license_browser: QTextBrowser
        self._about_runtime_summary_text = ""
        self._setup_ui(initial_tab)

    @staticmethod
    def _user_guide_path() -> Path:
        """返回用户手册路径。"""
        return get_runtime_root() / "docs" / "USER_GUIDE.md"

    def _load_user_guide_markdown(self) -> str:
        """读取用户手册 Markdown。"""
        guide_path = self._user_guide_path()
        if guide_path.exists():
            try:
                return guide_path.read_text(encoding="utf-8")
            except OSError as exc:
                return self.tr(f"# 使用手册读取失败\n\n无法读取 `{guide_path}`。\n\n错误: {exc}")
        return self.tr("# 使用手册不可用\n\n未找到 `docs/USER_GUIDE.md`。")

    @staticmethod
    def _extract_guide_headings(markdown_text: str) -> list[tuple[int, str]]:
        """从 Markdown 中提取目录标题。"""
        headings: list[tuple[int, str]] = []
        for raw_line in markdown_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("#"):
                continue
            level = len(line) - len(line.lstrip("#"))
            if level < 2 or level > 3:
                continue
            title = line[level:].strip()
            if title:
                headings.append((level, title))
        return headings

    def _guide_meta_text(self, guide_path: Path) -> str:
        """返回当前使用手册的元信息文案。"""
        if guide_path.exists():
            modified = datetime.fromtimestamp(guide_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            return self.tr(f"文档来源: {guide_path}    最后更新: {modified}")
        return self.tr(f"文档来源: {guide_path}    当前状态: 未找到，将显示内置提示")

    def _populate_guide_toc(self, markdown_text: str) -> None:
        """根据 Markdown 内容刷新目录。"""
        self.guide_toc_list.clear()
        for level, title in self._extract_guide_headings(markdown_text):
            item = QListWidgetItem(f"{'  ' if level == 3 else ''}{title}", self.guide_toc_list)
            item.setData(Qt.UserRole, title)

    def _reload_user_guide(self) -> None:
        """重新加载使用手册。"""
        guide_path = self._user_guide_path()
        markdown_text = self._load_user_guide_markdown()
        self.guide_browser.setMarkdown(markdown_text)
        self._populate_guide_toc(markdown_text)
        self.guide_meta_label.setText(self._guide_meta_text(guide_path))
        self.guide_search_status.setText(self.tr("已刷新使用手册"))

    def _open_user_guide_location(self) -> None:
        """打开使用手册所在目录。"""
        guide_path = self._user_guide_path()
        target = guide_path if guide_path.exists() else guide_path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    @staticmethod
    def _resolve_runtime_context() -> tuple[Optional[Path], Optional[object]]:
        """解析当前应用的配置目录与应用配置。"""
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

    def _collect_runtime_summary(self):
        """构造当前运行摘要。"""
        config_dir, app_config = self._resolve_runtime_context()
        return collect_runtime_summary(
            config_dir=config_dir,
            guide_path=self._user_guide_path(),
            app_config=app_config,
        )

    def _collect_runtime_report(self):
        """构造当前运行诊断报告。"""
        config_dir, app_config = self._resolve_runtime_context()
        return collect_runtime_diagnostic_report(
            config_dir=config_dir,
            guide_path=self._user_guide_path(),
            app_config=app_config,
        )

    def _refresh_about_runtime_summary(self) -> None:
        """刷新关于页的运行摘要。"""
        report = self._collect_runtime_report()
        self._about_runtime_summary_text = report.to_text()
        self.about_runtime_browser.setHtml(report.to_html())
        status_text = self.tr("运行自检通过") if report.ok else self.tr("运行自检存在问题")
        self.about_runtime_status.setText(status_text)

    def _copy_runtime_summary(self) -> None:
        """复制运行摘要。"""
        if not self._about_runtime_summary_text:
            self._refresh_about_runtime_summary()
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._about_runtime_summary_text)
            self.about_runtime_status.setText(self.tr("诊断信息已复制到剪贴板"))

    def _copy_issue_template(self) -> None:
        """复制问题反馈模板。"""
        report = self._collect_runtime_report()
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(build_issue_feedback_template(report))
            self.about_runtime_status.setText(self.tr("问题反馈模板已复制到剪贴板"))

    def _copy_acceptance_checklist(self) -> None:
        """复制预览版验收清单。"""
        report = self._collect_runtime_report()
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(build_preview_acceptance_checklist(report))
            self.about_runtime_status.setText(self.tr("验收清单已复制到剪贴板"))

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
                guide_path=self._user_guide_path(),
                app_config=app_config,
            )
            self.about_runtime_status.setText(self.tr(f"问题反馈模板已导出: {file_path}"))
        except OSError as exc:
            self.about_runtime_status.setText(self.tr(f"导出失败: {exc}"))

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
                guide_path=self._user_guide_path(),
                app_config=app_config,
            )
            self.about_runtime_status.setText(self.tr(f"验收清单已导出: {file_path}"))
        except OSError as exc:
            self.about_runtime_status.setText(self.tr(f"导出失败: {exc}"))

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
                guide_path=self._user_guide_path(),
                app_config=app_config,
            )
            self.about_runtime_status.setText(self.tr(f"预览版支持包已导出: {file_path}"))
        except OSError as exc:
            self.about_runtime_status.setText(self.tr(f"导出失败: {exc}"))

    def _export_runtime_summary(self) -> None:
        """导出诊断信息到文件。"""
        config_dir, app_config = self._resolve_runtime_context()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("导出诊断信息"),
            str(get_default_diagnostic_export_path(datetime.now())),
            self.tr("文本文件 (*.txt);;所有文件 (*)"),
        )
        if not file_path:
            return
        try:
            export_runtime_diagnostic_report(
                Path(file_path),
                config_dir=config_dir,
                guide_path=self._user_guide_path(),
                app_config=app_config,
            )
            self.about_runtime_status.setText(self.tr(f"诊断信息已导出: {file_path}"))
        except OSError as exc:
            self.about_runtime_status.setText(self.tr(f"导出失败: {exc}"))

    def _open_runtime_root(self) -> None:
        """打开运行目录。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_runtime_root())))

    def _open_logs_dir(self) -> None:
        """打开日志目录。"""
        target = Path(self._collect_runtime_summary().log_dir)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(target if target.exists() else target.parent))
        )

    def _open_config_dir(self) -> None:
        """打开配置目录。"""
        config_dir, _ = self._resolve_runtime_context()
        target = config_dir or self._collect_runtime_summary().config_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_issues_page(self) -> None:
        """打开问题反馈页面。"""
        QDesktopServices.openUrl(QUrl(ISSUES_URL))

    def _create_guide_tab(self) -> QWidget:
        """创建使用手册页签。"""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal, page)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        self.guide_toc_list = QListWidget(splitter)
        self.guide_toc_list.setMinimumWidth(220)
        self.guide_toc_list.setMaximumWidth(320)
        self.guide_toc_list.itemActivated.connect(self._jump_to_toc_item)
        self.guide_toc_list.itemClicked.connect(self._jump_to_toc_item)
        splitter.addWidget(self.guide_toc_list)

        guide_panel = QWidget(splitter)
        guide_layout = QVBoxLayout(guide_panel)
        guide_layout.setContentsMargins(0, 0, 0, 0)
        guide_layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.guide_search_edit = QLineEdit(guide_panel)
        self.guide_search_edit.setPlaceholderText(self.tr("搜索手册内容"))
        self.guide_search_edit.returnPressed.connect(self._search_guide_next)
        search_row.addWidget(self.guide_search_edit, 1)

        prev_button = QPushButton(self.tr("上一个"), guide_panel)
        prev_button.clicked.connect(self._search_guide_previous)
        search_row.addWidget(prev_button)

        next_button = QPushButton(self.tr("下一个"), guide_panel)
        next_button.clicked.connect(self._search_guide_next)
        search_row.addWidget(next_button)

        reload_button = QPushButton(self.tr("刷新文档"), guide_panel)
        reload_button.clicked.connect(self._reload_user_guide)
        search_row.addWidget(reload_button)

        open_path_button = QPushButton(self.tr("打开位置"), guide_panel)
        open_path_button.clicked.connect(self._open_user_guide_location)
        search_row.addWidget(open_path_button)

        self.guide_search_status = QLabel(self.tr("输入关键字后回车搜索"), guide_panel)
        self.guide_search_status.setStyleSheet("color: palette(mid);")
        search_row.addWidget(self.guide_search_status)
        guide_layout.addLayout(search_row)

        self.guide_meta_label = QLabel(guide_panel)
        self.guide_meta_label.setWordWrap(True)
        self.guide_meta_label.setStyleSheet("color: palette(mid);")
        self.guide_meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        guide_layout.addWidget(self.guide_meta_label)

        self.guide_browser = QTextBrowser(guide_panel)
        self.guide_browser.setOpenExternalLinks(True)
        self.guide_browser.setReadOnly(True)
        guide_layout.addWidget(self.guide_browser, 1)

        splitter.addWidget(guide_panel)
        splitter.setSizes([260, 700])
        self._reload_user_guide()

        return page

    def _create_about_tab(self) -> QWidget:
        """创建关于页签。"""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.about_browser = QTextBrowser(page)
        self.about_browser.setOpenExternalLinks(True)
        self.about_browser.setReadOnly(True)
        self.about_browser.setHtml(build_about_overview_html() + build_feedback_overview_html())
        layout.addWidget(self.about_browser)

        controls = QVBoxLayout()
        controls.setSpacing(8)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(8)
        copy_button = QPushButton(self.tr("复制诊断信息"), page)
        copy_button.clicked.connect(self._copy_runtime_summary)
        primary_row.addWidget(copy_button)

        acceptance_button = QPushButton(self.tr("复制验收清单"), page)
        acceptance_button.clicked.connect(self._copy_acceptance_checklist)
        primary_row.addWidget(acceptance_button)

        issue_template_button = QPushButton(self.tr("复制反馈模板"), page)
        issue_template_button.clicked.connect(self._copy_issue_template)
        primary_row.addWidget(issue_template_button)

        refresh_button = QPushButton(self.tr("刷新运行摘要"), page)
        refresh_button.clicked.connect(self._refresh_about_runtime_summary)
        primary_row.addWidget(refresh_button)
        primary_row.addStretch(1)
        controls.addLayout(primary_row)

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        export_button = QPushButton(self.tr("导出诊断报告"), page)
        export_button.clicked.connect(self._export_runtime_summary)
        export_row.addWidget(export_button)

        export_acceptance_button = QPushButton(self.tr("导出验收清单"), page)
        export_acceptance_button.clicked.connect(self._export_acceptance_checklist)
        export_row.addWidget(export_acceptance_button)

        export_issue_template_button = QPushButton(self.tr("导出反馈模板"), page)
        export_issue_template_button.clicked.connect(self._export_issue_template)
        export_row.addWidget(export_issue_template_button)

        export_support_bundle_button = QPushButton(self.tr("导出支持包"), page)
        export_support_bundle_button.clicked.connect(self._export_support_bundle)
        export_row.addWidget(export_support_bundle_button)

        export_row.addStretch(1)
        controls.addLayout(export_row)

        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(8)
        open_runtime_button = QPushButton(self.tr("打开运行目录"), page)
        open_runtime_button.clicked.connect(self._open_runtime_root)
        secondary_row.addWidget(open_runtime_button)

        open_config_button = QPushButton(self.tr("打开配置目录"), page)
        open_config_button.clicked.connect(self._open_config_dir)
        secondary_row.addWidget(open_config_button)

        open_logs_button = QPushButton(self.tr("打开日志目录"), page)
        open_logs_button.clicked.connect(self._open_logs_dir)
        secondary_row.addWidget(open_logs_button)

        issues_button = QPushButton(self.tr("问题反馈"), page)
        issues_button.clicked.connect(self._open_issues_page)
        secondary_row.addWidget(issues_button)
        secondary_row.addStretch(1)
        controls.addLayout(secondary_row)

        self.about_runtime_status = QLabel(
            self.tr("反馈预览版问题前，建议先导出诊断报告并附带关键日志"), page
        )
        self.about_runtime_status.setStyleSheet("color: palette(mid);")
        controls.addWidget(self.about_runtime_status)
        layout.addLayout(controls)

        self.about_runtime_browser = QTextBrowser(page)
        self.about_runtime_browser.setOpenExternalLinks(True)
        self.about_runtime_browser.setReadOnly(True)
        layout.addWidget(self.about_runtime_browser, 1)
        self._refresh_about_runtime_summary()
        return page

    def _jump_to_toc_item(self, item: QListWidgetItem) -> None:
        """跳转到目录项对应内容。"""
        heading = item.data(Qt.UserRole)
        if isinstance(heading, str) and heading:
            self._find_in_browser(heading, from_start=True)

    def _find_in_browser(
        self,
        text: str,
        *,
        from_start: bool = False,
        backward: bool = False,
    ) -> bool:
        """在使用手册中查找文本。"""
        if not text.strip():
            return False

        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlags()
        if from_start:
            cursor = self.guide_browser.textCursor()
            move_operation = QTextCursor.End if backward else QTextCursor.Start
            cursor.movePosition(move_operation)
            self.guide_browser.setTextCursor(cursor)

        found = self.guide_browser.find(text, flags)
        if found:
            self.tabs.setCurrentIndex(self.TAB_GUIDE)
        return found

    def _search_guide_next(self) -> None:
        """向后搜索。"""
        query = self.guide_search_edit.text().strip()
        if not query:
            self.guide_search_status.setText(self.tr("请输入要搜索的内容"))
            return
        if self._find_in_browser(query):
            self.guide_search_status.setText(self.tr(f"已定位: {query}"))
            return
        if self._find_in_browser(query, from_start=True):
            self.guide_search_status.setText(self.tr(f"已从开头重新定位: {query}"))
            return
        self.guide_search_status.setText(self.tr(f"未找到: {query}"))

    def _search_guide_previous(self) -> None:
        """向前搜索。"""
        query = self.guide_search_edit.text().strip()
        if not query:
            self.guide_search_status.setText(self.tr("请输入要搜索的内容"))
            return
        if self._find_in_browser(query, backward=True):
            self.guide_search_status.setText(self.tr(f"已定位: {query}"))
            return
        if self._find_in_browser(query, from_start=True, backward=True):
            self.guide_search_status.setText(self.tr(f"已从末尾重新定位: {query}"))
            return
        self.guide_search_status.setText(self.tr(f"未找到: {query}"))

    def _setup_ui(self, initial_tab: int) -> None:
        """构建界面。"""
        self.setWindowTitle(self.tr("帮助"))
        self.setMinimumSize(860, 640)
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(self.tr(f"{APP_NAME} 帮助中心"), self)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title)

        summary = QLabel(
            self.tr("使用选项卡查看用户手册、关于信息、运行摘要和许可证说明。"),
            self,
        )
        summary.setStyleSheet("color: palette(mid);")
        layout.addWidget(summary)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        guide_tab = self._create_guide_tab()
        self.tabs.addTab(guide_tab, self.tr("使用手册"))

        about_tab = self._create_about_tab()
        self.tabs.addTab(about_tab, self.tr("关于"))

        self.license_browser = QTextBrowser(self)
        self.license_browser.setOpenExternalLinks(True)
        self.license_browser.setReadOnly(True)
        self.license_browser.setHtml(build_license_overview_html())
        self.tabs.addTab(self.license_browser, self.tr("许可证"))

        max_index = self.tabs.count() - 1
        self.tabs.setCurrentIndex(min(max(0, initial_tab), max_index))

        footer = QHBoxLayout()
        footer.addWidget(
            QLabel(
                f'<a href="{REPOSITORY_URL}">github.com/neko-shell/Neko_Shell</a>',
                self,
            )
        )
        footer.itemAt(0).widget().setOpenExternalLinks(True)  # type: ignore[union-attr]
        footer.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        footer.addWidget(buttons)
        layout.addLayout(footer)
