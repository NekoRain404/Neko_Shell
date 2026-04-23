#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新版 UI 图标系统。

优先使用系统主题图标，缺失时回退到内置 SVG。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)

ICON_DIR = Path(__file__).resolve().parent / "assets" / "icons"


_ICON_CANDIDATES = {
    "app": ("utilities-terminal", "terminal", "app"),
    "new_connection": ("list-add", "document-new", "add"),
    "quick_connect": ("network-connect", "flash"),
    "local_terminal": ("utilities-terminal", "computer", "terminal"),
    "terminal_split": ("view-split-left-right", "view-split-top-bottom", "split"),
    "tunnel": ("network-vpn", "network-wireless", "tunnel"),
    "docker": ("docker", "package-x-generic", "docker"),
    "frp": ("network-server", "network-workgroup", "frp"),
    "settings": ("preferences-system", "configure", "settings"),
    "about": ("help-about", "dialog-information", "about"),
    "refresh": ("view-refresh", "view-refresh-symbolic", "about"),
    "edit": ("document-edit", "edit"),
    "delete": ("edit-delete", "user-trash", "delete"),
    "ssh": ("network-server", "utilities-terminal", "ssh"),
    "sftp": ("folder-remote", "folder", "sftp"),
    "ftp": ("folder-download", "folder", "ftp"),
    "serial": ("input-keyboard", "computer", "serial"),
    "tcp": ("network-wired", "network-idle", "tcp"),
    "udp": ("network-transmit-receive", "network-idle", "udp"),
    "vnc": ("video-display", "computer", "vnc"),
    "connected": ("emblem-default", "dialog-ok", "status-connected"),
    "connecting": ("view-refresh", "process-working", "status-connecting"),
    "error": ("dialog-error", "process-stop", "status-error"),
    "offline": ("network-offline", "process-stop", "status-offline"),
}


def _theme_icon(names: Iterable[str]) -> QIcon:
    for name in names:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon()


def _bundled_icon(name: str) -> QIcon:
    path = ICON_DIR / f"{name}.svg"
    if path.exists():
        return QIcon(str(path))
    return QIcon()


def _generated_icon(name: str) -> QIcon:
    """生成兜底图标，避免系统主题和内置资源缺失时出现空图标。"""
    if QGuiApplication.instance() is None:
        return QIcon()

    palette = {
        "ssh": ("#3f7ee8", "#1f4ea3"),
        "sftp": ("#2a9d8f", "#1a6c63"),
        "ftp": ("#2b9348", "#1f6b35"),
        "serial": ("#8f5fd7", "#6033a9"),
        "tcp": ("#d17a22", "#a25305"),
        "udp": ("#d95f76", "#af3650"),
        "vnc": ("#d14a7d", "#962751"),
        "docker": ("#2184d8", "#155b96"),
        "frp": ("#5d8f2f", "#41651f"),
        "tunnel": ("#0f7b6c", "#0a564c"),
        "settings": ("#6f7e8d", "#485564"),
        "about": ("#4a7fd1", "#2c4f8b"),
        "delete": ("#c95353", "#933737"),
        "edit": ("#b57821", "#825615"),
        "refresh": ("#4d8a66", "#346047"),
        "app": ("#8a4dd8", "#5a2c93"),
        "default": ("#607d8b", "#405560"),
    }
    accent, shadow = palette.get(name, palette["default"])
    glyph = (name[:1] or "?").upper()

    image = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    outer_rect = QRectF(2.0, 2.0, 28.0, 28.0)
    inner_rect = QRectF(4.5, 4.5, 23.0, 23.0)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(shadow))
    painter.drawRoundedRect(outer_rect, 8.0, 8.0)
    painter.setBrush(QColor(accent))
    painter.drawRoundedRect(inner_rect, 7.0, 7.0)

    painter.setPen(QPen(QColor(255, 255, 255, 110), 1.2))
    painter.drawLine(QPointF(8.0, 10.0), QPointF(24.0, 10.0))

    font = QFont()
    font.setBold(True)
    font.setPointSize(12)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(inner_rect, Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()

    return QIcon(QPixmap.fromImage(image))


def icon(name: str) -> QIcon:
    """返回指定语义名称的图标。"""
    candidates = _ICON_CANDIDATES.get(name, (name,))
    themed = _theme_icon(candidates)
    if not themed.isNull():
        return themed

    for candidate in candidates:
        bundled = _bundled_icon(candidate)
        if not bundled.isNull():
            return bundled

    generated = _generated_icon(str(candidates[0]))
    if not generated.isNull():
        return generated
    return QIcon()


def app_icon() -> QIcon:
    """应用图标。"""
    return icon("app")


def connection_type_icon(connection_type: str) -> QIcon:
    """根据连接类型返回图标。"""
    return icon((connection_type or "ssh").lower())


def status_icon(status_name: str) -> QIcon:
    """根据连接状态返回图标。"""
    return icon(status_name)


def status_brush(status_name: str) -> QBrush:
    """返回连接状态对应的文本颜色。"""
    color_map = {
        "connected": "#4e9368",
        "connecting": "#d18b29",
        "reconnecting": "#d18b29",
        "error": "#c95353",
        "offline": "#7d8c9d",
        "disconnected": "#7d8c9d",
    }
    return QBrush(QColor(color_map.get(status_name, "#7d8c9d")))
