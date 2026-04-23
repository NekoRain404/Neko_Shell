#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VNC 视图组件

提供基础的远程桌面画面显示与输入转发。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt, QRect, QSize
from PySide6.QtGui import QImage, QPainter, QColor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from neko_shell.core.connection import VNCConnection
from neko_shell.utils import get_logger


class VNCWidget(QWidget):
    """基础 VNC 桌面视图。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._logger = get_logger("VNCWidget")
        self._connection: Optional[VNCConnection] = None
        self._framebuffer: Optional[QImage] = None
        self._framebuffer_bytes: bytearray = bytearray()
        self._button_mask = 0
        self._view_only = False

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self._setup_ui()

    @property
    def connection(self) -> Optional[VNCConnection]:
        """获取当前绑定连接。"""
        return self._connection

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.status_label = QLabel(self.tr("等待 VNC 画面..."))
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setMinimumHeight(28)
        self.status_label.setMaximumHeight(28)
        self.status_label.setContentsMargins(10, 0, 10, 0)
        self.status_label.setStyleSheet("background:rgba(17,17,17,0.92);color:#ddd;border-bottom:1px solid #2b2b2b;")
        layout.addWidget(self.status_label)

    def set_connection(self, connection: VNCConnection) -> None:
        """绑定 VNC 连接并请求首帧。"""
        self._connection = connection
        self._view_only = bool(getattr(connection.config, "view_only", False))
        connection.on("frame_update", self._on_frame_update)

        width, height = connection.framebuffer_size
        self._framebuffer_bytes = bytearray(width * height * 3)
        self._framebuffer = QImage(
            self._framebuffer_bytes,
            width,
            height,
            width * 3,
            QImage.Format_RGB888,
        )
        self.status_label.setText(
            self.tr("已连接到 {name} ({width}x{height}){suffix}").format(
                name=connection.desktop_name or connection.config.name,
                width=width,
                height=height,
                suffix=self.tr(" [只读]") if self._view_only else "",
            )
        )
        self.setMinimumSize(width, height)
        try:
            connection.request_frame_update(incremental=False)
        except Exception as exc:
            self._logger.error("请求 VNC 首帧失败: %s", exc)
            self.status_label.setText(self.tr(f"VNC 初始化失败: {exc}"))

    def _image_target_rect(self) -> QRect:
        """计算保持宽高比的显示区域。"""
        if self._framebuffer is None:
            return self.rect()
        source_size = QSize(self._framebuffer.width(), self._framebuffer.height())
        target_size = source_size.scaled(self.size(), Qt.KeepAspectRatio)
        x = max(0, (self.width() - target_size.width()) // 2)
        y = max(0, (self.height() - target_size.height()) // 2)
        return QRect(x, y, target_size.width(), target_size.height())

    def _decode_raw_pixels(self, pixel_data: bytes, width: int, height: int) -> bytes:
        """将 VNC raw 像素解码为 RGB888。"""
        if not self._connection:
            return bytes(width * height * 3)

        pixel_format = getattr(self._connection, "_pixel_format", {})
        bits_per_pixel = int(pixel_format.get("bits_per_pixel", 32))
        bytes_per_pixel = max(bits_per_pixel // 8, 1)
        endian = "big" if pixel_format.get("big_endian") else "little"
        red_max = int(pixel_format.get("red_max", 255)) or 255
        green_max = int(pixel_format.get("green_max", 255)) or 255
        blue_max = int(pixel_format.get("blue_max", 255)) or 255
        red_shift = int(pixel_format.get("red_shift", 16))
        green_shift = int(pixel_format.get("green_shift", 8))
        blue_shift = int(pixel_format.get("blue_shift", 0))

        rgb = bytearray(width * height * 3)
        for idx in range(width * height):
            start = idx * bytes_per_pixel
            value = int.from_bytes(pixel_data[start:start + bytes_per_pixel], endian, signed=False)
            r = ((value >> red_shift) & red_max) * 255 // red_max
            g = ((value >> green_shift) & green_max) * 255 // green_max
            b = ((value >> blue_shift) & blue_max) * 255 // blue_max
            offset = idx * 3
            rgb[offset:offset + 3] = bytes((r, g, b))
        return bytes(rgb)

    def _on_frame_update(self, x: int, y: int, width: int, height: int, pixel_data: bytes) -> None:
        """处理帧缓冲增量更新。"""
        if self._framebuffer is None or self._connection is None:
            return

        rgb = self._decode_raw_pixels(pixel_data, width, height)
        rect_bytes = bytearray(rgb)
        image = QImage(rect_bytes, width, height, width * 3, QImage.Format_RGB888)

        painter = QPainter(self._framebuffer)
        painter.drawImage(QPoint(x, y), image)
        painter.end()

        self.update(QRect(x, y, width, height))
        try:
            self._connection.request_frame_update(incremental=True)
        except Exception as exc:
            self._logger.debug("请求 VNC 增量更新失败: %s", exc)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111"))
        if self._framebuffer is not None:
            painter.drawImage(self._image_target_rect(), self._framebuffer)
        else:
            super().paintEvent(event)

    def _map_position(self, position: QPoint) -> tuple[int, int]:
        """将控件坐标映射到远程桌面坐标。"""
        if self._framebuffer is None:
            return 0, 0
        target_rect = self._image_target_rect()
        if target_rect.width() <= 0 or target_rect.height() <= 0:
            return 0, 0
        relative_x = position.x() - target_rect.x()
        relative_y = position.y() - target_rect.y()
        relative_x = max(0, min(target_rect.width() - 1, relative_x))
        relative_y = max(0, min(target_rect.height() - 1, relative_y))
        x = max(0, min(self._framebuffer.width() - 1, relative_x * self._framebuffer.width() // target_rect.width()))
        y = max(0, min(self._framebuffer.height() - 1, relative_y * self._framebuffer.height() // target_rect.height()))
        return x, y

    @staticmethod
    def _pointer_mask(button: Qt.MouseButton) -> int:
        if button == Qt.LeftButton:
            return 1
        if button == Qt.MiddleButton:
            return 2
        if button == Qt.RightButton:
            return 4
        return 0

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._connection and not self._view_only:
            self._button_mask |= self._pointer_mask(event.button())
            x, y = self._map_position(event.position().toPoint())
            self._connection.send_pointer_event(x, y, self._button_mask)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._connection and not self._view_only:
            x, y = self._map_position(event.position().toPoint())
            self._connection.send_pointer_event(x, y, self._button_mask)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._connection and not self._view_only:
            self._button_mask &= ~self._pointer_mask(event.button())
            x, y = self._map_position(event.position().toPoint())
            self._connection.send_pointer_event(x, y, self._button_mask)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._connection and not self._view_only:
            text = event.text()
            if text:
                self._connection.send_key_event(ord(text), pressed=True)
                self._connection.send_key_event(ord(text), pressed=False)
        super().keyPressEvent(event)
