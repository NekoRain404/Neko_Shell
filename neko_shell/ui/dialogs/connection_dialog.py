#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接对话框

用于创建和编辑连接配置。
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

from typing import Optional, Dict, Any

from neko_shell.core.connection import ConnectionType
from neko_shell.models.connection import (
    FTPConfig,
    SerialConfig,
    SSHConfig,
    SFTPConfig,
    TCPConfig,
    UDPConfig,
    VNCConfig,
    FTPMode,
    FTPSType,
    SerialParity,
    SerialStopBits,
    SerialByteSize,
    SerialFlowControl,
    UDPMode,
    VNCSecurityType,
    VNCColorDepth,
)
from neko_shell.utils import ConfigManager, get_logger
from neko_shell.models.connection import BaseConnectionConfig


class ConnectionDialog(QDialog):
    """
    连接对话框

    用于创建或编辑连接配置。

    Example:
        >>> dialog = ConnectionDialog(ConnectionType.TCP, parent)
        >>> if dialog.exec() == QDialog.Accepted:
        ...     config = dialog.get_config()
    """

    def __init__(
        self, conn_type: Optional[ConnectionType] = None, parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        self._logger = get_logger("ConnectionDialog")
        self._conn_type = conn_type
        self._config: Optional[BaseConnectionConfig] = None
        self._config_manager: Optional[ConfigManager] = None
        self._open_after_accept = False
        self._open_after_save_enabled = False
        self._quick_connect_mode = False

        self._setup_ui()
        self._setup_connections()

        if conn_type:
            self.type_combo.setCurrentText(conn_type.value.upper())
            self._on_type_changed()

    def _setup_ui(self) -> None:
        """设置 UI"""
        self.setWindowTitle(self.tr("新建连接"))
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        # 连接类型选择
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel(self.tr("连接类型:")))

        self.type_combo = QComboBox()
        self.type_combo.addItems(["SSH", "SFTP", "FTP", "SERIAL", "TCP", "UDP", "VNC"])
        type_layout.addWidget(self.type_combo)
        type_layout.addStretch()

        layout.addLayout(type_layout)

        self.connection_hint_label = QLabel(self)
        self.connection_hint_label.setWordWrap(True)
        self.connection_hint_label.setObjectName("panelMeta")
        self.connection_hint_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.connection_hint_label)

        template_layout = QHBoxLayout()
        template_layout.addWidget(QLabel(self.tr("模板:")))
        self.template_combo = QComboBox()
        self.template_combo.addItem(self.tr("无模板"), None)
        template_layout.addWidget(self.template_combo, 1)

        self.apply_template_btn = QPushButton(self.tr("应用"))
        self.apply_template_btn.clicked.connect(self._apply_selected_template)
        template_layout.addWidget(self.apply_template_btn)

        self.save_template_btn = QPushButton(self.tr("保存为模板"))
        self.save_template_btn.clicked.connect(self._save_as_template)
        template_layout.addWidget(self.save_template_btn)

        self.delete_template_btn = QPushButton(self.tr("删除模板"))
        self.delete_template_btn.clicked.connect(self._delete_selected_template)
        template_layout.addWidget(self.delete_template_btn)
        layout.addLayout(template_layout)

        self.auth_template_row = QWidget(self)
        auth_template_layout = QHBoxLayout(self.auth_template_row)
        auth_template_layout.setContentsMargins(0, 0, 0, 0)
        auth_template_layout.addWidget(QLabel(self.tr("认证模板:")))
        self.auth_template_combo = QComboBox()
        self.auth_template_combo.addItem(self.tr("无认证模板"), None)
        auth_template_layout.addWidget(self.auth_template_combo, 1)

        self.apply_auth_template_btn = QPushButton(self.tr("应用"))
        self.apply_auth_template_btn.clicked.connect(self._apply_selected_auth_template)
        auth_template_layout.addWidget(self.apply_auth_template_btn)

        self.save_auth_template_btn = QPushButton(self.tr("保存认证模板"))
        self.save_auth_template_btn.clicked.connect(self._save_as_auth_template)
        auth_template_layout.addWidget(self.save_auth_template_btn)

        self.delete_auth_template_btn = QPushButton(self.tr("删除认证模板"))
        self.delete_auth_template_btn.clicked.connect(self._delete_selected_auth_template)
        auth_template_layout.addWidget(self.delete_auth_template_btn)
        layout.addWidget(self.auth_template_row)
        self.auth_template_row.hide()

        # 基本信息组
        basic_group = QGroupBox(self.tr("基本信息"))
        basic_layout = QFormLayout(basic_group)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(self.tr("连接名称"))
        basic_layout.addRow(self.tr("名称:"), self.name_edit)

        self.group_edit = QLineEdit()
        self.group_edit.setPlaceholderText(self.tr("例如 生产 / 数据库 / 默认"))
        self.group_edit.setText("default")
        basic_layout.addRow(self.tr("分组:"), self.group_edit)

        self.environment_edit = QLineEdit()
        self.environment_edit.setPlaceholderText(self.tr("例如 生产 / 预发 / 测试 / 开发"))
        basic_layout.addRow(self.tr("环境:"), self.environment_edit)

        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText(self.tr("例如 支付中台 / 用户中心"))
        basic_layout.addRow(self.tr("项目:"), self.project_edit)

        self.business_domain_edit = QLineEdit()
        self.business_domain_edit.setPlaceholderText(self.tr("例如 订单 / 风控 / 数据平台"))
        basic_layout.addRow(self.tr("业务域:"), self.business_domain_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(self.tr("逗号分隔，例如 prod, api, db"))
        basic_layout.addRow(self.tr("标签:"), self.tags_edit)

        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText(self.tr("用途说明，可用于搜索和识别"))
        basic_layout.addRow(self.tr("描述:"), self.description_edit)

        layout.addWidget(basic_group)

        # 配置标签页
        self.config_tabs = QTabWidget()
        layout.addWidget(self.config_tabs)

        # 创建各类型配置页面
        self._create_ssh_page()
        self._create_sftp_page()
        self._create_ftp_page()
        self._create_serial_page()
        self._create_tcp_page()
        self._create_udp_page()
        self._create_vnc_page()

        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.save_and_open_btn = QPushButton(self.tr("保存并连接"))
        self.save_and_open_btn.clicked.connect(self._accept_and_open)
        self.save_and_open_btn.hide()
        button_layout.addWidget(self.save_and_open_btn)

        self.ok_btn = QPushButton(self.tr("确定"))
        self.ok_btn.clicked.connect(self._accept_without_open)
        button_layout.addWidget(self.ok_btn)

        self.cancel_btn = QPushButton(self.tr("取消"))
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)
        self._refresh_type_hint()
        self._update_submit_buttons()

    def _create_remote_auth_page(self, tab_name: str, port: int) -> Dict[str, Any]:
        """创建 SSH/SFTP 共用认证页面。"""
        page = QWidget()
        layout = QFormLayout(page)

        host = QLineEdit()
        host.setPlaceholderText("192.168.1.100")
        layout.addRow(self.tr("主机:"), host)

        port_edit = QSpinBox()
        port_edit.setRange(1, 65535)
        port_edit.setValue(port)
        layout.addRow(self.tr("端口:"), port_edit)

        username = QLineEdit()
        username.setPlaceholderText(self.tr("用户名"))
        layout.addRow(self.tr("用户名:"), username)

        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        password.setPlaceholderText(self.tr("密码"))
        layout.addRow(self.tr("密码:"), password)

        key_path = QLineEdit()
        key_path.setPlaceholderText(self.tr("私钥文件路径"))
        layout.addRow(self.tr("私钥:"), key_path)

        key_btn = QPushButton(self.tr("浏览"))
        key_btn.clicked.connect(lambda: self._browse_key_file(key_path))
        layout.addRow("", key_btn)

        passphrase = QLineEdit()
        passphrase.setEchoMode(QLineEdit.Password)
        passphrase.setPlaceholderText(self.tr("私钥口令"))
        layout.addRow(self.tr("口令:"), passphrase)

        timeout = QDoubleSpinBox()
        timeout.setRange(1, 120)
        timeout.setValue(10)
        timeout.setSuffix(" 秒")
        layout.addRow(self.tr("超时:"), timeout)

        proxy_command = QLineEdit()
        proxy_command.setPlaceholderText(self.tr("可选 ProxyCommand"))
        layout.addRow(self.tr("代理命令:"), proxy_command)

        self.config_tabs.addTab(page, tab_name)

        return {
            "page": page,
            "host": host,
            "port": port_edit,
            "username": username,
            "password": password,
            "private_key_path": key_path,
            "passphrase": passphrase,
            "timeout": timeout,
            "proxy_command": proxy_command,
        }

    def _create_ssh_page(self) -> None:
        """创建 SSH 配置页面。"""
        self.ssh_fields = self._create_remote_auth_page("SSH", 22)

    def _create_sftp_page(self) -> None:
        """创建 SFTP 配置页面。"""
        self.sftp_fields = self._create_remote_auth_page("SFTP", 22)
        initial_path = QLineEdit()
        initial_path.setText(".")
        self.sftp_fields["page"].layout().addRow(self.tr("初始路径:"), initial_path)
        self.sftp_fields["initial_path"] = initial_path

    def _create_ftp_page(self) -> None:
        """创建 FTP 配置页面"""
        page = QWidget()
        layout = QFormLayout(page)

        self.ftp_host = QLineEdit()
        self.ftp_host.setPlaceholderText("ftp.example.com")
        layout.addRow(self.tr("主机:"), self.ftp_host)

        self.ftp_port = QSpinBox()
        self.ftp_port.setRange(1, 65535)
        self.ftp_port.setValue(21)
        layout.addRow(self.tr("端口:"), self.ftp_port)

        self.ftp_user = QLineEdit()
        self.ftp_user.setPlaceholderText(self.tr("用户名"))
        layout.addRow(self.tr("用户名:"), self.ftp_user)

        self.ftp_pass = QLineEdit()
        self.ftp_pass.setEchoMode(QLineEdit.Password)
        self.ftp_pass.setPlaceholderText(self.tr("密码"))
        layout.addRow(self.tr("密码:"), self.ftp_pass)

        self.ftp_mode = QComboBox()
        self.ftp_mode.addItems(["passive", "active"])
        layout.addRow(self.tr("模式:"), self.ftp_mode)

        self.ftp_ftps = QComboBox()
        self.ftp_ftps.addItems(["none", "implicit", "explicit"])
        layout.addRow(self.tr("FTPS:"), self.ftp_ftps)

        self.ftp_encoding = QLineEdit()
        self.ftp_encoding.setText("utf-8")
        layout.addRow(self.tr("编码:"), self.ftp_encoding)

        self.config_tabs.addTab(page, "FTP")

    def _create_serial_page(self) -> None:
        """创建串口配置页面"""
        page = QWidget()
        layout = QFormLayout(page)

        self.serial_port = QLineEdit()
        self.serial_port.setPlaceholderText("/dev/ttyUSB0 或 COM1")
        layout.addRow(self.tr("端口:"), self.serial_port)

        self.serial_baud = QComboBox()
        self.serial_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.serial_baud.setCurrentText("115200")
        layout.addRow(self.tr("波特率:"), self.serial_baud)

        self.serial_databits = QComboBox()
        self.serial_databits.addItems(["5", "6", "7", "8"])
        self.serial_databits.setCurrentText("8")
        layout.addRow(self.tr("数据位:"), self.serial_databits)

        self.serial_parity = QComboBox()
        self.serial_parity.addItems(["none", "even", "odd", "mark", "space"])
        layout.addRow(self.tr("校验:"), self.serial_parity)

        self.serial_stopbits = QComboBox()
        self.serial_stopbits.addItems(["1", "1.5", "2"])
        layout.addRow(self.tr("停止位:"), self.serial_stopbits)

        self.serial_flow = QComboBox()
        self.serial_flow.addItem(self.tr("无"), SerialFlowControl.NONE.value)
        self.serial_flow.addItem("XON/XOFF", SerialFlowControl.XON_XOFF.value)
        self.serial_flow.addItem("RTS/CTS", SerialFlowControl.RTS_CTS.value)
        self.serial_flow.addItem("DSR/DTR", SerialFlowControl.DSR_DTR.value)
        layout.addRow(self.tr("流控:"), self.serial_flow)

        self.config_tabs.addTab(page, "Serial")

    def _create_tcp_page(self) -> None:
        """创建 TCP 配置页面"""
        page = QWidget()
        layout = QFormLayout(page)

        self.tcp_host = QLineEdit()
        self.tcp_host.setPlaceholderText("192.168.1.100")
        layout.addRow(self.tr("主机:"), self.tcp_host)

        self.tcp_port = QSpinBox()
        self.tcp_port.setRange(1, 65535)
        layout.addRow(self.tr("端口:"), self.tcp_port)

        self.tcp_timeout = QDoubleSpinBox()
        self.tcp_timeout.setRange(1, 60)
        self.tcp_timeout.setValue(10)
        self.tcp_timeout.setSuffix(" 秒")
        layout.addRow(self.tr("超时:"), self.tcp_timeout)

        self.tcp_keepalive = QCheckBox()
        self.tcp_keepalive.setChecked(True)
        layout.addRow(self.tr("Keep-Alive:"), self.tcp_keepalive)

        self.config_tabs.addTab(page, "TCP")

    def _create_udp_page(self) -> None:
        """创建 UDP 配置页面"""
        page = QWidget()
        layout = QFormLayout(page)

        self.udp_mode = QComboBox()
        self.udp_mode.addItems(["client", "server", "bidirectional"])
        layout.addRow(self.tr("模式:"), self.udp_mode)

        self.udp_local_port = QSpinBox()
        self.udp_local_port.setRange(0, 65535)
        layout.addRow(self.tr("本地端口:"), self.udp_local_port)

        self.udp_remote_host = QLineEdit()
        self.udp_remote_host.setPlaceholderText("192.168.1.100")
        layout.addRow(self.tr("远程主机:"), self.udp_remote_host)

        self.udp_remote_port = QSpinBox()
        self.udp_remote_port.setRange(1, 65535)
        layout.addRow(self.tr("远程端口:"), self.udp_remote_port)

        self.udp_broadcast = QCheckBox()
        layout.addRow(self.tr("广播:"), self.udp_broadcast)

        self.config_tabs.addTab(page, "UDP")

    def _create_vnc_page(self) -> None:
        """创建 VNC 配置页面"""
        page = QWidget()
        layout = QFormLayout(page)

        self.vnc_host = QLineEdit()
        self.vnc_host.setPlaceholderText("192.168.1.100")
        layout.addRow(self.tr("主机:"), self.vnc_host)

        self.vnc_port = QSpinBox()
        self.vnc_port.setRange(1, 65535)
        self.vnc_port.setValue(5900)
        layout.addRow(self.tr("端口:"), self.vnc_port)

        self.vnc_password = QLineEdit()
        self.vnc_password.setEchoMode(QLineEdit.Password)
        layout.addRow(self.tr("密码:"), self.vnc_password)

        self.vnc_color_depth = QComboBox()
        self.vnc_color_depth.addItems(["8", "16", "24", "32"])
        self.vnc_color_depth.setCurrentText("24")
        layout.addRow(self.tr("色深:"), self.vnc_color_depth)

        self.vnc_shared = QCheckBox()
        self.vnc_shared.setChecked(True)
        layout.addRow(self.tr("共享:"), self.vnc_shared)

        self.vnc_view_only = QCheckBox()
        layout.addRow(self.tr("只读:"), self.vnc_view_only)

        self.config_tabs.addTab(page, "VNC")

    def _setup_connections(self) -> None:
        """设置信号连接"""
        self.type_combo.currentTextChanged.connect(self._on_type_changed)

    def set_open_after_save_enabled(self, enabled: bool) -> None:
        """设置是否展示“保存并连接”动作。"""
        self._open_after_save_enabled = enabled
        self._update_submit_buttons()
        self._refresh_type_hint()

    def set_quick_connect_mode(self, enabled: bool) -> None:
        """设置是否为快速连接模式。"""
        self._quick_connect_mode = enabled
        self._update_submit_buttons()
        self._refresh_type_hint()

    def should_open_after_accept(self) -> bool:
        """返回对话框关闭后是否应立即打开连接。"""
        return self._open_after_accept

    def _update_submit_buttons(self) -> None:
        """刷新底部提交按钮状态。"""
        show_save_and_open = self._open_after_save_enabled and not self._quick_connect_mode
        self.save_and_open_btn.setVisible(show_save_and_open)
        if self._quick_connect_mode:
            self.ok_btn.setText(self.tr("连接"))
        else:
            self.ok_btn.setText(self.tr("确定"))

    def _refresh_type_hint(self) -> None:
        """刷新当前连接类型提示。"""
        type_text = self.type_combo.currentText()
        hint_map = {
            "SSH": self.tr(
                "推荐先填写主机、用户名，以及密码或私钥。保存并连接后会直接进入终端，右键还能打开文件浏览器。"
            ),
            "SFTP": self.tr(
                "适合直接做文件传输和目录浏览。填写主机、用户名及认证信息后，连接将直接打开文件视图。"
            ),
            "FTP": self.tr("用于传统文件传输。建议确认被动/主动模式和 FTPS 方式后再保存。"),
            "SERIAL": self.tr("串口连接至少需要端口和波特率；保存后即可进入终端调试设备。"),
            "TCP": self.tr("适合调试原始 TCP 服务，请确认主机、端口和超时配置。"),
            "UDP": self.tr("适合网络调试，注意根据模式填写本地端口和远程主机信息。"),
            "VNC": self.tr(
                "连接后会直接进入远程桌面视图；Linux 下如需密码认证，请确认已安装 VNC 加密依赖。"
            ),
        }
        mode_text = ""
        if self._quick_connect_mode:
            mode_text = self.tr(" 当前为快速连接，仅本次打开，不会保存到连接列表。")
        elif self._open_after_save_enabled:
            mode_text = self.tr(" 你也可以直接使用“保存并连接”，减少首次使用的往返操作。")
        self.connection_hint_label.setText(f"{hint_map.get(type_text, '')}{mode_text}".strip())

    def set_config_manager(self, manager: ConfigManager) -> None:
        """设置配置管理器，用于模板读写。"""
        self._config_manager = manager
        self._reload_template_choices()
        self._reload_auth_template_choices()

    def _on_type_changed(self) -> None:
        """连接类型改变"""
        type_map = {
            "SSH": 0,
            "SFTP": 1,
            "FTP": 2,
            "SERIAL": 3,
            "TCP": 4,
            "UDP": 5,
            "VNC": 6,
        }

        type_text = self.type_combo.currentText()
        if type_text in type_map:
            self.config_tabs.setCurrentIndex(type_map[type_text])
        self._reload_template_choices()
        self._reload_auth_template_choices()
        self._refresh_type_hint()

    def _accept_without_open(self) -> None:
        """保存配置并关闭对话框。"""
        self._open_after_accept = False
        self.accept()

    def _accept_and_open(self) -> None:
        """保存配置并请求主窗口立即打开。"""
        self._open_after_accept = True
        self.accept()

    def _resolved_connection_name(self) -> str:
        """返回用于保存的连接名称。"""
        explicit_name = self.name_edit.text().strip()
        if explicit_name:
            return explicit_name

        type_text = self.type_combo.currentText()
        if type_text == "SSH":
            host = self.ssh_fields["host"].text().strip()
            username = self.ssh_fields["username"].text().strip()
            if host and username:
                return f"{username}@{host}"
            if host:
                return host
        elif type_text == "SFTP":
            host = self.sftp_fields["host"].text().strip()
            username = self.sftp_fields["username"].text().strip()
            if host and username:
                return f"SFTP {username}@{host}"
            if host:
                return f"SFTP {host}"
        elif type_text == "FTP":
            host = self.ftp_host.text().strip()
            if host:
                return f"FTP {host}"
        elif type_text == "SERIAL":
            port = self.serial_port.text().strip()
            if port:
                return port
        elif type_text == "TCP":
            host = self.tcp_host.text().strip()
            port = self.tcp_port.value()
            if host and port:
                return f"{host}:{port}"
            if host:
                return host
        elif type_text == "UDP":
            remote_host = self.udp_remote_host.text().strip()
            remote_port = self.udp_remote_port.value()
            if remote_host and remote_port:
                return f"UDP {remote_host}:{remote_port}"
            if remote_host:
                return f"UDP {remote_host}"
        elif type_text == "VNC":
            host = self.vnc_host.text().strip()
            port = self.vnc_port.value()
            if host and port:
                return f"VNC {host}:{port}"
            if host:
                return f"VNC {host}"
        return "未命名连接"

    def _validate_inputs(self) -> Optional[str]:
        """校验当前表单，返回错误文案。"""
        type_text = self.type_combo.currentText()
        if type_text == "SSH":
            if not self.ssh_fields["host"].text().strip():
                return self.tr("SSH 连接必须填写主机地址")
            if not self.ssh_fields["username"].text().strip():
                return self.tr("SSH 连接必须填写用户名")
            if not (
                self.ssh_fields["password"].text()
                or self.ssh_fields["private_key_path"].text().strip()
            ):
                return self.tr("SSH 连接至少需要填写密码或私钥路径")
        elif type_text == "SFTP":
            if not self.sftp_fields["host"].text().strip():
                return self.tr("SFTP 连接必须填写主机地址")
            if not self.sftp_fields["username"].text().strip():
                return self.tr("SFTP 连接必须填写用户名")
            if not (
                self.sftp_fields["password"].text()
                or self.sftp_fields["private_key_path"].text().strip()
            ):
                return self.tr("SFTP 连接至少需要填写密码或私钥路径")
        elif type_text == "FTP":
            if not self.ftp_host.text().strip():
                return self.tr("FTP 连接必须填写主机地址")
        elif type_text == "SERIAL":
            if not self.serial_port.text().strip():
                return self.tr("串口连接必须填写端口")
        elif type_text == "TCP":
            if not self.tcp_host.text().strip():
                return self.tr("TCP 连接必须填写主机地址")
            if self.tcp_port.value() <= 0:
                return self.tr("TCP 连接必须填写有效端口")
        elif type_text == "UDP":
            if self.udp_mode.currentText() != "server" and not self.udp_remote_host.text().strip():
                return self.tr("UDP 客户端或双向模式必须填写远程主机")
            if self.udp_mode.currentText() != "server" and self.udp_remote_port.value() <= 0:
                return self.tr("UDP 客户端或双向模式必须填写有效远程端口")
        elif type_text == "VNC":
            if not self.vnc_host.text().strip():
                return self.tr("VNC 连接必须填写主机地址")
        return None

    def accept(self) -> None:
        """在关闭前校验表单。"""
        error_text = self._validate_inputs()
        if error_text:
            QMessageBox.warning(self, self.tr("输入不完整"), error_text)
            return
        super().accept()

    def _reload_template_choices(self) -> None:
        """刷新当前类型对应的模板下拉框。"""
        current_data = self.template_combo.currentData()
        current_template_id = current_data.get("id") if isinstance(current_data, dict) else None
        self.template_combo.clear()
        self.template_combo.addItem(self.tr("无模板"), None)

        templates = []
        if self._config_manager is not None:
            templates = self._config_manager.load_templates_for_type(
                self.type_combo.currentText().lower(),
                template_scope="connection",
            )

        for template in templates:
            self.template_combo.addItem(template.get("name", self.tr("未命名模板")), template)

        if current_template_id is not None:
            for index in range(self.template_combo.count()):
                data = self.template_combo.itemData(index)
                if isinstance(data, dict) and data.get("id") == current_template_id:
                    self.template_combo.setCurrentIndex(index)
                    break
        self.apply_template_btn.setEnabled(bool(templates))
        self.delete_template_btn.setEnabled(bool(templates))

    def _supports_auth_templates(self) -> bool:
        """当前连接类型是否支持认证模板。"""
        return self.type_combo.currentText() in {"SSH", "SFTP"}

    def _current_auth_fields(self) -> Optional[Dict[str, Any]]:
        """返回当前 SSH/SFTP 的认证字段集合。"""
        type_text = self.type_combo.currentText()
        if type_text == "SSH":
            return self.ssh_fields
        if type_text == "SFTP":
            return self.sftp_fields
        return None

    def _reload_auth_template_choices(self) -> None:
        """刷新认证模板下拉框。"""
        supported = self._supports_auth_templates()
        self.auth_template_row.setVisible(supported)
        if not supported:
            self.auth_template_combo.clear()
            self.auth_template_combo.addItem(self.tr("无认证模板"), None)
            self.apply_auth_template_btn.setEnabled(False)
            self.delete_auth_template_btn.setEnabled(False)
            return

        current_data = self.auth_template_combo.currentData()
        current_template_id = current_data.get("id") if isinstance(current_data, dict) else None
        self.auth_template_combo.clear()
        self.auth_template_combo.addItem(self.tr("无认证模板"), None)

        templates = []
        if self._config_manager is not None:
            templates = self._config_manager.load_templates_for_type(
                self.type_combo.currentText().lower(),
                template_scope="auth_profile",
            )

        for template in templates:
            self.auth_template_combo.addItem(
                template.get("name", self.tr("未命名认证模板")),
                template,
            )

        if current_template_id is not None:
            for index in range(self.auth_template_combo.count()):
                data = self.auth_template_combo.itemData(index)
                if isinstance(data, dict) and data.get("id") == current_template_id:
                    self.auth_template_combo.setCurrentIndex(index)
                    break

        self.apply_auth_template_btn.setEnabled(bool(templates))
        self.delete_auth_template_btn.setEnabled(bool(templates))

    @staticmethod
    def _config_class_for_type(type_text: str):
        """根据类型返回配置类。"""
        type_map = {
            "SSH": SSHConfig,
            "SFTP": SFTPConfig,
            "FTP": FTPConfig,
            "SERIAL": SerialConfig,
            "TCP": TCPConfig,
            "UDP": UDPConfig,
            "VNC": VNCConfig,
        }
        return type_map[type_text]

    def _current_config_dict(self) -> Dict[str, Any]:
        """将当前表单转换为字典。"""
        return self.get_config().to_dict()

    def _current_auth_template_payload(self) -> Dict[str, Any]:
        """提取当前表单中的认证相关字段。"""
        fields = self._current_auth_fields()
        if fields is None:
            return {}
        return {
            "username": fields["username"].text().strip(),
            "password": fields["password"].text(),
            "private_key_path": fields["private_key_path"].text().strip(),
            "passphrase": fields["passphrase"].text(),
            "timeout": fields["timeout"].value(),
            "proxy_command": fields["proxy_command"].text().strip(),
        }

    def _save_as_template(self) -> None:
        """将当前表单保存为模板。"""
        if self._config_manager is None:
            QMessageBox.information(
                self, self.tr("提示"), self.tr("当前未绑定配置目录，无法保存模板")
            )
            return

        default_name = self.name_edit.text().strip() or f"{self.type_combo.currentText()} Template"
        template_name, ok = QInputDialog.getText(
            self,
            self.tr("保存模板"),
            self.tr("模板名称:"),
            text=default_name,
        )
        if not ok or not template_name.strip():
            return

        try:
            self._config_manager.upsert_connection_template(
                template_name,
                self.type_combo.currentText(),
                self._current_config_dict(),
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("保存模板失败"), str(exc))
            return

        self._reload_template_choices()
        for index in range(self.template_combo.count()):
            data = self.template_combo.itemData(index)
            if isinstance(data, dict) and data.get("name") == template_name.strip():
                self.template_combo.setCurrentIndex(index)
                break

    def _save_as_auth_template(self) -> None:
        """将当前认证信息保存为认证模板。"""
        if self._config_manager is None:
            QMessageBox.information(
                self,
                self.tr("提示"),
                self.tr("当前未绑定配置目录，无法保存认证模板"),
            )
            return
        if not self._supports_auth_templates():
            QMessageBox.information(self, self.tr("提示"), self.tr("当前连接类型不支持认证模板"))
            return

        fields = self._current_auth_fields()
        default_name = ""
        if fields is not None:
            default_name = fields["username"].text().strip()
        if not default_name:
            default_name = self.tr(f"{self.type_combo.currentText()} 认证模板")

        template_name, ok = QInputDialog.getText(
            self,
            self.tr("保存认证模板"),
            self.tr("认证模板名称:"),
            text=default_name,
        )
        if not ok or not template_name.strip():
            return

        try:
            self._config_manager.upsert_connection_template(
                template_name,
                self.type_combo.currentText(),
                self._current_auth_template_payload(),
                template_scope="auth_profile",
            )
        except Exception as exc:
            QMessageBox.critical(self, self.tr("保存认证模板失败"), str(exc))
            return

        self._reload_auth_template_choices()
        for index in range(self.auth_template_combo.count()):
            data = self.auth_template_combo.itemData(index)
            if isinstance(data, dict) and data.get("name") == template_name.strip():
                self.auth_template_combo.setCurrentIndex(index)
                break

    def _apply_selected_template(self) -> None:
        """应用选中的模板。"""
        template = self.template_combo.currentData()
        if not isinstance(template, dict):
            return

        type_text = self.type_combo.currentText()
        config_cls = self._config_class_for_type(type_text)
        payload = dict(template.get("payload", {}))
        current_name = self.name_edit.text().strip()
        payload["connection_type"] = type_text.lower()
        payload.setdefault("name", current_name or template.get("name", self.tr("未命名连接")))
        payload.pop("password", None)
        payload.pop("passphrase", None)
        payload.pop("id", None)

        try:
            config = config_cls.from_dict(payload)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("应用模板失败"), str(exc))
            return

        self.set_config(config)
        if current_name:
            self.name_edit.setText(current_name)

    def _apply_selected_auth_template(self) -> None:
        """应用选中的认证模板。"""
        fields = self._current_auth_fields()
        template = self.auth_template_combo.currentData()
        if fields is None or not isinstance(template, dict):
            return

        payload = dict(template.get("payload", {}))
        fields["username"].setText(str(payload.get("username") or ""))
        fields["password"].setText(str(payload.get("password") or ""))
        fields["private_key_path"].setText(str(payload.get("private_key_path") or ""))
        fields["passphrase"].setText(str(payload.get("passphrase") or ""))
        try:
            timeout_value = float(payload.get("timeout") or fields["timeout"].value())
        except (TypeError, ValueError):
            timeout_value = fields["timeout"].value()
        fields["timeout"].setValue(timeout_value)
        fields["proxy_command"].setText(str(payload.get("proxy_command") or ""))

    def _delete_selected_template(self) -> None:
        """删除当前选中的模板。"""
        if self._config_manager is None:
            return
        template = self.template_combo.currentData()
        if not isinstance(template, dict):
            return
        self._config_manager.remove_connection_template(template["id"])
        self._reload_template_choices()

    def _delete_selected_auth_template(self) -> None:
        """删除当前选中的认证模板。"""
        if self._config_manager is None:
            return
        template = self.auth_template_combo.currentData()
        if not isinstance(template, dict):
            return
        self._config_manager.remove_connection_template(template["id"])
        self._reload_auth_template_choices()

    def _browse_key_file(self, target_edit: QLineEdit) -> None:
        """浏览私钥文件。"""
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("选择私钥文件"))
        if file_path:
            target_edit.setText(file_path)

    def _build_ssh_like_config(self, fields: Dict[str, Any], config_cls):
        """构建 SSH/SFTP 配置。"""
        kwargs = {
            **self._base_config_kwargs(),
            "host": fields["host"].text().strip(),
            "port": fields["port"].value(),
            "username": fields["username"].text().strip(),
            "password": fields["password"].text(),
            "private_key_path": fields["private_key_path"].text().strip(),
            "passphrase": fields["passphrase"].text(),
            "timeout": fields["timeout"].value(),
            "proxy_command": fields["proxy_command"].text().strip(),
        }
        if config_cls is SFTPConfig:
            kwargs["initial_path"] = fields["initial_path"].text().strip() or "."
        return config_cls(**kwargs)

    def _parsed_tags(self) -> list[str]:
        """解析标签输入，去重并保留顺序。"""
        tags: list[str] = []
        seen: set[str] = set()
        for raw_tag in self.tags_edit.text().split(","):
            tag = raw_tag.strip()
            normalized = tag.casefold()
            if not tag or normalized in seen:
                continue
            seen.add(normalized)
            tags.append(tag)
        return tags

    def _base_config_kwargs(self) -> Dict[str, Any]:
        """提取所有连接类型共用的元数据字段。"""
        group_name = self.group_edit.text().strip() or "default"
        return {
            "name": self._resolved_connection_name(),
            "group": group_name,
            "environment": self.environment_edit.text().strip(),
            "project": self.project_edit.text().strip(),
            "business_domain": self.business_domain_edit.text().strip(),
            "tags": self._parsed_tags(),
            "description": self.description_edit.text().strip(),
        }

    def get_config(self) -> BaseConnectionConfig:
        """
        获取配置对象

        Returns:
            BaseConnectionConfig: 配置对象
        """
        name = self._resolved_connection_name()
        type_text = self.type_combo.currentText()
        common_kwargs = self._base_config_kwargs()

        if type_text == "SSH":
            return self._build_ssh_like_config(self.ssh_fields, SSHConfig)
        elif type_text == "SFTP":
            return self._build_ssh_like_config(self.sftp_fields, SFTPConfig)
        elif type_text == "FTP":
            return FTPConfig(
                name=name,
                group=common_kwargs["group"],
                environment=common_kwargs["environment"],
                project=common_kwargs["project"],
                business_domain=common_kwargs["business_domain"],
                tags=common_kwargs["tags"],
                description=common_kwargs["description"],
                host=self.ftp_host.text(),
                port=self.ftp_port.value(),
                username=self.ftp_user.text(),
                password=self.ftp_pass.text(),
                mode=FTPMode(self.ftp_mode.currentText()),
                ftps_type=FTPSType(self.ftp_ftps.currentText()),
                encoding=self.ftp_encoding.text(),
            )
        elif type_text == "SERIAL":
            return SerialConfig(
                name=name,
                group=common_kwargs["group"],
                environment=common_kwargs["environment"],
                project=common_kwargs["project"],
                business_domain=common_kwargs["business_domain"],
                tags=common_kwargs["tags"],
                description=common_kwargs["description"],
                port=self.serial_port.text(),
                baud_rate=int(self.serial_baud.currentText()),
                byte_size=SerialByteSize(self.serial_databits.currentText()),
                parity=SerialParity(self.serial_parity.currentText()),
                stop_bits=SerialStopBits(self.serial_stopbits.currentText()),
                flow_control=SerialFlowControl(self.serial_flow.currentData()),
            )
        elif type_text == "TCP":
            return TCPConfig(
                name=name,
                group=common_kwargs["group"],
                environment=common_kwargs["environment"],
                project=common_kwargs["project"],
                business_domain=common_kwargs["business_domain"],
                tags=common_kwargs["tags"],
                description=common_kwargs["description"],
                host=self.tcp_host.text(),
                port=self.tcp_port.value(),
                timeout=self.tcp_timeout.value(),
                keepalive=self.tcp_keepalive.isChecked(),
            )
        elif type_text == "UDP":
            return UDPConfig(
                name=name,
                group=common_kwargs["group"],
                environment=common_kwargs["environment"],
                project=common_kwargs["project"],
                business_domain=common_kwargs["business_domain"],
                tags=common_kwargs["tags"],
                description=common_kwargs["description"],
                mode=UDPMode(self.udp_mode.currentText()),
                local_port=self.udp_local_port.value(),
                remote_host=self.udp_remote_host.text(),
                remote_port=self.udp_remote_port.value(),
                broadcast=self.udp_broadcast.isChecked(),
            )
        elif type_text == "VNC":
            return VNCConfig(
                name=name,
                group=common_kwargs["group"],
                environment=common_kwargs["environment"],
                project=common_kwargs["project"],
                business_domain=common_kwargs["business_domain"],
                tags=common_kwargs["tags"],
                description=common_kwargs["description"],
                host=self.vnc_host.text(),
                port=self.vnc_port.value(),
                password=self.vnc_password.text(),
                color_depth=VNCColorDepth(int(self.vnc_color_depth.currentText())),
                shared=self.vnc_shared.isChecked(),
                view_only=self.vnc_view_only.isChecked(),
            )

        raise ValueError(f"未知的连接类型: {type_text}")

    def set_config(self, config: BaseConnectionConfig) -> None:
        """
        设置配置对象

        Args:
            config: 配置对象
        """
        self._config = config
        self.name_edit.setText(config.name)
        self.group_edit.setText(getattr(config, "group", "") or "default")
        self.environment_edit.setText(getattr(config, "environment", "") or "")
        self.project_edit.setText(getattr(config, "project", "") or "")
        self.business_domain_edit.setText(getattr(config, "business_domain", "") or "")
        self.tags_edit.setText(", ".join(getattr(config, "tags", []) or []))
        self.description_edit.setText(getattr(config, "description", "") or "")

        # 根据类型设置对应页面
        if isinstance(config, FTPConfig):
            self.type_combo.setCurrentText("FTP")
            self.ftp_host.setText(config.host)
            self.ftp_port.setValue(config.port)
            self.ftp_user.setText(config.username)
            self.ftp_pass.setText(config.password)
            self.ftp_mode.setCurrentText(config.mode.value)
            self.ftp_ftps.setCurrentText(config.ftps_type.value)
            self.ftp_encoding.setText(config.encoding)
        elif isinstance(config, TCPConfig):
            self.type_combo.setCurrentText("TCP")
            self.tcp_host.setText(config.host)
            self.tcp_port.setValue(config.port)
            self.tcp_timeout.setValue(config.timeout)
            self.tcp_keepalive.setChecked(config.keepalive)
        elif isinstance(config, SerialConfig):
            self.type_combo.setCurrentText("SERIAL")
            self.serial_port.setText(config.port)
            self.serial_baud.setCurrentText(str(config.baud_rate))
            self.serial_databits.setCurrentText(config.byte_size.value)
            self.serial_parity.setCurrentText(config.parity.value)
            self.serial_stopbits.setCurrentText(config.stop_bits.value)
            index = self.serial_flow.findData(config.flow_control.value)
            if index >= 0:
                self.serial_flow.setCurrentIndex(index)
        elif isinstance(config, SSHConfig) and not isinstance(config, SFTPConfig):
            self.type_combo.setCurrentText("SSH")
            self.ssh_fields["host"].setText(config.host)
            self.ssh_fields["port"].setValue(config.port)
            self.ssh_fields["username"].setText(config.username)
            self.ssh_fields["password"].setText(config.password)
            self.ssh_fields["private_key_path"].setText(config.private_key_path)
            self.ssh_fields["passphrase"].setText(config.passphrase)
            self.ssh_fields["timeout"].setValue(config.timeout)
            self.ssh_fields["proxy_command"].setText(config.proxy_command)
        elif isinstance(config, SFTPConfig):
            self.type_combo.setCurrentText("SFTP")
            self.sftp_fields["host"].setText(config.host)
            self.sftp_fields["port"].setValue(config.port)
            self.sftp_fields["username"].setText(config.username)
            self.sftp_fields["password"].setText(config.password)
            self.sftp_fields["private_key_path"].setText(config.private_key_path)
            self.sftp_fields["passphrase"].setText(config.passphrase)
            self.sftp_fields["timeout"].setValue(config.timeout)
            self.sftp_fields["proxy_command"].setText(config.proxy_command)
            self.sftp_fields["initial_path"].setText(config.initial_path)
        elif isinstance(config, UDPConfig):
            self.type_combo.setCurrentText("UDP")
            self.udp_mode.setCurrentText(config.mode.value)
            self.udp_local_port.setValue(config.local_port)
            self.udp_remote_host.setText(config.remote_host)
            self.udp_remote_port.setValue(config.remote_port)
            self.udp_broadcast.setChecked(config.broadcast)
        elif isinstance(config, VNCConfig):
            self.type_combo.setCurrentText("VNC")
            self.vnc_host.setText(config.host)
            self.vnc_port.setValue(config.port)
            self.vnc_password.setText(config.password)
            self.vnc_color_depth.setCurrentText(str(config.color_depth.value))
            self.vnc_shared.setChecked(config.shared)
            self.vnc_view_only.setChecked(config.view_only)
        # ... 其他类型类似
        self._reload_template_choices()
