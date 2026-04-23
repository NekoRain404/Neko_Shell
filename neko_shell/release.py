#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发行元数据与运行诊断工具。

为 UI、CLI 与发布链路提供统一的版本来源和可复制的运行摘要。
"""

from __future__ import annotations

import html
import importlib.util
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QStandardPaths, qVersion

from neko_shell.i18n import (
    get_available_languages,
    get_language_display_name,
    get_language_resource_files,
    get_qt_translations_dir,
    normalize_language_code,
    resolve_language_code,
)

APP_NAME = "Neko_Shell"
APP_AUTHOR = "Neko_Shell"
APP_VERSION = "0.1.0"
RELEASE_CHANNEL = "preview"
LICENSE_NAME = "GNU GPL v3.0 or later"
LICENSE_SPDX = "GPL-3.0-or-later"
REPOSITORY_URL = "https://github.com/neko-shell/Neko_Shell"
ISSUES_URL = "https://github.com/neko-shell/Neko_Shell/issues"
DOCUMENTATION_URL = "https://github.com/neko-shell/Neko_Shell#readme"
APP_SUMMARY = "面向个人使用的 Linux 远程连接与运维工作台。"

PREVIEW_RELEASE_CORE_ASSETS = (
    "neko-shell",
    "preview-manifest.json",
    "SHA256SUMS",
    "README.md",
    "LICENSE",
    "docs/USER_GUIDE.md",
    "docs/RELEASE_0.1.0-preview.md",
    "packaging/linux/neko-shell.desktop",
    "neko_shell/ui/assets/icons/app.svg",
)
PREVIEW_RELEASE_GENERATED_ASSETS = (
    "docs/PREVIEW_SELF_CHECK.txt",
    "docs/PREVIEW_DIAGNOSTICS.txt",
    "docs/PREVIEW_ISSUE_TEMPLATE.md",
    "docs/PREVIEW_ACCEPTANCE_CHECKLIST.md",
    "docs/PREVIEW_SUPPORT_BUNDLE.zip",
)


def format_release_channel() -> str:
    """返回适合显示的发布通道文本。"""
    mapping = {
        "preview": "Preview",
        "stable": "Stable",
    }
    normalized = RELEASE_CHANNEL.strip().lower()
    if not normalized:
        return ""
    return mapping.get(normalized, normalized.title())


def format_version_display() -> str:
    """返回适合 UI 展示的版本号。"""
    channel = format_release_channel()
    if not channel:
        return APP_VERSION
    return f"{APP_VERSION} {channel}"


def format_cli_version() -> str:
    """返回 CLI 使用的版本文本。"""
    return f"{APP_NAME} {format_version_display()}"


def get_release_default_config_dir() -> Path:
    """返回默认配置目录，避免依赖 utils 包初始化。"""
    base_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if base_dir:
        base_path = Path(base_dir)
        if base_path.name.lower() == APP_NAME.lower():
            return base_path
        return base_path / APP_NAME
    return Path.home() / ".config" / APP_NAME


def get_release_runtime_root() -> Path:
    """返回当前运行时根目录，避免依赖 utils 包初始化。"""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            return Path(bundle_root)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def get_release_distribution_root() -> Path:
    """返回发布目录根路径。"""
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        parent = executable_dir.parent
        if (parent / "preview-manifest.json").exists():
            return parent
        return executable_dir
    return get_release_runtime_root()


def get_release_linux_commands_path() -> Path:
    """返回命令索引路径。"""
    return get_release_runtime_root() / "conf" / "linux_commands.json"


def get_release_app_icon_path() -> Path:
    """返回应用图标路径。"""
    return get_release_runtime_root() / "neko_shell" / "ui" / "assets" / "icons" / "app.svg"


def get_release_preview_manifest_path() -> Path:
    """返回预览清单路径。"""
    return get_release_distribution_root() / "preview-manifest.json"


def get_release_log_dir(
    *,
    config_dir: Optional[Path] = None,
    app_config: Optional[Any] = None,
) -> Path:
    """返回日志目录。"""
    resolved_config_dir = (
        Path(config_dir) if config_dir is not None else get_release_default_config_dir()
    )
    configured_log_dir = _config_value(app_config, "log_dir", default="logs")
    log_dir = Path(configured_log_dir)
    if log_dir.is_absolute():
        return log_dir
    return resolved_config_dir / configured_log_dir


def _read_preview_manifest() -> Optional[dict[str, Any]]:
    """读取预览清单。"""
    path = get_release_preview_manifest_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@dataclass(frozen=True)
class ReleaseAssetSummary:
    """预览发布包资产完整度摘要。"""

    bundle_status: str
    assets_status: str
    missing_assets: str
    core_missing: tuple[str, ...]
    generated_missing: tuple[str, ...]
    checked: bool

    @property
    def has_core_missing(self) -> bool:
        """是否缺少核心发布资产。"""
        return bool(self.core_missing)

    @property
    def has_generated_missing(self) -> bool:
        """是否缺少构建期生成的反馈资产。"""
        return bool(self.generated_missing)


def _is_preview_release_context(distribution_root: Path) -> bool:
    """判断当前是否处于预览发布目录语境。"""
    return bool(
        getattr(sys, "frozen", False)
        or (distribution_root / "preview-manifest.json").exists()
        or (distribution_root / "neko-shell").exists()
    )


def _missing_release_assets(distribution_root: Path, assets: tuple[str, ...]) -> tuple[str, ...]:
    """返回缺失的发布资产相对路径。"""
    return tuple(asset for asset in assets if not (distribution_root / asset).exists())


def collect_preview_release_asset_status(
    distribution_root: Optional[Path] = None,
    *,
    validate: Optional[bool] = None,
) -> ReleaseAssetSummary:
    """收集 0.1 预览发布包资产完整度。"""
    resolved_root = (
        Path(distribution_root)
        if distribution_root is not None
        else get_release_distribution_root()
    )
    should_validate = _is_preview_release_context(resolved_root) if validate is None else validate
    if not should_validate:
        return ReleaseAssetSummary(
            bundle_status="源码运行，未进入发布包校验",
            assets_status="未检测到预览发布目录",
            missing_assets="-",
            core_missing=(),
            generated_missing=(),
            checked=False,
        )

    core_missing = _missing_release_assets(resolved_root, PREVIEW_RELEASE_CORE_ASSETS)
    generated_missing = _missing_release_assets(
        resolved_root,
        PREVIEW_RELEASE_GENERATED_ASSETS,
    )
    core_total = len(PREVIEW_RELEASE_CORE_ASSETS)
    generated_total = len(PREVIEW_RELEASE_GENERATED_ASSETS)
    core_available = core_total - len(core_missing)
    generated_available = generated_total - len(generated_missing)

    if core_missing:
        bundle_status = f"核心资产缺失 {len(core_missing)} 项"
    elif generated_missing:
        bundle_status = f"反馈材料待生成 {len(generated_missing)} 项"
    else:
        bundle_status = "完整"

    missing_assets = " / ".join(core_missing + generated_missing) or "-"
    return ReleaseAssetSummary(
        bundle_status=bundle_status,
        assets_status=(
            f"核心资产 {core_available}/{core_total}，"
            f"反馈材料 {generated_available}/{generated_total}"
        ),
        missing_assets=missing_assets,
        core_missing=core_missing,
        generated_missing=generated_missing,
        checked=True,
    )


def build_about_overview_html() -> str:
    """返回统一的关于页说明 HTML。"""
    return f"""
    <h2>{APP_NAME}</h2>
    <p><b>版本:</b> {html.escape(format_version_display())}</p>
    <p><b>作者:</b> {html.escape(APP_AUTHOR)}</p>
    <p>
        {html.escape(APP_NAME)} 是一个面向个人远程运维场景的桌面客户端，
        提供连接管理、终端操作、文件传输、VNC、Docker、FRP 和 SSH 隧道等能力。
    </p>
    <h3>当前重点能力</h3>
    <ul>
        <li>SSH / SFTP / FTP / 串口 / TCP / UDP / VNC</li>
        <li>文件浏览、批量传输、压缩解压与权限修改</li>
        <li>会话管理、最近连接、收藏、工作区恢复</li>
        <li>Docker / FRP / SSH 隧道等辅助运维入口</li>
    </ul>
    <p>
        本项目按 {html.escape(LICENSE_NAME)} 发布，不提供任何明示或暗示担保。
    </p>
    """


def build_feedback_overview_html() -> str:
    """返回统一的问题反馈说明 HTML。"""
    return f"""
    <h3>预览版反馈建议</h3>
    <ol>
        <li>优先导出支持包：<code>neko-shell --export-support-bundle &lt;文件&gt;</code>。</li>
        <li>发布前或反馈前可执行 <code>neko-shell --acceptance-checklist</code> 生成预览版验收清单。</li>
        <li>如需单独整理，也可执行 <code>neko-shell --self-check</code>、<code>neko-shell --export-diagnostic &lt;文件&gt;</code>、<code>neko-shell --issue-template</code> 或 <code>neko-shell --export-issue-template &lt;文件&gt;</code>。</li>
        <li>支持包会自动包含运行摘要、运行诊断、验收清单和问题反馈模板；日志和配置内容仍建议手动筛选后再附上。</li>
        <li>通过 <a href="{html.escape(ISSUES_URL)}">GitHub Issues</a> 提交反馈。</li>
    </ol>
    """


def build_license_overview_html() -> str:
    """返回统一的许可证说明 HTML。"""
    return f"""
    <h2>GNU General Public License</h2>
    <p><b>版本:</b> {html.escape(LICENSE_NAME)}</p>
    <p><b>SPDX:</b> {html.escape(LICENSE_SPDX)}</p>
    <p>
        本项目是自由软件；你可以在 GNU 通用公共许可证第 3 版
        或其后续版本条款下重新分发和修改它。
    </p>
    <p>
        本程序按“希望它有用”的目的发布，但 <b>没有任何担保</b>，
        包括但不限于适销性或特定用途适用性的默示担保。
    </p>
    <p>
        完整许可证文本请查看仓库根目录中的 <code>LICENSE</code> 文件。
    </p>
    <p>
        官方说明：
        <a href="https://www.gnu.org/licenses/gpl-3.0.html">
            https://www.gnu.org/licenses/gpl-3.0.html
        </a>
    </p>
    """


def build_credits_html() -> str:
    """返回统一的开源致谢 HTML。"""
    return """
    <h2>致谢</h2>
    <p>本项目基于下列开源项目与生态构建：</p>
    <ul>
        <li>PySide6: Qt for Python 图形界面框架</li>
        <li>Paramiko: SSH 与 SFTP 支持</li>
        <li>pyserial: 串口通信支持</li>
        <li>qtermwidget: 终端渲染与交互支持</li>
        <li>PyYAML / keyring: 配置与安全存储能力</li>
    </ul>
    <p>感谢所有上游维护者、测试者与贡献者。</p>
    """


def _has_module(*module_names: str) -> bool:
    """判断模块是否可导入。"""
    return any(importlib.util.find_spec(module_name) is not None for module_name in module_names)


def _bool_label(value: bool) -> str:
    """将布尔值转换为可读文本。"""
    return "可用" if value else "缺失"


def _format_language_entry(language: str) -> str:
    """将语言代码格式化为“代码 (名称)”文本。"""
    normalized = normalize_language_code(language)
    display_name = get_language_display_name(normalized)
    if display_name == normalized:
        return normalized
    return f"{normalized} ({display_name})"


def _format_effective_language_entry(configured_language: str, effective_language: str) -> str:
    """格式化实际生效语言，必要时附带回退说明。"""
    entry = _format_language_entry(effective_language)
    normalized_configured = normalize_language_code(configured_language)
    if normalized_configured == effective_language:
        return entry
    return f"{entry}，已从 {configured_language} 回退"


def _format_available_languages(languages: list[str]) -> str:
    """格式化可用语言列表。"""
    if not languages:
        return "-"
    return " / ".join(_format_language_entry(language) for language in languages)


def _describe_language_resources(languages: list[str]) -> str:
    """生成当前语言资源摘要。"""
    if len(languages) == 1 and languages[0] == "zh_CN":
        return "未发现外部语言包，仅使用内置中文源字符串"

    details: list[str] = []
    for language in languages:
        resource_files = get_language_resource_files(language)
        if language == "zh_CN" and not resource_files:
            details.append(f"{_format_language_entry(language)}: 内置中文源字符串")
            continue
        resource_names = ", ".join(path.name for path in resource_files) or "内置中文源字符串"
        if language == "zh_CN":
            details.append(f"{_format_language_entry(language)}: 内置中文 + {resource_names}")
        else:
            details.append(f"{_format_language_entry(language)}: {resource_names}")
    return "；".join(details)


def _config_value(app_config: Optional[Any], attribute: str, default: str = "-") -> str:
    """安全读取应用配置字段。"""
    if app_config is None:
        return default
    value = getattr(app_config, attribute, None)
    if value in (None, ""):
        return default
    return str(value)


def _detect_git_metadata(runtime_root: Path) -> tuple[str, str, str]:
    """尝试从源码仓库中读取提交信息。"""
    if getattr(sys, "frozen", False):
        return "-", "-", "-"
    if not (runtime_root / ".git").exists():
        return "-", "-", "-"
    try:
        revision = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=runtime_root,
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            ).stdout.strip()
            or "-"
        )
    except (OSError, subprocess.SubprocessError):
        return "-", "-", "-"

    try:
        status_output = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=runtime_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        ).stdout.strip()
        tree_state = "dirty" if status_output else "clean"
    except (OSError, subprocess.SubprocessError):
        tree_state = "-"
    return revision, tree_state, "git"


@dataclass(frozen=True)
class RuntimeSummary:
    """运行摘要。"""

    version_display: str
    release_channel: str
    runtime_mode: str
    platform_name: str
    python_version: str
    qt_version: str
    pyside_version: str
    executable_path: str
    runtime_root: str
    distribution_root: str
    release_bundle_status: str
    release_assets_status: str
    release_missing_assets: str
    config_dir: str
    log_dir: str
    log_dir_status: str
    user_guide_path: str
    user_guide_status: str
    command_index_path: str
    command_index_status: str
    app_icon_path: str
    app_icon_status: str
    preview_manifest_path: str
    preview_manifest_status: str
    preview_manifest_channel: str
    preview_manifest_built_at: str
    build_revision: str
    build_tree_state: str
    build_revision_source: str
    theme: str
    language: str
    effective_language: str
    available_languages: str
    app_translations_dir: str
    app_translations_status: str
    terminal_backend: str
    terminal_theme: str
    cryptography_status: str
    vnc_crypto_status: str
    qtermwidget_status: str

    def to_pairs(self) -> list[tuple[str, str]]:
        """转换为标签-值列表。"""
        return [
            ("应用", APP_NAME),
            ("版本", self.version_display),
            ("发布通道", self.release_channel),
            ("运行模式", self.runtime_mode),
            ("平台", self.platform_name),
            ("Python", self.python_version),
            ("Qt", self.qt_version),
            ("PySide6", self.pyside_version),
            ("可执行文件", self.executable_path),
            ("运行目录", self.runtime_root),
            ("发布目录", self.distribution_root),
            ("发布包状态", self.release_bundle_status),
            ("发布资产", self.release_assets_status),
            ("缺失资产", self.release_missing_assets),
            ("配置目录", self.config_dir),
            ("日志目录", self.log_dir_status),
            ("日志路径", self.log_dir),
            ("使用手册", self.user_guide_status),
            ("手册路径", self.user_guide_path),
            ("命令索引", self.command_index_status),
            ("命令索引路径", self.command_index_path),
            ("应用图标", self.app_icon_status),
            ("图标路径", self.app_icon_path),
            ("预览清单", self.preview_manifest_status),
            ("清单路径", self.preview_manifest_path),
            ("清单通道", self.preview_manifest_channel),
            ("构建时间", self.preview_manifest_built_at),
            ("构建提交", self.build_revision),
            ("源码状态", self.build_tree_state),
            ("来源渠道", self.build_revision_source),
            ("界面主题", self.theme),
            ("配置语言", _format_language_entry(self.language)),
            ("实际语言", _format_effective_language_entry(self.language, self.effective_language)),
            ("可用语言", self.available_languages),
            ("语言资源", self.app_translations_status),
            ("语言资源目录", self.app_translations_dir),
            ("终端后端", self.terminal_backend),
            ("终端主题", self.terminal_theme),
            ("cryptography", self.cryptography_status),
            ("VNC DES 依赖", self.vnc_crypto_status),
            ("QTermWidget", self.qtermwidget_status),
        ]

    def to_text(self) -> str:
        """转换为可复制的纯文本摘要。"""
        return "\n".join(f"{label}: {value}" for label, value in self.to_pairs())

    def to_html(self) -> str:
        """转换为表格 HTML。"""
        rows = "".join(
            (f"<tr><td><b>{html.escape(label)}</b></td>" f"<td>{html.escape(value)}</td></tr>")
            for label, value in self.to_pairs()
        )
        return (
            "<h3>运行摘要</h3>"
            "<p>建议在反馈 0.1 预览版问题时一并附上下面这段摘要。</p>"
            '<table cellspacing="6" cellpadding="2">'
            f"{rows}"
            "</table>"
        )


@dataclass(frozen=True)
class DiagnosticCheck:
    """诊断检查项。"""

    label: str
    status: str
    detail: str
    required: bool = False

    @property
    def ok(self) -> bool:
        """当前检查是否通过。"""
        return self.status != "fail"

    @property
    def status_text(self) -> str:
        """状态文案。"""
        mapping = {
            "pass": "通过",
            "warn": "警告",
            "fail": "失败",
        }
        return mapping.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        """状态颜色。"""
        mapping = {
            "pass": "#1f8f5f",
            "warn": "#b7791f",
            "fail": "#c53030",
        }
        return mapping.get(self.status, "#4a5568")


@dataclass(frozen=True)
class RuntimeDiagnosticReport:
    """运行诊断报告。"""

    summary: RuntimeSummary
    checks: list[DiagnosticCheck]

    @property
    def ok(self) -> bool:
        """所有必需检查是否通过。"""
        return all(check.ok or not check.required for check in self.checks)

    def to_text(self) -> str:
        """转换为纯文本。"""
        lines = [
            f"{APP_NAME} 运行诊断",
            "=" * 32,
            self.summary.to_text(),
            "",
            "检查结果:",
        ]
        for check in self.checks:
            required = "必需" if check.required else "可选"
            lines.append(f"- [{check.status_text}] {check.label} ({required}): {check.detail}")
        lines.append("")
        lines.append(f"综合结果: {'通过' if self.ok else '失败'}")
        return "\n".join(lines)

    def to_html(self) -> str:
        """转换为富文本。"""
        rows = "".join(
            (
                "<tr>"
                f"<td><b>{html.escape(check.label)}</b></td>"
                f'<td><span style="color: {check.status_color};">{html.escape(check.status_text)}</span></td>'
                f"<td>{html.escape('必需' if check.required else '可选')}</td>"
                f"<td>{html.escape(check.detail)}</td>"
                "</tr>"
            )
            for check in self.checks
        )
        overall = "通过" if self.ok else "失败"
        overall_color = "#1f8f5f" if self.ok else "#c53030"
        return (
            self.summary.to_html()
            + "<h3>运行自检</h3>"
            + "<p>下面的检查项用于确认 0.1 预览版是否具备基本运行条件。</p>"
            + '<table cellspacing="6" cellpadding="2">'
            + "<tr><th align='left'>项目</th><th align='left'>状态</th><th align='left'>类型</th><th align='left'>说明</th></tr>"
            + rows
            + "</table>"
            + f'<p><b>综合结果:</b> <span style="color: {overall_color};">{overall}</span></p>'
        )


def build_issue_feedback_template(report: RuntimeDiagnosticReport) -> str:
    """构造可直接填写的问题反馈模板。"""
    summary = report.summary
    lines = [
        f"# {APP_NAME} 预览版问题反馈",
        "",
        "## 环境信息",
        f"- 版本: {summary.version_display}",
        f"- 发布通道: {summary.release_channel}",
        f"- 平台: {summary.platform_name}",
        f"- 运行模式: {summary.runtime_mode}",
        f"- 发布包状态: {summary.release_bundle_status}",
        f"- 发布资产: {summary.release_assets_status}",
        f"- Python: {summary.python_version}",
        f"- Qt / PySide6: {summary.qt_version} / {summary.pyside_version}",
        f"- 构建提交: {summary.build_revision}",
        f"- 源码状态: {summary.build_tree_state}",
        f"- 来源渠道: {summary.build_revision_source}",
        "",
        "## 问题描述",
        "- 现象:",
        "- 期望结果:",
        "- 实际结果:",
        "",
        "## 复现步骤",
        "1. ",
        "2. ",
        "3. ",
        "",
        "## 附件检查",
        "- [ ] 已附诊断报告",
        "- [ ] 已附截图",
        "- [ ] 已附关键日志",
        "- [ ] 已说明是否源码运行或冻结二进制运行",
        "",
        "## 运行摘要",
        "```text",
        summary.to_text(),
        "```",
        "",
        "## 运行自检",
        "```text",
        report.to_text(),
        "```",
        "",
        f"> 建议通过 {ISSUES_URL} 提交，并保留对诊断报告文件路径或关键日志位置的说明。",
    ]
    return "\n".join(lines)


def _markdown_checkbox(done: bool) -> str:
    """返回 Markdown 复选框。"""
    return "[x]" if done else "[ ]"


def _path_exists(path_text: str) -> bool:
    """安全判断摘要中的路径是否存在。"""
    if not path_text or path_text == "-":
        return False
    try:
        return Path(path_text).exists()
    except OSError:
        return False


def build_preview_acceptance_checklist(report: RuntimeDiagnosticReport) -> str:
    """构造 0.1 预览版验收清单。"""
    summary = report.summary
    distribution_root = Path(summary.distribution_root)
    manifest_path = Path(summary.preview_manifest_path)
    checksum_path = distribution_root / "SHA256SUMS"
    release_notes_path = distribution_root / "docs" / "RELEASE_0.1.0-preview.md"
    user_guide_path = Path(summary.user_guide_path)
    desktop_file_path = distribution_root / "packaging" / "linux" / "neko-shell.desktop"

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    binary_mode = summary.runtime_mode == "冻结二进制"
    smoke_prefix = (
        "QT_QPA_PLATFORM=offscreen ./neko-shell/neko-shell"
        if binary_mode
        else "QT_QPA_PLATFORM=offscreen python -m neko_shell.main"
    )
    command_prefix = "./neko-shell/neko-shell" if binary_mode else "python -m neko_shell.main"

    lines = [
        f"# {APP_NAME} 0.1 预览版验收清单",
        "",
        "## 基本信息",
        f"- 版本: {summary.version_display}",
        f"- 发布通道: {summary.release_channel}",
        f"- 运行模式: {summary.runtime_mode}",
        f"- 平台: {summary.platform_name}",
        f"- 生成时间(UTC): {generated_at}",
        f"- 发布包状态: {summary.release_bundle_status}",
        f"- 发布资产: {summary.release_assets_status}",
        f"- 构建提交: {summary.build_revision}",
        f"- 源码状态: {summary.build_tree_state}",
        f"- 来源渠道: {summary.build_revision_source}",
        "",
        "## 自动运行自检",
    ]

    for check in report.checks:
        required_text = "必需" if check.required else "可选"
        lines.append(
            f"- {_markdown_checkbox(check.ok)} {check.label} ({required_text}, {check.status_text}): {check.detail}"
        )

    lines.extend(
        [
            "",
            "## 发行产物检查",
            f"- {_markdown_checkbox(_path_exists(str(manifest_path)))} `preview-manifest.json` 存在并可读取: `{manifest_path}`",
            f"- {_markdown_checkbox(_path_exists(str(checksum_path)))} `SHA256SUMS` 存在: `{checksum_path}`",
            f"- {_markdown_checkbox(_path_exists(str(user_guide_path)))} `docs/USER_GUIDE.md` 存在: `{user_guide_path}`",
            f"- {_markdown_checkbox(_path_exists(str(release_notes_path)))} `docs/RELEASE_0.1.0-preview.md` 存在: `{release_notes_path}`",
            f"- {_markdown_checkbox(_path_exists(str(desktop_file_path)))} Linux 桌面文件存在: `{desktop_file_path}`",
            f"- {_markdown_checkbox(_path_exists(summary.app_icon_path))} 应用图标存在: `{summary.app_icon_path}`",
            "",
            "## 命令行验收",
            f"- [ ] `{command_prefix} --version` 可以输出版本号。",
            f"- [ ] `{command_prefix} --self-check` 综合结果为通过，或者可选依赖缺失已被接受。",
            f"- [ ] `{command_prefix} --acceptance-checklist` 可以输出本清单。",
            f"- [ ] `{command_prefix} --export-diagnostic ./neko-shell-diagnostics.txt` 可以生成诊断报告。",
            f"- [ ] `{command_prefix} --export-issue-template ./neko-shell-issue.md` 可以生成反馈模板。",
            f"- [ ] `{command_prefix} --export-support-bundle ./neko-shell-support-bundle.zip` 可以生成支持包。",
            f"- [ ] `{smoke_prefix} --smoke-test` 可以完成离屏 GUI 启动验证。",
            "",
            "## GUI 基础验收",
            "- [ ] 主窗口可以正常启动和关闭。",
            "- [ ] 帮助中心可以打开，并能读取 `docs/USER_GUIDE.md`。",
            "- [ ] 关于页可以复制诊断信息、复制验收清单、复制反馈模板。",
            "- [ ] 关于页可以导出诊断报告、验收清单、反馈模板和支持包。",
            "- [ ] 设置页可以切换深色、浅色、护眼和跟随系统主题。",
            "",
            "## 个人核心工作流验收",
            "- [ ] 可以新建、编辑、收藏、删除一个 SSH 连接配置。",
            "- [ ] 可以打开本地终端，右键菜单中的复制、粘贴、清屏、搜索等动作可用。",
            "- [ ] 可以打开 SSH 终端，连接失败时有明确错误提示且不会卡死 UI。",
            "- [ ] 可以从连接右键菜单打开文件视图，并完成目录浏览。",
            "- [ ] SFTP 文件视图可以上传、下载、刷新目录、右键打开常用文件动作。",
            "- [ ] 系统监控面板能显示 CPU、内存、交换、磁盘、网络、负载和主机信息。",
            "- [ ] 快速打开、最近连接、收藏连接符合个人高频使用路径。",
            "",
            "## 反馈前确认",
            "- [ ] 反馈前已生成支持包。",
            "- [ ] 已补充复现步骤、截图或关键日志。",
            "- [ ] 未直接上传包含密码、私钥、Token 的配置或日志。",
            "",
            f"> 问题反馈地址: {ISSUES_URL}",
        ]
    )
    return "\n".join(lines)


def _check_path(
    label: str,
    path: Path,
    *,
    required: bool,
    success_detail: Optional[str] = None,
) -> DiagnosticCheck:
    """构造路径检查。"""
    if path.exists():
        return DiagnosticCheck(
            label=label,
            status="pass",
            detail=success_detail or str(path),
            required=required,
        )
    return DiagnosticCheck(
        label=label,
        status="fail" if required else "warn",
        detail=f"未找到: {path}",
        required=required,
    )


def _check_module(
    label: str,
    *,
    available: bool,
    required: bool,
    available_detail: str,
    missing_detail: str,
) -> DiagnosticCheck:
    """构造模块检查。"""
    return DiagnosticCheck(
        label=label,
        status="pass" if available else ("fail" if required else "warn"),
        detail=available_detail if available else missing_detail,
        required=required,
    )


def _check_config_dir(config_dir: Path) -> DiagnosticCheck:
    """检查配置目录可写。"""
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        probe = config_dir / ".neko_shell_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return DiagnosticCheck(
            label="配置目录可写",
            status="pass",
            detail=str(config_dir),
            required=True,
        )
    except OSError as exc:
        return DiagnosticCheck(
            label="配置目录可写",
            status="fail",
            detail=f"{config_dir} 不可写: {exc}",
            required=True,
        )


def _check_language_configuration(summary: RuntimeSummary) -> DiagnosticCheck:
    """检查当前配置语言是否与实际可用语言一致。"""
    if summary.language == summary.effective_language:
        return DiagnosticCheck(
            label="界面语言配置",
            status="pass",
            detail=(
                f"当前使用 {_format_language_entry(summary.effective_language)}；"
                f"{summary.app_translations_status}"
            ),
            required=False,
        )

    return DiagnosticCheck(
        label="界面语言配置",
        status="warn",
        detail=(
            f"配置为 {_format_language_entry(summary.language)}，"
            f"实际回退为 {_format_language_entry(summary.effective_language)}；"
            f"{summary.app_translations_status}"
        ),
        required=False,
    )


def _check_preview_release_assets(summary: RuntimeSummary) -> DiagnosticCheck:
    """检查预览发布包资产完整度。"""
    if summary.release_bundle_status.startswith("源码运行"):
        return DiagnosticCheck(
            label="预览发布包资产",
            status="pass",
            detail="源码运行模式，跳过发布目录完整性校验。",
            required=False,
        )

    detail = f"{summary.release_assets_status}；缺失: {summary.release_missing_assets}"
    if summary.release_bundle_status.startswith("核心资产缺失"):
        return DiagnosticCheck(
            label="预览发布包资产",
            status="fail",
            detail=detail,
            required=summary.runtime_mode == "冻结二进制",
        )
    if summary.release_bundle_status.startswith("反馈材料待生成"):
        return DiagnosticCheck(
            label="预览发布包资产",
            status="warn",
            detail=detail,
            required=False,
        )
    return DiagnosticCheck(
        label="预览发布包资产",
        status="pass",
        detail=detail,
        required=summary.runtime_mode == "冻结二进制",
    )


def collect_runtime_diagnostic_report(
    *,
    config_dir: Optional[Path] = None,
    guide_path: Optional[Path] = None,
    app_config: Optional[Any] = None,
) -> RuntimeDiagnosticReport:
    """收集完整运行诊断。"""
    summary = collect_runtime_summary(
        config_dir=config_dir,
        guide_path=guide_path,
        app_config=app_config,
    )
    command_index_path = Path(summary.command_index_path)
    icon_path = Path(summary.app_icon_path)
    guide_file_path = Path(summary.user_guide_path)
    manifest_path = Path(summary.preview_manifest_path)

    checks = [
        _check_path("日志目录", Path(summary.log_dir), required=False),
        _check_path("使用手册资源", guide_file_path, required=True),
        _check_path("命令索引资源", command_index_path, required=True),
        _check_path("应用图标资源", icon_path, required=False),
        _check_path(
            "预览清单",
            manifest_path,
            required=False,
            success_detail=f"{manifest_path} ({summary.preview_manifest_channel or '-'})",
        ),
        _check_preview_release_assets(summary),
        _check_config_dir(Path(summary.config_dir)),
        _check_language_configuration(summary),
        _check_module(
            "QTermWidget 后端",
            available=summary.qtermwidget_status == "可用",
            required=False,
            available_detail="已安装，可使用更完整的终端后端。",
            missing_detail="未安装，将自动回退到经典终端。",
        ),
        _check_module(
            "cryptography",
            available=summary.cryptography_status == "可用",
            required=False,
            available_detail="已安装，可使用配置加密与签名能力。",
            missing_detail="未安装，配置加密与签名能力受限。",
        ),
        _check_module(
            "VNC DES 依赖",
            available=summary.vnc_crypto_status == "可用",
            required=False,
            available_detail="已安装，可使用 VNC 密码认证。",
            missing_detail="未安装，VNC 密码认证可能不可用。",
        ),
    ]
    return RuntimeDiagnosticReport(summary=summary, checks=checks)


def collect_runtime_summary(
    *,
    config_dir: Optional[Path] = None,
    guide_path: Optional[Path] = None,
    app_config: Optional[Any] = None,
) -> RuntimeSummary:
    """收集运行环境摘要。"""
    resolved_config_dir = (
        Path(config_dir) if config_dir is not None else get_release_default_config_dir()
    )
    resolved_guide_path = (
        Path(guide_path)
        if guide_path is not None
        else get_release_runtime_root() / "docs" / "USER_GUIDE.md"
    )
    command_index_path = get_release_linux_commands_path()
    icon_path = get_release_app_icon_path()
    manifest_path = get_release_preview_manifest_path()
    distribution_root = get_release_distribution_root()
    release_asset_summary = collect_preview_release_asset_status(distribution_root)
    log_dir_path = get_release_log_dir(
        config_dir=resolved_config_dir,
        app_config=app_config,
    )
    manifest_payload = _read_preview_manifest() or {}
    source_revision, source_tree_state, source_channel = _detect_git_metadata(
        get_release_runtime_root()
    )
    configured_language = _config_value(app_config, "language", default="zh_CN")
    effective_language = resolve_language_code(configured_language)
    available_languages = get_available_languages()
    translations_dir = get_qt_translations_dir()
    build_revision = str(manifest_payload.get("git_commit") or source_revision or "-")
    build_tree_state = str(manifest_payload.get("git_tree_state") or source_tree_state or "-")
    build_revision_source = str(manifest_payload.get("git_source") or source_channel or "-")
    guide_status = "可用" if resolved_guide_path.exists() else "缺失"
    log_dir_status = "可用" if log_dir_path.exists() else "缺失"
    command_index_status = "可用" if command_index_path.exists() else "缺失"
    icon_status = "可用" if icon_path.exists() else "缺失"
    manifest_status = "可用" if manifest_path.exists() else "缺失"
    return RuntimeSummary(
        version_display=format_version_display(),
        release_channel=format_release_channel() or "-",
        runtime_mode="冻结二进制" if getattr(sys, "frozen", False) else "源码运行",
        platform_name=sys.platform,
        python_version=sys.version.split()[0],
        qt_version=qVersion(),
        pyside_version=PYSIDE_VERSION,
        executable_path=sys.executable,
        runtime_root=str(get_release_runtime_root()),
        distribution_root=str(distribution_root),
        release_bundle_status=release_asset_summary.bundle_status,
        release_assets_status=release_asset_summary.assets_status,
        release_missing_assets=release_asset_summary.missing_assets,
        config_dir=str(resolved_config_dir),
        log_dir=str(log_dir_path),
        log_dir_status=log_dir_status,
        user_guide_path=str(resolved_guide_path),
        user_guide_status=guide_status,
        command_index_path=str(command_index_path),
        command_index_status=command_index_status,
        app_icon_path=str(icon_path),
        app_icon_status=icon_status,
        preview_manifest_path=str(manifest_path),
        preview_manifest_status=manifest_status,
        preview_manifest_channel=str(manifest_payload.get("channel") or "-"),
        preview_manifest_built_at=str(manifest_payload.get("built_at_utc") or "-"),
        build_revision=build_revision,
        build_tree_state=build_tree_state,
        build_revision_source=build_revision_source,
        theme=_config_value(app_config, "theme"),
        language=configured_language,
        effective_language=effective_language,
        available_languages=_format_available_languages(available_languages),
        app_translations_dir=str(translations_dir),
        app_translations_status=_describe_language_resources(available_languages),
        terminal_backend=_config_value(app_config, "terminal_backend"),
        terminal_theme=_config_value(app_config, "terminal_theme"),
        cryptography_status=_bool_label(_has_module("cryptography")),
        vnc_crypto_status=_bool_label(_has_module("Crypto", "Cryptodome", "pyDes")),
        qtermwidget_status=_bool_label(_has_module("qtermwidget")),
    )


def get_default_diagnostic_export_path(
    timestamp: Optional[datetime] = None,
) -> Path:
    """返回默认诊断报告导出路径。"""
    resolved_timestamp = timestamp or datetime.now()
    filename = f"neko-shell-diagnostics-{resolved_timestamp.strftime('%Y%m%d-%H%M%S')}.txt"
    return Path.home() / filename


def get_default_issue_template_export_path(
    timestamp: Optional[datetime] = None,
) -> Path:
    """返回默认问题反馈模板导出路径。"""
    resolved_timestamp = timestamp or datetime.now()
    filename = f"neko-shell-issue-template-{resolved_timestamp.strftime('%Y%m%d-%H%M%S')}.md"
    return Path.home() / filename


def get_default_support_bundle_export_path(
    timestamp: Optional[datetime] = None,
) -> Path:
    """返回默认支持包导出路径。"""
    resolved_timestamp = timestamp or datetime.now()
    filename = f"neko-shell-support-bundle-{resolved_timestamp.strftime('%Y%m%d-%H%M%S')}.zip"
    return Path.home() / filename


def get_default_acceptance_checklist_export_path(
    timestamp: Optional[datetime] = None,
) -> Path:
    """返回默认验收清单导出路径。"""
    resolved_timestamp = timestamp or datetime.now()
    filename = (
        f"neko-shell-acceptance-checklist-" f"{resolved_timestamp.strftime('%Y%m%d-%H%M%S')}.md"
    )
    return Path.home() / filename


def export_runtime_diagnostic_report(
    output_path: Path,
    *,
    config_dir: Optional[Path] = None,
    guide_path: Optional[Path] = None,
    app_config: Optional[Any] = None,
) -> RuntimeDiagnosticReport:
    """导出运行诊断报告。"""
    report = collect_runtime_diagnostic_report(
        config_dir=config_dir,
        guide_path=guide_path,
        app_config=app_config,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.to_text() + "\n", encoding="utf-8")
    return report


def export_issue_feedback_template(
    output_path: Path,
    *,
    config_dir: Optional[Path] = None,
    guide_path: Optional[Path] = None,
    app_config: Optional[Any] = None,
) -> RuntimeDiagnosticReport:
    """导出问题反馈模板。"""
    report = collect_runtime_diagnostic_report(
        config_dir=config_dir,
        guide_path=guide_path,
        app_config=app_config,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_issue_feedback_template(report) + "\n",
        encoding="utf-8",
    )
    return report


def export_preview_acceptance_checklist(
    output_path: Path,
    *,
    config_dir: Optional[Path] = None,
    guide_path: Optional[Path] = None,
    app_config: Optional[Any] = None,
) -> RuntimeDiagnosticReport:
    """导出 0.1 预览版验收清单。"""
    report = collect_runtime_diagnostic_report(
        config_dir=config_dir,
        guide_path=guide_path,
        app_config=app_config,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_preview_acceptance_checklist(report) + "\n",
        encoding="utf-8",
    )
    return report


def export_support_bundle(
    output_path: Path,
    *,
    config_dir: Optional[Path] = None,
    guide_path: Optional[Path] = None,
    app_config: Optional[Any] = None,
) -> RuntimeDiagnosticReport:
    """导出用于问题反馈的支持包。"""
    report = collect_runtime_diagnostic_report(
        config_dir=config_dir,
        guide_path=guide_path,
        app_config=app_config,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    exported_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    issue_template = build_issue_feedback_template(report) + "\n"
    acceptance_checklist = build_preview_acceptance_checklist(report) + "\n"
    support_manifest = {
        "name": APP_NAME,
        "version": report.summary.version_display,
        "release_channel": report.summary.release_channel,
        "runtime_mode": report.summary.runtime_mode,
        "platform": report.summary.platform_name,
        "release_bundle_status": report.summary.release_bundle_status,
        "release_assets_status": report.summary.release_assets_status,
        "release_missing_assets": report.summary.release_missing_assets,
        "exported_at_utc": exported_at_utc,
        "build_revision": report.summary.build_revision,
        "build_tree_state": report.summary.build_tree_state,
        "build_revision_source": report.summary.build_revision_source,
        "issue_url": ISSUES_URL,
        "artifacts": [
            "README.txt",
            "runtime-summary.txt",
            "runtime-diagnostics.txt",
            "acceptance-checklist.md",
            "issue-template.md",
            "support-bundle-manifest.json",
        ],
    }
    bundle_root = "neko-shell-support-bundle"
    readme_text = "\n".join(
        [
            f"{APP_NAME} 预览版支持包",
            "=" * 24,
            f"版本: {report.summary.version_display}",
            f"运行模式: {report.summary.runtime_mode}",
            f"平台: {report.summary.platform_name}",
            f"发布包状态: {report.summary.release_bundle_status}",
            f"导出时间(UTC): {exported_at_utc}",
            f"构建提交: {report.summary.build_revision}",
            f"问题反馈地址: {ISSUES_URL}",
            "",
            "包含文件:",
            "- runtime-summary.txt",
            "- runtime-diagnostics.txt",
            "- acceptance-checklist.md",
            "- issue-template.md",
            "- support-bundle-manifest.json",
            "",
            "说明:",
            "- 支持包默认不自动打包日志和配置内容，避免误传敏感信息。",
            f"- 如需补充日志，请根据以下路径手动筛选: {report.summary.log_dir}",
            f"- 如需补充配置，请根据以下路径手动筛选: {report.summary.config_dir}",
        ]
    )

    with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{bundle_root}/README.txt", readme_text + "\n")
        archive.writestr(
            f"{bundle_root}/runtime-summary.txt",
            report.summary.to_text() + "\n",
        )
        archive.writestr(
            f"{bundle_root}/runtime-diagnostics.txt",
            report.to_text() + "\n",
        )
        archive.writestr(
            f"{bundle_root}/acceptance-checklist.md",
            acceptance_checklist,
        )
        archive.writestr(f"{bundle_root}/issue-template.md", issue_template)
        archive.writestr(
            f"{bundle_root}/support-bundle-manifest.json",
            json.dumps(support_manifest, ensure_ascii=False, indent=2) + "\n",
        )
        preview_manifest_path = Path(report.summary.preview_manifest_path)
        if preview_manifest_path.exists():
            archive.write(
                preview_manifest_path,
                arcname=f"{bundle_root}/preview-manifest.json",
            )
    return report
