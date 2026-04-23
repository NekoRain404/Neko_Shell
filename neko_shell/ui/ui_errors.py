#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI 错误提示工具。

目标：
- 统一错误弹窗结构
- 将“做什么失败”和“为什么失败”讲清楚
- 保留上下文信息（命令/连接/路径等）
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QMessageBox, QWidget


def _stringify_exception(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__

    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause and cause is not exc:
        cause_message = str(cause).strip()
        if cause_message and cause_message not in message:
            message = f"{message}\n\n原因: {cause_message}"
    return message


def build_operation_error_message(
    action: str,
    exc: BaseException,
    *,
    context: Optional[str] = None,
    hint: Optional[str] = None,
) -> str:
    """生成统一的错误消息内容。"""
    parts: list[str] = [f"{action} 失败。", "", _stringify_exception(exc)]
    if context:
        parts.extend(["", "上下文:", str(context).strip()])
    if hint:
        parts.extend(["", "建议:", str(hint).strip()])
    return "\n".join(part for part in parts if part is not None)


def show_operation_error(
    parent: QWidget,
    title: str,
    action: str,
    exc: BaseException,
    *,
    context: Optional[str] = None,
    hint: Optional[str] = None,
) -> None:
    """弹出统一格式的错误提示。"""
    QMessageBox.critical(
        parent,
        title,
        build_operation_error_message(action, exc, context=context, hint=hint),
    )

