#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FRP 配置模板生成器。

该模块原先散落在旧代码中，这里收敛为 Neko_Shell 内部可复用的纯函数，
避免 UI 层依赖额外的顶层包。
"""

from __future__ import annotations


def frpc(server_addr: str, token: str, proxy_type: str, local_port: int, remote_port: int) -> str:
    """生成 frpc (客户端) TOML 配置内容。"""
    return f"""serverAddr = "{server_addr}"
serverPort = 7000
auth.token = "{token}"

{proxy_config(proxy_type, local_port, remote_port, server_addr)}
"""


def proxy_config(proxy_type: str, local_port: int, remote_port: int, server_addr: str = "") -> str:
    """生成代理段配置。"""
    normalized = (proxy_type or "").lower()

    if normalized == "http":
        return f"""[[proxies]]
name = "http_proxy"
type = "http"
localIP = "127.0.0.1"
localPort = {local_port}
customDomains = ["{server_addr}"]
"""

    if normalized == "udp":
        return f"""[[proxies]]
name = "udp_proxy"
type = "udp"
localIP = "127.0.0.1"
localPort = {local_port}
remotePort = {remote_port}
"""

    # TCP 默认
    return f"""[[proxies]]
name = "tcp_proxy"
type = "tcp"
localIP = "127.0.0.1"
localPort = {local_port}
remotePort = {remote_port}
"""


def frps(token: str, proxy_type: str = "tcp", http_port: int | None = None) -> str:
    """生成 frps (服务端) TOML 配置内容。"""
    normalized = (proxy_type or "").lower()
    http_extra = ""
    if normalized == "http" and http_port:
        http_extra = f"\n# HTTP 类型需要额外指定 vhostHTTPPort\nvhostHTTPPort = {int(http_port)}\n"

    return f"""bindPort = 7000
auth.token = "{token}"
{http_extra}
"""

