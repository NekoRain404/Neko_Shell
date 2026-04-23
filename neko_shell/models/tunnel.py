#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH 隧道配置模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import uuid


@dataclass
class TunnelConfig:
    """SSH 隧道配置。"""

    name: str
    connection_id: str
    tunnel_type: str = "local"
    local_host: str = "127.0.0.1"
    local_port: int = 1080
    remote_host: str = "127.0.0.1"
    remote_port: Optional[int] = 80
    browser_url: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "connection_id": self.connection_id,
            "tunnel_type": self.tunnel_type,
            "local_host": self.local_host,
            "local_port": self.local_port,
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "browser_url": self.browser_url,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TunnelConfig":
        """从字典创建。"""
        converted = dict(data)
        if not converted.get("id"):
            converted["id"] = str(uuid.uuid4())
        if converted.get("remote_port") == "":
            converted["remote_port"] = None
        if isinstance(converted.get("local_port"), str):
            converted["local_port"] = int(converted["local_port"])
        if isinstance(converted.get("remote_port"), str) and converted["remote_port"]:
            converted["remote_port"] = int(converted["remote_port"])
        return cls(**converted)
