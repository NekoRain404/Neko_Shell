#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主题模块。

提供 dark、light、eye_care 以及 auto 主题解析。
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def _build_theme(
    name: str,
    *,
    window_bg: str,
    window_bg_alt: str,
    window_text: str,
    muted_text: str,
    panel_bg: str,
    panel_alt_bg: str,
    border: str,
    border_strong: str,
    accent: str,
    accent_hover: str,
    accent_pressed: str,
    accent_soft: str,
    input_bg: str,
    input_text: str,
    selection_bg: str,
    selection_text: str,
    menu_bg: str,
    toolbar_bg: str,
    status_bg: str,
    status_text: str,
    progress_bg: str,
    progress_chunk: str,
    terminal_bg: str,
    terminal_text: str,
    terminal_prompt: str,
    terminal_error: str,
    success: str,
    info: str,
) -> Dict[str, Any]:
    """构造统一主题配置。"""
    return {
        "name": name,
        "window": {
            "background": window_bg,
            "background_alt": window_bg_alt,
            "text": window_text,
            "muted_text": muted_text,
        },
        "widget": {
            "background": panel_bg,
            "background_alt": panel_alt_bg,
            "text": window_text,
            "border": border,
            "border_strong": border_strong,
        },
        "button": {
            "background": accent,
            "hover": accent_hover,
            "pressed": accent_pressed,
            "text": "#ffffff",
            "secondary_background": accent_soft,
            "secondary_hover": panel_alt_bg,
            "secondary_text": window_text,
        },
        "input": {
            "background": input_bg,
            "text": input_text,
            "border": border,
            "focus_border": accent,
            "selection_background": selection_bg,
            "selection_text": selection_text,
        },
        "tree": {
            "background": panel_bg,
            "item": panel_alt_bg,
            "item_selected": selection_bg,
            "text": window_text,
            "text_selected": selection_text,
        },
        "terminal": {
            "background": terminal_bg,
            "text": terminal_text,
            "prompt": terminal_prompt,
            "error": terminal_error,
        },
        "statusbar": {
            "background": status_bg,
            "text": status_text,
        },
        "progressbar": {
            "background": progress_bg,
            "chunk": progress_chunk,
            "text": window_text,
        },
        "menu": {
            "background": menu_bg,
            "toolbar_background": toolbar_bg,
        },
        "feedback": {
            "success": success,
            "info": info,
        },
        "accent": accent,
        "accent_soft": accent_soft,
    }


dark_theme: Dict[str, Any] = _build_theme(
    "dark",
    window_bg="#0f1720",
    window_bg_alt="#121d29",
    window_text="#e7edf5",
    muted_text="#91a1b5",
    panel_bg="#16212e",
    panel_alt_bg="#1b2a3a",
    border="#26384b",
    border_strong="#38506b",
    accent="#2f7cf6",
    accent_hover="#4c90ff",
    accent_pressed="#1f69de",
    accent_soft="#20364a",
    input_bg="#111b26",
    input_text="#e7edf5",
    selection_bg="#244f86",
    selection_text="#f8fbff",
    menu_bg="#14202d",
    toolbar_bg="#122030",
    status_bg="#10202f",
    status_text="#dfe8f3",
    progress_bg="#203040",
    progress_chunk="#3486ff",
    terminal_bg="#0c131c",
    terminal_text="#d4dde7",
    terminal_prompt="#77b6ff",
    terminal_error="#ff7b72",
    success="#66c18c",
    info="#75aef8",
)

light_theme: Dict[str, Any] = _build_theme(
    "light",
    window_bg="#f3efe7",
    window_bg_alt="#ebe4d8",
    window_text="#223042",
    muted_text="#68778a",
    panel_bg="#fffdfa",
    panel_alt_bg="#f6f1e8",
    border="#d7d0c2",
    border_strong="#c1b49d",
    accent="#1f7a8c",
    accent_hover="#258ca1",
    accent_pressed="#156877",
    accent_soft="#e2eff1",
    input_bg="#fffdf8",
    input_text="#223042",
    selection_bg="#cde7ea",
    selection_text="#12202a",
    menu_bg="#f6f1e8",
    toolbar_bg="#efe8dd",
    status_bg="#e7dfd1",
    status_text="#2a3848",
    progress_bg="#e3ddd1",
    progress_chunk="#1f7a8c",
    terminal_bg="#fbf8f2",
    terminal_text="#28374a",
    terminal_prompt="#1f7a8c",
    terminal_error="#c95353",
    success="#4e9368",
    info="#3e7691",
)

eye_care_theme: Dict[str, Any] = _build_theme(
    "eye_care",
    window_bg="#edf2e6",
    window_bg_alt="#e4ebd8",
    window_text="#31402c",
    muted_text="#6c7b64",
    panel_bg="#f7f9ef",
    panel_alt_bg="#eef3e3",
    border="#c4cfaf",
    border_strong="#a9b692",
    accent="#6c8d3d",
    accent_hover="#7d9f4a",
    accent_pressed="#5d7936",
    accent_soft="#dde7c9",
    input_bg="#fbfcf5",
    input_text="#31402c",
    selection_bg="#cedbb0",
    selection_text="#25311f",
    menu_bg="#edf2e2",
    toolbar_bg="#e7eed9",
    status_bg="#dfe8cf",
    status_text="#31402c",
    progress_bg="#d7e1c2",
    progress_chunk="#6c8d3d",
    terminal_bg="#f2f6ea",
    terminal_text="#33442d",
    terminal_prompt="#5e7d34",
    terminal_error="#b85d5d",
    success="#5f8a4c",
    info="#6d8570",
)


class ThemeManager:
    """主题管理器。"""

    _themes = {
        "dark": dark_theme,
        "light": light_theme,
        "eye_care": eye_care_theme,
    }
    _active_theme_name = "dark"
    _requested_theme_name = "dark"

    @classmethod
    def get_theme(cls, name: str) -> Optional[Dict[str, Any]]:
        """获取指定主题。"""
        return cls._themes.get(name)

    @classmethod
    def resolve_theme_name(cls, app: Optional[QApplication], theme_name: Optional[str]) -> str:
        """把 auto 等别名解析为实际主题名。"""
        requested = (theme_name or "dark").strip() or "dark"
        if requested != "auto":
            return requested if requested in cls._themes else "dark"

        if app is not None:
            try:
                color_scheme = app.styleHints().colorScheme()
                if color_scheme == Qt.ColorScheme.Dark:
                    return "dark"
                if color_scheme == Qt.ColorScheme.Light:
                    return "light"
            except Exception:
                pass

            try:
                palette = app.palette()
                color = palette.color(QPalette.Window)
                if color.lightness() < 128:
                    return "dark"
                return "light"
            except Exception:
                pass

        return "dark"

    @classmethod
    def get_active_theme_name(cls) -> str:
        """返回当前已生效的主题名。"""
        return cls._active_theme_name

    @classmethod
    def get_active_theme(cls) -> Dict[str, Any]:
        """返回当前已生效主题配置。"""
        return cls._themes.get(cls._active_theme_name, dark_theme)

    @classmethod
    def apply_theme(cls, app: QApplication, theme_name: str) -> None:
        """应用主题。"""
        resolved_name = cls.resolve_theme_name(app, theme_name)
        theme = cls.get_theme(resolved_name)
        if not theme:
            return

        stylesheet = cls._generate_stylesheet(theme)
        app.setStyleSheet(stylesheet)
        cls._active_theme_name = resolved_name
        cls._requested_theme_name = theme_name or resolved_name
        cls._apply_palette(app, theme)

    @classmethod
    def _apply_palette(cls, app: QApplication, theme: Dict[str, Any]) -> None:
        """同步 Qt 调色板，减少原生控件违和感。"""
        palette = app.palette()
        palette.setColor(QPalette.Window, QColor(theme["window"]["background"]))
        palette.setColor(QPalette.WindowText, QColor(theme["window"]["text"]))
        palette.setColor(QPalette.Base, QColor(theme["input"]["background"]))
        palette.setColor(QPalette.AlternateBase, QColor(theme["widget"]["background_alt"]))
        palette.setColor(QPalette.Text, QColor(theme["input"]["text"]))
        palette.setColor(QPalette.Button, QColor(theme["widget"]["background"]))
        palette.setColor(QPalette.ButtonText, QColor(theme["window"]["text"]))
        palette.setColor(QPalette.Highlight, QColor(theme["input"]["selection_background"]))
        palette.setColor(QPalette.HighlightedText, QColor(theme["input"]["selection_text"]))
        palette.setColor(QPalette.PlaceholderText, QColor(theme["window"]["muted_text"]))
        app.setPalette(palette)

    @classmethod
    def _generate_stylesheet(cls, theme: Dict[str, Any]) -> str:
        """生成应用样式表。"""
        window_bg = theme["window"]["background"]
        window_bg_alt = theme["window"]["background_alt"]
        window_text = theme["window"]["text"]
        muted_text = theme["window"]["muted_text"]

        widget_bg = theme["widget"]["background"]
        widget_bg_alt = theme["widget"]["background_alt"]
        widget_border = theme["widget"]["border"]
        widget_border_strong = theme["widget"]["border_strong"]

        btn_bg = theme["button"]["background"]
        btn_hover = theme["button"]["hover"]
        btn_pressed = theme["button"]["pressed"]
        btn_text = theme["button"]["text"]
        btn_secondary_bg = theme["button"]["secondary_background"]
        btn_secondary_hover = theme["button"]["secondary_hover"]
        btn_secondary_text = theme["button"]["secondary_text"]

        input_bg = theme["input"]["background"]
        input_text = theme["input"]["text"]
        input_border = theme["input"]["border"]
        input_focus = theme["input"]["focus_border"]
        selection_bg = theme["input"]["selection_background"]
        selection_text = theme["input"]["selection_text"]

        tree_bg = theme["tree"]["background"]
        tree_item = theme["tree"]["item"]
        tree_selected = theme["tree"]["item_selected"]
        tree_text = theme["tree"]["text"]
        tree_text_selected = theme["tree"]["text_selected"]

        status_bg = theme["statusbar"]["background"]
        status_text = theme["statusbar"]["text"]
        menu_bg = theme["menu"]["background"]
        toolbar_bg = theme["menu"]["toolbar_background"]
        accent_soft = theme["accent_soft"]
        success = theme["feedback"]["success"]
        info = theme["feedback"]["info"]

        return f"""
            QWidget {{
                color: {window_text};
                selection-background-color: {selection_bg};
                selection-color: {selection_text};
                font-size: 13px;
            }}

            QMainWindow, QDialog {{
                background-color: {window_bg};
            }}

            QWidget#shellRoot {{
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {window_bg},
                    stop:1 {window_bg_alt}
                );
            }}

            QWidget#sidePanel,
            QWidget#connectionTreePanel,
            QWidget#monitorPanel {{
                background-color: {widget_bg};
                border: 1px solid {widget_border};
                border-radius: 18px;
            }}

            QFrame#connectionHeaderCard,
            QFrame#connectionActionCard,
            QFrame#connectionSearchCard,
            QFrame#workspaceHeaderCard {{
                background-color: {widget_bg};
                border: 1px solid {widget_border};
                border-radius: 18px;
            }}

            QWidget#syncInputBar {{
                background-color: {widget_bg};
                border: 1px solid {widget_border};
                border-radius: 18px;
            }}

            QWidget#workspaceEmptyState {{
                background-color: transparent;
            }}

            QFrame#workspaceEmptyCard {{
                background-color: {widget_bg};
                border: 1px solid {widget_border};
                border-radius: 20px;
            }}

            QFrame#workspaceMetricCard {{
                background-color: {widget_bg_alt};
                border: 1px solid {widget_border};
                border-radius: 16px;
            }}

            QFrame#monitorResourcePanel,
            QFrame#monitorStatsPanel {{
                background-color: {widget_bg_alt};
                border: 1px solid {widget_border};
                border-radius: 14px;
            }}

            QWidget#connectionFilterPanel {{
                background-color: transparent;
            }}

            QGroupBox {{
                border: 1px solid {widget_border};
                border-radius: 16px;
                margin-top: 12px;
                padding: 12px;
                background-color: {widget_bg};
            }}

            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                color: {muted_text};
            }}

            QPushButton {{
                background-color: {btn_bg};
                color: {btn_text};
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 8px 14px;
                min-height: 18px;
                min-width: 84px;
                font-weight: 600;
            }}

            QPushButton:hover {{
                background-color: {btn_hover};
            }}

            QPushButton:pressed {{
                background-color: {btn_pressed};
            }}

            QPushButton:disabled {{
                background-color: {widget_bg_alt};
                color: {muted_text};
                border-color: {widget_border};
            }}

            QToolBar QToolButton,
            QToolButton#filterToggleButton,
            QPushButton[secondary="true"] {{
                background-color: {btn_secondary_bg};
                color: {btn_secondary_text};
                border: 1px solid {widget_border};
            }}

            QToolBar QToolButton:hover,
            QToolButton#filterToggleButton:hover,
            QPushButton[secondary="true"]:hover {{
                background-color: {btn_secondary_hover};
                border-color: {widget_border_strong};
            }}

            QLineEdit,
            QTextEdit,
            QPlainTextEdit,
            QTextBrowser,
            QSpinBox,
            QDoubleSpinBox,
            QTimeEdit,
            QDateTimeEdit,
            QListWidget,
            QTableWidget,
            QTreeWidget,
            QTreeView,
            QTableView {{
                background-color: {input_bg};
                color: {input_text};
                border: 1px solid {input_border};
                border-radius: 12px;
                padding: 6px 10px;
                selection-background-color: {selection_bg};
                selection-color: {selection_text};
            }}

            QLineEdit:focus,
            QTextEdit:focus,
            QPlainTextEdit:focus,
            QTextBrowser:focus,
            QSpinBox:focus,
            QDoubleSpinBox:focus,
            QTreeWidget:focus,
            QTreeView:focus,
            QTableView:focus,
            QTableWidget:focus,
            QListWidget:focus {{
                border: 1px solid {input_focus};
            }}

            QComboBox {{
                background-color: {input_bg};
                color: {input_text};
                border: 1px solid {input_border};
                border-radius: 12px;
                padding: 6px 10px;
                min-width: 110px;
            }}

            QComboBox:hover,
            QSpinBox:hover,
            QDoubleSpinBox:hover {{
                border-color: {widget_border_strong};
            }}

            QComboBox:focus {{
                border: 1px solid {input_focus};
            }}

            QComboBox::drop-down,
            QSpinBox::up-button,
            QSpinBox::down-button,
            QDoubleSpinBox::up-button,
            QDoubleSpinBox::down-button {{
                border: none;
                width: 18px;
            }}

            QComboBox QAbstractItemView,
            QListView,
            QMenu {{
                background-color: {menu_bg};
                color: {window_text};
                border: 1px solid {widget_border};
                border-radius: 12px;
                padding: 6px;
                selection-background-color: {selection_bg};
                selection-color: {selection_text};
            }}

            QHeaderView::section {{
                background-color: {widget_bg_alt};
                color: {muted_text};
                border: none;
                border-bottom: 1px solid {widget_border};
                padding: 8px 10px;
                font-weight: 600;
            }}

            QTreeWidget#connectionTreeView,
            QTreeWidget,
            QTreeView {{
                background-color: {tree_bg};
                color: {tree_text};
                border-radius: 16px;
            }}

            QTreeWidget::item,
            QTreeView::item {{
                padding: 6px;
                margin: 2px 4px;
                border-radius: 8px;
            }}

            QTreeWidget::item:hover,
            QTreeView::item:hover {{
                background-color: {tree_item};
            }}

            QTreeWidget::item:selected,
            QTreeView::item:selected {{
                background-color: {tree_selected};
                color: {tree_text_selected};
            }}

            QTabWidget::pane {{
                border: 1px solid {widget_border};
                border-radius: 18px;
                background-color: {widget_bg};
                top: -1px;
            }}

            QTabWidget#workspaceTabs::pane {{
                background-color: {widget_bg};
                border-radius: 18px;
            }}

            QTabBar::tab {{
                background-color: transparent;
                color: {muted_text};
                padding: 10px 16px;
                margin-right: 6px;
                border-radius: 12px;
                border: 1px solid transparent;
                font-weight: 600;
            }}

            QTabBar::tab:hover {{
                background-color: {accent_soft};
                color: {window_text};
            }}

            QTabBar::tab:selected {{
                background-color: {widget_bg};
                color: {window_text};
                border: 1px solid {widget_border};
            }}

            QProgressBar {{
                background-color: {theme["progressbar"]["background"]};
                color: {theme["progressbar"]["text"]};
                border: 1px solid {widget_border};
                border-radius: 8px;
                text-align: center;
                min-height: 14px;
            }}

            QProgressBar::chunk {{
                background-color: {theme["progressbar"]["chunk"]};
                border-radius: 7px;
            }}

            QLabel#monitorTitle,
            QLabel.sectionTitle {{
                font-size: 14px;
                font-weight: 700;
            }}

            QLabel#panelTitle {{
                font-size: 14px;
                font-weight: 700;
            }}

            QLabel#summaryBadge {{
                background-color: {accent_soft};
                color: {window_text};
                border: 1px solid {widget_border};
                border-radius: 11px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 700;
            }}

            QLabel#panelMeta,
            QLabel#syncInputHint,
            QLabel#syncResultLabel {{
                color: {muted_text};
            }}

            QLabel#mutedLabel {{
                color: {muted_text};
            }}

            QLabel#netRxLabel {{
                color: {success};
                font-weight: 600;
            }}

            QLabel#netTxLabel {{
                color: {info};
                font-weight: 600;
            }}

            QLabel#monitorMetricValue {{
                font-weight: 700;
            }}

            QLabel#workspaceMetricValue {{
                font-size: 24px;
                font-weight: 800;
                color: {window_text};
            }}

            QMenuBar {{
                background-color: {menu_bg};
                color: {window_text};
                border-bottom: 1px solid {widget_border};
                padding: 4px 10px;
            }}

            QMenuBar::item {{
                padding: 6px 10px;
                border-radius: 8px;
                background: transparent;
            }}

            QMenuBar::item:selected {{
                background-color: {accent_soft};
            }}

            QMenu::item {{
                padding: 8px 12px;
                border-radius: 8px;
            }}

            QMenu::item:selected {{
                background-color: {selection_bg};
            }}

            QToolBar#mainToolbar,
            QToolBar {{
                background-color: {toolbar_bg};
                border: 1px solid {widget_border};
                border-radius: 16px;
                spacing: 6px;
                padding: 4px 6px;
            }}

            QToolBar QToolButton {{
                background-color: {btn_secondary_bg};
                color: {window_text};
                border: 1px solid {widget_border};
                border-radius: 10px;
                padding: 6px 10px;
                margin: 2px;
                font-weight: 600;
            }}

            QToolButton#toolbarMenuButton {{
                background-color: {btn_secondary_bg};
                color: {window_text};
                border: 1px solid {widget_border};
                border-radius: 10px;
                padding: 7px 12px;
                margin: 2px;
                font-weight: 600;
            }}

            QToolButton#toolbarMenuButton:hover {{
                background-color: {btn_secondary_hover};
                border-color: {widget_border_strong};
            }}

            QWidget#toolbarSpacer {{
                background: transparent;
                border: none;
            }}

            QPushButton#syncCollapseButton {{
                min-width: 68px;
            }}

            QToolBar::separator {{
                background: {widget_border};
                width: 1px;
                margin: 8px 6px;
            }}

            QStatusBar {{
                background-color: {status_bg};
                color: {status_text};
                border-top: 1px solid {widget_border};
            }}

            QStatusBar QLabel {{
                color: {status_text};
            }}

            QScrollBar:vertical {{
                background-color: transparent;
                width: 12px;
                margin: 2px;
            }}

            QScrollBar::handle:vertical {{
                background-color: {widget_border_strong};
                border-radius: 6px;
                min-height: 30px;
            }}

            QScrollBar::handle:vertical:hover {{
                background-color: {input_focus};
            }}

            QScrollBar:horizontal {{
                background-color: transparent;
                height: 12px;
                margin: 2px;
            }}

            QScrollBar::handle:horizontal {{
                background-color: {widget_border_strong};
                border-radius: 6px;
                min-width: 30px;
            }}

            QScrollBar::add-line,
            QScrollBar::sub-line {{
                border: none;
                background: transparent;
            }}

            QCheckBox {{
                spacing: 8px;
            }}

            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 1px solid {widget_border_strong};
                background-color: {input_bg};
            }}

            QCheckBox::indicator:checked {{
                background-color: {btn_bg};
                border: 1px solid {btn_bg};
            }}

            QSplitter::handle {{
                background-color: transparent;
            }}

            QSplitter::handle:hover {{
                background-color: {accent_soft};
                border-radius: 4px;
            }}
        """

    @classmethod
    def get_available_themes(cls) -> list[str]:
        """获取可用主题列表。"""
        return ["dark", "light", "eye_care", "auto"]
