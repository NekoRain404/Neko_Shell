#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置对话框

用于配置应用程序设置。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from typing import Optional

from neko_shell.i18n import get_available_language_options, resolve_language_code
from neko_shell.ui.widgets.terminal_widget import get_terminal_theme_choices
from neko_shell.utils import (
    AppConfig,
    ConfigManager,
    dump_terminal_macro_lines,
    dump_terminal_snippet_lines,
    get_logger,
    normalize_terminal_favorite_snippets,
    parse_terminal_macro_lines,
    parse_terminal_snippet_lines,
)


def dump_shared_library_signer_profile_lines(
    profiles: dict[str, dict[str, str | None]] | None,
) -> list[str]:
    """将签名者资料转换为可编辑文本行。"""
    lines: list[str] = []
    for fingerprint, profile in sorted((profiles or {}).items(), key=lambda item: item[0]):
        display_name = str((profile or {}).get("display_name") or "").strip()
        note = str((profile or {}).get("note") or "").strip()
        expires_at = str((profile or {}).get("expires_at") or "").strip()
        rotate_before_at = str((profile or {}).get("rotate_before_at") or "").strip()
        lines.append(f"{fingerprint}::{display_name}::{note}::{expires_at}::{rotate_before_at}")
    return lines


def parse_shared_library_signer_profile_lines(
    lines: list[str],
) -> dict[str, dict[str, str | None]]:
    """解析签名者资料编辑文本。"""
    profiles: dict[str, dict[str, str | None]] = {}
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("::", 4)]
        fingerprint = parts[0].lower()
        if not fingerprint:
            continue
        display_name = parts[1] if len(parts) > 1 and parts[1] else None
        note = parts[2] if len(parts) > 2 and parts[2] else None
        expires_at = parts[3] if len(parts) > 3 and parts[3] else None
        rotate_before_at = parts[4] if len(parts) > 4 and parts[4] else None
        profiles[fingerprint] = {
            "fingerprint": fingerprint,
            "display_name": display_name,
            "note": note,
            "expires_at": expires_at,
            "rotate_before_at": rotate_before_at,
        }
    return profiles


def dump_shared_library_revoked_signer_lines(
    records: list[dict[str, str | None]] | None,
) -> list[str]:
    """将签名者撤销记录转换为可编辑文本行。"""
    lines: list[str] = []
    for record in records or []:
        fingerprint = str((record or {}).get("fingerprint") or "").strip().lower()
        if not fingerprint:
            continue
        reason = str((record or {}).get("reason") or "").strip()
        revoked_at = str((record or {}).get("revoked_at") or "").strip()
        note = str((record or {}).get("note") or "").strip()
        lines.append(f"{fingerprint}::{reason}::{revoked_at}::{note}")
    return lines


def parse_shared_library_revoked_signer_lines(
    lines: list[str],
) -> list[dict[str, str | None]]:
    """解析签名者撤销记录编辑文本。"""
    records: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("::", 3)]
        fingerprint = parts[0].lower()
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        records.append(
            {
                "fingerprint": fingerprint,
                "reason": parts[1] if len(parts) > 1 and parts[1] else None,
                "revoked_at": parts[2] if len(parts) > 2 and parts[2] else None,
                "note": parts[3] if len(parts) > 3 and parts[3] else None,
            }
        )
    return records


def dump_shared_library_signer_group_lines(
    groups: dict[str, list[str]] | None,
) -> list[str]:
    """将签名者分组转换为可编辑文本行。"""
    lines: list[str] = []
    for group_name, fingerprints in sorted((groups or {}).items(), key=lambda item: item[0]):
        normalized = [str(item).strip().lower() for item in fingerprints or [] if str(item).strip()]
        if not normalized:
            continue
        lines.append(f"{group_name}::{', '.join(normalized)}")
    return lines


def parse_shared_library_signer_group_lines(
    lines: list[str],
) -> dict[str, list[str]]:
    """解析签名者分组编辑文本。"""
    groups: dict[str, list[str]] = {}
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        name_part, sep, members_part = line.partition("::")
        group_name = name_part.strip()
        if not group_name:
            continue
        if not sep:
            members_part = ""
        members = [
            part.strip().lower()
            for part in members_part.replace("\n", ",").split(",")
            if part.strip()
        ]
        deduplicated: list[str] = []
        seen: set[str] = set()
        for member in members:
            if member in seen:
                continue
            seen.add(member)
            deduplicated.append(member)
        if deduplicated:
            groups[group_name] = deduplicated
    return groups


def dump_shared_library_rotation_exception_lines(
    records: list[dict[str, object]] | None,
) -> list[str]:
    """将轮换例外授权记录转换为可编辑文本行。"""
    lines: list[str] = []
    for record in records or []:
        fingerprint = str((record or {}).get("fingerprint") or "").strip().lower()
        if not fingerprint:
            continue
        package_types = [
            str(item).strip()
            for item in ((record or {}).get("package_types") or [])
            if str(item).strip()
        ]
        rotation_states = [
            str(item).strip()
            for item in ((record or {}).get("rotation_states") or [])
            if str(item).strip()
        ]
        expires_at = str((record or {}).get("expires_at") or "").strip()
        note = str((record or {}).get("note") or "").strip()
        lines.append(
            "::".join(
                [
                    fingerprint,
                    ",".join(package_types) or "*",
                    ",".join(rotation_states) or "*",
                    expires_at,
                    note,
                ]
            )
        )
    return lines


def parse_shared_library_rotation_exception_lines(
    lines: list[str],
) -> list[dict[str, object]]:
    """解析轮换例外授权编辑文本。"""
    records: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("::", 4)]
        fingerprint = parts[0].lower()
        if not fingerprint:
            continue
        package_scope = parts[1] if len(parts) > 1 else ""
        state_scope = parts[2] if len(parts) > 2 else ""
        expires_at = parts[3] if len(parts) > 3 and parts[3] else None
        note = parts[4] if len(parts) > 4 and parts[4] else None
        package_types = [
            item.strip().lower()
            for item in package_scope.split(",")
            if item.strip() and item.strip().lower() not in {"*", "all", "any"}
        ]
        rotation_states = [
            item.strip().lower()
            for item in state_scope.split(",")
            if item.strip() and item.strip().lower() not in {"*", "all", "any", "both"}
        ]
        key = (
            fingerprint,
            ",".join(package_types),
            ",".join(rotation_states),
            str(expires_at or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "fingerprint": fingerprint,
                "package_types": package_types,
                "rotation_states": rotation_states,
                "expires_at": expires_at,
                "note": note,
            }
        )
    return records


def dump_shared_library_team_approval_rule_lines(
    rules: list[dict[str, object]] | None,
) -> list[str]:
    """将团队级审批规则转换为可编辑文本行。"""
    lines: list[str] = []
    for rule in rules or []:
        name = str((rule or {}).get("name") or "").strip()
        if not name:
            continue
        action = str((rule or {}).get("action") or "approval").strip().lower() or "approval"
        source_apps = [
            str(item).strip()
            for item in ((rule or {}).get("source_apps") or [])
            if str(item).strip()
        ]
        package_types = [
            str(item).strip()
            for item in ((rule or {}).get("package_types") or [])
            if str(item).strip()
        ]
        signer_groups = [
            str(item).strip()
            for item in ((rule or {}).get("signer_groups") or [])
            if str(item).strip()
        ]
        rotation_states = [
            str(item).strip()
            for item in ((rule or {}).get("rotation_states") or [])
            if str(item).strip()
        ]
        minimum_signature_count = max(int((rule or {}).get("minimum_signature_count") or 0), 0)
        approval_level = str((rule or {}).get("approval_level") or "").strip()
        note = str((rule or {}).get("note") or "").strip()
        enabled = "on" if bool((rule or {}).get("enabled", True)) else "off"
        lines.append(
            "::".join(
                [
                    name,
                    action,
                    ",".join(source_apps) or "*",
                    ",".join(package_types) or "*",
                    ",".join(signer_groups) or "*",
                    ",".join(rotation_states) or "*",
                    str(minimum_signature_count or ""),
                    approval_level,
                    enabled,
                    note,
                ]
            )
        )
    return lines


def parse_shared_library_team_approval_rule_lines(
    lines: list[str],
) -> list[dict[str, object]]:
    """解析团队级审批规则编辑文本。"""
    rules: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        if line.count("::") >= 9:
            parts = [part.strip() for part in line.split("::", 9)]
        else:
            parts = [part.strip() for part in line.split("::", 7)]
        name = parts[0]
        if not name:
            continue
        action = parts[1].lower() if len(parts) > 1 and parts[1] else "approval"
        source_scope = parts[2] if len(parts) > 2 else ""
        package_scope = parts[3] if len(parts) > 3 else ""
        signer_group_scope = parts[4] if len(parts) > 4 else ""
        rotation_scope = parts[5] if len(parts) > 5 else ""
        if len(parts) >= 10:
            minimum_signature_count_text = parts[6]
            approval_level = parts[7] if parts[7] else None
            enabled_text = parts[8].lower() if parts[8] else "on"
            note = parts[9] if parts[9] else None
        else:
            minimum_signature_count_text = ""
            approval_level = None
            enabled_text = parts[6].lower() if len(parts) > 6 and parts[6] else "on"
            note = parts[7] if len(parts) > 7 and parts[7] else None
        source_apps = [
            item.strip()
            for item in source_scope.split(",")
            if item.strip() and item.strip().lower() not in {"*", "all", "any"}
        ]
        package_types = [
            item.strip().lower()
            for item in package_scope.split(",")
            if item.strip() and item.strip().lower() not in {"*", "all", "any"}
        ]
        signer_groups = [
            item.strip()
            for item in signer_group_scope.split(",")
            if item.strip() and item.strip().lower() not in {"*", "all", "any"}
        ]
        rotation_states = [
            item.strip().lower()
            for item in rotation_scope.split(",")
            if item.strip() and item.strip().lower() not in {"*", "all", "any"}
        ]
        try:
            minimum_signature_count = max(int(minimum_signature_count_text or 0), 0)
        except (TypeError, ValueError):
            minimum_signature_count = 0
        key = (
            name.casefold(),
            action,
            ",".join(item.casefold() for item in source_apps),
            ",".join(package_types),
            ",".join(item.casefold() for item in signer_groups),
            ",".join(rotation_states),
            str(minimum_signature_count),
            str(approval_level or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        rules.append(
            {
                "name": name,
                "action": action,
                "source_apps": source_apps,
                "package_types": package_types,
                "signer_groups": signer_groups,
                "rotation_states": rotation_states,
                "minimum_signature_count": minimum_signature_count,
                "approval_level": approval_level,
                "enabled": enabled_text not in {"0", "false", "off", "disabled", "no"},
                "note": note,
            }
        )
    return rules


class SettingsDialog(QDialog):
    """
    设置对话框

    用于配置应用程序的各种设置。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._logger = get_logger("SettingsDialog")
        self._config: Optional[AppConfig] = None
        self._config_manager: Optional[ConfigManager] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """设置 UI"""
        self.setWindowTitle(self.tr("设置"))
        self.setMinimumSize(840, 620)
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标签页
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.West)
        self.tabs.setUsesScrollButtons(False)
        layout.addWidget(self.tabs)

        # 常规设置
        general_page = self._create_general_page()
        self.tabs.addTab(general_page, self.tr("常规"))

        # 连接设置
        connection_page = self._create_connection_page()
        self.tabs.addTab(connection_page, self.tr("连接"))

        # 显示设置
        display_page = self._create_display_page()
        self.tabs.addTab(display_page, self.tr("显示"))

        shared_library_page = self._create_shared_library_page()
        self.tabs.addTab(shared_library_page, self.tr("共享中心"))

        # 安全设置
        security_page = self._create_security_page()
        self.tabs.addTab(security_page, self.tr("安全"))

        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        ok_btn = QPushButton(self.tr("确定"))
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton(self.tr("取消"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def set_config_manager(self, manager: ConfigManager) -> None:
        """设置配置管理器，用于安全操作。"""
        self._config_manager = manager
        self._update_security_actions()

    def _wrap_page_in_scroll_area(self, content: QWidget) -> QScrollArea:
        """将页面内容包装为可滚动区域。"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setWidget(content)
        return scroll_area

    def _create_page_canvas(self) -> tuple[QWidget, QVBoxLayout]:
        """创建页面画布。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        return page, layout

    def _create_settings_section(
        self,
        title: str,
        description: Optional[str] = None,
    ) -> tuple[QGroupBox, QVBoxLayout]:
        """创建分组区域。"""
        section = QGroupBox(title)
        section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        if description:
            description_label = QLabel(description, section)
            description_label.setObjectName("panelMeta")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)
        return section, layout

    def _create_editor_field(
        self,
        title: str,
        editor: QPlainTextEdit,
        hint: str,
    ) -> QWidget:
        """创建带标题的多行编辑区域。"""
        field = QWidget()
        layout = QVBoxLayout(field)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title_label = QLabel(f"<b>{title}</b>", field)
        layout.addWidget(title_label)

        hint_label = QLabel(hint, field)
        hint_label.setObjectName("panelMeta")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
        layout.addWidget(editor)
        return field

    @staticmethod
    def _configure_text_editor(
        editor: QPlainTextEdit,
        *,
        placeholder: str,
        height: int,
    ) -> None:
        """统一配置多行文本编辑器。"""
        editor.setPlaceholderText(placeholder)
        editor.setFixedHeight(height)

    def _create_general_page(self) -> QWidget:
        """创建常规设置页面"""
        page, layout = self._create_page_canvas()

        app_section, app_layout = self._create_settings_section(
            self.tr("应用偏好"),
            self.tr("保留个人使用中最常调的启动、语言和日志选项。"),
        )
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form_layout.setSpacing(10)

        # 语言
        self.language_combo = QComboBox()
        language_options = get_available_language_options()
        for language_code, display_name in language_options:
            self.language_combo.addItem(display_name, language_code)
        self.language_combo.setEnabled(len(language_options) > 1)
        if len(language_options) > 1:
            self.language_combo.setToolTip(self.tr("仅显示当前运行时实际可用的界面语言。"))
        else:
            self.language_combo.setToolTip(
                self.tr("当前运行时仅检测到内置简体中文界面。")
            )
        form_layout.addRow(self.tr("语言:"), self.language_combo)

        # 日志级别
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        form_layout.addRow(self.tr("日志级别:"), self.log_level_combo)

        self.restore_workspace_check = QCheckBox(self.tr("启动时恢复上次工作区"))
        self.restore_workspace_check.setChecked(True)
        form_layout.addRow(self.tr("工作区:"), self.restore_workspace_check)

        # 日志目录
        log_layout = QHBoxLayout()
        self.log_dir_edit = QLineEdit()
        self.log_dir_edit.setText("logs")
        self.log_dir_edit.setPlaceholderText("logs")
        self.log_dir_edit.setClearButtonEnabled(True)
        log_layout.addWidget(self.log_dir_edit)

        log_browse_btn = QPushButton(self.tr("浏览"))
        log_browse_btn.clicked.connect(self._browse_log_dir)
        log_layout.addWidget(log_browse_btn)

        form_layout.addRow(self.tr("日志目录:"), log_layout)
        app_layout.addLayout(form_layout)
        layout.addWidget(app_section)
        layout.addStretch(1)
        return self._wrap_page_in_scroll_area(page)

    def _create_connection_page(self) -> QWidget:
        """创建连接设置页面"""
        page, layout = self._create_page_canvas()
        connection_section, connection_layout = self._create_settings_section(
            self.tr("默认连接策略"),
            self.tr("这里仅维护全局默认值，自动重连开关仍在具体连接里单独配置。"),
        )
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form_layout.setSpacing(10)

        # 默认超时
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1, 120)
        self.timeout_spin.setValue(10)
        self.timeout_spin.setSuffix(" 秒")
        form_layout.addRow(self.tr("默认超时:"), self.timeout_spin)

        # 最大重连次数
        self.reconnect_spin = QSpinBox()
        self.reconnect_spin.setRange(0, 10)
        self.reconnect_spin.setValue(3)
        form_layout.addRow(self.tr("最大重连次数:"), self.reconnect_spin)
        connection_layout.addLayout(form_layout)
        layout.addWidget(connection_section)
        layout.addStretch(1)
        return self._wrap_page_in_scroll_area(page)

    def _create_display_page(self) -> QWidget:
        """创建显示设置页面"""
        page, layout = self._create_page_canvas()

        appearance_section, appearance_layout = self._create_settings_section(
            self.tr("界面外观"),
            self.tr("优先保留个人使用最常见的主题和终端渲染偏好。"),
        )
        appearance_form = QFormLayout()
        appearance_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        appearance_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        appearance_form.setSpacing(10)

        # 主题
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.tr("深色"), "dark")
        self.theme_combo.addItem(self.tr("浅色"), "light")
        self.theme_combo.addItem(self.tr("护眼"), "eye_care")
        self.theme_combo.addItem(self.tr("跟随系统"), "auto")
        appearance_form.addRow(self.tr("主题:"), self.theme_combo)

        self.terminal_backend_combo = QComboBox()
        self.terminal_backend_combo.addItem(self.tr("自动"), "auto")
        self.terminal_backend_combo.addItem(self.tr("经典终端"), "classic")
        self.terminal_backend_combo.addItem(self.tr("QTermWidget"), "qtermwidget")
        appearance_form.addRow(self.tr("终端后端:"), self.terminal_backend_combo)

        self.terminal_theme_combo = QComboBox()
        self.terminal_theme_combo.addItems(get_terminal_theme_choices())
        appearance_form.addRow(self.tr("终端主题:"), self.terminal_theme_combo)

        # 字体大小
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        self.font_size_spin.setValue(10)
        appearance_form.addRow(self.tr("字体大小:"), self.font_size_spin)
        appearance_layout.addLayout(appearance_form)
        layout.addWidget(appearance_section)

        commands_section, commands_layout = self._create_settings_section(
            self.tr("终端命令库"),
            self.tr("右键菜单、快捷入口和编排发送都会复用这里的命令配置。"),
        )
        self.terminal_snippets_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.terminal_snippets_edit,
            placeholder=self.tr("每行一条，支持“分组::命令”。"),
            height=120,
        )

        self.terminal_favorites_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.terminal_favorites_edit,
            placeholder=self.tr("每行一条常用命令。"),
            height=96,
        )

        self.terminal_macros_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.terminal_macros_edit,
            placeholder=self.tr("每行一条，支持“宏名::命令”。"),
            height=120,
        )
        commands_grid = QGridLayout()
        commands_grid.setContentsMargins(0, 0, 0, 0)
        commands_grid.setHorizontalSpacing(12)
        commands_grid.setVerticalSpacing(12)
        commands_grid.addWidget(
            self._create_editor_field(
                self.tr("命令分组"),
                self.terminal_snippets_edit,
                self.tr("建议按场景整理，例如常用、容器、巡检。"),
            ),
            0,
            0,
        )
        commands_grid.addWidget(
            self._create_editor_field(
                self.tr("收藏命令"),
                self.terminal_favorites_edit,
                self.tr("这里的命令会优先出现在快捷入口。"),
            ),
            0,
            1,
        )
        commands_grid.addWidget(
            self._create_editor_field(
                self.tr("命令宏"),
                self.terminal_macros_edit,
                self.tr("同名宏会自动归并，适合巡检和批量操作。"),
            ),
            1,
            0,
            1,
            2,
        )
        commands_grid.setColumnStretch(0, 1)
        commands_grid.setColumnStretch(1, 1)
        commands_layout.addLayout(commands_grid)
        layout.addWidget(commands_section)
        layout.addStretch(1)
        return self._wrap_page_in_scroll_area(page)

    def _create_shared_library_page(self) -> QWidget:
        """创建共享中心设置页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.shared_library_tabs = QTabWidget()
        self.shared_library_tabs.setDocumentMode(True)
        layout.addWidget(self.shared_library_tabs)

        self.shared_library_tabs.addTab(self._create_shared_library_sync_page(), self.tr("同步"))
        self.shared_library_tabs.addTab(self._create_shared_library_trust_page(), self.tr("信任"))
        self.shared_library_tabs.addTab(self._create_shared_library_governance_page(), self.tr("治理"))
        return page

    def _create_shared_library_sync_page(self) -> QWidget:
        """创建共享中心同步页。"""
        page, layout = self._create_page_canvas()
        sync_section, sync_layout = self._create_settings_section(
            self.tr("同步目录与策略"),
            self.tr("把常用同步行为单独放在一起，避免和治理规则混在一页。"),
        )
        sync_form = QFormLayout()
        sync_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        sync_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        sync_form.setSpacing(10)

        shared_layout = QHBoxLayout()
        self.shared_library_sync_dir_edit = QLineEdit()
        self.shared_library_sync_dir_edit.setPlaceholderText(
            self.tr("可选，用于跨机器同步共享中心")
        )
        self.shared_library_sync_dir_edit.setClearButtonEnabled(True)
        shared_layout.addWidget(self.shared_library_sync_dir_edit)

        shared_browse_btn = QPushButton(self.tr("浏览"))
        shared_browse_btn.clicked.connect(self._browse_shared_library_sync_dir)
        shared_layout.addWidget(shared_browse_btn)
        sync_form.addRow(self.tr("共享仓库目录:"), shared_layout)

        self.shared_library_sync_policy_combo = QComboBox()
        self.shared_library_sync_policy_combo.addItem(self.tr("手动同步"), "manual")
        self.shared_library_sync_policy_combo.addItem(self.tr("启动时自动拉取"), "startup_pull")
        self.shared_library_sync_policy_combo.addItem(
            self.tr("仅在索引更新时自动拉取"),
            "startup_pull_if_changed",
        )
        sync_form.addRow(self.tr("共享同步策略:"), self.shared_library_sync_policy_combo)

        self.shared_library_lock_timeout_spin = QSpinBox()
        self.shared_library_lock_timeout_spin.setRange(30, 86400)
        self.shared_library_lock_timeout_spin.setSingleStep(30)
        self.shared_library_lock_timeout_spin.setSuffix(self.tr(" 秒"))
        self.shared_library_lock_timeout_spin.setValue(600)
        sync_form.addRow(self.tr("共享锁超时:"), self.shared_library_lock_timeout_spin)
        sync_layout.addLayout(sync_form)

        auto_pull_package_types_layout = QHBoxLayout()
        auto_pull_package_types_layout.setContentsMargins(0, 0, 0, 0)
        auto_pull_package_types_layout.setSpacing(12)
        self.shared_auto_pull_workspace_templates_check = QCheckBox(self.tr("工作区模板共享包"))
        self.shared_auto_pull_workspace_templates_check.setChecked(True)
        auto_pull_package_types_layout.addWidget(self.shared_auto_pull_workspace_templates_check)
        self.shared_auto_pull_connection_filter_presets_check = QCheckBox(self.tr("筛选预设共享包"))
        self.shared_auto_pull_connection_filter_presets_check.setChecked(True)
        auto_pull_package_types_layout.addWidget(
            self.shared_auto_pull_connection_filter_presets_check
        )
        auto_pull_package_types_layout.addStretch(1)
        sync_form.addRow(self.tr("自动拉取包类型:"), auto_pull_package_types_layout)

        layout.addWidget(sync_section)
        layout.addStretch(1)
        return self._wrap_page_in_scroll_area(page)

    def _create_shared_library_trust_page(self) -> QWidget:
        """创建共享中心信任页。"""
        page, layout = self._create_page_canvas()
        trust_section, trust_layout = self._create_settings_section(
            self.tr("来源与签名"),
            self.tr("按来源、签名者和分组整理，避免所有多行字段挤成一张长表单。"),
        )

        self.shared_library_trusted_sources_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.shared_library_trusted_sources_edit,
            placeholder=self.tr("每行一个来源应用名。"),
            height=92,
        )
        self.shared_library_trusted_sources_edit.setPlainText(
            "\n".join(AppConfig().shared_library_trusted_source_apps)
        )

        self.shared_library_trusted_signers_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.shared_library_trusted_signers_edit,
            placeholder=self.tr("每行一个签名指纹。"),
            height=92,
        )

        self.shared_library_signer_profiles_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.shared_library_signer_profiles_edit,
            placeholder=self.tr("格式：指纹::别名::备注::有效期::轮换截止"),
            height=108,
        )

        self.shared_library_signer_groups_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.shared_library_signer_groups_edit,
            placeholder=self.tr("格式：分组名::指纹1, 指纹2"),
            height=92,
        )

        self.shared_library_revoked_signers_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.shared_library_revoked_signers_edit,
            placeholder=self.tr("格式：指纹::原因::撤销时间::备注"),
            height=96,
        )

        trust_grid = QGridLayout()
        trust_grid.setContentsMargins(0, 0, 0, 0)
        trust_grid.setHorizontalSpacing(12)
        trust_grid.setVerticalSpacing(12)
        trust_grid.addWidget(
            self._create_editor_field(
                self.tr("受信任来源"),
                self.shared_library_trusted_sources_edit,
                self.tr("留空表示允许全部来源。"),
            ),
            0,
            0,
        )
        trust_grid.addWidget(
            self._create_editor_field(
                self.tr("受信任签名者"),
                self.shared_library_trusted_signers_edit,
                self.tr("留空表示不限制签名者。"),
            ),
            0,
            1,
        )
        trust_grid.addWidget(
            self._create_editor_field(
                self.tr("签名者资料"),
                self.shared_library_signer_profiles_edit,
                self.tr("适合维护别名、备注和轮换时间。"),
            ),
            1,
            0,
        )
        trust_grid.addWidget(
            self._create_editor_field(
                self.tr("签名者分组"),
                self.shared_library_signer_groups_edit,
                self.tr("可用于审批与筛选规则复用。"),
            ),
            1,
            1,
        )
        trust_grid.addWidget(
            self._create_editor_field(
                self.tr("已撤销签名者"),
                self.shared_library_revoked_signers_edit,
                self.tr("撤销记录会同步生成撤销指纹名单。"),
            ),
            2,
            0,
            1,
            2,
        )
        trust_grid.setColumnStretch(0, 1)
        trust_grid.setColumnStretch(1, 1)
        trust_layout.addLayout(trust_grid)
        layout.addWidget(trust_section)
        layout.addStretch(1)
        return self._wrap_page_in_scroll_area(page)

    def _create_shared_library_governance_page(self) -> QWidget:
        """创建共享中心治理页。"""
        page, layout = self._create_page_canvas()
        policy_section, policy_layout = self._create_settings_section(
            self.tr("轮换治理"),
            self.tr("把规则、例外和审批项集中管理，减少常规页视觉负担。"),
        )
        policy_form = QFormLayout()
        policy_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        policy_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        policy_form.setSpacing(10)

        self.shared_library_rotation_due_policy_combo = QComboBox()
        self.shared_library_rotation_due_policy_combo.addItem(self.tr("仅提示"), "warn")
        self.shared_library_rotation_due_policy_combo.addItem(self.tr("进入审批"), "approval")
        self.shared_library_rotation_due_policy_combo.addItem(self.tr("直接阻断"), "block")
        policy_form.addRow(self.tr("临近轮换治理:"), self.shared_library_rotation_due_policy_combo)

        self.shared_library_rotation_overdue_policy_combo = QComboBox()
        self.shared_library_rotation_overdue_policy_combo.addItem(self.tr("仅提示"), "warn")
        self.shared_library_rotation_overdue_policy_combo.addItem(self.tr("进入审批"), "approval")
        self.shared_library_rotation_overdue_policy_combo.addItem(self.tr("直接阻断"), "block")
        self.shared_library_rotation_overdue_policy_combo.setCurrentIndex(
            self.shared_library_rotation_overdue_policy_combo.findData("approval")
        )
        policy_form.addRow(self.tr("轮换超期治理:"), self.shared_library_rotation_overdue_policy_combo)
        policy_layout.addLayout(policy_form)
        layout.addWidget(policy_section)

        self.shared_library_rotation_exceptions_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.shared_library_rotation_exceptions_edit,
            placeholder=self.tr("格式：指纹::包类型::*或due,overdue::截止时间::备注"),
            height=100,
        )

        self.shared_library_team_approval_rules_edit = QPlainTextEdit()
        self._configure_text_editor(
            self.shared_library_team_approval_rules_edit,
            placeholder=self.tr("格式：规则名::approval或block::来源::*::分组::*::最小签名数::审批级别::on/off::备注"),
            height=120,
        )

        rules_section, rules_layout = self._create_settings_section(
            self.tr("例外与审批"),
            self.tr("高级治理项保留在独立页签中，避免日常设置被少用规则淹没。"),
        )
        rules_layout.addWidget(
            self._create_editor_field(
                self.tr("轮换例外授权"),
                self.shared_library_rotation_exceptions_edit,
                self.tr("支持按包类型和轮换状态设置临时放行。"),
            )
        )
        rules_layout.addWidget(
            self._create_editor_field(
                self.tr("团队级审批规则"),
                self.shared_library_team_approval_rules_edit,
                self.tr("仅在需要更细颗粒治理时再填写。"),
            )
        )
        layout.addWidget(rules_section)
        layout.addStretch(1)
        return self._wrap_page_in_scroll_area(page)

    def _create_security_page(self) -> QWidget:
        """创建安全设置页面。"""
        page, layout = self._create_page_canvas()
        security_section, security_layout = self._create_settings_section(
            self.tr("主密码保护"),
            self.tr("用于保护本地配置文件，不影响已建立的连接会话。"),
        )

        self.security_status_label = QLabel()
        self.security_status_label.setWordWrap(True)
        security_layout.addWidget(self.security_status_label)

        action_layout = QHBoxLayout()
        self.encrypt_config_btn = QPushButton(self.tr("加密配置"))
        self.encrypt_config_btn.clicked.connect(self._encrypt_config_files)
        action_layout.addWidget(self.encrypt_config_btn)

        self.decrypt_config_btn = QPushButton(self.tr("解密配置"))
        self.decrypt_config_btn.clicked.connect(self._decrypt_config_files)
        action_layout.addWidget(self.decrypt_config_btn)
        action_layout.addStretch()
        security_layout.addLayout(action_layout)

        layout.addWidget(security_section)
        layout.addStretch()
        self._update_security_actions()
        return self._wrap_page_in_scroll_area(page)

    def _encrypted_config_count(self) -> int:
        """返回当前配置目录中已加密文件数量。"""
        if self._config_manager is None:
            return 0
        return sum(
            1
            for path in self._config_manager.config_file_paths()
            if path.exists() and path.read_bytes().startswith(b"NEKO_SHELL_ENC_V1\n")
        )

    def _master_password_enabled(self) -> bool:
        """判断当前应用会话是否已启用主密码保护。"""
        app = self._application()
        return bool(app and hasattr(app, "master_password_enabled") and app.master_password_enabled)

    def _security_status_text(self) -> str:
        """生成当前安全状态说明。"""
        if self._config_manager is None:
            return self.tr("当前未绑定配置目录，无法管理主密码保护。")

        encrypted_count = self._encrypted_config_count()
        master_password_enabled = self._master_password_enabled()

        if master_password_enabled:
            return self.tr("主密码保护已启用。本次会话已解锁，应用退出时会自动重新加密配置文件。")
        if encrypted_count > 0:
            return self.tr(f"检测到 {encrypted_count} 个加密配置文件。可输入主密码解密后继续维护。")
        return self.tr(
            "主密码保护未启用。启用后，应用退出时会自动加密，下次启动时会提示输入主密码解锁。"
        )

    def _update_security_actions(self) -> None:
        """根据配置管理器状态刷新安全按钮。"""
        enabled = self._config_manager is not None
        if hasattr(self, "encrypt_config_btn"):
            master_password_enabled = self._master_password_enabled() if enabled else False
            encrypted_count = self._encrypted_config_count() if enabled else 0
            self.security_status_label.setText(self._security_status_text())
            self.encrypt_config_btn.setEnabled(enabled)
            self.encrypt_config_btn.setText(
                self.tr("更新主密码") if master_password_enabled else self.tr("启用主密码保护")
            )
            self.decrypt_config_btn.setEnabled(
                enabled and (master_password_enabled or encrypted_count > 0)
            )
            self.decrypt_config_btn.setText(
                self.tr("关闭主密码保护") if master_password_enabled else self.tr("解密配置")
            )

    @staticmethod
    def _application():
        """返回当前 QApplication 实例。"""
        return QApplication.instance()

    def _prompt_master_password(self, confirm: bool = False) -> Optional[str]:
        """弹出主密码输入框。"""
        password, ok = QInputDialog.getText(
            self,
            self.tr("主密码"),
            self.tr("请输入主密码:"),
            QLineEdit.Password,
        )
        if not ok:
            return None
        if not password:
            QMessageBox.warning(self, self.tr("错误"), self.tr("主密码不能为空"))
            return None
        if not confirm:
            return password

        confirmation, confirmed = QInputDialog.getText(
            self,
            self.tr("确认主密码"),
            self.tr("请再次输入主密码:"),
            QLineEdit.Password,
        )
        if not confirmed:
            return None
        if password != confirmation:
            QMessageBox.warning(self, self.tr("错误"), self.tr("两次输入的主密码不一致"))
            return None
        return password

    def _encrypt_config_files(self) -> None:
        """使用主密码加密配置文件。"""
        if self._config_manager is None:
            return
        password = self._prompt_master_password(confirm=True)
        if password is None:
            return
        try:
            app = self._application()
            if app is not None and hasattr(app, "enable_master_password"):
                app.enable_master_password(password)
                message = self.tr("主密码保护已启用，应用退出时会自动加密配置文件。")
            else:
                paths = self._config_manager.encrypt_config_files(password)
                message = self.tr(f"已加密配置文件: {len(paths)}")
        except Exception as exc:
            self._logger.error("加密配置失败: %s", exc)
            QMessageBox.critical(self, self.tr("加密失败"), str(exc))
            return
        self._update_security_actions()
        QMessageBox.information(self, self.tr("完成"), message)

    def _decrypt_config_files(self) -> None:
        """使用主密码解密配置文件。"""
        if self._config_manager is None:
            return
        password = self._prompt_master_password(confirm=False)
        if password is None:
            return
        try:
            app = self._application()
            if app is not None and hasattr(app, "disable_master_password"):
                if any(
                    path.exists() and path.read_bytes().startswith(b"NEKO_SHELL_ENC_V1\n")
                    for path in self._config_manager.config_file_paths()
                ):
                    self._config_manager.decrypt_config_files(password)
                app.disable_master_password(password)
                message = self.tr("主密码保护已关闭，本次退出后配置将保持解密状态。")
            else:
                paths = self._config_manager.decrypt_config_files(password)
                message = self.tr(f"已解密配置文件: {len(paths)}")
        except Exception as exc:
            self._logger.error("解密配置失败: %s", exc)
            QMessageBox.critical(self, self.tr("解密失败"), str(exc))
            return
        self._update_security_actions()
        QMessageBox.information(self, self.tr("完成"), message)

    def _browse_log_dir(self) -> None:
        """浏览日志目录"""
        dir_path = QFileDialog.getExistingDirectory(self, self.tr("选择日志目录"))
        if dir_path:
            self.log_dir_edit.setText(dir_path)

    def _browse_shared_library_sync_dir(self) -> None:
        """浏览共享仓库目录。"""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择共享仓库目录"),
        )
        if dir_path:
            self.shared_library_sync_dir_edit.setText(dir_path)

    def load_config(self, config: AppConfig) -> None:
        """加载配置"""
        self._config = config

        # 常规
        configured_language = resolve_language_code(config.language)
        language_index = self.language_combo.findData(configured_language)
        if language_index < 0:
            language_index = self.language_combo.findData("zh_CN")
        if language_index < 0:
            language_index = 0
        self.language_combo.setCurrentIndex(language_index)
        self._config = config

        self.log_level_combo.setCurrentText(config.log_level)
        self.log_dir_edit.setText(config.log_dir)
        self.shared_library_sync_dir_edit.setText(config.shared_library_sync_dir)
        policy_index = self.shared_library_sync_policy_combo.findData(
            config.shared_library_sync_policy
        )
        if policy_index < 0:
            policy_index = self.shared_library_sync_policy_combo.findData("manual")
        self.shared_library_sync_policy_combo.setCurrentIndex(policy_index)
        self.shared_library_lock_timeout_spin.setValue(config.shared_library_lock_timeout)
        due_policy_index = self.shared_library_rotation_due_policy_combo.findData(
            config.shared_library_rotation_due_policy
        )
        if due_policy_index < 0:
            due_policy_index = self.shared_library_rotation_due_policy_combo.findData("warn")
        self.shared_library_rotation_due_policy_combo.setCurrentIndex(due_policy_index)
        overdue_policy_index = self.shared_library_rotation_overdue_policy_combo.findData(
            config.shared_library_rotation_overdue_policy
        )
        if overdue_policy_index < 0:
            overdue_policy_index = self.shared_library_rotation_overdue_policy_combo.findData(
                "approval"
            )
        self.shared_library_rotation_overdue_policy_combo.setCurrentIndex(overdue_policy_index)
        self.shared_library_trusted_sources_edit.setPlainText(
            "\n".join(config.shared_library_trusted_source_apps)
        )
        self.shared_library_trusted_signers_edit.setPlainText(
            "\n".join(config.shared_library_trusted_signer_fingerprints)
        )
        self.shared_library_signer_profiles_edit.setPlainText(
            "\n".join(
                dump_shared_library_signer_profile_lines(config.shared_library_signer_profiles)
            )
        )
        self.shared_library_signer_groups_edit.setPlainText(
            "\n".join(dump_shared_library_signer_group_lines(config.shared_library_signer_groups))
        )
        self.shared_library_revoked_signers_edit.setPlainText(
            "\n".join(
                dump_shared_library_revoked_signer_lines(
                    config.shared_library_revoked_signer_records
                )
            )
        )
        self.shared_library_rotation_exceptions_edit.setPlainText(
            "\n".join(
                dump_shared_library_rotation_exception_lines(
                    config.shared_library_rotation_exception_records
                )
            )
        )
        self.shared_library_team_approval_rules_edit.setPlainText(
            "\n".join(
                dump_shared_library_team_approval_rule_lines(
                    config.shared_library_team_approval_rules
                )
            )
        )
        allowed_types = set(config.shared_library_auto_pull_allowed_package_types)
        self.shared_auto_pull_workspace_templates_check.setChecked(
            "workspace_templates" in allowed_types
        )
        self.shared_auto_pull_connection_filter_presets_check.setChecked(
            "connection_filter_presets" in allowed_types
        )
        self.restore_workspace_check.setChecked(config.restore_workspace_on_startup)

        # 连接
        self.timeout_spin.setValue(config.default_timeout)
        self.reconnect_spin.setValue(config.max_reconnect_attempts)

        # 显示
        theme_index = self.theme_combo.findData(config.theme)
        if theme_index < 0:
            theme_index = self.theme_combo.findData("dark")
        self.theme_combo.setCurrentIndex(theme_index)
        terminal_index = self.terminal_backend_combo.findData(config.terminal_backend)
        if terminal_index >= 0:
            self.terminal_backend_combo.setCurrentIndex(terminal_index)
        self.terminal_theme_combo.setCurrentText(config.terminal_theme)
        self.font_size_spin.setValue(config.terminal_font_size)
        self.terminal_snippets_edit.setPlainText(
            "\n".join(dump_terminal_snippet_lines(config.terminal_snippet_groups))
        )
        self.terminal_favorites_edit.setPlainText("\n".join(config.terminal_favorite_snippets))
        self.terminal_macros_edit.setPlainText(
            "\n".join(dump_terminal_macro_lines(config.terminal_macros))
        )

    def get_config(self) -> AppConfig:
        """获取配置"""
        snippet_groups = parse_terminal_snippet_lines(
            self.terminal_snippets_edit.toPlainText().splitlines()
        )
        terminal_macros = parse_terminal_macro_lines(
            self.terminal_macros_edit.toPlainText().splitlines()
        )
        signer_profiles = parse_shared_library_signer_profile_lines(
            self.shared_library_signer_profiles_edit.toPlainText().splitlines()
        )
        signer_groups = parse_shared_library_signer_group_lines(
            self.shared_library_signer_groups_edit.toPlainText().splitlines()
        )
        revoked_signer_records = parse_shared_library_revoked_signer_lines(
            self.shared_library_revoked_signers_edit.toPlainText().splitlines()
        )
        rotation_exception_records = parse_shared_library_rotation_exception_lines(
            self.shared_library_rotation_exceptions_edit.toPlainText().splitlines()
        )
        team_approval_rules = parse_shared_library_team_approval_rule_lines(
            self.shared_library_team_approval_rules_edit.toPlainText().splitlines()
        )

        return AppConfig(
            language=str(self.language_combo.currentData() or "zh_CN"),
            log_level=self.log_level_combo.currentText(),
            log_dir=self.log_dir_edit.text(),
            shared_library_sync_dir=self.shared_library_sync_dir_edit.text().strip(),
            shared_library_sync_policy=self.shared_library_sync_policy_combo.currentData(),
            shared_library_lock_timeout=self.shared_library_lock_timeout_spin.value(),
            shared_library_rotation_due_policy=self.shared_library_rotation_due_policy_combo.currentData(),
            shared_library_rotation_overdue_policy=self.shared_library_rotation_overdue_policy_combo.currentData(),
            shared_library_trusted_source_apps=[
                line.strip()
                for line in self.shared_library_trusted_sources_edit.toPlainText().splitlines()
                if line.strip()
            ],
            shared_library_trusted_signer_fingerprints=[
                line.strip().lower()
                for line in self.shared_library_trusted_signers_edit.toPlainText().splitlines()
                if line.strip()
            ],
            shared_library_signer_profiles=signer_profiles,
            shared_library_signer_groups=signer_groups,
            shared_library_revoked_signer_fingerprints=[
                str(record.get("fingerprint") or "").strip().lower()
                for record in revoked_signer_records
                if str(record.get("fingerprint") or "").strip()
            ],
            shared_library_revoked_signer_records=revoked_signer_records,
            shared_library_rotation_exception_records=rotation_exception_records,
            shared_library_team_approval_rules=team_approval_rules,
            shared_library_auto_pull_allowed_package_types=[
                package_type
                for enabled, package_type in (
                    (
                        self.shared_auto_pull_workspace_templates_check.isChecked(),
                        "workspace_templates",
                    ),
                    (
                        self.shared_auto_pull_connection_filter_presets_check.isChecked(),
                        "connection_filter_presets",
                    ),
                )
                if enabled
            ],
            restore_workspace_on_startup=self.restore_workspace_check.isChecked(),
            default_timeout=self.timeout_spin.value(),
            max_reconnect_attempts=self.reconnect_spin.value(),
            theme=self.theme_combo.currentData(),
            terminal_backend=self.terminal_backend_combo.currentData(),
            terminal_font_size=self.font_size_spin.value(),
            terminal_theme=self.terminal_theme_combo.currentText().strip() or "Ubuntu",
            terminal_snippet_groups=snippet_groups,
            terminal_snippets=[
                command for commands in snippet_groups.values() for command in commands
            ],
            terminal_favorite_snippets=normalize_terminal_favorite_snippets(
                self.terminal_favorites_edit.toPlainText().splitlines(),
                snippet_groups,
            ),
            terminal_macros=terminal_macros,
        )
