#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统监控组件。"""

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QDateTime, Qt, Signal, QTimer
from PySide6.QtGui import QFont

from typing import Optional, Dict, Any

from neko_shell.core.connection import BaseConnection
from neko_shell.utils import get_logger


class SystemMonitorWidget(QWidget):
    """
    系统监控组件

    显示资源条、网络与系统关键指标。

    Signals:
        refresh_requested: 刷新请求
    """

    # 信号
    refresh_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._logger = get_logger("SystemMonitorWidget")
        self._connection: Optional[BaseConnection] = None

        # 监控数据
        self._cpu_usage = 0.0
        self._mem_usage = 0.0
        self._disk_usage = 0.0
        self._swap_usage = 0.0
        self._net_rx_speed = 0.0
        self._net_tx_speed = 0.0
        self._load1 = 0.0
        self._load5 = 0.0
        self._load15 = 0.0
        self._uptime_hours = 0.0
        self._process_count = 0.0
        self._running_tasks = 0.0
        self._mem_used_mb = 0.0
        self._mem_available_mb = 0.0
        self._disk_free_gb = 0.0
        self._disk_used_gb = 0.0
        self._host_name = ""
        self._system_name = ""
        self._cpu_cores = 0.0
        self._active_interface = ""
        self._root_mount = "/"
        self._root_device = ""
        self._last_refresh_text = "--"
        self._details_expanded = False

        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self) -> None:
        """设置 UI"""
        self.setObjectName("monitorCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_label = QLabel(self.tr("系统监控"))
        title_label.setObjectName("monitorTitle")
        title_label.setFont(QFont("", 10, QFont.Bold))
        title_row.addWidget(title_label)

        self.monitor_subtitle = QLabel(self.tr("等待连接监控数据"), self)
        self.monitor_subtitle.setObjectName("panelMeta")
        title_row.addWidget(self.monitor_subtitle)
        title_row.addStretch()

        self.expand_button = QPushButton(self.tr("展开详情"), self)
        self.expand_button.setObjectName("monitorToggleButton")
        self.expand_button.setProperty("secondary", True)
        self.expand_button.clicked.connect(self._toggle_details)
        title_row.addWidget(self.expand_button)
        layout.addLayout(title_row)

        summary_panel = QFrame()
        summary_panel.setObjectName("monitorResourcePanel")
        summary_layout = QGridLayout(summary_panel)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setHorizontalSpacing(12)
        summary_layout.setVerticalSpacing(8)
        summary_layout.addWidget(self._create_metric_row("CPU", "cpu"), 0, 0)
        summary_layout.addWidget(self._create_metric_row(self.tr("内存"), "mem"), 0, 1)
        summary_layout.addWidget(self._create_metric_row(self.tr("磁盘"), "disk"), 1, 0)
        summary_layout.addWidget(self._create_metric_row(self.tr("交换"), "swap"), 1, 1)
        layout.addWidget(summary_panel)

        self.details_container = QFrame()
        self.details_container.setObjectName("monitorStatsPanel")
        details_layout = QVBoxLayout(self.details_container)
        details_layout.setContentsMargins(12, 12, 12, 12)
        details_layout.setSpacing(8)

        stats_columns = QHBoxLayout()
        stats_columns.setSpacing(16)
        left_stats_column = QVBoxLayout()
        left_stats_column.setSpacing(8)
        right_stats_column = QVBoxLayout()
        right_stats_column.setSpacing(8)
        self._stat_labels: dict[str, QLabel] = {}
        stat_specs = [
            (self.tr("主机"), "host"),
            (self.tr("系统"), "system"),
            (self.tr("CPU 核心"), "cpu_cores"),
            (self.tr("活跃网卡"), "interface"),
            (self.tr("根挂载"), "root_mount"),
            (self.tr("负载"), "load"),
            (self.tr("运行时长"), "uptime"),
            (self.tr("任务"), "tasks"),
            (self.tr("内存明细"), "memory_detail"),
            (self.tr("磁盘明细"), "disk_detail"),
            (self.tr("网络"), "network"),
            (self.tr("最近刷新"), "last_refresh"),
        ]
        for index, (title, key) in enumerate(stat_specs):
            info_block = QWidget(self.details_container)
            info_layout = QVBoxLayout(info_block)
            info_layout.setContentsMargins(0, 0, 0, 0)
            info_layout.setSpacing(2)

            stat_title_label = QLabel(title, info_block)
            stat_title_label.setObjectName("mutedLabel")
            value_label = QLabel("--", info_block)
            value_label.setWordWrap(True)
            value_label.setObjectName("monitorValueLabel")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

            info_layout.addWidget(stat_title_label)
            info_layout.addWidget(value_label)
            self._stat_labels[key] = value_label

            if index % 2 == 0:
                left_stats_column.addWidget(info_block)
            else:
                right_stats_column.addWidget(info_block)

        left_stats_column.addStretch()
        right_stats_column.addStretch()
        stats_columns.addLayout(left_stats_column, 1)
        stats_columns.addLayout(right_stats_column, 1)
        details_layout.addLayout(stats_columns)

        net_layout = QHBoxLayout()
        net_layout.addWidget(QLabel(self.tr("实时流量:")))
        self.rx_label = QLabel("↓ 0 KB/s")
        self.rx_label.setObjectName("netRxLabel")
        net_layout.addWidget(self.rx_label)

        self.tx_label = QLabel("↑ 0 KB/s")
        self.tx_label.setObjectName("netTxLabel")
        net_layout.addWidget(self.tx_label)
        net_layout.addStretch()
        details_layout.addLayout(net_layout)
        layout.addWidget(self.details_container)
        self.set_expanded(False)

    def _setup_timer(self) -> None:
        """设置刷新定时器"""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start(2000)  # 2秒刷新一次

    def set_connection(self, connection: BaseConnection) -> None:
        """设置关联的连接"""
        self._connection = connection
        if connection is None:
            self.clear_data()
        else:
            self.monitor_subtitle.setText(self.tr("已绑定当前连接"))

    def clear_data(self) -> None:
        """清空当前监控数据显示。"""
        self._cpu_usage = 0.0
        self._mem_usage = 0.0
        self._disk_usage = 0.0
        self._swap_usage = 0.0
        self._net_rx_speed = 0.0
        self._net_tx_speed = 0.0
        self._load1 = 0.0
        self._load5 = 0.0
        self._load15 = 0.0
        self._uptime_hours = 0.0
        self._process_count = 0.0
        self._running_tasks = 0.0
        self._mem_used_mb = 0.0
        self._mem_available_mb = 0.0
        self._disk_free_gb = 0.0
        self._disk_used_gb = 0.0
        self._host_name = ""
        self._system_name = ""
        self._cpu_cores = 0.0
        self._active_interface = ""
        self._root_mount = "/"
        self._root_device = ""
        self._last_refresh_text = "--"
        self.monitor_subtitle.setText(
            self.tr("等待连接监控数据") if self._connection is not None else self.tr("未连接")
        )
        self._update_display()

    def update_data(self, data: Dict[str, Any]) -> None:
        """
        更新监控数据

        Args:
            data: 监控数据字典
        """
        self._cpu_usage = data.get("cpu", 0.0)
        self._mem_usage = data.get("memory", 0.0)
        self._disk_usage = data.get("disk", 0.0)
        self._swap_usage = data.get("swap", 0.0)
        self._net_rx_speed = data.get("rx_speed", 0.0)
        self._net_tx_speed = data.get("tx_speed", 0.0)
        self._load1 = data.get("load1", 0.0)
        self._load5 = data.get("load5", 0.0)
        self._load15 = data.get("load15", 0.0)
        self._uptime_hours = data.get("uptime_hours", 0.0)
        self._process_count = data.get("process_count", 0.0)
        self._running_tasks = data.get("running_tasks", 0.0)
        self._mem_used_mb = data.get("memory_used_mb", 0.0)
        self._mem_available_mb = data.get("memory_available_mb", 0.0)
        self._disk_free_gb = data.get("disk_free_gb", 0.0)
        self._disk_used_gb = data.get("disk_used_gb", 0.0)
        self._host_name = data.get("hostname", "") or ""
        self._system_name = data.get("system", "") or ""
        self._cpu_cores = data.get("cpu_cores", 0.0)
        self._active_interface = data.get("active_interface", "") or ""
        self._root_mount = data.get("root_mount", "/") or "/"
        self._root_device = data.get("root_device", "") or ""
        self._last_refresh_text = QDateTime.currentDateTime().toString("HH:mm:ss")
        subtitle_parts = [part for part in (self._host_name, self._system_name) if part]
        if subtitle_parts:
            self.monitor_subtitle.setText(" · ".join(subtitle_parts))
        else:
            self.monitor_subtitle.setText(self.tr("当前连接"))

        self._update_display()

    def is_expanded(self) -> bool:
        """返回详情面板是否展开。"""
        return self._details_expanded

    def set_expanded(self, expanded: bool) -> None:
        """切换详情面板显示状态。"""
        self._details_expanded = bool(expanded)
        self.details_container.setVisible(self._details_expanded)
        self.expand_button.setText(
            self.tr("收起详情") if self._details_expanded else self.tr("展开详情")
        )

    def _toggle_details(self) -> None:
        """展开或收起监控详情。"""
        self.set_expanded(not self._details_expanded)

    def _update_display(self) -> None:
        """更新显示"""
        self._set_metric("cpu", self._cpu_usage)
        self._set_metric("mem", self._mem_usage)
        self._set_metric("disk", self._disk_usage)
        self._set_metric("swap", self._swap_usage)

        self._stat_labels["host"].setText(self._host_name or "--")
        self._stat_labels["system"].setText(self._system_name or "--")
        self._stat_labels["cpu_cores"].setText(
            str(int(self._cpu_cores)) if self._cpu_cores else "--"
        )
        self._stat_labels["interface"].setText(self._active_interface or "--")
        root_text = self._root_mount or "/"
        if self._root_device:
            root_text = f"{root_text} ({self._root_device})"
        self._stat_labels["root_mount"].setText(root_text)
        self._stat_labels["load"].setText(
            f"{self._load1:.2f} / {self._load5:.2f} / {self._load15:.2f}"
        )
        self._stat_labels["uptime"].setText(self._format_uptime(self._uptime_hours))
        self._stat_labels["tasks"].setText(
            self.tr(f"运行 {int(self._running_tasks)} / 总计 {int(self._process_count)}")
        )
        self._stat_labels["memory_detail"].setText(
            self.tr(
                f"已用 {self._format_size_mb(self._mem_used_mb)}  可用 {self._format_size_mb(self._mem_available_mb)}"
            )
        )
        self._stat_labels["disk_detail"].setText(
            self.tr(f"已用 {self._disk_used_gb:.1f} GB  可用 {self._disk_free_gb:.1f} GB")
        )
        self._stat_labels["network"].setText(
            self.tr(
                f"下行 {self._format_speed(self._net_rx_speed)}  上行 {self._format_speed(self._net_tx_speed)}"
            )
        )
        self._stat_labels["last_refresh"].setText(self._last_refresh_text)

        self.rx_label.setText(f"↓ {self._format_speed(self._net_rx_speed)}")
        self.tx_label.setText(f"↑ {self._format_speed(self._net_tx_speed)}")

    def _create_metric_row(self, title: str, key: str) -> QWidget:
        """创建资源指标行。"""
        row = QWidget(self)
        row.setObjectName("monitorMetricRow")
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("mutedLabel")
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setFormat("%p%")
        bar.setMaximumHeight(16)
        value_label = QLabel("0.0%")
        value_label.setObjectName("monitorMetricValue")
        value_label.setMinimumWidth(58)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(title_label, 0, 0)
        layout.addWidget(bar, 0, 1)
        layout.addWidget(value_label, 0, 2)

        setattr(self, f"{key}_bar", bar)
        setattr(self, f"{key}_label", value_label)
        return row

    def _set_metric(self, key: str, value: float) -> None:
        """更新资源条显示。"""
        bar: QProgressBar = getattr(self, f"{key}_bar")
        label: QLabel = getattr(self, f"{key}_label")
        bar.setValue(int(value))
        label.setText(f"{value:.1f}%")

    def _format_speed(self, speed: float) -> str:
        """格式化网络速度"""
        if speed < 1024:
            return f"{speed:.0f} B/s"
        elif speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        else:
            return f"{speed / 1024 / 1024:.2f} MB/s"

    @staticmethod
    def _format_size_mb(value_mb: float) -> str:
        """格式化内存容量。"""
        if value_mb >= 1024:
            return f"{value_mb / 1024:.1f} GB"
        return f"{value_mb:.0f} MB"

    @staticmethod
    def _format_uptime(hours: float) -> str:
        """格式化运行时长。"""
        total_hours = int(hours)
        days = total_hours // 24
        remain_hours = total_hours % 24
        if days > 0:
            return f"{days} 天 {remain_hours} 小时"
        return f"{remain_hours} 小时"

    def _on_timer(self) -> None:
        """定时刷新"""
        if (
            self._connection
            and self._connection.is_connected()
            and hasattr(self._connection, "get_monitor_data")
        ):
            # 请求更新数据
            self.refresh_requested.emit()
