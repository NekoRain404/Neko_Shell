#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH 连接模块

实现了基于 Paramiko 的 SSH 连接功能。
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Optional, Tuple

from .base import BaseConnection, ConnectionInfo, ConnectionStatus, ConnectionType
from neko_shell.models.connection import SSHConfig
from neko_shell.utils.exceptions import (
    AuthenticationError,
    ConnectionError,
    ConnectionLostError,
    OperationError,
    TimeoutError,
)

_paramiko = None


def _get_paramiko():
    """延迟加载 paramiko。"""
    global _paramiko
    if _paramiko is None:
        try:
            import paramiko
        except ImportError as exc:
            raise ImportError("paramiko 未安装，请先安装 paramiko") from exc
        _paramiko = paramiko
    return _paramiko


class SSHConnection(BaseConnection):
    """
    SSH 连接实现。

    提供密码/密钥认证、命令执行和可选交互式 shell。
    """

    def __init__(self, config: SSHConfig):
        super().__init__(config)
        self._client = None
        self._shell = None
        self._shell_reader: Optional[threading.Thread] = None
        self._shell_running = False
        self.prefers_shell_commands = True
        self._monitor_lock = threading.Lock()
        self._last_cpu_snapshot: Optional[tuple[int, int]] = None
        self._last_net_snapshot: Optional[dict[str, tuple[int, int]]] = None
        self._last_monitor_ts: Optional[float] = None
        self._reconnect_delay = 1.0

    @property
    def host(self) -> str:
        """获取主机地址。"""
        return self._config.host

    @property
    def username(self) -> str:
        """获取用户名。"""
        return self._config.username

    @property
    def password(self) -> str:
        """获取密码。"""
        return self._config.password

    @property
    def port(self) -> int:
        """获取端口号。"""
        return self._config.port

    @property
    def conn(self):
        """兼容旧模块的 Paramiko client 访问方式。"""
        return self._client

    @staticmethod
    def _monitor_command() -> str:
        """返回监控采样命令。"""
        return (
            "sh -lc 'hostname; "
            "echo __CS_SYS__; uname -srmo; "
            "echo __CS_CPUINFO__; nproc; "
            "echo __CS_STAT__; head -n 1 /proc/stat; "
            "echo __CS_MEM__; grep -E \"^(MemTotal|MemAvailable|SwapTotal|SwapFree):\" /proc/meminfo; "
            "echo __CS_DF__; df -P / | tail -n 1; "
            "echo __CS_LOAD__; cat /proc/loadavg; "
            "echo __CS_UPTIME__; cat /proc/uptime; "
            "echo __CS_NET__; cat /proc/net/dev'"
        )

    def _build_connect_kwargs(self) -> dict[str, Any]:
        """构造 SSH 连接参数。"""
        paramiko = _get_paramiko()
        kwargs: dict[str, Any] = {
            "hostname": self._config.host,
            "port": self._config.port,
            "username": self._config.username,
            "timeout": self._config.timeout,
            "banner_timeout": self._config.timeout,
            "auth_timeout": self._config.timeout,
            "allow_agent": self._config.allow_agent,
            "look_for_keys": self._config.look_for_keys,
        }

        if self._config.password:
            kwargs["password"] = self._config.password
        if self._config.private_key_path:
            kwargs["key_filename"] = self._config.private_key_path
        if self._config.passphrase:
            kwargs["passphrase"] = self._config.passphrase
        if self._config.proxy_command:
            kwargs["sock"] = paramiko.ProxyCommand(self._config.proxy_command)

        return kwargs

    def connect(self) -> None:
        """建立 SSH 连接。"""
        self._set_status(ConnectionStatus.CONNECTING)
        self._logger.info("正在连接 SSH 服务器: %s:%s", self._config.host, self._config.port)

        paramiko = _get_paramiko()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(**self._build_connect_kwargs())
            self._client = client
            self._set_status(ConnectionStatus.CONNECTED)
        except paramiko.AuthenticationException as exc:
            self._set_status(ConnectionStatus.ERROR, str(exc))
            raise AuthenticationError(f"SSH 认证失败: {exc}") from exc
        except paramiko.BadHostKeyException as exc:
            self._set_status(ConnectionStatus.ERROR, str(exc))
            raise ConnectionError(f"SSH 主机密钥校验失败: {exc}") from exc
        except (paramiko.SSHException, socket.error, OSError) as exc:
            self._set_status(ConnectionStatus.ERROR, str(exc))
            if isinstance(exc, socket.timeout):
                raise TimeoutError(f"SSH 连接超时: {self._config.host}:{self._config.port}") from exc
            raise ConnectionError(f"SSH 连接失败: {exc}") from exc

    def _cleanup_runtime_state(self) -> None:
        """清理当前 SSH 运行时状态，不主动切换状态。"""
        self._shell_running = False

        if self._shell_reader and self._shell_reader.is_alive():
            self._shell_reader.join(timeout=1.0)
        self._shell_reader = None

        if self._shell is not None:
            try:
                self._shell.close()
            except Exception:
                pass
            self._shell = None

        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def reconnect(self) -> None:
        """按配置执行自动重连。"""
        attempts = max(1, int(getattr(self._config, "max_reconnect_attempts", 1) or 1))
        last_error: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            self._set_status(
                ConnectionStatus.RECONNECTING,
                f"正在重连 ({attempt}/{attempts})",
            )
            self._cleanup_runtime_state()
            try:
                self.connect()
                self._logger.info(
                    "SSH 重连成功 [%s:%s] (%s/%s)",
                    self._config.host,
                    self._config.port,
                    attempt,
                    attempts,
                )
                return
            except Exception as exc:
                last_error = exc
                self._logger.warning(
                    "SSH 重连失败 [%s:%s] (%s/%s): %s",
                    self._config.host,
                    self._config.port,
                    attempt,
                    attempts,
                    exc,
                )
                if attempt < attempts:
                    time.sleep(self._reconnect_delay)

        message = f"SSH 自动重连失败: {last_error}" if last_error else "SSH 自动重连失败"
        self._set_status(ConnectionStatus.ERROR, message)
        raise ConnectionLostError(message)

    def disconnect(self) -> None:
        """断开 SSH 连接。"""
        self._cleanup_runtime_state()
        self._set_status(ConnectionStatus.DISCONNECTED)

    def is_connected(self) -> bool:
        """检查 SSH 连接状态。"""
        if self._client is None:
            return False

        transport = self._client.get_transport()
        return bool(transport and transport.is_active())

    def get_info(self) -> ConnectionInfo:
        """获取连接信息。"""
        return ConnectionInfo(
            id=self._id,
            name=self._config.name,
            connection_type=ConnectionType.SSH,
            host=self._config.host,
            port=self._config.port,
            status=self._status,
            error_message=self._last_error,
        )

    def _check_connection(self) -> None:
        """检查 SSH 连接状态。"""
        if self.is_connected():
            return
        if getattr(self._config, "auto_reconnect", False):
            self.reconnect()
            if self.is_connected():
                return
        raise ConnectionLostError("SSH 连接已断开")

    @staticmethod
    def _decode_stream(stream: Any) -> str:
        """将 Paramiko 输出流解码为文本。"""
        data = stream.read()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)

    def exec_command(self, command: str, timeout: Optional[float] = None) -> Tuple[int, str, str]:
        """执行远程命令并返回退出码、标准输出和标准错误。"""
        self._check_connection()

        try:
            stdin, stdout, stderr = self._client.exec_command(
                command,
                timeout=timeout or self._config.timeout,
                get_pty=self._config.request_pty,
            )
            exit_status = stdout.channel.recv_exit_status()
            return (
                exit_status,
                self._decode_stream(stdout),
                self._decode_stream(stderr),
            )
        except socket.timeout as exc:
            raise TimeoutError(f"SSH 命令执行超时: {command}") from exc
        except Exception as exc:
            raise OperationError(f"SSH 命令执行失败: {exc}") from exc

    def exec(self, cmd: str = "", pty: bool = False, timeout: Optional[float] = None) -> str:
        """
        兼容旧主线的文本命令执行方法。

        Returns:
            str: 标准输出文本
        """
        self._check_connection()
        try:
            _, stdout, _ = self._client.exec_command(
                cmd,
                timeout=timeout or self._config.timeout,
                get_pty=pty,
            )
            return self._decode_stream(stdout)
        except socket.timeout as exc:
            raise TimeoutError(f"SSH 命令执行超时: {cmd}") from exc
        except Exception as exc:
            raise OperationError(f"SSH 命令执行失败: {exc}") from exc

    def sudo_exec(self, cmd: str = "", pty: bool = False, timeout: Optional[float] = None) -> str:
        """
        使用 sudo 执行命令，兼容旧主线调用方式。
        """
        self._check_connection()
        if self.username == "root":
            return self.exec(cmd=cmd, pty=pty, timeout=timeout)

        try:
            stdin, stdout, _ = self._client.exec_command(
                f"sudo -S {cmd}",
                timeout=timeout or self._config.timeout,
                get_pty=pty,
            )
            if self.password:
                stdin.write(f"{self.password}\n")
                stdin.flush()
            return self._decode_stream(stdout)
        except socket.timeout as exc:
            raise TimeoutError(f"SSH sudo 命令执行超时: {cmd}") from exc
        except Exception as exc:
            raise OperationError(f"SSH sudo 命令执行失败: {exc}") from exc

    def open_shell(self) -> None:
        """打开交互式 shell。"""
        self._check_connection()
        if self._shell is not None and not self._shell.closed:
            return

        self._shell = self._client.invoke_shell(
            term=self._config.term_type,
            width=self._config.term_width,
            height=self._config.term_height,
        )
        self._shell.settimeout(0.2)
        self._shell_running = True
        self._shell_reader = threading.Thread(target=self._read_shell_loop, daemon=True)
        self._shell_reader.start()

    def _read_shell_loop(self) -> None:
        """持续读取 shell 输出。"""
        while self._shell_running and self._shell is not None:
            try:
                if self._shell.recv_ready():
                    data = self._shell.recv(4096)
                    if not data:
                        break
                    self.emit("data_received", data)
                else:
                    time.sleep(0.05)
            except socket.timeout:
                continue
            except Exception as exc:
                self._logger.debug("SSH shell 读取结束: %s", exc)
                break

        self._shell_running = False

    def write(self, data: bytes) -> int:
        """向交互式 shell 写入数据。"""
        if self._shell is None or self._shell.closed:
            self.open_shell()

        if self._shell is None:
            raise OperationError("SSH shell 未初始化")

        try:
            payload = data if isinstance(data, bytes) else bytes(data)
            return self._shell.send(payload)
        except Exception as exc:
            raise OperationError(f"SSH shell 写入失败: {exc}") from exc

    def open_sftp(self):
        """打开并返回 SFTP 会话。"""
        self._check_connection()
        return self._client.open_sftp()

    @staticmethod
    def _parse_cpu_snapshot(line: str) -> tuple[int, int]:
        """解析 /proc/stat 首行快照。"""
        parts = line.split()
        if len(parts) < 5 or parts[0] != "cpu":
            return (0, 0)
        values = [int(value) for value in parts[1:]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return (total, idle)

    @staticmethod
    def _parse_mem_usage(lines: list[str]) -> float:
        """解析内存使用率。"""
        metrics: dict[str, int] = {}
        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metrics[key.strip()] = int(value.strip().split()[0])
        total = metrics.get("MemTotal", 0)
        available = metrics.get("MemAvailable", 0)
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, ((total - available) / total) * 100))

    @staticmethod
    def _parse_mem_metrics(lines: list[str]) -> dict[str, float]:
        """解析内存与交换区详细信息。"""
        metrics: dict[str, int] = {}
        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metrics[key.strip()] = int(value.strip().split()[0])

        total = metrics.get("MemTotal", 0)
        available = metrics.get("MemAvailable", 0)
        swap_total = metrics.get("SwapTotal", 0)
        swap_free = metrics.get("SwapFree", 0)
        used = max(0, total - available)
        swap_used = max(0, swap_total - swap_free)

        memory_usage = 0.0 if total <= 0 else max(0.0, min(100.0, (used / total) * 100))
        swap_usage = 0.0 if swap_total <= 0 else max(0.0, min(100.0, (swap_used / swap_total) * 100))
        return {
            "memory": memory_usage,
            "memory_total_mb": total / 1024 if total else 0.0,
            "memory_available_mb": available / 1024 if available else 0.0,
            "memory_used_mb": used / 1024 if used else 0.0,
            "swap": swap_usage,
            "swap_total_mb": swap_total / 1024 if swap_total else 0.0,
            "swap_used_mb": swap_used / 1024 if swap_used else 0.0,
        }

    @staticmethod
    def _parse_disk_usage(line: str) -> float:
        """解析根分区磁盘使用率。"""
        parts = line.split()
        if len(parts) < 5:
            return 0.0
        return float(parts[4].rstrip("%"))

    @staticmethod
    def _parse_disk_metrics(line: str) -> dict[str, float]:
        """解析根分区详细磁盘指标。"""
        parts = line.split()
        if len(parts) < 6:
            return {
                "disk": 0.0,
                "disk_total_gb": 0.0,
                "disk_used_gb": 0.0,
                "disk_free_gb": 0.0,
            }

        total_blocks = float(parts[1])
        used_blocks = float(parts[2])
        free_blocks = float(parts[3])
        usage = float(parts[4].rstrip("%"))
        block_to_gb = 1024.0 * 1024.0
        return {
            "disk": usage,
            "disk_total_gb": total_blocks / block_to_gb,
            "disk_used_gb": used_blocks / block_to_gb,
            "disk_free_gb": free_blocks / block_to_gb,
        }

    @staticmethod
    def _parse_loadavg(line: str) -> dict[str, float]:
        """解析系统负载与任务数。"""
        parts = line.split()
        if len(parts) < 4:
            return {"load1": 0.0, "load5": 0.0, "load15": 0.0, "running_tasks": 0.0, "process_count": 0.0}
        tasks = parts[3].split("/", 1)
        running = float(tasks[0]) if tasks and tasks[0].isdigit() else 0.0
        total = float(tasks[1]) if len(tasks) > 1 and tasks[1].isdigit() else 0.0
        return {
            "load1": float(parts[0]),
            "load5": float(parts[1]),
            "load15": float(parts[2]),
            "running_tasks": running,
            "process_count": total,
        }

    @staticmethod
    def _parse_uptime(line: str) -> float:
        """解析系统运行时长，返回小时数。"""
        parts = line.split()
        if not parts:
            return 0.0
        try:
            return float(parts[0]) / 3600.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_net_snapshot(text: str) -> dict[str, tuple[int, int]]:
        """解析网络流量快照。"""
        result: dict[str, tuple[int, int]] = {}
        for line in text.splitlines()[2:]:
            if ":" not in line:
                continue
            name, payload = line.split(":", 1)
            iface = name.strip()
            if iface == "lo":
                continue
            values = payload.split()
            if len(values) >= 16:
                result[iface] = (int(values[0]), int(values[8]))
        return result

    @staticmethod
    def _parse_cpu_cores(line: str) -> float:
        """解析 CPU 核心数。"""
        try:
            return float(line.strip())
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _compute_cpu_usage(
        previous: Optional[tuple[int, int]],
        current: tuple[int, int],
    ) -> float:
        """根据两次快照计算 CPU 使用率。"""
        if previous is None:
            return 0.0
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))

    @staticmethod
    def _compute_network_speed(
        previous: Optional[dict[str, tuple[int, int]]],
        current: dict[str, tuple[int, int]],
        interval: float,
    ) -> tuple[float, float]:
        """根据两次网络快照计算上下行速率。"""
        if not previous or interval <= 0:
            return (0.0, 0.0)

        best_rx = 0.0
        best_tx = 0.0
        for iface, (rx_bytes, tx_bytes) in current.items():
            if iface not in previous:
                continue
            prev_rx, prev_tx = previous[iface]
            best_rx = max(best_rx, max(0, rx_bytes - prev_rx) / interval)
            best_tx = max(best_tx, max(0, tx_bytes - prev_tx) / interval)
        return (best_rx, best_tx)

    @staticmethod
    def _select_active_interface(
        previous: Optional[dict[str, tuple[int, int]]],
        current: dict[str, tuple[int, int]],
    ) -> str:
        """选取当前最活跃的网络接口。"""
        if not current:
            return ""
        if not previous:
            return next(iter(current.keys()), "")

        best_iface = ""
        best_score = -1
        for iface, (rx_bytes, tx_bytes) in current.items():
            prev_rx, prev_tx = previous.get(iface, (rx_bytes, tx_bytes))
            score = max(0, rx_bytes - prev_rx) + max(0, tx_bytes - prev_tx)
            if score > best_score:
                best_score = score
                best_iface = iface
        return best_iface or next(iter(current.keys()), "")

    @staticmethod
    def _parse_root_filesystem(line: str) -> dict[str, str]:
        """解析根分区设备与挂载点。"""
        parts = line.split()
        if len(parts) < 6:
            return {"root_device": "", "root_mount": "/"}
        return {
            "root_device": parts[0],
            "root_mount": parts[5],
        }

    def get_monitor_data(self) -> dict[str, Any]:
        """
        获取远程主机监控数据。

        Returns:
            dict: 包含监控面板所需的扩展指标
        """
        with self._monitor_lock:
            _, stdout, _ = self.exec_command(self._monitor_command(), timeout=self._config.timeout)

            sections = stdout.split("__CS_SYS__\n", 1)
            host_section = sections[0].strip()
            remainder = sections[1] if len(sections) > 1 else ""
            sections = remainder.split("__CS_CPUINFO__\n", 1)
            system_section = sections[0].strip()
            remainder = sections[1] if len(sections) > 1 else ""
            sections = remainder.split("__CS_STAT__\n", 1)
            cpuinfo_section = sections[0].strip()
            remainder = sections[1] if len(sections) > 1 else ""
            sections = remainder.split("__CS_MEM__\n", 1)
            cpu_section = sections[0].strip()
            remainder = sections[1] if len(sections) > 1 else ""
            sections = remainder.split("__CS_DF__\n", 1)
            mem_section = sections[0].strip()
            remainder = sections[1] if len(sections) > 1 else ""
            sections = remainder.split("__CS_LOAD__\n", 1)
            disk_section = sections[0].strip()
            remainder = sections[1] if len(sections) > 1 else ""
            sections = remainder.split("__CS_UPTIME__\n", 1)
            load_section = sections[0].strip()
            remainder = sections[1] if len(sections) > 1 else ""
            sections = remainder.split("__CS_NET__\n", 1)
            uptime_section = sections[0].strip()
            net_section = sections[1].strip() if len(sections) > 1 else ""

            cpu_snapshot = self._parse_cpu_snapshot(cpu_section.splitlines()[0] if cpu_section else "")
            net_snapshot = self._parse_net_snapshot(net_section)
            now = time.time()
            interval = now - self._last_monitor_ts if self._last_monitor_ts is not None else 0.0

            previous_net_snapshot = self._last_net_snapshot
            data: dict[str, Any] = {
                "hostname": host_section.splitlines()[0].strip() if host_section else self.host,
                "system": system_section.splitlines()[0].strip() if system_section else "",
                "cpu_cores": self._parse_cpu_cores(cpuinfo_section.splitlines()[0] if cpuinfo_section else ""),
                "cpu": self._compute_cpu_usage(self._last_cpu_snapshot, cpu_snapshot),
            }
            data.update(self._parse_mem_metrics(mem_section.splitlines()))
            disk_line = disk_section.splitlines()[0] if disk_section else ""
            data.update(self._parse_disk_metrics(disk_line))
            data.update(self._parse_root_filesystem(disk_line))
            data.update(self._parse_loadavg(load_section.splitlines()[0] if load_section else ""))
            data["uptime_hours"] = self._parse_uptime(uptime_section.splitlines()[0] if uptime_section else "")
            rx_speed, tx_speed = self._compute_network_speed(previous_net_snapshot, net_snapshot, interval)
            data["rx_speed"] = rx_speed
            data["tx_speed"] = tx_speed
            data["active_interface"] = self._select_active_interface(previous_net_snapshot, net_snapshot)

            self._last_cpu_snapshot = cpu_snapshot
            self._last_net_snapshot = net_snapshot
            self._last_monitor_ts = now

            return data
