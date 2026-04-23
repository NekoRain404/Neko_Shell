#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH 隧道转发实现。

该模块为 TunnelManagerWidget 提供本地/远程/动态端口转发的基础能力。
实现目标：
- 跨平台 (Linux/Windows/macOS)
- 不依赖额外第三方库（除 paramiko）
- 提供清晰的 stop/cleanup 语义
"""

from __future__ import annotations

import logging
import os
import select
import socket
import struct
import threading
from contextlib import suppress
from dataclasses import dataclass
from typing import Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)

BUFFER_SIZE = 8192
SOCKET_TIMEOUT = 1.0
SELECT_TIMEOUT = 1.0


def _load_private_key(key_file: str, passphrase: Optional[str] = None) -> Optional[paramiko.PKey]:
    if not key_file:
        return None
    expanded = os.path.expanduser(key_file)
    for key_cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey, paramiko.DSSKey):
        try:
            return key_cls.from_private_key_file(expanded, password=passphrase)
        except Exception:
            continue
    raise ValueError(f"无法识别私钥类型: {key_file}")


def _bridge_sockets(left: socket.socket, right) -> None:
    """在本地 socket 与 paramiko Channel 之间双向转发。"""
    left.settimeout(SOCKET_TIMEOUT)
    with suppress(Exception):
        right.settimeout(SOCKET_TIMEOUT)

    while True:
        try:
            rlist, _, _ = select.select([left, right], [], [], SELECT_TIMEOUT)
        except Exception:
            break

        if left in rlist:
            try:
                data = left.recv(BUFFER_SIZE)
            except Exception:
                break
            if not data:
                break
            with suppress(Exception):
                right.send(data)

        if right in rlist:
            try:
                data = right.recv(BUFFER_SIZE)
            except Exception:
                break
            if not data:
                break
            with suppress(Exception):
                left.sendall(data)

    with suppress(Exception):
        left.close()
    with suppress(Exception):
        right.close()


@dataclass
class _TunnelHandle:
    """统一的隧道句柄，供管理器 stop/remove 使用。"""

    ssh_client: paramiko.SSHClient
    stop_func: callable

    def stop(self) -> None:
        self.stop_func()


class ForwarderManager:
    """管理多个 SSH 隧道实例。"""

    def __init__(self) -> None:
        self.tunnels: dict[str, _TunnelHandle] = {}
        # TunnelManagerWidget 会把 (ssh_client -> transport) 填充到这里，保持兼容。
        self.ssh_clients: dict[object, object] = {}
        self._lock = threading.Lock()

    def add_tunnel(self, tunnel_id: str, tunnel: _TunnelHandle) -> None:
        with self._lock:
            self.tunnels[tunnel_id] = tunnel

    def remove_tunnel(self, tunnel_id: str) -> None:
        with self._lock:
            tunnel = self.tunnels.pop(tunnel_id, None)
        if tunnel is None:
            return

        with suppress(Exception):
            tunnel.stop()
        # 关闭 SSH client（该隧道可能与其他隧道共享一个 client，这里只做 best-effort）
        with suppress(Exception):
            tunnel.ssh_client.close()

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self.tunnels.keys())
        for tunnel_id in ids:
            with suppress(Exception):
                self.remove_tunnel(tunnel_id)
        with suppress(Exception):
            self.ssh_clients.clear()

    def start_tunnel(
        self,
        tunnel_id: str,
        tunnel_type: str,
        local_host: str,
        local_port: int,
        remote_host: Optional[str] = None,
        remote_port: Optional[int] = None,
        ssh_host: Optional[str] = None,
        ssh_port: Optional[int] = None,
        ssh_user: Optional[str] = None,
        ssh_password: Optional[str] = None,
        key_file: Optional[str] = None,
        passphrase: Optional[str] = None,
        proxy_command: Optional[str] = None,
        allow_agent: bool = True,
        look_for_keys: bool = True,
    ) -> Tuple[_TunnelHandle, paramiko.SSHClient, paramiko.Transport]:
        if local_port < 1024 and os.name != "nt":
            if os.getuid() != 0:
                raise PermissionError(f"绑定端口 {local_port} 需要 root 权限，请使用大于 1024 的端口。")

        private_key = _load_private_key(key_file, passphrase) if key_file else None

        ssh_client = paramiko.SSHClient()
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = dict(
            hostname=ssh_host,
            port=int(ssh_port or 22),
            username=ssh_user,
            timeout=10,
            banner_timeout=30,
            auth_timeout=20,
            allow_agent=allow_agent,
            look_for_keys=look_for_keys,
        )
        if proxy_command:
            connect_kwargs["sock"] = paramiko.ProxyCommand(proxy_command)

        try:
            if private_key is not None:
                ssh_client.connect(pkey=private_key, **connect_kwargs)
            elif ssh_password:
                ssh_client.connect(password=ssh_password, **connect_kwargs)
            else:
                ssh_client.connect(**connect_kwargs)
        except Exception as exc:
            with suppress(Exception):
                ssh_client.close()
            raise RuntimeError(f"SSH 连接失败: {exc}") from exc

        transport = ssh_client.get_transport()
        if transport is None:
            with suppress(Exception):
                ssh_client.close()
            raise RuntimeError("无法获取 SSH Transport")
        transport.set_keepalive(30)

        stop_event = threading.Event()

        if tunnel_type == "local":
            if remote_host is None or remote_port is None:
                raise ValueError("本地转发需要 remote_host/remote_port")
            handle = self._start_local_forward(
                ssh_client,
                transport,
                tunnel_id=tunnel_id,
                local_host=local_host,
                local_port=local_port,
                remote_host=remote_host,
                remote_port=int(remote_port),
                stop_event=stop_event,
            )
        elif tunnel_type == "remote":
            if remote_host is None or remote_port is None:
                raise ValueError("远程转发需要 remote_host/remote_port")
            handle = self._start_remote_forward(
                ssh_client,
                transport,
                tunnel_id=tunnel_id,
                remote_bind_host=remote_host,
                remote_bind_port=int(remote_port),
                local_target_host=local_host,
                local_target_port=local_port,
                stop_event=stop_event,
            )
        elif tunnel_type == "dynamic":
            handle = self._start_dynamic_forward(
                ssh_client,
                transport,
                tunnel_id=tunnel_id,
                local_host=local_host,
                local_port=local_port,
                stop_event=stop_event,
            )
        else:
            with suppress(Exception):
                ssh_client.close()
            raise ValueError(f"未知隧道类型: {tunnel_type}")

        return handle, ssh_client, transport

    @staticmethod
    def _start_local_forward(
        ssh_client: paramiko.SSHClient,
        transport: paramiko.Transport,
        tunnel_id: str,
        local_host: str,
        local_port: int,
        remote_host: str,
        remote_port: int,
        stop_event: threading.Event,
    ) -> _TunnelHandle:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((local_host, int(local_port)))
        server.listen(50)
        server.settimeout(SOCKET_TIMEOUT)

        def _worker() -> None:
            try:
                while not stop_event.is_set():
                    try:
                        client, _addr = server.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break

                    try:
                        chan = transport.open_channel(
                            "direct-tcpip",
                            (remote_host, int(remote_port)),
                            client.getsockname(),
                        )
                    except Exception as exc:
                        logger.debug("打开转发通道失败 [%s]: %s", tunnel_id, exc)
                        with suppress(Exception):
                            client.close()
                        continue

                    threading.Thread(target=_bridge_sockets, args=(client, chan), daemon=True).start()
            finally:
                with suppress(Exception):
                    server.close()

        thread = threading.Thread(target=_worker, name=f"neko_shell_tunnel_local_{tunnel_id}", daemon=True)
        thread.start()

        def _stop() -> None:
            stop_event.set()
            with suppress(Exception):
                server.close()

        return _TunnelHandle(ssh_client=ssh_client, stop_func=_stop)

    @staticmethod
    def _start_remote_forward(
        ssh_client: paramiko.SSHClient,
        transport: paramiko.Transport,
        tunnel_id: str,
        remote_bind_host: str,
        remote_bind_port: int,
        local_target_host: str,
        local_target_port: int,
        stop_event: threading.Event,
    ) -> _TunnelHandle:
        # handler(channel, origin, server_port) -> None
        def _handler(channel, origin, _server_port) -> None:
            if stop_event.is_set():
                with suppress(Exception):
                    channel.close()
                return
            try:
                sock = socket.create_connection((local_target_host, int(local_target_port)), timeout=10)
            except Exception as exc:
                logger.debug("远程转发连接本地目标失败 [%s]: %s", tunnel_id, exc)
                with suppress(Exception):
                    channel.close()
                return
            threading.Thread(target=_bridge_sockets, args=(sock, channel), daemon=True).start()

        transport.request_port_forward(remote_bind_host, int(remote_bind_port), handler=_handler)

        def _stop() -> None:
            stop_event.set()
            with suppress(Exception):
                transport.cancel_port_forward(remote_bind_host, int(remote_bind_port))

        return _TunnelHandle(ssh_client=ssh_client, stop_func=_stop)

    @staticmethod
    def _start_dynamic_forward(
        ssh_client: paramiko.SSHClient,
        transport: paramiko.Transport,
        tunnel_id: str,
        local_host: str,
        local_port: int,
        stop_event: threading.Event,
    ) -> _TunnelHandle:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((local_host, int(local_port)))
        server.listen(50)
        server.settimeout(SOCKET_TIMEOUT)

        def _recv_exact(sock: socket.socket, n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    raise EOFError("连接关闭")
                buf += chunk
            return buf

        def _handle_client(client: socket.socket) -> None:
            try:
                # SOCKS5 greeting
                header = _recv_exact(client, 2)
                ver, nmethods = header[0], header[1]
                if ver != 5:
                    return
                _ = _recv_exact(client, nmethods)  # methods
                client.sendall(b"\x05\x00")  # no auth

                # request
                req = _recv_exact(client, 4)
                ver, cmd, _rsv, atyp = req
                if ver != 5 or cmd != 1:
                    return
                if atyp == 1:  # IPv4
                    addr = socket.inet_ntoa(_recv_exact(client, 4))
                elif atyp == 3:  # domain
                    length = _recv_exact(client, 1)[0]
                    addr = _recv_exact(client, length).decode("utf-8", errors="ignore")
                elif atyp == 4:  # IPv6
                    addr = socket.inet_ntop(socket.AF_INET6, _recv_exact(client, 16))
                else:
                    return
                port = struct.unpack("!H", _recv_exact(client, 2))[0]

                try:
                    chan = transport.open_channel("direct-tcpip", (addr, int(port)), client.getsockname())
                except Exception as exc:
                    logger.debug("SOCKS 打开通道失败 [%s]: %s", tunnel_id, exc)
                    # connection refused
                    client.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
                    return

                # success response (bind addr/port ignored)
                client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                _bridge_sockets(client, chan)
            except Exception:
                with suppress(Exception):
                    client.close()

        def _worker() -> None:
            try:
                while not stop_event.is_set():
                    try:
                        client, _addr = server.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    threading.Thread(target=_handle_client, args=(client,), daemon=True).start()
            finally:
                with suppress(Exception):
                    server.close()

        thread = threading.Thread(target=_worker, name=f"neko_shell_tunnel_socks_{tunnel_id}", daemon=True)
        thread.start()

        def _stop() -> None:
            stop_event.set()
            with suppress(Exception):
                server.close()

        return _TunnelHandle(ssh_client=ssh_client, stop_func=_stop)

