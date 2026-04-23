#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块

提供配置的加载、保存和管理功能。
"""

import json
import os
import re
import shlex
import shutil
import hashlib
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar, Union
from uuid import uuid4

import yaml

from neko_shell.release import APP_NAME, APP_VERSION
from neko_shell.utils.crypto import ConfigEncryptor, PackageSigner, SecureStorage
from neko_shell.utils.exceptions import ConfigurationError

T = TypeVar("T", bound="BaseConfig")


SHARE_PACKAGE_SOURCE_APP = APP_NAME
SHARE_PACKAGE_SOURCE_VERSION = APP_VERSION
SHARE_PACKAGE_FORMAT_VERSION = 1
SHARED_LIBRARY_CONFIG_VERSION = 1
SHARED_LIBRARY_HISTORY_CONFIG_VERSION = 1
SHARED_LIBRARY_APPROVALS_CONFIG_VERSION = 1
SHARED_LIBRARY_GOVERNANCE_AUDIT_CONFIG_VERSION = 1
SHARED_LIBRARY_INDEX_FORMAT_VERSION = 1
SHARED_LIBRARY_SYNC_HISTORY_LIMIT = 200
SHARED_LIBRARY_GOVERNANCE_AUDIT_LIMIT = 500
SHARED_LIBRARY_LOCK_FILENAME = "shared-library.lock"
SHARED_LIBRARY_SIGNING_KEY_FILENAME = "shared-library-signing-key.pem"
SHARED_LIBRARY_SYNC_POLICY_MANUAL = "manual"
SHARED_LIBRARY_SYNC_POLICY_STARTUP_PULL = "startup_pull"
SHARED_LIBRARY_SYNC_POLICY_STARTUP_PULL_IF_CHANGED = "startup_pull_if_changed"
SHARED_LIBRARY_ROTATION_POLICY_WARN = "warn"
SHARED_LIBRARY_ROTATION_POLICY_APPROVAL = "approval"
SHARED_LIBRARY_ROTATION_POLICY_BLOCK = "block"
SHARED_LIBRARY_SIGNER_POLICY_WARNING_DAYS = 30
SHARED_LIBRARY_SIGNER_ROTATION_WARNING_DAYS = 30
SHARED_LIBRARY_ROTATION_EXCEPTION_STATES = ("due", "overdue")
SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_APPROVAL = "approval"
SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_BLOCK = "block"
SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTIONS = (
    SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_APPROVAL,
    SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_BLOCK,
)
SHARED_LIBRARY_TEAM_APPROVAL_RULE_ROTATION_STATES = (
    "none",
    "scheduled",
    "due",
    "overdue",
)


DEFAULT_TERMINAL_SNIPPET_GROUPS = {
    "常用": [
        "pwd",
        "ls -la",
        "df -h",
    ],
    "系统": [
        "free -h",
        "top",
        "journalctl -xe",
    ],
    "网络": [
        "ip a",
        "ss -tulpn",
        "ping -c 4 8.8.8.8",
    ],
    "容器": [
        "docker ps",
        "docker stats --no-stream",
        "docker logs --tail 100 <container>",
    ],
}

DEFAULT_TERMINAL_FAVORITES = [
    "pwd",
    "ls -la",
    "docker ps",
    "journalctl -xe",
]

DEFAULT_TERMINAL_MACROS = {
    "系统巡检": [
        "pwd",
        "whoami",
        "uname -a",
        "uptime",
        "df -h",
        "free -h",
    ],
    "网络检查": [
        "ip a",
        "ip route",
        "ss -tulpn",
    ],
}


def _normalize_usage_count(value: Any) -> int:
    """规整使用次数。"""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(count, 0)


def _normalize_bool_flag(value: Any, default: bool = False) -> bool:
    """规整布尔开关，兼容字符串。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(value)


def _normalize_command_list(commands: Any) -> List[str]:
    """清理命令列表，保证顺序稳定且无重复空项。"""
    normalized: List[str] = []
    seen: set[str] = set()
    for item in commands or []:
        if not isinstance(item, str):
            continue
        command = item.strip()
        if not command or command in seen:
            continue
        normalized.append(command)
        seen.add(command)

    return normalized


def _normalize_share_labels(labels: Any) -> List[str]:
    """规整共享标签列表。"""
    normalized: List[str] = []
    seen: set[str] = set()
    for item in labels or []:
        if not isinstance(item, str):
            continue
        label = item.strip()
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(label)
    return normalized


def _normalize_package_version(value: Any) -> int:
    """规整共享包版本号。"""
    try:
        version = int(value)
    except (TypeError, ValueError):
        return 1
    return max(version, 1)


def _normalize_shared_library_sync_policy(value: Any) -> str:
    """规整共享仓库同步策略。"""
    normalized = str(value or SHARED_LIBRARY_SYNC_POLICY_MANUAL).strip().lower()
    if normalized in {
        SHARED_LIBRARY_SYNC_POLICY_MANUAL,
        SHARED_LIBRARY_SYNC_POLICY_STARTUP_PULL,
        SHARED_LIBRARY_SYNC_POLICY_STARTUP_PULL_IF_CHANGED,
    }:
        return normalized
    return SHARED_LIBRARY_SYNC_POLICY_MANUAL


def _normalize_shared_library_lock_timeout(value: Any) -> int:
    """规整共享仓库锁超时时间。"""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 600
    return min(max(seconds, 30), 86400)


def _normalize_shared_library_rotation_policy(value: Any) -> str:
    """规整共享签名轮换治理动作。"""
    normalized = str(value or SHARED_LIBRARY_ROTATION_POLICY_WARN).strip().lower()
    if normalized in {
        SHARED_LIBRARY_ROTATION_POLICY_WARN,
        SHARED_LIBRARY_ROTATION_POLICY_APPROVAL,
        SHARED_LIBRARY_ROTATION_POLICY_BLOCK,
    }:
        return normalized
    return SHARED_LIBRARY_ROTATION_POLICY_WARN


def _normalize_shared_library_rotation_exception_states(
    value: Any,
    *,
    allow_empty: bool = False,
) -> List[str]:
    """规整轮换例外授权适用状态列表。"""
    normalized: List[str] = []
    seen: set[str] = set()
    raw_items: List[Any]
    if isinstance(value, str):
        raw_items = [part.strip() for part in value.replace("/", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []

    for item in raw_items:
        state = str(item or "").strip().lower()
        if state in {"*", "all", "any", "both"}:
            for supported_state in SHARED_LIBRARY_ROTATION_EXCEPTION_STATES:
                if supported_state not in seen:
                    seen.add(supported_state)
                    normalized.append(supported_state)
            continue
        if state not in SHARED_LIBRARY_ROTATION_EXCEPTION_STATES or state in seen:
            continue
        seen.add(state)
        normalized.append(state)
    if normalized or allow_empty:
        return normalized
    return list(SHARED_LIBRARY_ROTATION_EXCEPTION_STATES)


def _shared_library_rotation_policy_label(policy: Any) -> str:
    """返回共享签名轮换治理动作文本。"""
    normalized = _normalize_shared_library_rotation_policy(policy)
    if normalized == SHARED_LIBRARY_ROTATION_POLICY_APPROVAL:
        return "进入审批"
    if normalized == SHARED_LIBRARY_ROTATION_POLICY_BLOCK:
        return "直接阻断"
    return "仅提示"


def _shared_library_rotation_exception_status(
    expires_at: Any,
    *,
    now: Optional[datetime] = None,
) -> str:
    """判断轮换例外授权当前状态。"""
    text = str(expires_at or "").strip()
    if not text:
        return "active"
    parsed = _parse_iso_datetime(text)
    if parsed is None:
        return "invalid"
    current = now or datetime.now(timezone.utc)
    if current >= parsed:
        return "expired"
    return "active"


def _shared_library_package_type_label(package_type: Any) -> str:
    """返回共享包类型文本。"""
    normalized = str(package_type or "").strip().lower()
    if normalized == "workspace_templates":
        return "工作区模板"
    if normalized == "connection_filter_presets":
        return "筛选预设"
    return normalized or "未知类型"


def _normalize_shared_library_group_names(
    value: Any,
    *,
    allow_empty: bool = False,
) -> List[str]:
    """规整签名者分组名称列表。"""
    normalized: List[str] = []
    seen: set[str] = set()
    raw_items: List[Any]
    if isinstance(value, str):
        raw_items = [part.strip() for part in value.replace("/", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []

    for item in raw_items:
        group_name = str(item or "").strip()
        if not group_name:
            continue
        lowered = group_name.lower()
        if lowered in {"*", "all", "any"}:
            return [] if allow_empty else normalized
        key = group_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(group_name)
    return normalized


def _normalize_shared_library_team_approval_rule_action(value: Any) -> str:
    """规整团队级审批规则动作。"""
    normalized = str(value or SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_APPROVAL).strip().lower()
    if normalized in SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTIONS:
        return normalized
    return SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_APPROVAL


def _shared_library_team_approval_rule_action_label(action: Any) -> str:
    """返回团队级审批规则动作文本。"""
    normalized = _normalize_shared_library_team_approval_rule_action(action)
    if normalized == SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_BLOCK:
        return "直接阻断"
    return "进入审批"


def _normalize_shared_library_team_approval_rule_rotation_states(
    value: Any,
    *,
    allow_empty: bool = False,
) -> List[str]:
    """规整团队级审批规则匹配的轮换状态。"""
    normalized: List[str] = []
    seen: set[str] = set()
    raw_items: List[Any]
    if isinstance(value, str):
        raw_items = [part.strip() for part in value.replace("/", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []

    for item in raw_items:
        state = str(item or "").strip().lower()
        if state in {"*", "all", "any"}:
            return [] if allow_empty else list(SHARED_LIBRARY_TEAM_APPROVAL_RULE_ROTATION_STATES)
        if state not in SHARED_LIBRARY_TEAM_APPROVAL_RULE_ROTATION_STATES or state in seen:
            continue
        seen.add(state)
        normalized.append(state)
    if normalized or allow_empty:
        return normalized
    return list(SHARED_LIBRARY_TEAM_APPROVAL_RULE_ROTATION_STATES)


def _shared_library_team_approval_rule_rotation_state_label(state: Any) -> str:
    """返回团队级审批规则中的轮换状态文本。"""
    normalized = str(state or "").strip().lower()
    if normalized == "due":
        return "临近轮换"
    if normalized == "overdue":
        return "轮换超期"
    if normalized == "scheduled":
        return "已计划轮换"
    if normalized == "none":
        return "未设置轮换"
    return normalized or "未知状态"


def _normalize_shared_library_team_approval_rule_matches(value: Any) -> List[str]:
    """规整审批记录中命中的团队级规则名称。"""
    normalized: List[str] = []
    seen: set[str] = set()
    for item in value or []:
        name = str(item or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(name)
    return normalized


def _normalize_shared_library_trusted_sources(value: Any) -> List[str]:
    """规整共享中心受信任来源应用列表。"""
    normalized: List[str] = []
    seen: set[str] = set()
    if isinstance(value, str):
        raw_items = [part.strip() for part in value.replace("/", ",").split(",")]
    else:
        raw_items = value or []
    for item in raw_items:
        if not isinstance(item, str):
            continue
        source = item.strip()
        if not source:
            continue
        key = source.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(source)
    return normalized


def _normalize_shared_library_trusted_signer_fingerprints(value: Any) -> List[str]:
    """规整受信任签名指纹列表。"""
    normalized: List[str] = []
    seen: set[str] = set()
    for item in value or []:
        fingerprint = str(item or "").strip().lower()
        if not fingerprint or not re.fullmatch(r"[0-9a-f]{16,64}", fingerprint):
            continue
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized.append(fingerprint)
    return normalized


def _normalize_shared_library_signer_fingerprint(value: Any) -> Optional[str]:
    """规整单个共享签名指纹。"""
    normalized = _normalize_shared_library_trusted_signer_fingerprints([value])
    return normalized[0] if normalized else None


def _normalize_shared_library_signer_profiles(
    value: Any,
) -> Dict[str, Dict[str, Optional[str]]]:
    """规整签名者资料。"""
    normalized: Dict[str, Dict[str, Optional[str]]] = {}
    source_items: List[tuple[Any, Any]] = []
    if isinstance(value, dict):
        source_items = list(value.items())
    elif isinstance(value, list):
        source_items = [(item.get("fingerprint"), item) for item in value if isinstance(item, dict)]

    for raw_fingerprint, raw_profile in source_items:
        fingerprint = _normalize_shared_library_signer_fingerprint(raw_fingerprint)
        if not fingerprint:
            continue
        profile = raw_profile if isinstance(raw_profile, dict) else {}
        display_name = str(profile.get("display_name") or profile.get("name") or "").strip() or None
        note = str(profile.get("note") or profile.get("description") or "").strip() or None
        expires_at = (
            str(
                profile.get("expires_at")
                or profile.get("policy_expires_at")
                or profile.get("valid_until")
                or ""
            ).strip()
            or None
        )
        rotate_before_at = (
            str(
                profile.get("rotate_before_at")
                or profile.get("rotation_due_at")
                or profile.get("rotation_before")
                or ""
            ).strip()
            or None
        )
        normalized[fingerprint] = {
            "fingerprint": fingerprint,
            "display_name": display_name,
            "note": note,
            "expires_at": expires_at,
            "rotate_before_at": rotate_before_at,
        }
    return normalized


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    """解析 ISO 时间，兼容无时区或 Z 后缀。"""
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _shared_library_signer_policy_status(
    expires_at: Any,
    *,
    now: Optional[datetime] = None,
) -> str:
    """计算签名者策略有效期状态。"""
    if not str(expires_at or "").strip():
        return "none"
    parsed = _parse_iso_datetime(expires_at)
    if parsed is None:
        return "invalid"
    current = now or datetime.now(timezone.utc)
    if current >= parsed:
        return "expired"
    warning_at = parsed - timedelta(days=SHARED_LIBRARY_SIGNER_POLICY_WARNING_DAYS)
    if current >= warning_at:
        return "expiring"
    return "active"


def _shared_library_signer_rotation_status(
    rotate_before_at: Any,
    *,
    now: Optional[datetime] = None,
) -> str:
    """计算签名者轮换状态。"""
    if not str(rotate_before_at or "").strip():
        return "none"
    parsed = _parse_iso_datetime(rotate_before_at)
    if parsed is None:
        return "invalid"
    current = now or datetime.now(timezone.utc)
    if current >= parsed:
        return "overdue"
    warning_at = parsed - timedelta(days=SHARED_LIBRARY_SIGNER_ROTATION_WARNING_DAYS)
    if current >= warning_at:
        return "due"
    return "scheduled"


def _normalize_shared_library_signer_groups(value: Any) -> Dict[str, List[str]]:
    """规整签名者分组配置。"""
    normalized: Dict[str, List[str]] = {}
    source_items: List[tuple[Any, Any]] = []
    if isinstance(value, dict):
        source_items = list(value.items())
    elif isinstance(value, list):
        source_items = [
            (item.get("name") or item.get("group"), item.get("fingerprints"))
            for item in value
            if isinstance(item, dict)
        ]

    for raw_name, raw_members in source_items:
        name = str(raw_name or "").strip()
        if not name:
            continue
        members: List[str] = []
        if isinstance(raw_members, str):
            members = [
                part.strip() for part in raw_members.replace("\n", ",").split(",") if part.strip()
            ]
        elif isinstance(raw_members, (list, tuple, set)):
            members = [str(item).strip() for item in raw_members if str(item).strip()]
        fingerprints = _normalize_shared_library_trusted_signer_fingerprints(members)
        if not fingerprints:
            continue
        normalized[name] = fingerprints
    return normalized


def _normalize_shared_library_revoked_signer_records(
    value: Any,
) -> List[Dict[str, Optional[str]]]:
    """规整已撤销签名者记录。"""
    normalized: List[Dict[str, Optional[str]]] = []
    seen: set[str] = set()
    source_items = value if isinstance(value, list) else []
    for item in source_items:
        if not isinstance(item, dict):
            continue
        fingerprint = _normalize_shared_library_signer_fingerprint(item.get("fingerprint"))
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized.append(
            {
                "fingerprint": fingerprint,
                "reason": str(item.get("reason") or "").strip() or None,
                "note": str(item.get("note") or "").strip() or None,
                "revoked_at": str(item.get("revoked_at") or "").strip() or None,
            }
        )
    return normalized


def _normalize_shared_library_rotation_exception_records(
    value: Any,
) -> List[Dict[str, Any]]:
    """规整轮换例外授权记录。"""
    normalized: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    source_items = value if isinstance(value, list) else []
    for item in source_items:
        if not isinstance(item, dict):
            continue
        fingerprint = _normalize_shared_library_signer_fingerprint(item.get("fingerprint"))
        if not fingerprint:
            continue
        package_types = _normalize_shared_library_package_types(
            (
                item.get("package_types")
                if item.get("package_types") is not None
                else item.get("package_type")
            ),
            allow_empty=True,
        )
        rotation_states = _normalize_shared_library_rotation_exception_states(
            (
                item.get("rotation_states")
                if item.get("rotation_states") is not None
                else item.get("rotation_state")
            ),
            allow_empty=True,
        )
        expires_at = str(item.get("expires_at") or item.get("expire_at") or "").strip() or None
        note = str(item.get("note") or item.get("reason") or "").strip() or None
        key = (
            fingerprint,
            ",".join(package_types),
            ",".join(rotation_states),
            str(expires_at or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "fingerprint": fingerprint,
                "package_types": package_types,
                "rotation_states": rotation_states,
                "expires_at": expires_at,
                "note": note,
                "source_approval_id": str(item.get("source_approval_id") or "").strip() or None,
                "source_approval_name": str(item.get("source_approval_name") or "").strip() or None,
            }
        )
    return normalized


def _normalize_shared_library_additional_signatures(
    value: Any,
) -> List[Dict[str, Optional[str]]]:
    """规整共享包附加签名列表。"""
    normalized: List[Dict[str, Optional[str]]] = []
    seen: set[tuple[str, str, str]] = set()
    source_items = value if isinstance(value, list) else []
    for item in source_items:
        if not isinstance(item, dict):
            continue
        algorithm = str(item.get("signature_algorithm") or item.get("algorithm") or "").strip()
        signature = str(item.get("signature") or "").strip()
        public_key = str(item.get("signature_public_key") or item.get("public_key") or "").strip()
        signer = str(item.get("signature_signer") or item.get("signer") or "").strip() or None
        fingerprint = (
            str(item.get("signature_fingerprint") or item.get("fingerprint") or "").strip().lower()
            or None
        )
        if not fingerprint and public_key:
            try:
                fingerprint = PackageSigner.fingerprint_from_public_key(public_key)
            except Exception:
                fingerprint = None
        if not signature and not public_key and not signer and not fingerprint:
            continue
        key = (signature, public_key, str(fingerprint or ""))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "signature_algorithm": algorithm or None,
                "signature": signature or None,
                "signature_public_key": public_key or None,
                "signature_signer": signer,
                "signature_fingerprint": fingerprint,
            }
        )
    return normalized


def _normalize_shared_library_team_approval_rules(
    value: Any,
) -> List[Dict[str, Any]]:
    """规整团队级审批规则。"""
    normalized: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    source_items = value if isinstance(value, list) else []
    for item in source_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("rule_name") or "").strip()
        if not name:
            continue
        action = _normalize_shared_library_team_approval_rule_action(item.get("action"))
        source_apps = _normalize_shared_library_trusted_sources(
            item.get("source_apps") if item.get("source_apps") is not None else item.get("sources")
        )
        package_types = _normalize_shared_library_package_types(
            (
                item.get("package_types")
                if item.get("package_types") is not None
                else item.get("package_type")
            ),
            allow_empty=True,
        )
        signer_groups = _normalize_shared_library_group_names(
            (
                item.get("signer_groups")
                if item.get("signer_groups") is not None
                else item.get("groups")
            ),
            allow_empty=True,
        )
        rotation_states = _normalize_shared_library_team_approval_rule_rotation_states(
            (
                item.get("rotation_states")
                if item.get("rotation_states") is not None
                else item.get("rotation_statuses")
            ),
            allow_empty=True,
        )
        try:
            minimum_signature_count = max(int(item.get("minimum_signature_count") or 0), 0)
        except (TypeError, ValueError):
            minimum_signature_count = 0
        approval_level = (
            str(
                item.get("approval_level") or item.get("level") or item.get("required_level") or ""
            ).strip()
            or None
        )
        key = (
            name.casefold(),
            action,
            ",".join(item.casefold() for item in source_apps),
            ",".join(package_types),
            ",".join(item.casefold() for item in signer_groups),
            ",".join(rotation_states),
            str(minimum_signature_count),
            str(approval_level or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "name": name,
                "enabled": _normalize_bool_flag(item.get("enabled"), True),
                "action": action,
                "source_apps": source_apps,
                "package_types": package_types,
                "signer_groups": signer_groups,
                "rotation_states": rotation_states,
                "minimum_signature_count": minimum_signature_count,
                "approval_level": approval_level,
                "note": str(item.get("note") or item.get("reason") or "").strip() or None,
            }
        )
    return normalized


def _subtract_shared_library_signer_fingerprints(
    base: List[str],
    excluded: List[str],
) -> List[str]:
    """从签名指纹列表中移除被排除项。"""
    excluded_keys = set(_normalize_shared_library_trusted_signer_fingerprints(excluded))
    return [
        fingerprint
        for fingerprint in _normalize_shared_library_trusted_signer_fingerprints(base)
        if fingerprint not in excluded_keys
    ]


def _normalize_shared_library_index_cache(value: Any) -> Dict[str, int]:
    """规整共享仓库索引缓存。"""
    normalized: Dict[str, int] = {}
    if not isinstance(value, dict):
        return normalized
    for raw_path, raw_index in value.items():
        path = str(raw_path or "").strip()
        if not path:
            continue
        try:
            index_version = int(raw_index)
        except (TypeError, ValueError):
            continue
        normalized[path] = max(index_version, 0)
    return normalized


def _normalize_shared_library_package_types(
    value: Any,
    *,
    allow_empty: bool = False,
) -> List[str]:
    """规整共享包类型列表。"""
    supported_types = ("workspace_templates", "connection_filter_presets")
    normalized: List[str] = []
    seen: set[str] = set()
    if isinstance(value, str):
        raw_items = [part.strip() for part in value.replace("/", ",").split(",")]
    else:
        raw_items = value or []
    for item in raw_items:
        package_type = str(item or "").strip().lower()
        if package_type in {"*", "all", "any"}:
            return [] if allow_empty else list(supported_types)
        if package_type not in supported_types or package_type in seen:
            continue
        seen.add(package_type)
        normalized.append(package_type)
    if normalized or allow_empty:
        return normalized
    return list(supported_types)


def _normalize_shared_library_approval_decision(value: Any) -> str:
    """规整共享包审批决策。"""
    normalized = str(value or "pending").strip().lower()
    if normalized in {"approved", "rejected", "pending"}:
        return normalized
    return "pending"


def _normalize_shared_library_integrity_status(value: Any) -> str:
    """规整共享包完整性状态。"""
    normalized = str(value or "verified").strip().lower()
    if normalized in {"verified", "missing", "invalid", "missing_file", "unreadable"}:
        return normalized
    return "verified"


def _normalize_shared_library_signature_status(value: Any) -> str:
    """规整共享包签名状态。"""
    normalized = str(value or "missing").strip().lower()
    if normalized in {"verified", "missing", "invalid", "unsupported"}:
        return normalized
    return "missing"


def _slugify_filename(value: Any, default: str) -> str:
    """将名称转换为稳定安全的文件名片段。"""
    text = str(value or "").strip().casefold()
    if not text:
        return default
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text or default


def normalize_terminal_snippet_groups(
    groups: Any, allow_empty: bool = False
) -> Dict[str, List[str]]:
    """清理终端命令分组，兼容旧版扁平列表。"""
    default_groups = {
        group_name: list(commands)
        for group_name, commands in DEFAULT_TERMINAL_SNIPPET_GROUPS.items()
    }
    if isinstance(groups, list):
        normalized_list = _normalize_command_list(groups)
        if normalized_list:
            return {"常用": normalized_list}
        return {} if allow_empty else {"常用": list(DEFAULT_TERMINAL_SNIPPET_GROUPS["常用"])}

    if not isinstance(groups, dict):
        return {} if allow_empty else default_groups

    normalized_groups: Dict[str, List[str]] = {}
    for raw_name, raw_commands in groups.items():
        if not isinstance(raw_name, str):
            continue
        group_name = raw_name.strip() or "常用"
        commands = _normalize_command_list(raw_commands)
        if commands:
            normalized_groups[group_name] = commands

    return normalized_groups or ({} if allow_empty else default_groups)


def flatten_terminal_snippet_groups(groups: Any, allow_empty: bool = False) -> List[str]:
    """将命令分组拍平成稳定顺序的命令列表。"""
    flattened: List[str] = []
    seen: set[str] = set()
    for commands in normalize_terminal_snippet_groups(groups, allow_empty=allow_empty).values():
        for command in commands:
            if command in seen:
                continue
            flattened.append(command)
            seen.add(command)
    return flattened


DEFAULT_TERMINAL_SNIPPETS = flatten_terminal_snippet_groups(DEFAULT_TERMINAL_SNIPPET_GROUPS)


def normalize_terminal_snippets(snippets: Optional[List[Any]]) -> List[str]:
    """清理终端快捷命令列表，保证顺序稳定且无重复空项。"""
    normalized = _normalize_command_list(snippets)
    return normalized or list(DEFAULT_TERMINAL_SNIPPETS)


def normalize_terminal_favorite_snippets(
    favorites: Any,
    groups: Any = None,
    allow_empty: bool = False,
) -> List[str]:
    """清理收藏命令，只保留当前分组中存在的项。"""
    commands = set(flatten_terminal_snippet_groups(groups, allow_empty=allow_empty))
    normalized_favorites = _normalize_command_list(favorites)
    if not commands:
        if normalized_favorites:
            return normalized_favorites
        return [] if allow_empty else list(DEFAULT_TERMINAL_FAVORITES)

    filtered = [command for command in normalized_favorites if command in commands]
    if filtered:
        return filtered
    if allow_empty:
        return []
    return [command for command in DEFAULT_TERMINAL_FAVORITES if command in commands]


def normalize_terminal_macros(macros: Any, allow_empty: bool = False) -> Dict[str, List[str]]:
    """清理终端宏定义，保持名称稳定且命令列表有效。"""
    default_macros = {
        macro_name: list(commands) for macro_name, commands in DEFAULT_TERMINAL_MACROS.items()
    }
    if not isinstance(macros, dict):
        return {} if allow_empty else default_macros

    normalized: Dict[str, List[str]] = {}
    for raw_name, raw_commands in macros.items():
        if not isinstance(raw_name, str):
            continue
        macro_name = raw_name.strip()
        if not macro_name:
            continue
        commands = _normalize_command_list(raw_commands)
        if commands:
            normalized[macro_name] = commands

    return normalized or ({} if allow_empty else default_macros)


def parse_terminal_snippet_lines(lines: List[str]) -> Dict[str, List[str]]:
    """将设置页中的文本行解析为命令分组。"""
    parsed: Dict[str, List[str]] = {}
    for raw_line in lines:
        if not isinstance(raw_line, str):
            continue
        line = raw_line.strip()
        if not line:
            continue
        if "::" in line:
            group_name, command = line.split("::", 1)
        else:
            group_name, command = "常用", line
        group_name = group_name.strip() or "常用"
        command = command.strip()
        if not command:
            continue
        parsed.setdefault(group_name, []).append(command)
    return normalize_terminal_snippet_groups(parsed)


def dump_terminal_snippet_lines(groups: Any) -> List[str]:
    """将命令分组格式化为设置页可编辑的文本行。"""
    lines: List[str] = []
    for group_name, commands in normalize_terminal_snippet_groups(groups).items():
        lines.extend(f"{group_name}::{command}" for command in commands)
    return lines


def parse_terminal_macro_lines(lines: List[str]) -> Dict[str, List[str]]:
    """将设置页中的文本行解析为命令宏。"""
    parsed: Dict[str, List[str]] = {}
    for raw_line in lines:
        if not isinstance(raw_line, str):
            continue
        line = raw_line.strip()
        if not line or "::" not in line:
            continue
        macro_name, command = line.split("::", 1)
        macro_name = macro_name.strip()
        command = command.strip()
        if not macro_name or not command:
            continue
        parsed.setdefault(macro_name, []).append(command)
    return normalize_terminal_macros(parsed, allow_empty=True)


def dump_terminal_macro_lines(macros: Any) -> List[str]:
    """将命令宏格式化为设置页可编辑的文本行。"""
    lines: List[str] = []
    for macro_name, commands in normalize_terminal_macros(macros, allow_empty=True).items():
        lines.extend(f"{macro_name}::{command}" for command in commands)
    return lines


@dataclass
class BaseConfig:
    """配置基类"""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """从字典创建"""
        return cls(**data)


@dataclass
class AppConfig:
    """
    应用全局配置

    Attributes:
        default_timeout: 默认超时时间（秒）
        max_reconnect_attempts: 最大重连次数
        log_level: 日志级别
        log_dir: 日志目录
        theme: 主题名称
        language: 界面语言
        terminal_backend: 终端后端
        terminal_font_size: 终端字体大小
        terminal_theme: 终端配色主题
        restore_workspace_on_startup: 启动时恢复上次工作区
    """

    default_timeout: float = 10.0
    max_reconnect_attempts: int = 3
    log_level: str = "INFO"
    log_dir: str = "logs"
    theme: str = "dark"
    language: str = "zh_CN"
    terminal_backend: str = "auto"
    terminal_font_size: int = 10
    terminal_theme: str = "Ubuntu"
    terminal_snippets: List[str] = field(default_factory=lambda: list(DEFAULT_TERMINAL_SNIPPETS))
    terminal_snippet_groups: Dict[str, List[str]] = field(
        default_factory=lambda: {
            group_name: list(commands)
            for group_name, commands in DEFAULT_TERMINAL_SNIPPET_GROUPS.items()
        }
    )
    terminal_favorite_snippets: List[str] = field(
        default_factory=lambda: list(DEFAULT_TERMINAL_FAVORITES)
    )
    terminal_macros: Dict[str, List[str]] = field(
        default_factory=lambda: {
            macro_name: list(commands) for macro_name, commands in DEFAULT_TERMINAL_MACROS.items()
        }
    )
    restore_workspace_on_startup: bool = True
    shared_library_sync_dir: str = ""
    shared_library_sync_policy: str = SHARED_LIBRARY_SYNC_POLICY_MANUAL
    shared_library_lock_timeout: int = 600
    shared_library_rotation_due_policy: str = SHARED_LIBRARY_ROTATION_POLICY_WARN
    shared_library_rotation_overdue_policy: str = SHARED_LIBRARY_ROTATION_POLICY_APPROVAL
    shared_library_trusted_source_apps: List[str] = field(
        default_factory=lambda: [SHARE_PACKAGE_SOURCE_APP]
    )
    shared_library_trusted_signer_fingerprints: List[str] = field(default_factory=list)
    shared_library_signer_profiles: Dict[str, Dict[str, Optional[str]]] = field(
        default_factory=dict
    )
    shared_library_signer_groups: Dict[str, List[str]] = field(default_factory=dict)
    shared_library_revoked_signer_fingerprints: List[str] = field(default_factory=list)
    shared_library_revoked_signer_records: List[Dict[str, Optional[str]]] = field(
        default_factory=list
    )
    shared_library_rotation_exception_records: List[Dict[str, Any]] = field(default_factory=list)
    shared_library_team_approval_rules: List[Dict[str, Any]] = field(default_factory=list)
    shared_library_auto_pull_allowed_package_types: List[str] = field(
        default_factory=lambda: ["workspace_templates", "connection_filter_presets"]
    )
    shared_library_index_cache: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """兼容旧字段并保持片段/分组/收藏三者一致。"""
        default_groups = {
            group_name: list(commands)
            for group_name, commands in DEFAULT_TERMINAL_SNIPPET_GROUPS.items()
        }
        snippets = normalize_terminal_snippets(self.terminal_snippets)
        if self.terminal_snippet_groups == default_groups and snippets != list(
            DEFAULT_TERMINAL_SNIPPETS
        ):
            groups = normalize_terminal_snippet_groups(snippets)
        else:
            groups = normalize_terminal_snippet_groups(self.terminal_snippet_groups)

        self.terminal_snippet_groups = groups
        self.terminal_snippets = flatten_terminal_snippet_groups(groups)
        self.terminal_favorite_snippets = normalize_terminal_favorite_snippets(
            self.terminal_favorite_snippets,
            groups,
        )
        if isinstance(self.terminal_macros, dict):
            self.terminal_macros = normalize_terminal_macros(self.terminal_macros, allow_empty=True)
        else:
            self.terminal_macros = normalize_terminal_macros(self.terminal_macros)
        self.shared_library_sync_policy = _normalize_shared_library_sync_policy(
            self.shared_library_sync_policy
        )
        self.shared_library_lock_timeout = _normalize_shared_library_lock_timeout(
            self.shared_library_lock_timeout
        )
        self.shared_library_rotation_due_policy = _normalize_shared_library_rotation_policy(
            self.shared_library_rotation_due_policy
        )
        self.shared_library_rotation_overdue_policy = _normalize_shared_library_rotation_policy(
            self.shared_library_rotation_overdue_policy
        )
        self.shared_library_trusted_source_apps = _normalize_shared_library_trusted_sources(
            self.shared_library_trusted_source_apps
        )
        self.shared_library_trusted_signer_fingerprints = (
            _normalize_shared_library_trusted_signer_fingerprints(
                self.shared_library_trusted_signer_fingerprints
            )
        )
        self.shared_library_signer_profiles = _normalize_shared_library_signer_profiles(
            self.shared_library_signer_profiles
        )
        self.shared_library_signer_groups = _normalize_shared_library_signer_groups(
            self.shared_library_signer_groups
        )
        self.shared_library_revoked_signer_records = (
            _normalize_shared_library_revoked_signer_records(
                self.shared_library_revoked_signer_records
            )
        )
        self.shared_library_rotation_exception_records = (
            _normalize_shared_library_rotation_exception_records(
                self.shared_library_rotation_exception_records
            )
        )
        self.shared_library_team_approval_rules = _normalize_shared_library_team_approval_rules(
            self.shared_library_team_approval_rules
        )
        self.shared_library_revoked_signer_fingerprints = (
            _normalize_shared_library_trusted_signer_fingerprints(
                self.shared_library_revoked_signer_fingerprints
            )
        )
        revoked_record_fingerprints = [
            str(record.get("fingerprint") or "").strip()
            for record in self.shared_library_revoked_signer_records
            if str(record.get("fingerprint") or "").strip()
        ]
        all_revoked_fingerprints = _normalize_shared_library_trusted_signer_fingerprints(
            self.shared_library_revoked_signer_fingerprints + revoked_record_fingerprints
        )
        revoked_record_map = {
            str(record.get("fingerprint") or "").strip(): dict(record)
            for record in self.shared_library_revoked_signer_records
            if str(record.get("fingerprint") or "").strip()
        }
        self.shared_library_revoked_signer_records = [
            revoked_record_map.get(
                fingerprint,
                {
                    "fingerprint": fingerprint,
                    "reason": None,
                    "note": None,
                    "revoked_at": None,
                },
            )
            for fingerprint in all_revoked_fingerprints
        ]
        self.shared_library_revoked_signer_fingerprints = all_revoked_fingerprints
        self.shared_library_trusted_signer_fingerprints = (
            _subtract_shared_library_signer_fingerprints(
                self.shared_library_trusted_signer_fingerprints,
                self.shared_library_revoked_signer_fingerprints,
            )
        )
        self.shared_library_auto_pull_allowed_package_types = (
            _normalize_shared_library_package_types(
                self.shared_library_auto_pull_allowed_package_types
            )
        )
        self.shared_library_index_cache = _normalize_shared_library_index_cache(
            self.shared_library_index_cache
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        groups = normalize_terminal_snippet_groups(self.terminal_snippet_groups)
        return {
            **asdict(self),
            "terminal_snippet_groups": groups,
            "terminal_snippets": flatten_terminal_snippet_groups(groups),
            "terminal_favorite_snippets": normalize_terminal_favorite_snippets(
                self.terminal_favorite_snippets,
                groups,
            ),
            "terminal_macros": normalize_terminal_macros(self.terminal_macros, allow_empty=True),
        }

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "AppConfig":
        """从包含额外元数据的映射中恢复配置。"""
        payload = data.get("settings", data) if isinstance(data, dict) else {}
        allowed_keys = set(cls.__dataclass_fields__.keys())
        normalized = {key: value for key, value in payload.items() if key in allowed_keys}
        normalized["terminal_snippet_groups"] = normalize_terminal_snippet_groups(
            normalized.get("terminal_snippet_groups", normalized.get("terminal_snippets"))
        )
        normalized["terminal_snippets"] = flatten_terminal_snippet_groups(
            normalized["terminal_snippet_groups"]
        )
        normalized["terminal_favorite_snippets"] = normalize_terminal_favorite_snippets(
            normalized.get("terminal_favorite_snippets"),
            normalized["terminal_snippet_groups"],
        )
        if "terminal_macros" in normalized:
            normalized["terminal_macros"] = normalize_terminal_macros(
                normalized.get("terminal_macros"),
                allow_empty=True,
            )
        else:
            normalized["terminal_macros"] = normalize_terminal_macros(None)
        return cls(**normalized)


class ConfigManager:
    """
    配置管理器

    管理应用配置和连接配置的加载、保存。
    """

    APP_CONFIG_VERSION = 2
    CONNECTIONS_CONFIG_VERSION = 2
    TUNNELS_CONFIG_VERSION = 2
    WORKSPACE_CONFIG_VERSION = 1
    TEMPLATES_CONFIG_VERSION = 1
    SHARED_LIBRARY_CONFIG_VERSION = SHARED_LIBRARY_CONFIG_VERSION
    SHARED_LIBRARY_HISTORY_CONFIG_VERSION = SHARED_LIBRARY_HISTORY_CONFIG_VERSION
    SHARED_LIBRARY_APPROVALS_CONFIG_VERSION = SHARED_LIBRARY_APPROVALS_CONFIG_VERSION
    CONFIG_DIR_MODE = 0o700
    CONFIG_FILE_MODE = 0o600
    CONNECTION_METADATA_FIELDS = (
        "favorite",
        "last_connected_at",
        "session_snippet_groups",
        "session_favorite_snippets",
        "session_macros",
    )

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._secure_directory(self.config_dir)

        self._app_config: Optional[AppConfig] = None
        self._connections: Dict[str, Any] = {}

    @staticmethod
    def _normalize_connection_id(connection: Dict[str, Any]) -> Dict[str, Any]:
        """为历史配置补齐稳定的连接 ID。"""
        normalized = dict(connection)
        if not normalized.get("id"):
            normalized["id"] = normalized.get("name") or str(uuid4())
        return normalized

    @classmethod
    def _normalize_connection_record(cls, connection: Dict[str, Any]) -> Dict[str, Any]:
        """补齐连接元数据，兼容历史配置。"""
        normalized = cls._normalize_connection_id(connection)
        normalized["favorite"] = bool(normalized.get("favorite", False))
        normalized["last_connected_at"] = normalized.get("last_connected_at") or None
        normalized["session_snippet_groups"] = normalize_terminal_snippet_groups(
            normalized.get("session_snippet_groups"),
            allow_empty=True,
        )
        normalized["session_favorite_snippets"] = normalize_terminal_favorite_snippets(
            normalized.get("session_favorite_snippets"),
            normalized["session_snippet_groups"],
            allow_empty=True,
        )
        normalized["session_macros"] = normalize_terminal_macros(
            normalized.get("session_macros"),
            allow_empty=True,
        )
        return normalized

    @staticmethod
    def _normalize_tunnel_id(tunnel: Dict[str, Any]) -> Dict[str, Any]:
        """为历史配置补齐稳定的隧道 ID。"""
        normalized = dict(tunnel)
        if not normalized.get("id"):
            normalized["id"] = str(uuid4())
        return normalized

    @staticmethod
    def _extract_password(connection: Dict[str, Any]) -> Optional[str]:
        """提取连接中的敏感密码字段。"""
        password = connection.get("password")
        if isinstance(password, str) and password:
            return password
        return None

    @classmethod
    def _secure_directory(cls, path: Path) -> None:
        if os.name != "nt" and path.exists():
            path.chmod(cls.CONFIG_DIR_MODE)

    @classmethod
    def _secure_file(cls, path: Path) -> None:
        if os.name != "nt" and path.exists():
            path.chmod(cls.CONFIG_FILE_MODE)

    @staticmethod
    def _load_mapping(path: Path) -> Any:
        if not path.exists():
            return {}
        if ConfigEncryptor.is_encrypted_file(path):
            raise ConfigurationError(f"配置文件已加密，请先使用主密码解密: {path.name}")
        with open(path, "r", encoding="utf-8") as file_handle:
            if path.suffix in [".yaml", ".yml"]:
                return yaml.safe_load(file_handle) or {}
            return json.load(file_handle)

    @staticmethod
    def _extract_records(data: Any, key: str) -> List[Dict[str, Any]]:
        """兼容历史列表根节点和新版带版本头的映射结构。"""
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if not isinstance(data, dict):
            return []

        payload = data.get(key)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        # 极老版本可能直接是单条记录的平铺结构
        if key == "connections" and "connection_type" in data:
            return [data]
        if key == "tunnels" and "connection_id" in data:
            return [data]

        return []

    def _write_mapping(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._secure_directory(path.parent)
        with open(path, "w", encoding="utf-8") as file_handle:
            if path.suffix in [".yaml", ".yml"]:
                yaml.dump(
                    payload,
                    file_handle,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            else:
                json.dump(payload, file_handle, indent=2, ensure_ascii=False)
        self._secure_file(path)

    def _hydrate_sensitive_fields(self, connection: Dict[str, Any]) -> Dict[str, Any]:
        """从安全存储恢复敏感字段。"""
        hydrated = dict(connection)
        for field_name in ("password", "passphrase"):
            secret = SecureStorage.retrieve_password(f"{hydrated['id']}:{field_name}")
            if secret:
                hydrated[field_name] = secret
        return hydrated

    def _sanitize_connection(self, connection: Dict[str, Any]) -> Dict[str, Any]:
        """移除不应写入配置文件的敏感字段。"""
        sanitized = dict(connection)
        sanitized.pop("password", None)
        sanitized.pop("passphrase", None)
        return sanitized

    def _persist_sensitive_fields(self, connection: Dict[str, Any]) -> None:
        """将敏感字段写入安全存储。"""
        for field_name in ("password", "passphrase"):
            secret = connection.get(field_name)
            storage_key = f"{connection['id']}:{field_name}"
            if isinstance(secret, str) and secret:
                if not SecureStorage.store_password(storage_key, secret):
                    raise ConfigurationError(f"安全存储不可用，无法保存敏感字段: {field_name}")
            elif SecureStorage.retrieve_password(storage_key) is not None:
                SecureStorage.delete_password(storage_key)

    def _serialize_connection(
        self, connection_config: Union[Dict[str, Any], BaseConfig, Any]
    ) -> Dict[str, Any]:
        """将连接配置对象或字典标准化为可保存结构。"""
        if hasattr(connection_config, "to_dict"):
            data = connection_config.to_dict()
            for field_name in ("password", "passphrase"):
                secret = getattr(connection_config, field_name, None)
                if isinstance(secret, str) and secret:
                    data[field_name] = secret
        else:
            data = dict(connection_config)
        return self._normalize_connection_record(data)

    @staticmethod
    def _connection_field_names(
        connection_config: Union[Dict[str, Any], BaseConfig, Any],
    ) -> set[str]:
        """返回调用方显式提供的连接字段集合。"""
        if hasattr(connection_config, "to_dict"):
            return set(connection_config.to_dict().keys())
        return set(dict(connection_config).keys())

    @property
    def app_config(self) -> AppConfig:
        """获取应用配置"""
        if self._app_config is None:
            self._app_config = self.load_app_config()
        return self._app_config

    @property
    def connections_config_path(self) -> Path:
        """连接配置文件路径"""
        return self.config_dir / "connections.yaml"

    @property
    def tunnels_config_path(self) -> Path:
        """隧道配置文件路径"""
        return self.config_dir / "tunnels.yaml"

    @property
    def app_config_path(self) -> Path:
        """应用配置文件路径"""
        return self.config_dir / "config.yaml"

    @property
    def workspace_config_path(self) -> Path:
        """工作区状态文件路径。"""
        return self.config_dir / "workspace.yaml"

    @property
    def templates_config_path(self) -> Path:
        """连接模板配置文件路径。"""
        return self.config_dir / "templates.yaml"

    @property
    def shared_library_config_path(self) -> Path:
        """共享中心索引文件路径。"""
        return self.config_dir / "shared-library.yaml"

    @property
    def shared_library_history_config_path(self) -> Path:
        """共享中心同步历史文件路径。"""
        return self.config_dir / "shared-library-history.yaml"

    @property
    def shared_library_approval_config_path(self) -> Path:
        """共享中心审批记录文件路径。"""
        return self.config_dir / "shared-library-approvals.yaml"

    @property
    def shared_library_governance_audit_config_path(self) -> Path:
        """共享中心治理审计记录文件路径。"""
        return self.config_dir / "shared-library-governance-audit.yaml"

    @property
    def shared_library_signing_key_path(self) -> Path:
        """共享中心签名私钥文件路径。"""
        return self.config_dir / SHARED_LIBRARY_SIGNING_KEY_FILENAME

    @property
    def shared_library_dir(self) -> Path:
        """共享中心包目录。"""
        path = self.config_dir / "shared-library"
        path.mkdir(parents=True, exist_ok=True)
        self._secure_directory(path)
        return path

    @staticmethod
    def shared_library_lock_path(sync_dir: Union[str, Path]) -> Path:
        """返回共享仓库锁文件路径。"""
        return Path(sync_dir) / SHARED_LIBRARY_LOCK_FILENAME

    @property
    def shared_workspace_templates_dir(self) -> Path:
        """工作区模板共享包目录。"""
        path = self.shared_library_dir / "workspace_templates"
        path.mkdir(parents=True, exist_ok=True)
        self._secure_directory(path)
        return path

    @property
    def shared_connection_filter_presets_dir(self) -> Path:
        """筛选预设共享包目录。"""
        path = self.shared_library_dir / "connection_filter_presets"
        path.mkdir(parents=True, exist_ok=True)
        self._secure_directory(path)
        return path

    def config_file_paths(self) -> List[Path]:
        """返回由配置管理器维护的配置文件路径。"""
        return [
            self.app_config_path,
            self.connections_config_path,
            self.tunnels_config_path,
            self.workspace_config_path,
            self.templates_config_path,
            self.shared_library_config_path,
            self.shared_library_history_config_path,
            self.shared_library_approval_config_path,
            self.shared_library_governance_audit_config_path,
        ]

    def encrypt_config_files(self, master_password: str) -> List[Path]:
        """使用主密码加密现有配置文件。"""
        encryptor = ConfigEncryptor(master_password)
        encrypted_paths: List[Path] = []
        for path in self.config_file_paths():
            if not path.exists() or ConfigEncryptor.is_encrypted_file(path):
                continue
            encryptor.encrypt_file(path)
            self._secure_file(path)
            encrypted_paths.append(path)
        return encrypted_paths

    def decrypt_config_files(self, master_password: str) -> List[Path]:
        """使用主密码解密已加密配置文件。"""
        encryptor = ConfigEncryptor(master_password)
        decrypted_paths: List[Path] = []
        for path in self.config_file_paths():
            if not path.exists() or not ConfigEncryptor.is_encrypted_file(path):
                continue
            encryptor.decrypt_file(path)
            self._secure_file(path)
            decrypted_paths.append(path)
        return decrypted_paths

    def load_app_config(self) -> AppConfig:
        """加载应用配置"""
        data = self._load_mapping(self.app_config_path)
        self._secure_file(self.app_config_path)
        return AppConfig.from_mapping(data)

    def save_app_config(self, config: Optional[AppConfig] = None) -> None:
        """保存应用配置"""
        config = config or self._app_config or AppConfig()
        self._app_config = config
        payload = {
            "version": self.APP_CONFIG_VERSION,
            **config.to_dict(),
        }
        self._write_mapping(self.app_config_path, payload)

    def load_connections(self) -> List[Dict[str, Any]]:
        """加载所有连接配置"""
        data = self._load_mapping(self.connections_config_path)
        self._secure_file(self.connections_config_path)
        connections = [
            self._hydrate_sensitive_fields(self._normalize_connection_record(conn))
            for conn in self._extract_records(data, "connections")
        ]
        return connections

    def save_connections(self, connections: List[Dict[str, Any]]) -> None:
        """保存所有连接配置"""
        normalized_connections: List[Dict[str, Any]] = []
        for connection in connections:
            serialized = self._serialize_connection(connection)
            self._persist_sensitive_fields(serialized)
            normalized_connections.append(self._sanitize_connection(serialized))

        payload = {
            "version": self.CONNECTIONS_CONFIG_VERSION,
            "connections": normalized_connections,
        }
        self._write_mapping(self.connections_config_path, payload)

    def add_connection(
        self, connection_config: Union[Dict[str, Any], BaseConfig, Any]
    ) -> Dict[str, Any]:
        """添加连接配置"""
        connections = self.load_connections()
        serialized = self._serialize_connection(connection_config)
        connections.append(serialized)
        self.save_connections(connections)
        return dict(serialized)

    def remove_connection(self, connection_id: str) -> None:
        """删除连接配置"""
        connections = self.load_connections()
        connections = [
            connection for connection in connections if connection.get("id") != connection_id
        ]
        self.save_connections(connections)
        for field_name in ("password", "passphrase"):
            SecureStorage.delete_password(f"{connection_id}:{field_name}")

    def update_connection(
        self, connection_id: str, config: Union[Dict[str, Any], BaseConfig, Any]
    ) -> Dict[str, Any]:
        """更新连接配置"""
        connections = self.load_connections()
        provided_fields = self._connection_field_names(config)
        serialized = self._serialize_connection(config)
        serialized["id"] = connection_id
        for index, connection in enumerate(connections):
            if connection.get("id") == connection_id:
                for field_name in self.CONNECTION_METADATA_FIELDS:
                    if field_name not in provided_fields:
                        serialized[field_name] = connection.get(field_name)
                connections[index] = serialized
                break
        else:
            connections.append(serialized)
        self.save_connections(connections)
        return dict(serialized)

    def _update_connection_metadata(self, connection_id: str, **updates: Any) -> Dict[str, Any]:
        """更新连接元数据并持久化。"""
        connections = self.load_connections()
        for index, connection in enumerate(connections):
            if connection.get("id") != connection_id:
                continue
            updated = dict(connection)
            updated.update(updates)
            updated = self._normalize_connection_record(updated)
            connections[index] = updated
            self.save_connections(connections)
            return dict(updated)
        raise ConfigurationError(f"未找到连接配置: {connection_id}")

    def set_connection_favorite(self, connection_id: str, favorite: bool) -> Dict[str, Any]:
        """设置连接收藏状态。"""
        return self._update_connection_metadata(connection_id, favorite=bool(favorite))

    def update_connection_session_data(
        self,
        connection_id: str,
        session_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """更新连接的会话级终端数据。"""
        session_groups = normalize_terminal_snippet_groups(
            session_data.get("session_snippet_groups"),
            allow_empty=True,
        )
        payload = {
            "session_snippet_groups": session_groups,
            "session_favorite_snippets": normalize_terminal_favorite_snippets(
                session_data.get("session_favorite_snippets"),
                session_groups,
                allow_empty=True,
            ),
            "session_macros": normalize_terminal_macros(
                session_data.get("session_macros"),
                allow_empty=True,
            ),
        }
        return self._update_connection_metadata(connection_id, **payload)

    def mark_connection_used(
        self,
        connection_id: str,
        used_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录连接最近一次成功使用时间。"""
        timestamp = used_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return self._update_connection_metadata(connection_id, last_connected_at=timestamp)

    def load_recent_connections(self, limit: int = 10) -> List[Dict[str, Any]]:
        """按最近使用时间倒序返回连接。"""
        connections = [
            connection
            for connection in self.load_connections()
            if connection.get("last_connected_at")
        ]
        connections.sort(
            key=lambda connection: (
                connection.get("last_connected_at") or "",
                (connection.get("name") or "").casefold(),
            ),
            reverse=True,
        )
        return connections[:limit]

    def load_favorite_connections(self) -> List[Dict[str, Any]]:
        """返回已收藏连接，优先展示最近使用项。"""
        connections = [
            connection for connection in self.load_connections() if connection.get("favorite")
        ]
        connections.sort(key=lambda connection: (connection.get("name") or "").casefold())
        connections.sort(
            key=lambda connection: connection.get("last_connected_at") or "",
            reverse=True,
        )
        return connections

    def export_connections(self, export_path: Union[str, Path]) -> Path:
        """导出连接配置到外部文件。"""
        path = Path(export_path)
        exported_connections = [
            self._sanitize_connection(self._serialize_connection(connection))
            for connection in self.load_connections()
        ]
        payload = {
            "version": self.CONNECTIONS_CONFIG_VERSION,
            "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "connections": exported_connections,
        }
        self._write_mapping(path, payload)
        return path

    def _merge_imported_connections(
        self,
        imported_records: List[Dict[str, Any]],
        *,
        replace_existing: bool = False,
    ) -> List[Dict[str, Any]]:
        """合并外部导入的连接记录并持久化。"""
        if replace_existing:
            merged_connections = imported_records
        else:
            merged_map = {
                connection["id"]: connection
                for connection in self.load_connections()
                if connection.get("id")
            }
            for connection in imported_records:
                merged_map[connection["id"]] = connection
            merged_connections = list(merged_map.values())

        self.save_connections(merged_connections)
        return merged_connections

    def import_connections(
        self,
        import_path: Union[str, Path],
        *,
        replace_existing: bool = False,
    ) -> List[Dict[str, Any]]:
        """从外部文件导入连接配置。"""
        path = Path(import_path)
        imported_records = [
            self._serialize_connection(connection)
            for connection in self._extract_records(self._load_mapping(path), "connections")
        ]
        return self._merge_imported_connections(
            imported_records,
            replace_existing=replace_existing,
        )

    def import_openssh_config(
        self,
        import_path: Union[str, Path],
        *,
        replace_existing: bool = False,
    ) -> List[Dict[str, Any]]:
        """从 OpenSSH 配置导入 SSH 连接。"""
        try:
            from paramiko.config import SSHConfig as ParamikoSSHConfig
        except Exception as exc:  # pragma: no cover - 依赖缺失由运行环境决定
            raise ConfigurationError(f"无法加载 OpenSSH 配置解析器: {exc}") from exc

        path = Path(import_path)
        parser = ParamikoSSHConfig()
        with open(path, "r", encoding="utf-8") as file_handle:
            parser.parse(file_handle)

        imported_records: List[Dict[str, Any]] = []
        imported_ids: set[str] = set()
        for entry in getattr(parser, "_config", []):
            host_patterns = entry.get("host")
            if not isinstance(host_patterns, list):
                continue
            for pattern in host_patterns:
                alias = str(pattern or "").strip()
                if not alias or alias.startswith("!") or any(char in alias for char in ("*", "?")):
                    continue
                lookup = parser.lookup(alias)
                host = str(lookup.get("hostname") or "").strip() or alias
                port_value = lookup.get("port") or 22
                try:
                    port = int(str(port_value).strip())
                except (TypeError, ValueError):
                    port = 22
                identity_files = lookup.get("identityfile") or []
                if isinstance(identity_files, str):
                    identity_files = [identity_files]
                private_key_path = ""
                if identity_files:
                    private_key_path = str(Path(os.path.expanduser(str(identity_files[0]))))

                connection_id = (
                    f"ssh-{re.sub(r'[^a-zA-Z0-9._-]+', '-', alias).strip('-') or 'host'}"
                )
                suffix = 2
                while connection_id in imported_ids:
                    connection_id = f"ssh-{re.sub(r'[^a-zA-Z0-9._-]+', '-', alias).strip('-') or 'host'}-{suffix}"
                    suffix += 1
                imported_ids.add(connection_id)

                imported_records.append(
                    self._serialize_connection(
                        {
                            "id": connection_id,
                            "name": alias,
                            "connection_type": "ssh",
                            "host": host,
                            "port": port,
                            "username": str(lookup.get("user") or "").strip(),
                            "private_key_path": private_key_path,
                            "proxy_command": str(lookup.get("proxycommand") or "").strip(),
                            "look_for_keys": bool(identity_files),
                            "group": "OpenSSH",
                            "description": f"导入自 OpenSSH 配置: {path.name}",
                        }
                    )
                )

        if not imported_records:
            raise ConfigurationError("未在 OpenSSH 配置中解析到可导入的具体 Host 条目")

        return self._merge_imported_connections(
            imported_records,
            replace_existing=replace_existing,
        )

    def import_host_list(
        self,
        import_path: Union[str, Path],
        *,
        replace_existing: bool = False,
    ) -> List[Dict[str, Any]]:
        """从纯文本主机清单导入 SSH 连接。"""
        path = Path(import_path)
        imported_records: List[Dict[str, Any]] = []
        imported_ids: set[str] = set()

        with open(path, "r", encoding="utf-8") as file_handle:
            for raw_line in file_handle:
                line = raw_line.split("#", 1)[0].strip()
                if not line:
                    continue
                parsed = self._parse_host_list_line(line)
                if not parsed:
                    continue

                base_name = str(parsed.get("name") or parsed.get("host") or "host").strip()
                connection_id = (
                    f"ssh-{re.sub(r'[^a-zA-Z0-9._-]+', '-', base_name).strip('-') or 'host'}"
                )
                suffix = 2
                while connection_id in imported_ids:
                    connection_id = (
                        f"ssh-{re.sub(r'[^a-zA-Z0-9._-]+', '-', base_name).strip('-') or 'host'}-{suffix}"
                    )
                    suffix += 1
                imported_ids.add(connection_id)

                imported_records.append(
                    self._serialize_connection(
                        {
                            "id": connection_id,
                            "name": parsed["name"],
                            "connection_type": "ssh",
                            "host": parsed["host"],
                            "port": parsed["port"],
                            "username": parsed["username"],
                            "group": parsed["group"],
                            "description": f"导入自主机清单: {path.name}",
                        }
                    )
                )

        if not imported_records:
            raise ConfigurationError("未在主机清单中解析到可导入的主机条目")

        return self._merge_imported_connections(
            imported_records,
            replace_existing=replace_existing,
        )

    @staticmethod
    def _parse_host_list_endpoint(value: str) -> Dict[str, Any]:
        """解析 `user@host:port` 风格端点。"""
        raw = str(value or "").strip()
        username = ""
        host = raw
        port = 22
        if "@" in raw:
            username, host = raw.split("@", 1)
            username = username.strip()
            host = host.strip()

        if host.count(":") == 1:
            host_candidate, port_candidate = host.rsplit(":", 1)
            try:
                port = int(port_candidate.strip())
                host = host_candidate.strip()
            except (TypeError, ValueError):
                pass

        return {
            "username": username,
            "host": host.strip(),
            "port": port,
        }

    @classmethod
    def _parse_host_list_line(cls, line: str) -> Optional[Dict[str, Any]]:
        """解析主机清单单行。"""
        try:
            tokens = shlex.split(line)
        except ValueError:
            tokens = line.split()
        if not tokens:
            return None

        name = ""
        endpoint_token = tokens[0]
        extras = tokens[1:]

        if len(tokens) >= 2 and not any(char in tokens[0] for char in ("@", ":", ".")):
            name = tokens[0].strip()
            endpoint_token = tokens[1]
            extras = tokens[2:]

        endpoint = cls._parse_host_list_endpoint(endpoint_token)
        host = str(endpoint.get("host") or "").strip()
        if not host:
            return None

        username = str(endpoint.get("username") or "").strip()
        port = int(endpoint.get("port") or 22)
        group = "主机清单"

        if extras:
            first_extra = str(extras[0] or "").strip()
            if first_extra:
                if first_extra.isdigit():
                    port = int(first_extra)
                elif not username:
                    username = first_extra
                else:
                    group = first_extra

        if len(extras) >= 2:
            second_extra = str(extras[1] or "").strip()
            if second_extra:
                if second_extra.isdigit():
                    port = int(second_extra)
                else:
                    group = second_extra

        if len(extras) >= 3:
            group = str(" ".join(str(item).strip() for item in extras[2:] if str(item).strip()) or group)

        resolved_name = name or host
        return {
            "name": resolved_name,
            "host": host,
            "port": max(port, 1),
            "username": username,
            "group": group,
        }

    def export_workspace_templates(
        self,
        export_path: Union[str, Path],
        *,
        template_kind: Optional[str] = None,
        template_ids: Optional[List[str]] = None,
        package_info: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """导出工作区模板到外部文件。"""
        path = Path(export_path)
        templates = self.load_workspace_templates()
        if template_ids is not None:
            selected_ids = {
                str(template_id).strip() for template_id in template_ids if str(template_id).strip()
            }
            templates = [
                template for template in templates if str(template.get("id") or "") in selected_ids
            ]
        if template_kind is not None:
            normalized_kind = self._normalize_workspace_template_kind(template_kind)
            templates = [
                template
                for template in templates
                if str(template.get("template_kind") or "workspace") == normalized_kind
            ]
        normalized_templates = self._normalize_workspace_templates(templates)
        exported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        payload = {
            "version": self.TEMPLATES_CONFIG_VERSION,
            "exported_at": exported_at,
            "package": self._build_share_package_metadata(
                "workspace_templates",
                len(normalized_templates),
                package_info=package_info,
                exported_at=exported_at,
            ),
            "workspace_templates": normalized_templates,
        }
        content_hash = self._build_share_package_content_hash("workspace_templates", payload)
        payload["package"]["content_hash"] = content_hash
        payload["package"].update(
            self._build_share_package_signature_metadata(
                str(payload["package"].get("source_app") or SHARE_PACKAGE_SOURCE_APP),
                content_hash,
                additional_signers=(
                    list(package_info.get("additional_signers") or [])
                    if isinstance(package_info, dict)
                    else None
                ),
            )
        )
        self._write_mapping(path, payload)
        return path

    def preview_workspace_template_import(
        self,
        import_path: Union[str, Path],
    ) -> Dict[str, Any]:
        """预览工作区模板导入摘要。"""
        path = Path(import_path)
        payload = self._load_mapping(path)
        imported_templates = self._normalize_workspace_templates(
            self._extract_records(payload, "workspace_templates")
        )
        package = self._extract_share_package_metadata(
            payload,
            package_type="workspace_templates",
            item_count=len(imported_templates),
        )
        summary = self._build_named_record_import_summary(
            self.load_workspace_templates(),
            imported_templates,
            package=package,
        )
        summary["path"] = str(path)
        return summary

    def import_workspace_templates_with_summary(
        self,
        import_path: Union[str, Path],
        *,
        replace_existing: bool = False,
        conflict_strategy: str = "replace",
    ) -> Dict[str, Any]:
        """导入工作区模板并返回摘要。"""
        path = Path(import_path)
        payload = self._load_mapping(path)
        imported_templates = self._normalize_workspace_templates(
            self._extract_records(payload, "workspace_templates")
        )
        package = self._extract_share_package_metadata(
            payload,
            package_type="workspace_templates",
            item_count=len(imported_templates),
        )
        preview = self._build_named_record_import_summary(
            self.load_workspace_templates(),
            imported_templates,
            package=package,
        )

        if replace_existing:
            merged_templates = imported_templates
            stats = {
                "imported_count": len(imported_templates),
                "new_count": len(imported_templates),
                "replaced_count": 0,
                "renamed_count": 0,
                "skipped_count": 0,
                "conflict_count": 0,
            }
            effective_strategy = "replace_all"
        else:
            effective_strategy = self._normalize_import_conflict_strategy(conflict_strategy)
            existing_templates = self.load_workspace_templates()
            merged_templates, stats = self._merge_named_records_for_import(
                existing_templates,
                imported_templates,
                conflict_strategy=effective_strategy,
            )

        self.save_workspace_templates(merged_templates)
        templates = self.load_workspace_templates()
        return {
            "templates": templates,
            "package": package,
            "preview": preview,
            "path": str(path),
            "conflict_strategy": effective_strategy,
            **stats,
        }

    def import_workspace_templates(
        self,
        import_path: Union[str, Path],
        *,
        replace_existing: bool = False,
        conflict_strategy: str = "replace",
    ) -> List[Dict[str, Any]]:
        """从外部文件导入工作区模板。"""
        result = self.import_workspace_templates_with_summary(
            import_path,
            replace_existing=replace_existing,
            conflict_strategy=conflict_strategy,
        )
        return result["templates"]

    def duplicate_workspace_template(
        self,
        template_id: str,
        new_name: str,
    ) -> Dict[str, Any]:
        """复制现有工作区模板。"""
        template_name = new_name.strip()
        if not template_name:
            raise ConfigurationError("工作区模板名称不能为空")

        template = next(
            (
                current
                for current in self.load_workspace_templates()
                if current.get("id") == template_id
            ),
            None,
        )
        if template is None:
            raise ConfigurationError("未找到工作区模板")

        duplicate = dict(template)
        duplicate["id"] = str(uuid4())
        duplicate["name"] = template_name
        duplicate["usage_count"] = 0
        duplicate["last_used_at"] = None
        duplicate["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        templates = self.load_workspace_templates()
        templates.append(duplicate)
        self.save_workspace_templates(templates)
        return duplicate

    def load_tunnels(self) -> List[Dict[str, Any]]:
        """加载所有隧道配置。"""
        data = self._load_mapping(self.tunnels_config_path)
        self._secure_file(self.tunnels_config_path)
        return [
            self._normalize_tunnel_id(tunnel) for tunnel in self._extract_records(data, "tunnels")
        ]

    def save_tunnels(self, tunnels: List[Dict[str, Any]]) -> None:
        """保存所有隧道配置。"""
        normalized = [self._normalize_tunnel_id(tunnel) for tunnel in tunnels]
        payload = {
            "version": self.TUNNELS_CONFIG_VERSION,
            "tunnels": normalized,
        }
        self._write_mapping(self.tunnels_config_path, payload)

    def add_tunnel(self, tunnel_config: Union[Dict[str, Any], Any]) -> Dict[str, Any]:
        """添加隧道配置。"""
        tunnels = self.load_tunnels()
        data = tunnel_config.to_dict() if hasattr(tunnel_config, "to_dict") else dict(tunnel_config)
        data = self._normalize_tunnel_id(data)
        tunnels.append(data)
        self.save_tunnels(tunnels)
        return dict(data)

    def update_tunnel(
        self, tunnel_id: str, tunnel_config: Union[Dict[str, Any], Any]
    ) -> Dict[str, Any]:
        """更新隧道配置。"""
        tunnels = self.load_tunnels()
        data = tunnel_config.to_dict() if hasattr(tunnel_config, "to_dict") else dict(tunnel_config)
        data["id"] = tunnel_id
        for index, tunnel in enumerate(tunnels):
            if tunnel.get("id") == tunnel_id:
                tunnels[index] = data
                break
        else:
            tunnels.append(data)
        self.save_tunnels(tunnels)
        return dict(data)

    def remove_tunnel(self, tunnel_id: str) -> None:
        """删除隧道配置。"""
        tunnels = [tunnel for tunnel in self.load_tunnels() if tunnel.get("id") != tunnel_id]
        self.save_tunnels(tunnels)

    @staticmethod
    def _normalize_workspace_layout(layout: Any) -> Dict[str, Any]:
        """规整工作区布局数据。"""
        if not isinstance(layout, dict):
            return {}

        normalized: Dict[str, Any] = {}
        for key in ("main_splitter_sizes", "work_splitter_sizes"):
            values = layout.get(key)
            if not isinstance(values, list):
                continue
            cleaned: List[int] = []
            for value in values:
                try:
                    size = int(value)
                except (TypeError, ValueError):
                    continue
                if size >= 0:
                    cleaned.append(size)
            if len(cleaned) >= 2:
                normalized[key] = cleaned

        sync_input_enabled = layout.get("sync_input_enabled")
        if isinstance(sync_input_enabled, bool):
            normalized["sync_input_enabled"] = sync_input_enabled

        sync_input_scope = layout.get("sync_input_scope")
        if isinstance(sync_input_scope, str) and sync_input_scope.strip():
            normalized["sync_input_scope"] = sync_input_scope.strip()

        return normalized

    @staticmethod
    def _normalize_workspace_tabs(tabs: Any) -> List[Dict[str, Any]]:
        """规整工作区标签记录。"""
        if not isinstance(tabs, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            kind = str(tab.get("kind") or "").strip()
            if not kind:
                continue
            item = {"kind": kind}
            if kind in {"connection", "file_browser"}:
                connection_id = str(tab.get("connection_id") or "").strip()
                if not connection_id:
                    continue
                item["connection_id"] = connection_id
            normalized.append(item)
        return normalized

    def _normalize_workspace_state_payload(self, workspace_state: Any) -> Dict[str, Any]:
        """规整工作区状态载荷。"""
        data = workspace_state if isinstance(workspace_state, dict) else {}
        current_index = data.get("current_index", 0)
        try:
            current_index_value = int(current_index)
        except (TypeError, ValueError):
            current_index_value = 0
        return {
            "tabs": self._normalize_workspace_tabs(data.get("tabs")),
            "current_index": max(0, current_index_value),
            "layout": self._normalize_workspace_layout(data.get("layout")),
        }

    @staticmethod
    def _workspace_connection_ids_from_state(workspace_state: Dict[str, Any]) -> List[str]:
        """从工作区状态中提取连接 ID。"""
        connection_ids: List[str] = []
        seen: set[str] = set()
        for tab in workspace_state.get("tabs", []):
            if not isinstance(tab, dict) or tab.get("kind") not in {"connection", "file_browser"}:
                continue
            connection_id = str(tab.get("connection_id") or "").strip()
            if not connection_id or connection_id in seen:
                continue
            seen.add(connection_id)
            connection_ids.append(connection_id)
        return connection_ids

    def load_workspace_state(self) -> Dict[str, Any]:
        """加载工作区状态。"""
        data = self._load_mapping(self.workspace_config_path)
        self._secure_file(self.workspace_config_path)
        normalized = self._normalize_workspace_state_payload(data)
        normalized["version"] = self.WORKSPACE_CONFIG_VERSION
        return normalized

    def save_workspace_state(self, workspace_state: Dict[str, Any]) -> None:
        """保存工作区状态。"""
        normalized = self._normalize_workspace_state_payload(workspace_state)
        payload = {
            "version": self.WORKSPACE_CONFIG_VERSION,
            "tabs": normalized["tabs"],
            "current_index": normalized["current_index"],
            "layout": normalized["layout"],
            "saved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        self._write_mapping(self.workspace_config_path, payload)

    def clear_workspace_state(self) -> None:
        """清空工作区状态。"""
        self.save_workspace_state({"tabs": [], "current_index": 0, "layout": {}})

    def load_connection_templates(self) -> List[Dict[str, Any]]:
        """加载连接模板。"""
        data = self._load_mapping(self.templates_config_path)
        self._secure_file(self.templates_config_path)
        return self._normalize_connection_templates(self._extract_records(data, "templates"))

    def save_connection_templates(self, templates: List[Dict[str, Any]]) -> None:
        """保存连接模板。"""
        data = self._load_mapping(self.templates_config_path)
        payload = {
            "version": self.TEMPLATES_CONFIG_VERSION,
            "templates": self._normalize_connection_templates(templates),
            "workspace_templates": self._normalize_workspace_templates(
                self._extract_records(data, "workspace_templates")
            ),
            "connection_filter_presets": self._normalize_connection_filter_presets(
                self._extract_records(data, "connection_filter_presets")
            ),
        }
        self._write_mapping(self.templates_config_path, payload)

    def upsert_connection_template(
        self,
        name: str,
        connection_type: str,
        payload: Dict[str, Any],
        template_id: Optional[str] = None,
        template_scope: str = "connection",
    ) -> Dict[str, Any]:
        """新增或更新连接模板。"""
        if not name.strip():
            raise ConfigurationError("模板名称不能为空")

        sanitized_payload = dict(payload)
        for field_name in ("id", "password", "passphrase", "favorite", "last_connected_at"):
            sanitized_payload.pop(field_name, None)

        template = {
            "id": template_id or str(uuid4()),
            "name": name.strip(),
            "connection_type": connection_type.lower(),
            "template_scope": self._normalize_connection_template_scope(template_scope),
            "payload": sanitized_payload,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

        templates = self.load_connection_templates()
        for index, current in enumerate(templates):
            if current.get("id") == template["id"] or (
                current.get("name") == template["name"]
                and current.get("connection_type") == template["connection_type"]
            ):
                templates[index] = template
                break
        else:
            templates.append(template)
        self.save_connection_templates(templates)
        return template

    def remove_connection_template(self, template_id: str) -> None:
        """删除连接模板。"""
        templates = [
            template
            for template in self.load_connection_templates()
            if template.get("id") != template_id
        ]
        self.save_connection_templates(templates)

    @staticmethod
    def _normalize_connection_templates(templates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """规整连接模板记录。"""
        normalized: List[Dict[str, Any]] = []
        for template in templates:
            if not isinstance(template, dict):
                continue
            payload = template.get("payload")
            if not isinstance(payload, dict):
                continue
            normalized.append(
                {
                    "id": template.get("id") or str(uuid4()),
                    "name": template.get("name") or "未命名模板",
                    "connection_type": str(template.get("connection_type", "")).lower(),
                    "template_scope": ConfigManager._normalize_connection_template_scope(
                        template.get("template_scope")
                    ),
                    "payload": dict(payload),
                    "updated_at": template.get("updated_at") or None,
                }
            )
        return normalized

    @staticmethod
    def _normalize_connection_template_scope(scope: Any) -> str:
        """规整连接模板作用域。"""
        normalized = str(scope or "connection").strip().lower()
        if normalized in {"connection", "auth_profile"}:
            return normalized
        return "connection"

    @staticmethod
    def _normalize_workspace_template_kind(kind: Any) -> str:
        """规整工作区模板类型。"""
        normalized = str(kind or "workspace").strip().lower()
        if normalized in {"workspace", "ops_workspace", "scene_workspace"}:
            return normalized
        return "workspace"

    @staticmethod
    def _normalize_import_conflict_strategy(strategy: Any) -> str:
        """规整导入冲突处理策略。"""
        normalized = str(strategy or "replace").strip().lower()
        if normalized in {"replace", "skip", "rename"}:
            return normalized
        raise ConfigurationError("不支持的导入冲突策略")

    @staticmethod
    def _build_share_package_metadata(
        package_type: str,
        item_count: int,
        *,
        package_info: Optional[Dict[str, Any]] = None,
        exported_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构造共享导出包元数据。"""
        info = dict(package_info or {})
        package_name = str(info.get("name") or "").strip() or None
        description = str(info.get("description") or "").strip() or None
        source_app = str(info.get("source_app") or SHARE_PACKAGE_SOURCE_APP).strip()
        source_version = str(info.get("source_version") or SHARE_PACKAGE_SOURCE_VERSION).strip()
        exported_by = str(info.get("exported_by") or "").strip() or None
        source_scope = str(info.get("source_scope") or "").strip() or None
        labels = _normalize_share_labels(info.get("labels"))
        package_version = _normalize_package_version(info.get("package_version"))
        content_hash = str(info.get("content_hash") or "").strip() or None
        signature_algorithm = str(info.get("signature_algorithm") or "").strip() or None
        signature = str(info.get("signature") or "").strip() or None
        signature_signer = str(info.get("signature_signer") or "").strip() or None
        signature_public_key = str(info.get("signature_public_key") or "").strip() or None
        signature_fingerprint = str(info.get("signature_fingerprint") or "").strip() or None
        additional_signatures = _normalize_shared_library_additional_signatures(
            info.get("additional_signatures")
        )

        return {
            "format_version": SHARE_PACKAGE_FORMAT_VERSION,
            "package_type": package_type,
            "name": package_name,
            "description": description,
            "source_app": source_app or SHARE_PACKAGE_SOURCE_APP,
            "source_version": source_version or SHARE_PACKAGE_SOURCE_VERSION,
            "source_scope": source_scope,
            "exported_by": exported_by,
            "exported_at": exported_at,
            "item_count": max(int(item_count or 0), 0),
            "labels": labels,
            "package_version": package_version,
            "content_hash": content_hash,
            "signature_algorithm": signature_algorithm,
            "signature": signature,
            "signature_signer": signature_signer,
            "signature_public_key": signature_public_key,
            "signature_fingerprint": signature_fingerprint,
            "additional_signatures": additional_signatures,
        }

    def _extract_share_package_metadata(
        self,
        payload: Dict[str, Any],
        *,
        package_type: str,
        item_count: int,
    ) -> Dict[str, Any]:
        """读取并规整共享导入包元数据。"""
        raw_package = payload.get("package")
        exported_at = str(payload.get("exported_at") or "").strip() or None
        if not isinstance(raw_package, dict):
            return self._build_share_package_metadata(
                package_type,
                item_count,
                exported_at=exported_at,
            )

        merged_info = dict(raw_package)
        if exported_at and not merged_info.get("exported_at"):
            merged_info["exported_at"] = exported_at

        return self._build_share_package_metadata(
            str(merged_info.get("package_type") or package_type).strip() or package_type,
            item_count,
            package_info=merged_info,
            exported_at=str(merged_info.get("exported_at") or exported_at or "").strip() or None,
        )

    def _build_share_package_content_hash(
        self,
        package_type: str,
        payload: Dict[str, Any],
    ) -> str:
        """基于共享包内容生成稳定摘要，用于版本比对。"""
        normalized_type = self._normalize_shared_library_package_type(package_type)
        record_key = (
            "workspace_templates"
            if normalized_type == "workspace_templates"
            else "connection_filter_presets"
        )
        items = self._extract_records(payload, record_key)
        package = dict(payload.get("package") or {})
        content_payload = {
            "package_type": normalized_type,
            "package": {
                "name": str(package.get("name") or "").strip(),
                "description": str(package.get("description") or "").strip(),
                "source_app": str(package.get("source_app") or SHARE_PACKAGE_SOURCE_APP).strip(),
                "source_version": str(
                    package.get("source_version") or SHARE_PACKAGE_SOURCE_VERSION
                ).strip(),
                "source_scope": str(package.get("source_scope") or "").strip(),
                "exported_by": str(package.get("exported_by") or "").strip(),
                "labels": _normalize_share_labels(package.get("labels")),
                "item_count": max(int(package.get("item_count") or len(items)), 0),
                "package_version": _normalize_package_version(package.get("package_version")),
            },
            "items": items,
        }
        encoded = json.dumps(
            content_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _load_or_create_shared_library_signing_private_key(self) -> str:
        """加载或生成共享中心签名私钥。"""
        key_path = self.shared_library_signing_key_path
        if key_path.exists():
            private_key_pem = key_path.read_text(encoding="utf-8").strip()
            self._secure_file(key_path)
            if private_key_pem:
                return private_key_pem

        private_key_pem = PackageSigner.generate_private_key_pem()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(private_key_pem, encoding="utf-8")
        self._secure_file(key_path)
        return private_key_pem

    @staticmethod
    def _build_share_package_signature_entry(
        private_key_pem: str,
        content_hash: str,
        *,
        signer_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """基于指定私钥构造一条共享包签名记录。"""
        public_key = PackageSigner.public_key_from_private_key_pem(private_key_pem)
        fingerprint = PackageSigner.fingerprint_from_public_key(public_key)
        effective_signer = (
            signer_name or SHARE_PACKAGE_SOURCE_APP
        ).strip() or SHARE_PACKAGE_SOURCE_APP
        return {
            "signature_algorithm": PackageSigner.SIGNATURE_ALGORITHM,
            "signature": PackageSigner.sign_text(private_key_pem, content_hash),
            "signature_signer": f"{effective_signer}@{fingerprint[:12]}",
            "signature_public_key": public_key,
            "signature_fingerprint": fingerprint,
        }

    def _build_share_package_signature_metadata(
        self,
        source_app: str,
        content_hash: str,
        *,
        additional_signers: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """构造共享包签名元数据。"""
        try:
            private_key_pem = self._load_or_create_shared_library_signing_private_key()
            primary_signature = self._build_share_package_signature_entry(
                private_key_pem,
                content_hash,
                signer_name=source_app.strip() or SHARE_PACKAGE_SOURCE_APP,
            )
            additional_entries: List[Dict[str, Any]] = []
            for signer in additional_signers or []:
                if not isinstance(signer, dict):
                    continue
                co_sign_private_key = str(
                    signer.get("private_key_pem") or signer.get("private_key") or ""
                ).strip()
                if not co_sign_private_key:
                    continue
                try:
                    additional_entries.append(
                        self._build_share_package_signature_entry(
                            co_sign_private_key,
                            content_hash,
                            signer_name=str(
                                signer.get("signer_name")
                                or signer.get("source_app")
                                or signer.get("name")
                                or source_app
                            ).strip()
                            or source_app,
                        )
                    )
                except Exception:
                    continue
            return {
                **primary_signature,
                "additional_signatures": _normalize_shared_library_additional_signatures(
                    additional_entries
                ),
            }
        except Exception:
            return {}

    def add_shared_library_package_additional_signature(
        self,
        package_path: Union[str, Path],
        *,
        private_key_pem: str,
        signer_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """为已导出的共享包追加一条附加签名。"""
        path = Path(package_path)
        payload = self._load_mapping(path)
        package = dict(payload.get("package") or {})
        package_type = str(package.get("package_type") or "").strip()
        if not package_type:
            raise ConfigurationError("共享包缺少 package_type，无法追加签名")
        content_hash = self._build_share_package_content_hash(package_type, payload)
        package["content_hash"] = content_hash
        additional_signatures = _normalize_shared_library_additional_signatures(
            package.get("additional_signatures")
        )
        additional_signatures.append(
            self._build_share_package_signature_entry(
                private_key_pem,
                content_hash,
                signer_name=signer_name
                or str(package.get("source_app") or SHARE_PACKAGE_SOURCE_APP),
            )
        )
        package["additional_signatures"] = _normalize_shared_library_additional_signatures(
            additional_signatures
        )
        payload["package"] = package
        self._write_mapping(path, payload)
        return dict(package)

    @staticmethod
    def _record_import_conflicts(
        existing_records: List[Dict[str, Any]],
        imported_record: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """查找导入记录与现有记录的冲突项。"""
        imported_id = str(imported_record.get("id") or "").strip()
        imported_name = str(imported_record.get("name") or "").strip()
        imported_name_key = imported_name.casefold()
        conflicts: List[Dict[str, Any]] = []

        for index, existing in enumerate(existing_records):
            existing_id = str(existing.get("id") or "").strip()
            existing_name = str(existing.get("name") or "").strip()
            reasons: List[str] = []
            if imported_id and existing_id and imported_id == existing_id:
                reasons.append("id")
            if imported_name_key and existing_name.casefold() == imported_name_key:
                reasons.append("name")
            if reasons:
                conflicts.append(
                    {
                        "index": index,
                        "record": dict(existing),
                        "reasons": reasons,
                    }
                )

        return conflicts

    @staticmethod
    def _make_import_copy_name(name: str, existing_names: set[str]) -> str:
        """为冲突导入记录生成唯一名称。"""
        base_name = name.strip() or "未命名模板"
        candidate = f"{base_name} (导入)"
        if candidate.casefold() not in existing_names:
            return candidate

        suffix = 2
        while True:
            candidate = f"{base_name} (导入 {suffix})"
            if candidate.casefold() not in existing_names:
                return candidate
            suffix += 1

    def _build_named_record_import_summary(
        self,
        existing_records: List[Dict[str, Any]],
        imported_records: List[Dict[str, Any]],
        *,
        package: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建命名记录导入摘要。"""
        new_count = 0
        conflict_items: List[Dict[str, Any]] = []
        for imported in imported_records:
            conflicts = self._record_import_conflicts(existing_records, imported)
            if conflicts:
                reason_parts: List[str] = []
                for conflict in conflicts:
                    for reason in conflict["reasons"]:
                        if reason not in reason_parts:
                            reason_parts.append(reason)
                conflict_items.append(
                    {
                        "name": str(imported.get("name") or "未命名项"),
                        "id": str(imported.get("id") or ""),
                        "reason": "+".join(reason_parts),
                        "existing_names": [
                            str(conflict["record"].get("name") or "未命名项")
                            for conflict in conflicts
                        ],
                    }
                )
            else:
                new_count += 1

        return {
            "package": package,
            "item_count": len(imported_records),
            "new_count": new_count,
            "conflict_count": len(conflict_items),
            "conflicts": conflict_items,
            "sample_names": [
                str(record.get("name") or "未命名项") for record in imported_records[:10]
            ],
        }

    def _merge_named_records_for_import(
        self,
        existing_records: List[Dict[str, Any]],
        imported_records: List[Dict[str, Any]],
        *,
        conflict_strategy: str,
    ) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
        """按指定冲突策略合并命名记录。"""
        strategy = self._normalize_import_conflict_strategy(conflict_strategy)
        merged_records = [dict(record) for record in existing_records]
        stats = {
            "imported_count": len(imported_records),
            "new_count": 0,
            "replaced_count": 0,
            "renamed_count": 0,
            "skipped_count": 0,
            "conflict_count": 0,
        }

        for imported in imported_records:
            record = dict(imported)
            conflicts = self._record_import_conflicts(merged_records, record)
            if not conflicts:
                merged_records.append(record)
                stats["new_count"] += 1
                continue

            stats["conflict_count"] += 1
            if strategy == "skip":
                stats["skipped_count"] += 1
                continue

            if strategy == "rename":
                existing_names = {
                    str(existing.get("name") or "").strip().casefold()
                    for existing in merged_records
                    if str(existing.get("name") or "").strip()
                }
                record["id"] = str(uuid4())
                record["name"] = self._make_import_copy_name(
                    str(record.get("name") or ""),
                    existing_names,
                )
                merged_records.append(record)
                stats["renamed_count"] += 1
                continue

            conflict_indexes = sorted(
                {int(conflict["index"]) for conflict in conflicts},
                reverse=True,
            )
            for conflict_index in conflict_indexes:
                merged_records.pop(conflict_index)
            merged_records.append(record)
            stats["replaced_count"] += 1

        return merged_records, stats

    @staticmethod
    def _normalize_connection_filter_state(filters: Any) -> Dict[str, str]:
        """规整连接树筛选状态。"""
        if not isinstance(filters, dict):
            return {
                "search": "",
                "type": "__all__",
                "view": "group",
                "favorite": "__all__",
                "group": "__all__",
            }

        return {
            "search": str(filters.get("search") or "").strip(),
            "type": str(filters.get("type") or "__all__").strip() or "__all__",
            "view": str(filters.get("view") or "group").strip() or "group",
            "favorite": str(filters.get("favorite") or "__all__").strip() or "__all__",
            "group": str(filters.get("group") or "__all__").strip() or "__all__",
        }

    def _normalize_connection_filter_presets(
        self, presets: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """规整连接筛选预设记录。"""
        normalized: List[Dict[str, Any]] = []
        for preset in presets:
            if not isinstance(preset, dict):
                continue
            name = str(preset.get("name") or "").strip()
            if not name:
                continue
            normalized.append(
                {
                    "id": preset.get("id") or str(uuid4()),
                    "name": name,
                    "filters": self._normalize_connection_filter_state(preset.get("filters")),
                    "usage_count": _normalize_usage_count(preset.get("usage_count")),
                    "last_used_at": preset.get("last_used_at") or None,
                    "updated_at": preset.get("updated_at") or None,
                }
            )
        normalized.sort(key=lambda preset: str(preset.get("name", "")).casefold())
        return normalized

    def _normalize_workspace_templates(
        self, templates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """规整工作区模板记录。"""
        normalized: List[Dict[str, Any]] = []
        for template in templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or "").strip()
            if not name:
                continue
            workspace_state = self._normalize_workspace_state_payload(
                template.get("workspace_state")
            )
            connection_ids: List[str] = []
            seen: set[str] = set()
            for value in template.get("connection_ids", []) or []:
                if not isinstance(value, str):
                    continue
                connection_id = value.strip()
                if not connection_id or connection_id in seen:
                    continue
                seen.add(connection_id)
                connection_ids.append(connection_id)
            for connection_id in self._workspace_connection_ids_from_state(workspace_state):
                if connection_id in seen:
                    continue
                seen.add(connection_id)
                connection_ids.append(connection_id)
            if not connection_ids and not workspace_state.get("tabs"):
                continue
            normalized.append(
                {
                    "id": template.get("id") or str(uuid4()),
                    "name": name,
                    "connection_ids": connection_ids,
                    "workspace_state": workspace_state,
                    "template_kind": self._normalize_workspace_template_kind(
                        template.get("template_kind")
                    ),
                    "scope_view": str(template.get("scope_view") or "").strip() or None,
                    "scope_name": str(template.get("scope_name") or "").strip() or None,
                    "include_file_browsers": bool(template.get("include_file_browsers")),
                    "include_local_terminal": bool(template.get("include_local_terminal")),
                    "filter_state": (
                        self._normalize_connection_filter_state(template.get("filter_state"))
                        if isinstance(template.get("filter_state"), dict)
                        else None
                    ),
                    "task_preset_key": str(template.get("task_preset_key") or "").strip() or None,
                    "task_preset_title": str(template.get("task_preset_title") or "").strip()
                    or None,
                    "usage_count": _normalize_usage_count(template.get("usage_count")),
                    "last_used_at": template.get("last_used_at") or None,
                    "updated_at": template.get("updated_at") or None,
                }
            )
        normalized.sort(key=lambda template: str(template.get("name", "")).casefold())
        return normalized

    def load_workspace_templates(self) -> List[Dict[str, Any]]:
        """加载工作区模板。"""
        data = self._load_mapping(self.templates_config_path)
        self._secure_file(self.templates_config_path)
        return self._normalize_workspace_templates(
            self._extract_records(data, "workspace_templates")
        )

    def save_workspace_templates(self, templates: List[Dict[str, Any]]) -> None:
        """保存工作区模板。"""
        data = self._load_mapping(self.templates_config_path)
        payload = {
            "version": self.TEMPLATES_CONFIG_VERSION,
            "templates": self._normalize_connection_templates(
                self._extract_records(data, "templates")
            ),
            "workspace_templates": self._normalize_workspace_templates(templates),
            "connection_filter_presets": self._normalize_connection_filter_presets(
                self._extract_records(data, "connection_filter_presets")
            ),
        }
        self._write_mapping(self.templates_config_path, payload)

    def upsert_workspace_template(
        self,
        name: str,
        connection_ids: List[str],
        workspace_state: Optional[Dict[str, Any]] = None,
        template_id: Optional[str] = None,
        *,
        template_kind: str = "workspace",
        include_file_browsers: bool = False,
        include_local_terminal: bool = False,
        scope_view: Optional[str] = None,
        scope_name: Optional[str] = None,
        filter_state: Optional[Dict[str, Any]] = None,
        task_preset_key: Optional[str] = None,
        task_preset_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """新增或更新工作区模板。"""
        template_name = name.strip()
        if not template_name:
            raise ConfigurationError("工作区模板名称不能为空")

        normalized_ids: List[str] = []
        seen: set[str] = set()
        for value in connection_ids:
            if not isinstance(value, str):
                continue
            connection_id = value.strip()
            if not connection_id or connection_id in seen:
                continue
            seen.add(connection_id)
            normalized_ids.append(connection_id)
        normalized_state = self._normalize_workspace_state_payload(workspace_state or {})
        if not normalized_state["tabs"] and normalized_ids:
            normalized_state = self._normalize_workspace_state_payload(
                {
                    "tabs": [
                        {"kind": "connection", "connection_id": connection_id}
                        for connection_id in normalized_ids
                    ],
                    "current_index": 0,
                }
            )

        for connection_id in self._workspace_connection_ids_from_state(normalized_state):
            if connection_id in seen:
                continue
            seen.add(connection_id)
            normalized_ids.append(connection_id)
        if not normalized_ids and not normalized_state["tabs"]:
            raise ConfigurationError("工作区模板至少需要一个连接或工作区标签")

        templates = self.load_workspace_templates()
        existing = next(
            (
                current
                for current in templates
                if current.get("id") == template_id or current.get("name") == template_name
            ),
            None,
        )

        template = {
            "id": template_id or (existing.get("id") if existing else None) or str(uuid4()),
            "name": template_name,
            "connection_ids": normalized_ids,
            "workspace_state": normalized_state,
            "template_kind": self._normalize_workspace_template_kind(template_kind),
            "scope_view": str(scope_view or "").strip() or None,
            "scope_name": str(scope_name or "").strip() or None,
            "include_file_browsers": bool(include_file_browsers),
            "include_local_terminal": bool(include_local_terminal),
            "filter_state": (
                self._normalize_connection_filter_state(filter_state)
                if isinstance(filter_state, dict)
                else None
            ),
            "task_preset_key": str(task_preset_key or "").strip() or None,
            "task_preset_title": str(task_preset_title or "").strip() or None,
            "usage_count": _normalize_usage_count(existing.get("usage_count") if existing else 0),
            "last_used_at": existing.get("last_used_at") if existing else None,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

        for index, current in enumerate(templates):
            if current.get("id") == template["id"] or current.get("name") == template["name"]:
                templates[index] = template
                break
        else:
            templates.append(template)
        self.save_workspace_templates(templates)
        return template

    def remove_workspace_template(self, template_id: str) -> None:
        """删除工作区模板。"""
        templates = [
            template
            for template in self.load_workspace_templates()
            if template.get("id") != template_id
        ]
        self.save_workspace_templates(templates)

    def mark_workspace_template_used(
        self,
        template_id: str,
        used_at: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """记录工作区模板被打开。"""
        templates = self.load_workspace_templates()
        updated: Optional[Dict[str, Any]] = None
        timestamp = used_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        for index, template in enumerate(templates):
            if template.get("id") != template_id:
                continue
            current = dict(template)
            current["usage_count"] = _normalize_usage_count(current.get("usage_count")) + 1
            current["last_used_at"] = timestamp
            templates[index] = current
            updated = current
            break

        if updated is not None:
            self.save_workspace_templates(templates)
        return updated

    def load_connection_filter_presets(self) -> List[Dict[str, Any]]:
        """加载连接树筛选预设。"""
        data = self._load_mapping(self.templates_config_path)
        self._secure_file(self.templates_config_path)
        return self._normalize_connection_filter_presets(
            self._extract_records(data, "connection_filter_presets")
        )

    def save_connection_filter_presets(self, presets: List[Dict[str, Any]]) -> None:
        """保存连接树筛选预设。"""
        data = self._load_mapping(self.templates_config_path)
        payload = {
            "version": self.TEMPLATES_CONFIG_VERSION,
            "templates": self._normalize_connection_templates(
                self._extract_records(data, "templates")
            ),
            "workspace_templates": self._normalize_workspace_templates(
                self._extract_records(data, "workspace_templates")
            ),
            "connection_filter_presets": self._normalize_connection_filter_presets(presets),
        }
        self._write_mapping(self.templates_config_path, payload)

    def export_connection_filter_presets(
        self,
        export_path: Union[str, Path],
        *,
        preset_ids: Optional[List[str]] = None,
        package_info: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """导出筛选预设到外部文件。"""
        path = Path(export_path)
        presets = self.load_connection_filter_presets()
        if preset_ids is not None:
            selected_ids = {
                str(preset_id).strip() for preset_id in preset_ids if str(preset_id).strip()
            }
            presets = [preset for preset in presets if str(preset.get("id") or "") in selected_ids]
        normalized_presets = self._normalize_connection_filter_presets(presets)
        exported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        payload = {
            "version": self.TEMPLATES_CONFIG_VERSION,
            "exported_at": exported_at,
            "package": self._build_share_package_metadata(
                "connection_filter_presets",
                len(normalized_presets),
                package_info=package_info,
                exported_at=exported_at,
            ),
            "connection_filter_presets": normalized_presets,
        }
        content_hash = self._build_share_package_content_hash("connection_filter_presets", payload)
        payload["package"]["content_hash"] = content_hash
        payload["package"].update(
            self._build_share_package_signature_metadata(
                str(payload["package"].get("source_app") or SHARE_PACKAGE_SOURCE_APP),
                content_hash,
                additional_signers=(
                    list(package_info.get("additional_signers") or [])
                    if isinstance(package_info, dict)
                    else None
                ),
            )
        )
        self._write_mapping(path, payload)
        return path

    def preview_connection_filter_preset_import(
        self,
        import_path: Union[str, Path],
    ) -> Dict[str, Any]:
        """预览筛选预设导入摘要。"""
        path = Path(import_path)
        payload = self._load_mapping(path)
        imported_presets = self._normalize_connection_filter_presets(
            self._extract_records(payload, "connection_filter_presets")
        )
        package = self._extract_share_package_metadata(
            payload,
            package_type="connection_filter_presets",
            item_count=len(imported_presets),
        )
        summary = self._build_named_record_import_summary(
            self.load_connection_filter_presets(),
            imported_presets,
            package=package,
        )
        summary["path"] = str(path)
        return summary

    def import_connection_filter_presets_with_summary(
        self,
        import_path: Union[str, Path],
        *,
        replace_existing: bool = False,
        conflict_strategy: str = "replace",
    ) -> Dict[str, Any]:
        """导入筛选预设并返回摘要。"""
        path = Path(import_path)
        payload = self._load_mapping(path)
        imported_presets = self._normalize_connection_filter_presets(
            self._extract_records(payload, "connection_filter_presets")
        )
        package = self._extract_share_package_metadata(
            payload,
            package_type="connection_filter_presets",
            item_count=len(imported_presets),
        )
        preview = self._build_named_record_import_summary(
            self.load_connection_filter_presets(),
            imported_presets,
            package=package,
        )

        if replace_existing:
            merged_presets = imported_presets
            stats = {
                "imported_count": len(imported_presets),
                "new_count": len(imported_presets),
                "replaced_count": 0,
                "renamed_count": 0,
                "skipped_count": 0,
                "conflict_count": 0,
            }
            effective_strategy = "replace_all"
        else:
            effective_strategy = self._normalize_import_conflict_strategy(conflict_strategy)
            existing_presets = self.load_connection_filter_presets()
            merged_presets, stats = self._merge_named_records_for_import(
                existing_presets,
                imported_presets,
                conflict_strategy=effective_strategy,
            )

        self.save_connection_filter_presets(merged_presets)
        presets = self.load_connection_filter_presets()
        return {
            "presets": presets,
            "package": package,
            "preview": preview,
            "path": str(path),
            "conflict_strategy": effective_strategy,
            **stats,
        }

    def import_connection_filter_presets(
        self,
        import_path: Union[str, Path],
        *,
        replace_existing: bool = False,
        conflict_strategy: str = "replace",
    ) -> List[Dict[str, Any]]:
        """从外部文件导入筛选预设。"""
        result = self.import_connection_filter_presets_with_summary(
            import_path,
            replace_existing=replace_existing,
            conflict_strategy=conflict_strategy,
        )
        return result["presets"]

    @staticmethod
    def _normalize_shared_library_package_type(package_type: Any) -> str:
        """规整共享中心包类型。"""
        normalized = str(package_type or "").strip().lower()
        if normalized in {"workspace_templates", "connection_filter_presets"}:
            return normalized
        raise ConfigurationError("不支持的共享包类型")

    def _shared_library_directory_for_type(self, package_type: str) -> Path:
        """返回指定共享包类型的目录。"""
        normalized = self._normalize_shared_library_package_type(package_type)
        if normalized == "workspace_templates":
            return self.shared_workspace_templates_dir
        return self.shared_connection_filter_presets_dir

    def _normalize_shared_library_records(
        self,
        records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """规整共享中心索引记录。"""
        normalized: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            file_path = str(record.get("file_path") or "").strip()
            package_type = str(record.get("package_type") or "").strip()
            if not file_path or not package_type:
                continue
            try:
                normalized_package_type = self._normalize_shared_library_package_type(package_type)
            except ConfigurationError:
                continue
            normalized.append(
                {
                    "id": str(record.get("id") or uuid4()),
                    "package_type": normalized_package_type,
                    "name": str(record.get("name") or "").strip() or "未命名共享包",
                    "description": str(record.get("description") or "").strip() or None,
                    "source_scope": str(record.get("source_scope") or "").strip() or None,
                    "source_app": str(record.get("source_app") or SHARE_PACKAGE_SOURCE_APP).strip()
                    or SHARE_PACKAGE_SOURCE_APP,
                    "source_version": str(
                        record.get("source_version") or SHARE_PACKAGE_SOURCE_VERSION
                    ).strip()
                    or SHARE_PACKAGE_SOURCE_VERSION,
                    "exported_by": str(record.get("exported_by") or "").strip() or None,
                    "exported_at": str(record.get("exported_at") or "").strip() or None,
                    "item_count": max(int(record.get("item_count") or 0), 0),
                    "labels": _normalize_share_labels(record.get("labels")),
                    "package_version": _normalize_package_version(record.get("package_version")),
                    "content_hash": str(record.get("content_hash") or "").strip() or None,
                    "signature_algorithm": str(record.get("signature_algorithm") or "").strip()
                    or None,
                    "signature_signer": str(record.get("signature_signer") or "").strip() or None,
                    "signature_public_key": str(record.get("signature_public_key") or "").strip()
                    or None,
                    "signature_fingerprint": str(record.get("signature_fingerprint") or "").strip()
                    or None,
                    "additional_signature_count": max(
                        int(record.get("additional_signature_count") or 0),
                        0,
                    ),
                    "sample_names": [
                        str(item).strip()
                        for item in (record.get("sample_names") or [])
                        if str(item).strip()
                    ][:10],
                    "file_path": file_path,
                    "relative_path": str(record.get("relative_path") or "").strip() or None,
                    "created_at": str(record.get("created_at") or "").strip() or None,
                    "updated_at": str(record.get("updated_at") or "").strip() or None,
                }
            )
        normalized.sort(
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        normalized.sort(key=lambda item: str(item.get("name") or "").casefold())
        return normalized

    def load_shared_library_records(
        self,
        package_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """加载共享中心记录。"""
        data = self._load_mapping(self.shared_library_config_path)
        self._secure_file(self.shared_library_config_path)
        records = self._normalize_shared_library_records(
            self._extract_records(data, "shared_packages")
        )
        if package_type is None:
            return records
        normalized_type = self._normalize_shared_library_package_type(package_type)
        return [record for record in records if record.get("package_type") == normalized_type]

    def save_shared_library_records(self, records: List[Dict[str, Any]]) -> None:
        """保存共享中心记录。"""
        payload = {
            "version": self.SHARED_LIBRARY_CONFIG_VERSION,
            "shared_packages": self._normalize_shared_library_records(records),
        }
        self._write_mapping(self.shared_library_config_path, payload)

    def _shared_library_record_from_package(
        self,
        package_type: str,
        file_path: Path,
        payload: Dict[str, Any],
        *,
        package_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """从共享包载荷提取索引记录。"""
        normalized_type = self._normalize_shared_library_package_type(package_type)
        record_key = (
            "workspace_templates"
            if normalized_type == "workspace_templates"
            else "connection_filter_presets"
        )
        package = self._extract_share_package_metadata(
            payload,
            package_type=normalized_type,
            item_count=len(self._extract_records(payload, record_key)),
        )
        content_hash = self._build_share_package_content_hash(normalized_type, payload)
        sample_names = [
            str(item.get("name") or "未命名项")
            for item in self._extract_records(payload, record_key)[:10]
            if isinstance(item, dict)
        ]
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return {
            "id": package_id or str(uuid4()),
            "package_type": normalized_type,
            "name": str(package.get("name") or file_path.stem).strip() or file_path.stem,
            "description": package.get("description"),
            "source_scope": package.get("source_scope"),
            "source_app": package.get("source_app") or SHARE_PACKAGE_SOURCE_APP,
            "source_version": package.get("source_version") or SHARE_PACKAGE_SOURCE_VERSION,
            "exported_by": package.get("exported_by"),
            "exported_at": package.get("exported_at"),
            "item_count": max(int(package.get("item_count") or 0), 0),
            "labels": _normalize_share_labels(package.get("labels")),
            "package_version": _normalize_package_version(package.get("package_version")),
            "content_hash": str(package.get("content_hash") or content_hash).strip()
            or content_hash,
            "signature_algorithm": str(package.get("signature_algorithm") or "").strip() or None,
            "signature_signer": str(package.get("signature_signer") or "").strip() or None,
            "signature_public_key": str(package.get("signature_public_key") or "").strip() or None,
            "signature_fingerprint": str(package.get("signature_fingerprint") or "").strip()
            or None,
            "additional_signature_count": len(
                _normalize_shared_library_additional_signatures(
                    package.get("additional_signatures")
                )
            ),
            "sample_names": sample_names,
            "file_path": str(file_path),
            "created_at": now,
            "updated_at": now,
        }

    def _publish_shared_library_package(
        self,
        package_type: str,
        package_name: str,
        export_callback: Any,
        *,
        package_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """将一个共享包发布到共享中心。"""
        normalized_type = self._normalize_shared_library_package_type(package_type)
        directory = self._shared_library_directory_for_type(normalized_type)
        existing_records = self.load_shared_library_records(package_type=normalized_type)
        all_records = self.load_shared_library_records()
        effective_package_info = dict(package_info or {})
        normalized_name = (
            str(effective_package_info.get("name") or package_name).strip() or package_name
        )
        if not effective_package_info.get("package_version"):
            history_versions = [
                _normalize_package_version(record.get("package_version"))
                for record in existing_records
                if str(record.get("name") or "").strip().casefold() == normalized_name.casefold()
            ]
            effective_package_info["package_version"] = (
                (max(history_versions) + 1) if history_versions else 1
            )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-{_slugify_filename(package_name, normalized_type)}.yaml"
        file_path = self._make_unique_file_path(directory / filename)
        export_callback(file_path, package_info=effective_package_info)
        payload = self._load_mapping(file_path)
        record = self._shared_library_record_from_package(normalized_type, file_path, payload)
        all_records.append(record)
        self.save_shared_library_records(all_records)
        return record

    def publish_workspace_template_to_shared_library(
        self,
        template_id: str,
        *,
        package_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发布一个工作区模板到共享中心。"""
        template = next(
            (item for item in self.load_workspace_templates() if item.get("id") == template_id),
            None,
        )
        if template is None:
            raise ConfigurationError("未找到工作区模板")
        package_name = (
            str(template.get("name") or "workspace-template").strip() or "workspace-template"
        )
        effective_package_info = {
            "name": package_name,
            **dict(package_info or {}),
        }
        return self._publish_shared_library_package(
            "workspace_templates",
            package_name,
            lambda file_path, package_info=None: self.export_workspace_templates(
                file_path,
                template_ids=[str(template.get("id") or "")],
                package_info=package_info,
            ),
            package_info=effective_package_info,
        )

    def publish_connection_filter_preset_to_shared_library(
        self,
        preset_id: str,
        *,
        package_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发布一个筛选预设到共享中心。"""
        preset = next(
            (item for item in self.load_connection_filter_presets() if item.get("id") == preset_id),
            None,
        )
        if preset is None:
            raise ConfigurationError("未找到筛选预设")
        package_name = str(preset.get("name") or "filter-preset").strip() or "filter-preset"
        effective_package_info = {
            "name": package_name,
            **dict(package_info or {}),
        }
        return self._publish_shared_library_package(
            "connection_filter_presets",
            package_name,
            lambda file_path, package_info=None: self.export_connection_filter_presets(
                file_path,
                preset_ids=[str(preset.get("id") or "")],
                package_info=package_info,
            ),
            package_info=effective_package_info,
        )

    def get_shared_library_record(
        self,
        record_id: str,
        *,
        package_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """按 ID 获取共享中心记录。"""
        records = self.load_shared_library_records(package_type=package_type)
        return next((record for record in records if record.get("id") == record_id), None)

    def preview_shared_library_import(self, record_id: str) -> Dict[str, Any]:
        """预览共享中心包导入摘要。"""
        record = self.get_shared_library_record(record_id)
        if record is None:
            raise ConfigurationError("未找到共享包")
        file_path = Path(str(record.get("file_path") or ""))
        if not file_path.exists():
            raise ConfigurationError("共享包文件不存在")
        if record.get("package_type") == "workspace_templates":
            summary = self.preview_workspace_template_import(file_path)
        else:
            summary = self.preview_connection_filter_preset_import(file_path)
        summary["shared_record"] = dict(record)
        return summary

    def import_from_shared_library(
        self,
        record_id: str,
        *,
        conflict_strategy: str = "replace",
    ) -> Dict[str, Any]:
        """从共享中心导入一个共享包。"""
        record = self.get_shared_library_record(record_id)
        if record is None:
            raise ConfigurationError("未找到共享包")
        file_path = Path(str(record.get("file_path") or ""))
        if not file_path.exists():
            raise ConfigurationError("共享包文件不存在")
        if record.get("package_type") == "workspace_templates":
            result = self.import_workspace_templates_with_summary(
                file_path,
                conflict_strategy=conflict_strategy,
            )
        else:
            result = self.import_connection_filter_presets_with_summary(
                file_path,
                conflict_strategy=conflict_strategy,
            )
        result["shared_record"] = dict(record)
        return result

    def remove_shared_library_record(
        self,
        record_id: str,
        *,
        remove_file: bool = True,
    ) -> None:
        """从共享中心移除一个共享包记录。"""
        records = self.load_shared_library_records()
        remaining: List[Dict[str, Any]] = []
        target_record: Optional[Dict[str, Any]] = None
        for record in records:
            if record.get("id") == record_id and target_record is None:
                target_record = record
                continue
            remaining.append(record)
        if target_record is None:
            raise ConfigurationError("未找到共享包")
        self.save_shared_library_records(remaining)
        if remove_file:
            file_path = Path(str(target_record.get("file_path") or ""))
            if file_path.exists():
                file_path.unlink()

    @staticmethod
    def _shared_library_identity_key(record: Dict[str, Any]) -> tuple[str, str]:
        """返回共享包的弱身份键，用于版本对比。"""
        return (
            str(record.get("package_type") or "").strip(),
            str(record.get("name") or "").strip().casefold(),
        )

    @staticmethod
    def _shared_library_record_signature(record: Dict[str, Any]) -> tuple[str, str, int, str, str]:
        """生成共享包记录的稳定签名，用于同步去重。"""
        return (
            str(record.get("package_type") or "").strip(),
            str(record.get("name") or "").strip(),
            _normalize_package_version(record.get("package_version")),
            str(record.get("content_hash") or "").strip(),
            str(record.get("exported_at") or "").strip(),
        )

    def _normalize_shared_library_sync_history(
        self,
        records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """规整共享同步历史记录。"""
        normalized: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            action = str(record.get("action") or "").strip().lower()
            if action not in {"push", "pull"}:
                continue
            conflicts: List[Dict[str, Any]] = []
            for conflict in record.get("conflicts") or []:
                if not isinstance(conflict, dict):
                    continue
                conflicts.append(
                    {
                        "name": str(conflict.get("name") or "").strip() or "未命名共享包",
                        "package_type": str(conflict.get("package_type") or "").strip() or None,
                        "status": str(conflict.get("status") or "").strip() or None,
                        "local_version": _normalize_package_version(conflict.get("local_version")),
                        "external_version": _normalize_package_version(
                            conflict.get("external_version")
                        ),
                    }
                )

            normalized.append(
                {
                    "id": str(record.get("id") or uuid4()),
                    "action": action,
                    "sync_dir": str(record.get("sync_dir") or "").strip(),
                    "recorded_at": str(record.get("recorded_at") or "").strip() or None,
                    "record_count": max(int(record.get("record_count") or 0), 0),
                    "new_count": max(int(record.get("new_count") or 0), 0),
                    "exact_match_count": max(int(record.get("exact_match_count") or 0), 0),
                    "conflict_count": max(int(record.get("conflict_count") or 0), 0),
                    "newer_local_count": max(int(record.get("newer_local_count") or 0), 0),
                    "older_local_count": max(int(record.get("older_local_count") or 0), 0),
                    "newer_external_count": max(int(record.get("newer_external_count") or 0), 0),
                    "older_external_count": max(int(record.get("older_external_count") or 0), 0),
                    "created_count": max(int(record.get("created_count") or 0), 0),
                    "updated_count": max(int(record.get("updated_count") or 0), 0),
                    "pushed_count": max(int(record.get("pushed_count") or 0), 0),
                    "imported_count": max(int(record.get("imported_count") or 0), 0),
                    "skipped_count": max(int(record.get("skipped_count") or 0), 0),
                    "untrusted_count": max(int(record.get("untrusted_count") or 0), 0),
                    "integrity_blocked_count": max(
                        int(record.get("integrity_blocked_count") or 0), 0
                    ),
                    "integrity_unverified_count": max(
                        int(record.get("integrity_unverified_count") or 0), 0
                    ),
                    "signature_blocked_count": max(
                        int(record.get("signature_blocked_count") or 0), 0
                    ),
                    "signature_unverified_count": max(
                        int(record.get("signature_unverified_count") or 0), 0
                    ),
                    "revoked_signer_count": max(int(record.get("revoked_signer_count") or 0), 0),
                    "expired_signer_policy_count": max(
                        int(record.get("expired_signer_policy_count") or 0), 0
                    ),
                    "rotation_due_count": max(int(record.get("rotation_due_count") or 0), 0),
                    "rotation_overdue_count": max(
                        int(record.get("rotation_overdue_count") or 0), 0
                    ),
                    "rotation_warning_count": max(
                        int(record.get("rotation_warning_count") or 0), 0
                    ),
                    "rotation_exception_count": max(
                        int(record.get("rotation_exception_count") or 0), 0
                    ),
                    "blocked_package_type_count": max(
                        int(record.get("blocked_package_type_count") or 0), 0
                    ),
                    "untrusted_signer_count": max(
                        int(record.get("untrusted_signer_count") or 0), 0
                    ),
                    "approval_required_count": max(
                        int(record.get("approval_required_count") or 0), 0
                    ),
                    "approved_override_count": max(
                        int(record.get("approved_override_count") or 0), 0
                    ),
                    "skipped_missing": max(int(record.get("skipped_missing") or 0), 0),
                    "index_version": max(int(record.get("index_version") or 0), 0),
                    "conflicts": conflicts[:10],
                }
            )

        normalized.sort(key=lambda item: str(item.get("recorded_at") or ""), reverse=True)
        return normalized[:SHARED_LIBRARY_SYNC_HISTORY_LIMIT]

    def _normalize_shared_library_governance_audit_records(
        self,
        records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """规整共享治理审计记录。"""
        normalized: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            event_kind = str(record.get("event_kind") or "").strip().lower()
            if not event_kind:
                continue
            detail_lines = [
                str(item).strip()
                for item in (record.get("detail_lines") or [])
                if str(item).strip()
            ]
            normalized.append(
                {
                    "id": str(record.get("id") or uuid4()),
                    "recorded_at": str(record.get("recorded_at") or "").strip() or None,
                    "actor": str(record.get("actor") or "").strip() or None,
                    "event_kind": event_kind,
                    "target_type": str(record.get("target_type") or "").strip() or None,
                    "target_value": str(record.get("target_value") or "").strip() or None,
                    "target_label": str(record.get("target_label") or "").strip() or None,
                    "summary": str(record.get("summary") or "").strip() or None,
                    "decision": str(record.get("decision") or "").strip() or None,
                    "detail_lines": detail_lines[:12],
                }
            )
        normalized.sort(key=lambda item: str(item.get("recorded_at") or ""), reverse=True)
        return normalized[:SHARED_LIBRARY_GOVERNANCE_AUDIT_LIMIT]

    def load_shared_library_governance_audit_records(self) -> List[Dict[str, Any]]:
        """加载共享治理审计记录。"""
        data = self._load_mapping(self.shared_library_governance_audit_config_path)
        self._secure_file(self.shared_library_governance_audit_config_path)
        return self._normalize_shared_library_governance_audit_records(
            self._extract_records(data, "audits")
        )

    def save_shared_library_governance_audit_records(self, records: List[Dict[str, Any]]) -> None:
        """保存共享治理审计记录。"""
        payload = {
            "version": SHARED_LIBRARY_GOVERNANCE_AUDIT_CONFIG_VERSION,
            "audits": self._normalize_shared_library_governance_audit_records(records),
        }
        self._write_mapping(self.shared_library_governance_audit_config_path, payload)

    def _default_shared_library_governance_actor(self) -> str:
        """返回默认治理操作者标识。"""
        actor = str(os.getenv("NEKO_SHELL_AUDIT_ACTOR") or "").strip()
        if actor:
            return actor
        username = str(
            os.getenv("USER") or os.getenv("USERNAME") or os.getenv("LOGNAME") or "unknown"
        ).strip()
        hostname = str(socket.gethostname() or "localhost").strip()
        return f"{username}@{hostname}"

    def append_shared_library_governance_audit_event(
        self,
        *,
        event_kind: str,
        target_type: str,
        target_value: Optional[str] = None,
        target_label: Optional[str] = None,
        summary: Optional[str] = None,
        decision: Optional[str] = None,
        detail_lines: Optional[List[str]] = None,
        actor: Optional[str] = None,
        recorded_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """追加一条共享治理审计事件。"""
        records = self.load_shared_library_governance_audit_records()
        entry = {
            "id": str(uuid4()),
            "recorded_at": str(recorded_at or "").strip()
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "actor": str(actor or self._default_shared_library_governance_actor()).strip() or None,
            "event_kind": str(event_kind or "").strip().lower(),
            "target_type": str(target_type or "").strip() or None,
            "target_value": str(target_value or "").strip() or None,
            "target_label": str(target_label or "").strip() or None,
            "summary": str(summary or "").strip() or None,
            "decision": str(decision or "").strip() or None,
            "detail_lines": [
                str(item).strip() for item in (detail_lines or []) if str(item).strip()
            ],
        }
        records.insert(0, entry)
        self.save_shared_library_governance_audit_records(records)
        return self.load_shared_library_governance_audit_records()[0]

    def load_shared_library_sync_history(self) -> List[Dict[str, Any]]:
        """加载共享中心同步历史。"""
        data = self._load_mapping(self.shared_library_history_config_path)
        self._secure_file(self.shared_library_history_config_path)
        return self._normalize_shared_library_sync_history(self._extract_records(data, "history"))

    def save_shared_library_sync_history(self, records: List[Dict[str, Any]]) -> None:
        """保存共享中心同步历史。"""
        payload = {
            "version": self.SHARED_LIBRARY_HISTORY_CONFIG_VERSION,
            "history": self._normalize_shared_library_sync_history(records),
        }
        self._write_mapping(self.shared_library_history_config_path, payload)

    def append_shared_library_sync_history(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """追加一条共享中心同步历史。"""
        history = self.load_shared_library_sync_history()
        entry = {
            **dict(record),
            "id": str(record.get("id") or uuid4()),
            "recorded_at": str(record.get("recorded_at") or "").strip()
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        history.insert(0, entry)
        self.save_shared_library_sync_history(history)
        return self.load_shared_library_sync_history()[0]

    @staticmethod
    def _shared_library_approval_identity_key(
        record: Dict[str, Any],
    ) -> tuple[str, str, str, str, int]:
        """返回共享包审批记录的稳定身份键。"""
        content_hash = str(record.get("content_hash") or "").strip()
        package_type = str(record.get("package_type") or "").strip().lower()
        source_app = str(record.get("source_app") or "").strip().casefold()
        name = str(record.get("name") or "").strip().casefold()
        version = _normalize_package_version(record.get("package_version"))
        return (content_hash, package_type, source_app, name, version)

    def _normalize_shared_library_approval_records(
        self,
        records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """规整共享包审批记录。"""
        normalized: List[Dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, int]] = set()
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                package_type = self._normalize_shared_library_package_type(
                    record.get("package_type")
                )
            except ConfigurationError:
                continue
            name = str(record.get("name") or "").strip() or "未命名共享包"
            source_app = str(record.get("source_app") or SHARE_PACKAGE_SOURCE_APP).strip()
            content_hash = str(record.get("content_hash") or "").strip()
            package_version = _normalize_package_version(record.get("package_version"))
            identity = (
                content_hash,
                package_type,
                source_app.casefold(),
                name.casefold(),
                package_version,
            )
            if identity in seen:
                continue
            seen.add(identity)
            reasons = _normalize_command_list(record.get("reasons"))
            decision = _normalize_shared_library_approval_decision(record.get("decision"))
            decided_at = str(record.get("decided_at") or "").strip() or None
            if decision == "pending":
                decided_at = None
            signature_fingerprint = _normalize_shared_library_signer_fingerprint(
                record.get("signature_fingerprint")
            )
            normalized.append(
                {
                    "id": str(record.get("id") or uuid4()),
                    "content_hash": content_hash,
                    "package_type": package_type,
                    "source_app": source_app or SHARE_PACKAGE_SOURCE_APP,
                    "name": name,
                    "package_version": package_version,
                    "sync_dir": str(record.get("sync_dir") or "").strip() or None,
                    "reasons": reasons,
                    "signature_signer": str(record.get("signature_signer") or "").strip() or None,
                    "signature_fingerprint": signature_fingerprint,
                    **self._shared_library_signer_context(signature_fingerprint),
                    "matched_team_approval_rules": _normalize_shared_library_team_approval_rule_matches(
                        record.get("matched_team_approval_rules")
                    ),
                    "matched_team_approval_levels": _normalize_shared_library_team_approval_rule_matches(
                        record.get("matched_team_approval_levels")
                    ),
                    "required_signature_count": max(
                        int(record.get("required_signature_count") or 0),
                        0,
                    ),
                    "verified_signature_count": max(
                        int(record.get("verified_signature_count") or 0),
                        0,
                    ),
                    "decision": decision,
                    "requested_at": str(record.get("requested_at") or "").strip()
                    or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "decided_at": decided_at,
                }
            )

        decision_order = {"pending": 0, "approved": 1, "rejected": 2}
        normalized.sort(
            key=lambda item: (
                decision_order.get(str(item.get("decision") or "pending"), 9),
                str(item.get("decided_at") or item.get("requested_at") or ""),
            ),
            reverse=False,
        )
        normalized.sort(
            key=lambda item: str(item.get("decided_at") or item.get("requested_at") or ""),
            reverse=True,
        )
        normalized.sort(
            key=lambda item: decision_order.get(str(item.get("decision") or "pending"), 9)
        )
        return normalized

    def load_shared_library_approval_records(self) -> List[Dict[str, Any]]:
        """加载共享包审批记录。"""
        data = self._load_mapping(self.shared_library_approval_config_path)
        self._secure_file(self.shared_library_approval_config_path)
        return self._normalize_shared_library_approval_records(
            self._extract_records(data, "approvals")
        )

    def save_shared_library_approval_records(self, records: List[Dict[str, Any]]) -> None:
        """保存共享包审批记录。"""
        payload = {
            "version": self.SHARED_LIBRARY_APPROVALS_CONFIG_VERSION,
            "approvals": self._normalize_shared_library_approval_records(records),
        }
        self._write_mapping(self.shared_library_approval_config_path, payload)

    def get_shared_library_approval_record(
        self,
        record: Dict[str, Any],
        *,
        approval_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """查找共享包对应的审批记录。"""
        records = (
            approval_records
            if approval_records is not None
            else self.load_shared_library_approval_records()
        )
        identity = self._shared_library_approval_identity_key(record)
        for approval in records:
            if self._shared_library_approval_identity_key(approval) == identity:
                return dict(approval)
        return None

    def upsert_shared_library_approval_decision(
        self,
        record: Dict[str, Any],
        *,
        decision: str,
        sync_dir: Optional[Union[str, Path]] = None,
        reasons: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """写入或更新共享包审批决策。"""
        normalized_decision = _normalize_shared_library_approval_decision(decision)
        approvals = self.load_shared_library_approval_records()
        identity = self._shared_library_approval_identity_key(record)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        merged_reasons = _normalize_command_list(reasons or record.get("reasons"))
        updated: Optional[Dict[str, Any]] = None
        for index, approval in enumerate(approvals):
            if self._shared_library_approval_identity_key(approval) != identity:
                continue
            updated = {
                **approval,
                "sync_dir": str(sync_dir or approval.get("sync_dir") or "").strip() or None,
                "reasons": merged_reasons or list(approval.get("reasons") or []),
                "signature_signer": str(
                    record.get("signature_signer") or approval.get("signature_signer") or ""
                ).strip()
                or None,
                "signature_fingerprint": _normalize_shared_library_signer_fingerprint(
                    record.get("signature_fingerprint") or approval.get("signature_fingerprint")
                ),
                "matched_team_approval_rules": _normalize_shared_library_team_approval_rule_matches(
                    list(approval.get("matched_team_approval_rules") or [])
                    + list(record.get("matched_team_approval_rules") or [])
                ),
                "matched_team_approval_levels": _normalize_shared_library_team_approval_rule_matches(
                    list(approval.get("matched_team_approval_levels") or [])
                    + list(record.get("matched_team_approval_levels") or [])
                ),
                "required_signature_count": max(
                    int(approval.get("required_signature_count") or 0),
                    int(record.get("required_signature_count") or 0),
                ),
                "verified_signature_count": max(
                    int(approval.get("verified_signature_count") or 0),
                    int(record.get("verified_signature_count") or 0),
                ),
                "decision": normalized_decision,
                "decided_at": now if normalized_decision != "pending" else None,
            }
            approvals[index] = updated
            break

        if updated is None:
            updated = {
                "id": str(uuid4()),
                "content_hash": str(record.get("content_hash") or "").strip(),
                "package_type": self._normalize_shared_library_package_type(
                    record.get("package_type")
                ),
                "source_app": str(record.get("source_app") or SHARE_PACKAGE_SOURCE_APP).strip()
                or SHARE_PACKAGE_SOURCE_APP,
                "name": str(record.get("name") or "").strip() or "未命名共享包",
                "package_version": _normalize_package_version(record.get("package_version")),
                "sync_dir": str(sync_dir or "").strip() or None,
                "reasons": merged_reasons,
                "signature_signer": str(record.get("signature_signer") or "").strip() or None,
                "signature_fingerprint": _normalize_shared_library_signer_fingerprint(
                    record.get("signature_fingerprint")
                ),
                "matched_team_approval_rules": _normalize_shared_library_team_approval_rule_matches(
                    record.get("matched_team_approval_rules")
                ),
                "matched_team_approval_levels": _normalize_shared_library_team_approval_rule_matches(
                    record.get("matched_team_approval_levels")
                ),
                "required_signature_count": max(
                    int(record.get("required_signature_count") or 0), 0
                ),
                "verified_signature_count": max(
                    int(record.get("verified_signature_count") or 0), 0
                ),
                "decision": normalized_decision,
                "requested_at": now,
                "decided_at": now if normalized_decision != "pending" else None,
            }
            approvals.append(updated)

        self.save_shared_library_approval_records(approvals)
        self.append_shared_library_governance_audit_event(
            event_kind="approval_decision",
            target_type="approval",
            target_value=str(updated.get("id") or "").strip() or None,
            target_label=str(updated.get("name") or "").strip() or "未命名共享包",
            summary=(
                f"审批{_normalize_shared_library_approval_decision(decision)}: "
                f"{updated.get('name') or '未命名共享包'}"
            ),
            decision=normalized_decision,
            detail_lines=[
                f"包类型: {str(updated.get('package_type') or '').strip() or '未知'}",
                f"来源应用: {str(updated.get('source_app') or '').strip() or SHARE_PACKAGE_SOURCE_APP}",
                f"签名者: {str(updated.get('signature_signer') or '').strip() or '未知'}",
                (
                    f"签名指纹: {str(updated.get('signature_fingerprint') or '').strip()}"
                    if str(updated.get("signature_fingerprint") or "").strip()
                    else ""
                ),
                (
                    "原因: "
                    + ", ".join(
                        [
                            str(reason).strip()
                            for reason in updated.get("reasons") or []
                            if str(reason).strip()
                        ]
                    )
                    if any(str(reason).strip() for reason in updated.get("reasons") or [])
                    else ""
                ),
            ],
        )
        current = self.get_shared_library_approval_record(updated)
        return current or updated

    def queue_shared_library_approval_records(
        self,
        sync_dir: Union[str, Path],
        records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """将共享包加入本地待审队列，不覆盖已有审批结论。"""
        approvals = self.load_shared_library_approval_records()
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        updated = False
        queued_records: List[Dict[str, Any]] = []

        for record in records:
            identity = self._shared_library_approval_identity_key(record)
            reasons = _normalize_command_list(record.get("reasons"))
            matched = False
            for index, approval in enumerate(approvals):
                if self._shared_library_approval_identity_key(approval) != identity:
                    continue
                matched = True
                merged_reasons = _normalize_command_list(
                    list(approval.get("reasons") or []) + reasons
                )
                next_record = {
                    **approval,
                    "sync_dir": str(sync_dir or approval.get("sync_dir") or "").strip() or None,
                    "reasons": merged_reasons,
                    "signature_signer": str(
                        record.get("signature_signer") or approval.get("signature_signer") or ""
                    ).strip()
                    or None,
                    "signature_fingerprint": _normalize_shared_library_signer_fingerprint(
                        record.get("signature_fingerprint") or approval.get("signature_fingerprint")
                    ),
                    "matched_team_approval_rules": _normalize_shared_library_team_approval_rule_matches(
                        list(approval.get("matched_team_approval_rules") or [])
                        + list(record.get("matched_team_approval_rules") or [])
                    ),
                    "matched_team_approval_levels": _normalize_shared_library_team_approval_rule_matches(
                        list(approval.get("matched_team_approval_levels") or [])
                        + list(record.get("matched_team_approval_levels") or [])
                    ),
                    "required_signature_count": max(
                        int(approval.get("required_signature_count") or 0),
                        int(record.get("required_signature_count") or 0),
                    ),
                    "verified_signature_count": max(
                        int(approval.get("verified_signature_count") or 0),
                        int(record.get("verified_signature_count") or 0),
                    ),
                }
                if approval.get("decision") == "pending":
                    next_record["requested_at"] = now
                approvals[index] = next_record
                queued_records.append(next_record)
                updated = True
                break

            if matched:
                continue

            queued_record = {
                "id": str(uuid4()),
                "content_hash": str(record.get("content_hash") or "").strip(),
                "package_type": self._normalize_shared_library_package_type(
                    record.get("package_type")
                ),
                "source_app": str(record.get("source_app") or SHARE_PACKAGE_SOURCE_APP).strip()
                or SHARE_PACKAGE_SOURCE_APP,
                "name": str(record.get("name") or "").strip() or "未命名共享包",
                "package_version": _normalize_package_version(record.get("package_version")),
                "sync_dir": str(sync_dir or "").strip() or None,
                "reasons": reasons,
                "signature_signer": str(record.get("signature_signer") or "").strip() or None,
                "signature_fingerprint": _normalize_shared_library_signer_fingerprint(
                    record.get("signature_fingerprint")
                ),
                "matched_team_approval_rules": _normalize_shared_library_team_approval_rule_matches(
                    record.get("matched_team_approval_rules")
                ),
                "matched_team_approval_levels": _normalize_shared_library_team_approval_rule_matches(
                    record.get("matched_team_approval_levels")
                ),
                "required_signature_count": max(
                    int(record.get("required_signature_count") or 0), 0
                ),
                "verified_signature_count": max(
                    int(record.get("verified_signature_count") or 0), 0
                ),
                "decision": "pending",
                "requested_at": now,
                "decided_at": None,
            }
            approvals.append(queued_record)
            queued_records.append(queued_record)
            updated = True

        if updated:
            self.save_shared_library_approval_records(approvals)
        return self._normalize_shared_library_approval_records(queued_records)

    @staticmethod
    def _normalize_shared_library_sync_dir_key(sync_dir: Union[str, Path]) -> str:
        """将共享仓库目录转换为稳定缓存键。"""
        try:
            return str(Path(sync_dir).expanduser().resolve())
        except Exception:
            return str(Path(sync_dir))

    def get_shared_library_cached_index_version(self, sync_dir: Union[str, Path]) -> int:
        """返回共享仓库已缓存的索引版本。"""
        cache_key = self._normalize_shared_library_sync_dir_key(sync_dir)
        cache = dict(self.app_config.shared_library_index_cache or {})
        return max(int(cache.get(cache_key) or 0), 0)

    def update_shared_library_cached_index_version(
        self,
        sync_dir: Union[str, Path],
        index_version: int,
    ) -> None:
        """更新共享仓库已缓存的索引版本。"""
        config = self.app_config
        cache = dict(config.shared_library_index_cache or {})
        cache_key = self._normalize_shared_library_sync_dir_key(sync_dir)
        cache[cache_key] = max(int(index_version or 0), 0)
        config.shared_library_index_cache = _normalize_shared_library_index_cache(cache)
        self.save_app_config(config)

    def trust_shared_library_source_app(self, source_app: str) -> List[str]:
        """将来源应用加入自动拉取信任列表。"""
        normalized_source = str(source_app or "").strip()
        if not normalized_source:
            raise ConfigurationError("来源应用不能为空")
        config = self.app_config
        trusted_sources = list(config.shared_library_trusted_source_apps or [])
        trusted_sources.append(normalized_source)
        config.shared_library_trusted_source_apps = _normalize_shared_library_trusted_sources(
            trusted_sources
        )
        self.save_app_config(config)
        self.append_shared_library_governance_audit_event(
            event_kind="trust_source",
            target_type="source_app",
            target_value=normalized_source,
            target_label=normalized_source,
            summary=f"信任来源应用 {normalized_source}",
            detail_lines=[
                "策略变更: 自动拉取来源信任",
                f"当前受信任来源数: {len(config.shared_library_trusted_source_apps or [])}",
            ],
        )
        return list(config.shared_library_trusted_source_apps)

    def trust_shared_library_signer_fingerprint(self, fingerprint: str) -> List[str]:
        """将签名指纹加入自动拉取信任列表。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            raise ConfigurationError("签名指纹不能为空或格式无效")
        config = self.app_config
        trusted_fingerprints = list(config.shared_library_trusted_signer_fingerprints or [])
        trusted_fingerprints.append(normalized_fingerprint)
        config.shared_library_trusted_signer_fingerprints = (
            _normalize_shared_library_trusted_signer_fingerprints(trusted_fingerprints)
        )
        config.shared_library_revoked_signer_fingerprints = (
            _subtract_shared_library_signer_fingerprints(
                config.shared_library_revoked_signer_fingerprints,
                [normalized_fingerprint],
            )
        )
        config.shared_library_revoked_signer_records = [
            record
            for record in config.shared_library_revoked_signer_records or []
            if str(record.get("fingerprint") or "").strip() != normalized_fingerprint
        ]
        self.save_app_config(config)
        signer_context = self._shared_library_signer_context(normalized_fingerprint)
        self.append_shared_library_governance_audit_event(
            event_kind="trust_signer",
            target_type="signer",
            target_value=normalized_fingerprint,
            target_label=str(signer_context.get("signer_display_name") or "").strip()
            or normalized_fingerprint,
            summary=f"信任签名者 {normalized_fingerprint[:12]}",
            detail_lines=[
                (
                    f"签名者别名: {signer_context.get('signer_display_name')}"
                    if signer_context.get("signer_display_name")
                    else ""
                ),
                (
                    f"签名分组: {signer_context.get('signer_group_label')}"
                    if signer_context.get("signer_group_label")
                    else ""
                ),
                f"当前受信任签名者数: {len(config.shared_library_trusted_signer_fingerprints or [])}",
            ],
        )
        return list(config.shared_library_trusted_signer_fingerprints)

    def revoke_shared_library_signer_fingerprint(
        self,
        fingerprint: str,
        *,
        reason: Optional[str] = None,
        note: Optional[str] = None,
        revoked_at: Optional[str] = None,
    ) -> List[str]:
        """将签名指纹加入撤销列表，并从信任列表中移除。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            raise ConfigurationError("签名指纹不能为空或格式无效")
        config = self.app_config
        revoked_fingerprints = list(config.shared_library_revoked_signer_fingerprints or [])
        revoked_fingerprints.append(normalized_fingerprint)
        config.shared_library_revoked_signer_fingerprints = (
            _normalize_shared_library_trusted_signer_fingerprints(revoked_fingerprints)
        )
        config.shared_library_trusted_signer_fingerprints = (
            _subtract_shared_library_signer_fingerprints(
                config.shared_library_trusted_signer_fingerprints,
                [normalized_fingerprint],
            )
        )
        normalized_revoked_at = (
            str(revoked_at or "").strip()
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        updated_record = {
            "fingerprint": normalized_fingerprint,
            "reason": str(reason or "").strip() or None,
            "note": str(note or "").strip() or None,
            "revoked_at": normalized_revoked_at,
        }
        remaining_records = [
            record
            for record in config.shared_library_revoked_signer_records or []
            if str(record.get("fingerprint") or "").strip() != normalized_fingerprint
        ]
        remaining_records.append(updated_record)
        config.shared_library_revoked_signer_records = remaining_records
        self.save_app_config(config)
        signer_context = self._shared_library_signer_context(normalized_fingerprint)
        self.append_shared_library_governance_audit_event(
            event_kind="revoke_signer",
            target_type="signer",
            target_value=normalized_fingerprint,
            target_label=str(signer_context.get("signer_display_name") or "").strip()
            or normalized_fingerprint,
            summary=f"撤销签名者 {normalized_fingerprint[:12]}",
            detail_lines=[
                (
                    f"签名者别名: {signer_context.get('signer_display_name')}"
                    if signer_context.get("signer_display_name")
                    else ""
                ),
                (
                    f"签名分组: {signer_context.get('signer_group_label')}"
                    if signer_context.get("signer_group_label")
                    else ""
                ),
                f"撤销原因: {updated_record['reason']}" if updated_record.get("reason") else "",
                f"撤销备注: {updated_record['note']}" if updated_record.get("note") else "",
                (
                    f"撤销时间: {updated_record['revoked_at']}"
                    if updated_record.get("revoked_at")
                    else ""
                ),
            ],
        )
        return list(config.shared_library_revoked_signer_fingerprints)

    def get_shared_library_signer_profile(self, fingerprint: str) -> Dict[str, Optional[str]]:
        """获取签名者资料。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            return {}
        return dict(
            (self.app_config.shared_library_signer_profiles or {}).get(normalized_fingerprint) or {}
        )

    def upsert_shared_library_signer_profile(
        self,
        fingerprint: str,
        *,
        display_name: Optional[str] = None,
        note: Optional[str] = None,
        expires_at: Optional[str] = None,
        rotate_before_at: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """新增或更新签名者资料。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            raise ConfigurationError("签名指纹不能为空或格式无效")
        config = self.app_config
        profiles = dict(config.shared_library_signer_profiles or {})
        existing = dict(profiles.get(normalized_fingerprint) or {})
        profile = {
            "fingerprint": normalized_fingerprint,
            "display_name": str(display_name or existing.get("display_name") or "").strip() or None,
            "note": str(note or existing.get("note") or "").strip() or None,
            "expires_at": str(expires_at or existing.get("expires_at") or "").strip() or None,
            "rotate_before_at": str(
                rotate_before_at or existing.get("rotate_before_at") or ""
            ).strip()
            or None,
        }
        profiles[normalized_fingerprint] = profile
        config.shared_library_signer_profiles = profiles
        self.save_app_config(config)
        self.append_shared_library_governance_audit_event(
            event_kind="update_signer_profile",
            target_type="signer_profile",
            target_value=normalized_fingerprint,
            target_label=str(profile.get("display_name") or "").strip() or normalized_fingerprint,
            summary=f"更新签名者资料 {normalized_fingerprint[:12]}",
            detail_lines=[
                f"签名者别名: {profile['display_name']}" if profile.get("display_name") else "",
                f"签名备注: {profile['note']}" if profile.get("note") else "",
                f"策略有效期: {profile['expires_at']}" if profile.get("expires_at") else "",
                (
                    f"轮换截止: {profile['rotate_before_at']}"
                    if profile.get("rotate_before_at")
                    else ""
                ),
            ],
        )
        return dict(profile)

    def get_shared_library_rotation_exception_record(
        self,
        fingerprint: str,
        *,
        package_type: Optional[str] = None,
        rotation_status: Optional[str] = None,
        include_expired: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """获取指定签名者命中的轮换例外授权。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            return None
        normalized_package_type = (
            self._normalize_shared_library_package_type(package_type)
            if package_type is not None
            else None
        )
        normalized_rotation_status = (
            str(rotation_status or "").strip().lower() if rotation_status is not None else None
        )
        current = datetime.now(timezone.utc)
        for record in self.app_config.shared_library_rotation_exception_records or []:
            candidate = dict(record)
            if (
                _normalize_shared_library_signer_fingerprint(candidate.get("fingerprint"))
                != normalized_fingerprint
            ):
                continue
            package_types = _normalize_shared_library_package_types(
                candidate.get("package_types"),
                allow_empty=True,
            )
            if (
                normalized_package_type is not None
                and package_types
                and (normalized_package_type not in package_types)
            ):
                continue
            rotation_states = _normalize_shared_library_rotation_exception_states(
                candidate.get("rotation_states"),
                allow_empty=True,
            )
            if (
                normalized_rotation_status is not None
                and rotation_states
                and (normalized_rotation_status not in rotation_states)
            ):
                continue
            status = _shared_library_rotation_exception_status(
                candidate.get("expires_at"),
                now=current,
            )
            candidate["status"] = status
            if not include_expired and status != "active":
                continue
            return candidate
        return None

    def upsert_shared_library_rotation_exception_record(
        self,
        fingerprint: str,
        *,
        package_types: Optional[List[str]] = None,
        rotation_states: Optional[List[str]] = None,
        expires_at: Optional[str] = None,
        note: Optional[str] = None,
        source_approval_id: Optional[str] = None,
        source_approval_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """新增或更新轮换例外授权。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            raise ConfigurationError("签名指纹不能为空或格式无效")
        normalized_package_types = _normalize_shared_library_package_types(
            package_types,
            allow_empty=True,
        )
        normalized_rotation_states = _normalize_shared_library_rotation_exception_states(
            rotation_states,
            allow_empty=True,
        )
        normalized_expires_at = str(expires_at or "").strip() or None
        normalized_note = str(note or "").strip() or None
        normalized_source_approval_id = str(source_approval_id or "").strip() or None
        normalized_source_approval_name = str(source_approval_name or "").strip() or None

        config = self.app_config
        records = list(config.shared_library_rotation_exception_records or [])
        updated = {
            "fingerprint": normalized_fingerprint,
            "package_types": normalized_package_types,
            "rotation_states": normalized_rotation_states,
            "expires_at": normalized_expires_at,
            "note": normalized_note,
            "source_approval_id": normalized_source_approval_id,
            "source_approval_name": normalized_source_approval_name,
        }
        identity = (
            normalized_fingerprint,
            ",".join(normalized_package_types),
            ",".join(normalized_rotation_states),
        )
        replaced = False
        for index, record in enumerate(records):
            current = dict(record)
            current_identity = (
                str(current.get("fingerprint") or "").strip().lower(),
                ",".join(
                    _normalize_shared_library_package_types(
                        current.get("package_types"),
                        allow_empty=True,
                    )
                ),
                ",".join(
                    _normalize_shared_library_rotation_exception_states(
                        current.get("rotation_states"),
                        allow_empty=True,
                    )
                ),
            )
            if current_identity != identity:
                continue
            updated = {
                **current,
                **updated,
                "note": (
                    normalized_note
                    if note is not None
                    else (str(current.get("note") or "").strip() or None)
                ),
                "expires_at": (
                    normalized_expires_at
                    if expires_at is not None
                    else (str(current.get("expires_at") or "").strip() or None)
                ),
                "source_approval_id": (
                    normalized_source_approval_id
                    if source_approval_id is not None
                    else (str(current.get("source_approval_id") or "").strip() or None)
                ),
                "source_approval_name": (
                    normalized_source_approval_name
                    if source_approval_name is not None
                    else (str(current.get("source_approval_name") or "").strip() or None)
                ),
            }
            records[index] = updated
            replaced = True
            break
        if not replaced:
            records.append(updated)

        config.shared_library_rotation_exception_records = (
            _normalize_shared_library_rotation_exception_records(records)
        )
        self.save_app_config(config)

        signer_context = self._shared_library_signer_context(normalized_fingerprint)
        package_labels = [
            _shared_library_package_type_label(item)
            for item in (updated.get("package_types") or [])
        ]
        rotation_labels = [
            "轮换临近" if item == "due" else "轮换超期"
            for item in (updated.get("rotation_states") or [])
        ]
        self.append_shared_library_governance_audit_event(
            event_kind="grant_rotation_exception",
            target_type="rotation_exception",
            target_value=normalized_fingerprint,
            target_label=str(signer_context.get("signer_display_name") or "").strip()
            or normalized_fingerprint,
            summary=f"授予轮换例外授权 {normalized_fingerprint[:12]}",
            detail_lines=[
                (
                    f"签名者别名: {signer_context.get('signer_display_name')}"
                    if signer_context.get("signer_display_name")
                    else ""
                ),
                (
                    f"适用包类型: {', '.join(package_labels)}"
                    if package_labels
                    else "适用包类型: 全部共享包"
                ),
                (
                    f"适用轮换状态: {', '.join(rotation_labels)}"
                    if rotation_labels
                    else "适用轮换状态: 全部轮换状态"
                ),
                f"截止时间: {updated['expires_at']}" if updated.get("expires_at") else "",
                f"备注: {updated['note']}" if updated.get("note") else "",
                (
                    f"来源审批单: {updated['source_approval_name']}"
                    if updated.get("source_approval_name")
                    else ""
                ),
            ],
        )
        current = self.get_shared_library_rotation_exception_record(
            normalized_fingerprint,
            package_type=(
                normalized_package_types[0] if len(normalized_package_types) == 1 else None
            ),
            rotation_status=(
                normalized_rotation_states[0] if len(normalized_rotation_states) == 1 else None
            ),
            include_expired=True,
        )
        return current or dict(updated)

    def remove_shared_library_rotation_exception_record(
        self,
        fingerprint: str,
        *,
        package_types: Optional[List[str]] = None,
        rotation_states: Optional[List[str]] = None,
    ) -> bool:
        """移除轮换例外授权。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            raise ConfigurationError("签名指纹不能为空或格式无效")
        normalized_package_types = _normalize_shared_library_package_types(
            package_types,
            allow_empty=True,
        )
        normalized_rotation_states = _normalize_shared_library_rotation_exception_states(
            rotation_states,
            allow_empty=True,
        )

        config = self.app_config
        records = list(config.shared_library_rotation_exception_records or [])
        removed_record: Optional[Dict[str, Any]] = None
        remaining: List[Dict[str, Any]] = []
        for record in records:
            current = dict(record)
            current_identity = (
                str(current.get("fingerprint") or "").strip().lower(),
                ",".join(
                    _normalize_shared_library_package_types(
                        current.get("package_types"),
                        allow_empty=True,
                    )
                ),
                ",".join(
                    _normalize_shared_library_rotation_exception_states(
                        current.get("rotation_states"),
                        allow_empty=True,
                    )
                ),
            )
            target_identity = (
                normalized_fingerprint,
                ",".join(normalized_package_types),
                ",".join(normalized_rotation_states),
            )
            if removed_record is None and current_identity == target_identity:
                removed_record = current
                continue
            remaining.append(current)

        if removed_record is None:
            return False

        config.shared_library_rotation_exception_records = (
            _normalize_shared_library_rotation_exception_records(remaining)
        )
        self.save_app_config(config)

        signer_context = self._shared_library_signer_context(normalized_fingerprint)
        package_labels = [
            _shared_library_package_type_label(item)
            for item in (removed_record.get("package_types") or [])
        ]
        rotation_labels = [
            "轮换临近" if item == "due" else "轮换超期"
            for item in (removed_record.get("rotation_states") or [])
        ]
        self.append_shared_library_governance_audit_event(
            event_kind="remove_rotation_exception",
            target_type="rotation_exception",
            target_value=normalized_fingerprint,
            target_label=str(signer_context.get("signer_display_name") or "").strip()
            or normalized_fingerprint,
            summary=f"移除轮换例外授权 {normalized_fingerprint[:12]}",
            detail_lines=[
                (
                    f"签名者别名: {signer_context.get('signer_display_name')}"
                    if signer_context.get("signer_display_name")
                    else ""
                ),
                (
                    f"适用包类型: {', '.join(package_labels)}"
                    if package_labels
                    else "适用包类型: 全部共享包"
                ),
                (
                    f"适用轮换状态: {', '.join(rotation_labels)}"
                    if rotation_labels
                    else "适用轮换状态: 全部轮换状态"
                ),
                (
                    f"原截止时间: {removed_record['expires_at']}"
                    if removed_record.get("expires_at")
                    else ""
                ),
                f"原备注: {removed_record['note']}" if removed_record.get("note") else "",
                (
                    f"来源审批单: {removed_record['source_approval_name']}"
                    if removed_record.get("source_approval_name")
                    else ""
                ),
            ],
        )
        return True

    def get_shared_library_signer_group_names(self, fingerprint: str) -> List[str]:
        """获取签名者所属分组列表。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            return []
        groups: List[str] = []
        for group_name, members in (self.app_config.shared_library_signer_groups or {}).items():
            if normalized_fingerprint in list(members or []):
                groups.append(str(group_name))
        return sorted(groups, key=str.casefold)

    def get_shared_library_revoked_signer_record(
        self,
        fingerprint: str,
    ) -> Optional[Dict[str, Optional[str]]]:
        """获取签名者撤销记录。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            return None
        for record in self.app_config.shared_library_revoked_signer_records or []:
            if str(record.get("fingerprint") or "").strip() == normalized_fingerprint:
                return dict(record)
        return None

    def _shared_library_signer_context(self, fingerprint: Optional[str]) -> Dict[str, Any]:
        """构造签名者上下文信息。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            return {
                "signer_display_name": None,
                "signer_note": None,
                "signer_groups": [],
                "signer_group_label": None,
                "policy_expires_at": None,
                "policy_status": "none",
                "rotation_due_at": None,
                "rotation_status": "none",
                "revoked_reason": None,
                "revoked_note": None,
                "revoked_at": None,
            }
        profile = self.get_shared_library_signer_profile(normalized_fingerprint)
        signer_groups = self.get_shared_library_signer_group_names(normalized_fingerprint)
        revoked_record = self.get_shared_library_revoked_signer_record(normalized_fingerprint) or {}
        policy_expires_at = str(profile.get("expires_at") or "").strip() or None
        rotation_due_at = str(profile.get("rotate_before_at") or "").strip() or None
        return {
            "signer_display_name": str(profile.get("display_name") or "").strip() or None,
            "signer_note": str(profile.get("note") or "").strip() or None,
            "signer_groups": signer_groups,
            "signer_group_label": " / ".join(signer_groups) if signer_groups else None,
            "policy_expires_at": policy_expires_at,
            "policy_status": _shared_library_signer_policy_status(policy_expires_at),
            "rotation_due_at": rotation_due_at,
            "rotation_status": _shared_library_signer_rotation_status(rotation_due_at),
            "revoked_reason": str(revoked_record.get("reason") or "").strip() or None,
            "revoked_note": str(revoked_record.get("note") or "").strip() or None,
            "revoked_at": str(revoked_record.get("revoked_at") or "").strip() or None,
        }

    def _match_shared_library_rotation_exception(
        self,
        fingerprint: Any,
        *,
        package_type: Any = None,
        rotation_status: Any = None,
        now: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """查找命中的轮换例外授权。"""
        normalized_fingerprint = _normalize_shared_library_signer_fingerprint(fingerprint)
        if not normalized_fingerprint:
            return None
        normalized_package_type = self._normalize_shared_library_package_type(package_type)
        normalized_rotation_status = str(rotation_status or "").strip().lower()
        if normalized_rotation_status not in SHARED_LIBRARY_ROTATION_EXCEPTION_STATES:
            return None

        current = now or datetime.now(timezone.utc)
        for record in self.app_config.shared_library_rotation_exception_records or []:
            candidate = dict(record)
            if (
                _normalize_shared_library_signer_fingerprint(candidate.get("fingerprint"))
                != normalized_fingerprint
            ):
                continue
            package_types = _normalize_shared_library_package_types(
                candidate.get("package_types"),
                allow_empty=True,
            )
            if package_types and normalized_package_type not in package_types:
                continue
            rotation_states = _normalize_shared_library_rotation_exception_states(
                candidate.get("rotation_states"),
                allow_empty=True,
            )
            if rotation_states and normalized_rotation_status not in rotation_states:
                continue
            status = _shared_library_rotation_exception_status(
                candidate.get("expires_at"),
                now=current,
            )
            if status != "active":
                continue
            candidate["status"] = status
            return candidate
        return None

    def match_shared_library_team_approval_rules(
        self,
        record: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """返回命中当前共享包记录的团队级审批规则。"""
        source_app = str(record.get("source_app") or "").strip()
        if not source_app:
            return []
        try:
            package_type = self._normalize_shared_library_package_type(record.get("package_type"))
        except ConfigurationError:
            return []
        fingerprint = _normalize_shared_library_signer_fingerprint(
            record.get("signature_fingerprint")
        )
        signer_groups = [
            str(item).strip()
            for item in (
                record.get("signer_groups")
                or self.get_shared_library_signer_group_names(fingerprint)
            )
            if str(item).strip()
        ]
        signer_group_keys = {item.casefold() for item in signer_groups}
        verified_signature_count = max(int(record.get("verified_signature_count") or 0), 0)
        rotation_status = (
            str(
                record.get("rotation_status")
                or self._shared_library_signer_context(fingerprint).get("rotation_status")
                or "none"
            )
            .strip()
            .lower()
            or "none"
        )
        if rotation_status not in SHARED_LIBRARY_TEAM_APPROVAL_RULE_ROTATION_STATES:
            rotation_status = "none"

        matched: List[Dict[str, Any]] = []
        for rule in self.app_config.shared_library_team_approval_rules or []:
            if not _normalize_bool_flag(rule.get("enabled"), True):
                continue
            source_apps = list(rule.get("source_apps") or [])
            if source_apps and source_app.casefold() not in {
                item.casefold() for item in source_apps
            }:
                continue
            package_types = list(rule.get("package_types") or [])
            if package_types and package_type not in package_types:
                continue
            rule_groups = list(rule.get("signer_groups") or [])
            if rule_groups and not any(
                item.casefold() in signer_group_keys for item in rule_groups
            ):
                continue
            rotation_states = list(rule.get("rotation_states") or [])
            if rotation_states and rotation_status not in rotation_states:
                continue
            minimum_signature_count = max(int(rule.get("minimum_signature_count") or 0), 0)
            if minimum_signature_count > 0 and verified_signature_count >= minimum_signature_count:
                continue
            matched.append(
                {
                    "name": str(rule.get("name") or "").strip() or "未命名规则",
                    "action": _normalize_shared_library_team_approval_rule_action(
                        rule.get("action")
                    ),
                    "action_label": _shared_library_team_approval_rule_action_label(
                        rule.get("action")
                    ),
                    "source_apps": source_apps,
                    "package_types": package_types,
                    "package_type_labels": (
                        [_shared_library_package_type_label(item) for item in package_types]
                        if package_types
                        else ["全部共享包"]
                    ),
                    "signer_groups": rule_groups,
                    "rotation_states": rotation_states,
                    "minimum_signature_count": minimum_signature_count,
                    "current_signature_count": verified_signature_count,
                    "approval_level": str(rule.get("approval_level") or "").strip() or None,
                    "rotation_state_labels": (
                        [
                            _shared_library_team_approval_rule_rotation_state_label(item)
                            for item in rotation_states
                        ]
                        if rotation_states
                        else ["全部轮换状态"]
                    ),
                    "note": str(rule.get("note") or "").strip() or None,
                }
            )
        return matched

    def filter_shared_library_records_by_team_approval_rules(
        self,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """根据团队级审批规则对共享包记录分类。"""
        approval_records: List[Dict[str, Any]] = []
        blocked_records: List[Dict[str, Any]] = []
        unmatched_records: List[Dict[str, Any]] = []

        for record in records:
            matched_rules = self.match_shared_library_team_approval_rules(record)
            if not matched_rules:
                unmatched_records.append(dict(record))
                continue
            action_map = {
                item["name"]: item["action"]
                for item in matched_rules
                if str(item.get("name") or "").strip()
            }
            matched_rule_names = list(action_map.keys())
            enriched_record = {
                **dict(record),
                "matched_team_approval_rules": matched_rule_names,
                "matched_team_approval_levels": [
                    str(item.get("approval_level") or "").strip()
                    for item in matched_rules
                    if str(item.get("approval_level") or "").strip()
                ],
                "required_signature_count": max(
                    int(item.get("minimum_signature_count") or 0) for item in matched_rules
                ),
            }
            if SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_BLOCK in action_map.values():
                blocked_records.append(enriched_record)
                continue
            approval_records.append(enriched_record)

        return {
            "approval_records": approval_records,
            "blocked_records": blocked_records,
            "unmatched_records": unmatched_records,
        }

    def inspect_shared_library_signer_governance(
        self,
        sync_dir: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """汇总共享签名治理状态，便于设置页、状态页和审计展示。"""
        config = self.app_config
        profiles = dict(config.shared_library_signer_profiles or {})
        signer_groups = _normalize_shared_library_signer_groups(config.shared_library_signer_groups)
        trusted_set = set(config.shared_library_trusted_signer_fingerprints or [])
        revoked_set = set(config.shared_library_revoked_signer_fingerprints or [])
        approvals = self.load_shared_library_approval_records()
        pending_approvals = [record for record in approvals if record.get("decision") == "pending"]
        grouped_signers = {
            fingerprint
            for fingerprints in signer_groups.values()
            for fingerprint in list(fingerprints or [])
        }
        known_signers = sorted(
            set(profiles.keys()) | trusted_set | revoked_set | grouped_signers,
            key=str.casefold,
        )
        signer_contexts = {
            fingerprint: self._shared_library_signer_context(fingerprint)
            for fingerprint in known_signers
        }
        rotation_exception_records = _normalize_shared_library_rotation_exception_records(
            config.shared_library_rotation_exception_records
        )

        def _signer_label(fingerprint: str) -> str:
            profile = profiles.get(fingerprint) or {}
            display_name = str(profile.get("display_name") or "").strip()
            return f"{display_name} ({fingerprint[:12]})" if display_name else fingerprint

        def _rotation_exception_summary(record: Dict[str, Any]) -> Dict[str, Any]:
            fingerprint = str(record.get("fingerprint") or "").strip().lower()
            signer_label = _signer_label(fingerprint)
            package_types = _normalize_shared_library_package_types(
                record.get("package_types"),
                allow_empty=True,
            )
            rotation_states = _normalize_shared_library_rotation_exception_states(
                record.get("rotation_states"),
                allow_empty=True,
            )
            status = _shared_library_rotation_exception_status(record.get("expires_at"))
            return {
                "fingerprint": fingerprint,
                "label": signer_label,
                "package_types": package_types,
                "package_type_labels": (
                    [_shared_library_package_type_label(item) for item in package_types]
                    if package_types
                    else ["全部共享包"]
                ),
                "rotation_states": rotation_states,
                "rotation_state_labels": (
                    ["轮换临近" if item == "due" else "轮换超期" for item in rotation_states]
                    if rotation_states
                    else ["全部轮换状态"]
                ),
                "expires_at": str(record.get("expires_at") or "").strip() or None,
                "note": str(record.get("note") or "").strip() or None,
                "source_approval_id": str(record.get("source_approval_id") or "").strip() or None,
                "source_approval_name": str(record.get("source_approval_name") or "").strip()
                or None,
                "status": status,
            }

        active_rotation_exceptions = [
            _rotation_exception_summary(record)
            for record in rotation_exception_records
            if _shared_library_rotation_exception_status(record.get("expires_at")) == "active"
        ]
        expired_rotation_exceptions = [
            _rotation_exception_summary(record)
            for record in rotation_exception_records
            if _shared_library_rotation_exception_status(record.get("expires_at")) != "active"
        ]

        group_summaries: List[Dict[str, Any]] = []
        for group_name, fingerprints in sorted(
            signer_groups.items(), key=lambda item: item[0].casefold()
        ):
            normalized_fingerprints = list(fingerprints or [])
            group_summaries.append(
                {
                    "name": group_name,
                    "fingerprint_count": len(normalized_fingerprints),
                    "trusted_count": sum(
                        1 for fingerprint in normalized_fingerprints if fingerprint in trusted_set
                    ),
                    "revoked_count": sum(
                        1 for fingerprint in normalized_fingerprints if fingerprint in revoked_set
                    ),
                    "profile_count": sum(
                        1 for fingerprint in normalized_fingerprints if fingerprint in profiles
                    ),
                    "expired_policy_count": sum(
                        1
                        for fingerprint in normalized_fingerprints
                        if signer_contexts.get(fingerprint, {}).get("policy_status") == "expired"
                    ),
                    "expiring_policy_count": sum(
                        1
                        for fingerprint in normalized_fingerprints
                        if signer_contexts.get(fingerprint, {}).get("policy_status") == "expiring"
                    ),
                    "rotation_due_count": sum(
                        1
                        for fingerprint in normalized_fingerprints
                        if signer_contexts.get(fingerprint, {}).get("rotation_status") == "due"
                    ),
                    "rotation_overdue_count": sum(
                        1
                        for fingerprint in normalized_fingerprints
                        if signer_contexts.get(fingerprint, {}).get("rotation_status") == "overdue"
                    ),
                    "members": [
                        _signer_label(fingerprint) for fingerprint in normalized_fingerprints
                    ],
                }
            )

        recent_revocations = sorted(
            [
                {
                    "fingerprint": str(record.get("fingerprint") or "").strip(),
                    "label": _signer_label(str(record.get("fingerprint") or "").strip()),
                    "reason": str(record.get("reason") or "").strip() or None,
                    "note": str(record.get("note") or "").strip() or None,
                    "revoked_at": str(record.get("revoked_at") or "").strip() or None,
                    "groups": self.get_shared_library_signer_group_names(
                        str(record.get("fingerprint") or "").strip()
                    ),
                }
                for record in config.shared_library_revoked_signer_records or []
                if str(record.get("fingerprint") or "").strip()
            ],
            key=lambda item: (
                str(item.get("revoked_at") or ""),
                str(item.get("fingerprint") or ""),
            ),
            reverse=True,
        )
        ungrouped_profiles = sorted(
            [
                _signer_label(fingerprint)
                for fingerprint in profiles
                if not self.get_shared_library_signer_group_names(fingerprint)
            ],
            key=str.casefold,
        )
        recent_audit_events = self.load_shared_library_governance_audit_records()
        audit_actors = {
            str(record.get("actor") or "").strip()
            for record in recent_audit_events
            if str(record.get("actor") or "").strip()
        }
        expired_policies = [
            {
                "fingerprint": fingerprint,
                "label": _signer_label(fingerprint),
                "expires_at": signer_contexts.get(fingerprint, {}).get("policy_expires_at"),
                "groups": list(signer_contexts.get(fingerprint, {}).get("signer_groups") or []),
            }
            for fingerprint in known_signers
            if signer_contexts.get(fingerprint, {}).get("policy_status") == "expired"
        ]
        expiring_policies = [
            {
                "fingerprint": fingerprint,
                "label": _signer_label(fingerprint),
                "expires_at": signer_contexts.get(fingerprint, {}).get("policy_expires_at"),
                "groups": list(signer_contexts.get(fingerprint, {}).get("signer_groups") or []),
            }
            for fingerprint in known_signers
            if signer_contexts.get(fingerprint, {}).get("policy_status") == "expiring"
        ]
        rotation_due_signers = [
            {
                "fingerprint": fingerprint,
                "label": _signer_label(fingerprint),
                "rotate_before_at": signer_contexts.get(fingerprint, {}).get("rotation_due_at"),
                "groups": list(signer_contexts.get(fingerprint, {}).get("signer_groups") or []),
            }
            for fingerprint in known_signers
            if signer_contexts.get(fingerprint, {}).get("rotation_status") == "due"
        ]
        rotation_overdue_signers = [
            {
                "fingerprint": fingerprint,
                "label": _signer_label(fingerprint),
                "rotate_before_at": signer_contexts.get(fingerprint, {}).get("rotation_due_at"),
                "groups": list(signer_contexts.get(fingerprint, {}).get("signer_groups") or []),
            }
            for fingerprint in known_signers
            if signer_contexts.get(fingerprint, {}).get("rotation_status") == "overdue"
        ]
        team_approval_rule_summaries = [
            {
                "name": str(rule.get("name") or "").strip() or "未命名规则",
                "enabled": _normalize_bool_flag(rule.get("enabled"), True),
                "action": _normalize_shared_library_team_approval_rule_action(rule.get("action")),
                "action_label": _shared_library_team_approval_rule_action_label(rule.get("action")),
                "source_apps": list(rule.get("source_apps") or []),
                "package_types": list(rule.get("package_types") or []),
                "package_type_labels": (
                    [
                        _shared_library_package_type_label(item)
                        for item in list(rule.get("package_types") or [])
                    ]
                    if list(rule.get("package_types") or [])
                    else ["全部共享包"]
                ),
                "signer_groups": list(rule.get("signer_groups") or []),
                "rotation_states": list(rule.get("rotation_states") or []),
                "minimum_signature_count": max(int(rule.get("minimum_signature_count") or 0), 0),
                "approval_level": str(rule.get("approval_level") or "").strip() or None,
                "rotation_state_labels": (
                    [
                        _shared_library_team_approval_rule_rotation_state_label(item)
                        for item in list(rule.get("rotation_states") or [])
                    ]
                    if list(rule.get("rotation_states") or [])
                    else ["全部轮换状态"]
                ),
                "note": str(rule.get("note") or "").strip() or None,
            }
            for rule in (config.shared_library_team_approval_rules or [])
        ]

        summary: Dict[str, Any] = {
            "known_signer_count": len(known_signers),
            "signer_profile_count": len(profiles),
            "signer_group_count": len(signer_groups),
            "grouped_signer_count": len(grouped_signers),
            "ungrouped_profile_count": len(ungrouped_profiles),
            "ungrouped_profiles": ungrouped_profiles,
            "trusted_signer_count": len(trusted_set),
            "revoked_signer_count": len(revoked_set),
            "expired_policy_count": len(expired_policies),
            "expiring_policy_count": len(expiring_policies),
            "rotation_due_count": len(rotation_due_signers),
            "rotation_overdue_count": len(rotation_overdue_signers),
            "rotation_exception_count": len(rotation_exception_records),
            "active_rotation_exception_count": len(active_rotation_exceptions),
            "expired_rotation_exception_count": len(expired_rotation_exceptions),
            "expired_policies": expired_policies,
            "expiring_policies": expiring_policies,
            "rotation_due_signers": rotation_due_signers,
            "rotation_overdue_signers": rotation_overdue_signers,
            "active_rotation_exceptions": active_rotation_exceptions,
            "expired_rotation_exceptions": expired_rotation_exceptions,
            "rotation_due_policy": config.shared_library_rotation_due_policy,
            "rotation_overdue_policy": config.shared_library_rotation_overdue_policy,
            "pending_approval_count": len(pending_approvals),
            "team_approval_rule_count": len(team_approval_rule_summaries),
            "enabled_team_approval_rule_count": sum(
                1 for rule in team_approval_rule_summaries if rule.get("enabled")
            ),
            "team_approval_gate_count": sum(
                1
                for rule in team_approval_rule_summaries
                if rule.get("enabled")
                and rule.get("action") == SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_APPROVAL
            ),
            "team_block_rule_count": sum(
                1
                for rule in team_approval_rule_summaries
                if rule.get("enabled")
                and rule.get("action") == SHARED_LIBRARY_TEAM_APPROVAL_RULE_ACTION_BLOCK
            ),
            "team_approval_rule_summaries": team_approval_rule_summaries,
            "group_summaries": group_summaries,
            "recent_revocations": recent_revocations,
            "audit_event_count": len(recent_audit_events),
            "audit_actor_count": len(audit_actors),
            "recent_audit_events": recent_audit_events[:10],
        }

        normalized_sync_dir = str(sync_dir or "").strip()
        if normalized_sync_dir:
            try:
                integrity = self.inspect_shared_library_pull_integrity(
                    normalized_sync_dir,
                    trusted_source_apps=config.shared_library_trusted_source_apps,
                    trusted_signer_fingerprints=config.shared_library_trusted_signer_fingerprints,
                    revoked_signer_fingerprints=config.shared_library_revoked_signer_fingerprints,
                    allowed_package_types=config.shared_library_auto_pull_allowed_package_types,
                    rotation_due_policy=config.shared_library_rotation_due_policy,
                    rotation_overdue_policy=config.shared_library_rotation_overdue_policy,
                )
            except ConfigurationError:
                integrity = None
            summary["integrity"] = integrity
        else:
            summary["integrity"] = None
        return summary

    def allow_shared_library_auto_pull_package_type(self, package_type: str) -> List[str]:
        """允许指定共享包类型自动拉取。"""
        normalized_package_type = self._normalize_shared_library_package_type(package_type)
        config = self.app_config
        allowed_types = list(config.shared_library_auto_pull_allowed_package_types or [])
        allowed_types.append(normalized_package_type)
        config.shared_library_auto_pull_allowed_package_types = (
            _normalize_shared_library_package_types(allowed_types)
        )
        self.save_app_config(config)
        self.append_shared_library_governance_audit_event(
            event_kind="allow_package_type",
            target_type="package_type",
            target_value=normalized_package_type,
            target_label=normalized_package_type,
            summary=f"允许共享包类型自动拉取 {normalized_package_type}",
            detail_lines=[
                f"当前允许包类型数: {len(config.shared_library_auto_pull_allowed_package_types or [])}"
            ],
        )
        return list(config.shared_library_auto_pull_allowed_package_types)

    def format_shared_library_governance_report(
        self,
        sync_dir: Optional[Union[str, Path]] = None,
    ) -> str:
        """生成共享治理文本报告。"""
        summary = self.inspect_shared_library_signer_governance(sync_dir)
        lines = [
            "Neko_Shell 共享治理报告",
            f"生成时间: {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}",
            f"已知签名者: {int(summary.get('known_signer_count') or 0)}",
            f"签名者资料: {int(summary.get('signer_profile_count') or 0)}",
            f"签名者分组: {int(summary.get('signer_group_count') or 0)}",
            f"已分组签名者: {int(summary.get('grouped_signer_count') or 0)}",
            f"未分组资料: {int(summary.get('ungrouped_profile_count') or 0)}",
            f"受信任签名者: {int(summary.get('trusted_signer_count') or 0)}",
            f"已撤销签名者: {int(summary.get('revoked_signer_count') or 0)}",
            f"已过期策略: {int(summary.get('expired_policy_count') or 0)}",
            f"临近到期策略: {int(summary.get('expiring_policy_count') or 0)}",
            f"轮换临近截止: {int(summary.get('rotation_due_count') or 0)}",
            f"轮换已超期: {int(summary.get('rotation_overdue_count') or 0)}",
            f"轮换例外授权: {int(summary.get('rotation_exception_count') or 0)}",
            f"生效例外授权: {int(summary.get('active_rotation_exception_count') or 0)}",
            f"已失效例外授权: {int(summary.get('expired_rotation_exception_count') or 0)}",
            f"临近轮换治理: {_shared_library_rotation_policy_label(summary.get('rotation_due_policy'))}",
            f"轮换超期治理: {_shared_library_rotation_policy_label(summary.get('rotation_overdue_policy'))}",
            f"待审记录: {int(summary.get('pending_approval_count') or 0)}",
            f"团队级审批规则: {int(summary.get('team_approval_rule_count') or 0)}",
            f"启用中的团队规则: {int(summary.get('enabled_team_approval_rule_count') or 0)}",
            f"团队审批门禁: {int(summary.get('team_approval_gate_count') or 0)}",
            f"团队阻断规则: {int(summary.get('team_block_rule_count') or 0)}",
            f"审计事件: {int(summary.get('audit_event_count') or 0)}",
            f"活跃操作者: {int(summary.get('audit_actor_count') or 0)}",
        ]
        if summary.get("group_summaries"):
            lines.extend(["", "签名分组摘要:"])
            for group in list(summary.get("group_summaries") or [])[:10]:
                lines.append(
                    f"- {group.get('name', '未命名分组')}: "
                    f"{int(group.get('fingerprint_count') or 0)} 名, "
                    f"受信任 {int(group.get('trusted_count') or 0)}, "
                    f"已撤销 {int(group.get('revoked_count') or 0)}"
                )
        if summary.get("recent_revocations"):
            lines.extend(["", "最近撤销记录:"])
            for record in list(summary.get("recent_revocations") or [])[:5]:
                suffix = []
                if record.get("revoked_at"):
                    suffix.append(str(record.get("revoked_at")))
                if record.get("reason"):
                    suffix.append(str(record.get("reason")))
                lines.append(
                    f"- {str(record.get('label') or record.get('fingerprint') or '').strip()}"
                    + (f" · {' · '.join(suffix)}" if suffix else "")
                )
        if summary.get("expired_policies"):
            lines.extend(["", "已过期策略:"])
            for record in list(summary.get("expired_policies") or [])[:5]:
                suffix = str(record.get("expires_at") or "").strip()
                lines.append(
                    f"- {str(record.get('label') or record.get('fingerprint') or '').strip()}"
                    + (f" · {suffix}" if suffix else "")
                )
        if summary.get("rotation_overdue_signers"):
            lines.extend(["", "轮换已超期:"])
            for record in list(summary.get("rotation_overdue_signers") or [])[:5]:
                suffix = str(record.get("rotate_before_at") or "").strip()
                lines.append(
                    f"- {str(record.get('label') or record.get('fingerprint') or '').strip()}"
                    + (f" · {suffix}" if suffix else "")
                )
        if summary.get("active_rotation_exceptions"):
            lines.extend(["", "生效中的轮换例外授权:"])
            for record in list(summary.get("active_rotation_exceptions") or [])[:5]:
                parts = [
                    ", ".join(list(record.get("package_type_labels") or [])) or "全部共享包",
                    ", ".join(list(record.get("rotation_state_labels") or [])) or "全部轮换状态",
                ]
                if record.get("source_approval_name"):
                    parts.append(f"来源审批: {record.get('source_approval_name')}")
                if record.get("expires_at"):
                    parts.append(str(record.get("expires_at")))
                if record.get("note"):
                    parts.append(str(record.get("note")))
                lines.append(
                    f"- {str(record.get('label') or record.get('fingerprint') or '').strip()}"
                    + (f" · {' · '.join(parts)}" if parts else "")
                )
        if summary.get("team_approval_rule_summaries"):
            lines.extend(["", "团队级审批规则:"])
            for record in list(summary.get("team_approval_rule_summaries") or [])[:8]:
                scopes = [
                    f"动作 {record.get('action_label')}",
                    ", ".join(list(record.get("package_type_labels") or [])) or "全部共享包",
                    (
                        "来源 " + ", ".join(list(record.get("source_apps") or []))
                        if list(record.get("source_apps") or [])
                        else "来源 全部"
                    ),
                    (
                        "分组 " + ", ".join(list(record.get("signer_groups") or []))
                        if list(record.get("signer_groups") or [])
                        else "分组 全部"
                    ),
                    ", ".join(list(record.get("rotation_state_labels") or [])) or "全部轮换状态",
                ]
                if int(record.get("minimum_signature_count") or 0) > 0:
                    scopes.append(f"最小签名数 {int(record.get('minimum_signature_count') or 0)}")
                if record.get("approval_level"):
                    scopes.append(f"审批级别 {record.get('approval_level')}")
                if record.get("note"):
                    scopes.append(str(record.get("note")))
                lines.append(
                    f"- {str(record.get('name') or '未命名规则').strip()}"
                    + (f" · {' · '.join(scopes)}" if scopes else "")
                )
        if summary.get("recent_audit_events"):
            lines.extend(["", "最近治理动作:"])
            for record in list(summary.get("recent_audit_events") or [])[:8]:
                lines.append(
                    f"- {str(record.get('recorded_at') or '').strip()} · "
                    f"{str(record.get('actor') or '未知操作者').strip()} · "
                    f"{str(record.get('summary') or record.get('event_kind') or '未知事件').strip()}"
                )
        integrity = summary.get("integrity")
        if isinstance(integrity, dict):
            lines.extend(
                [
                    "",
                    "共享仓库校验概览:",
                    f"- 校验异常: {int(integrity.get('blocked_count') or 0)}",
                    f"- 未校验: {int(integrity.get('unverified_count') or 0)}",
                    f"- 已撤销签名者命中: {int(integrity.get('revoked_signer_count') or 0)}",
                    f"- 已过期签名策略: {int(integrity.get('expired_signer_policy_count') or 0)}",
                    f"- 轮换临近截止命中: {int(integrity.get('rotation_due_count') or 0)}",
                    f"- 轮换已超期命中: {int(integrity.get('rotation_overdue_count') or 0)}",
                    f"- 轮换例外授权命中: {int(integrity.get('rotation_exception_count') or 0)}",
                ]
            )
        return "\n".join(lines)

    def export_shared_library_governance_report(
        self,
        file_path: Union[str, Path],
        *,
        sync_dir: Optional[Union[str, Path]] = None,
    ) -> Path:
        """导出共享治理报告，支持 TXT / JSON。"""
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        suffix = target.suffix.lower()
        summary = self.inspect_shared_library_signer_governance(sync_dir)
        if suffix == ".json":
            payload = {
                "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "report_type": "shared_library_governance",
                "sync_dir": str(sync_dir or "").strip() or None,
                "summary": summary,
            }
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            target.write_text(
                self.format_shared_library_governance_report(sync_dir),
                encoding="utf-8",
            )
        self._secure_file(target)
        return target

    @staticmethod
    def filter_shared_library_records_by_source_apps(
        records: List[Dict[str, Any]],
        trusted_source_apps: Optional[List[str]],
    ) -> Dict[str, Any]:
        """按来源应用过滤共享记录。"""
        trusted_apps = _normalize_shared_library_trusted_sources(trusted_source_apps)
        if not trusted_apps:
            return {
                "trusted_records": [dict(record) for record in records],
                "untrusted_records": [],
                "trusted_source_apps": [],
                "untrusted_sources": [],
            }

        trusted_keys = {item.casefold() for item in trusted_apps}
        trusted_records: List[Dict[str, Any]] = []
        untrusted_records: List[Dict[str, Any]] = []
        untrusted_sources: List[str] = []
        seen_sources: set[str] = set()
        for record in records:
            source_app = str(record.get("source_app") or "").strip()
            if source_app.casefold() in trusted_keys:
                trusted_records.append(dict(record))
                continue
            untrusted_records.append(dict(record))
            source_key = source_app.casefold()
            if source_app and source_key not in seen_sources:
                seen_sources.add(source_key)
                untrusted_sources.append(source_app)

        return {
            "trusted_records": trusted_records,
            "untrusted_records": untrusted_records,
            "trusted_source_apps": trusted_apps,
            "untrusted_sources": untrusted_sources,
        }

    def filter_shared_library_records_by_package_types(
        self,
        records: List[Dict[str, Any]],
        allowed_package_types: Optional[List[str]],
    ) -> Dict[str, Any]:
        """按共享包类型过滤共享记录。"""
        if allowed_package_types is None:
            return {
                "allowed_records": [dict(record) for record in records],
                "blocked_records": [],
                "allowed_package_types": [],
                "blocked_package_types": [],
            }

        allowed_types = _normalize_shared_library_package_types(
            allowed_package_types,
            allow_empty=True,
        )
        allowed_keys = {item.casefold() for item in allowed_types}
        allowed_records: List[Dict[str, Any]] = []
        blocked_records: List[Dict[str, Any]] = []
        blocked_package_types: List[str] = []
        seen_types: set[str] = set()

        for record in records:
            package_type = str(record.get("package_type") or "").strip().lower()
            if package_type in allowed_keys:
                allowed_records.append(dict(record))
                continue
            blocked_records.append(dict(record))
            if package_type and package_type not in seen_types:
                seen_types.add(package_type)
                blocked_package_types.append(package_type)

        return {
            "allowed_records": allowed_records,
            "blocked_records": blocked_records,
            "allowed_package_types": allowed_types,
            "blocked_package_types": blocked_package_types,
        }

    def filter_shared_library_records_by_signer_fingerprints(
        self,
        records: List[Dict[str, Any]],
        trusted_signer_fingerprints: Optional[List[str]],
    ) -> Dict[str, Any]:
        """按签名指纹过滤共享记录。"""
        trusted_fingerprints = _normalize_shared_library_trusted_signer_fingerprints(
            trusted_signer_fingerprints
        )
        if not trusted_fingerprints:
            return {
                "trusted_records": [dict(record) for record in records],
                "untrusted_records": [],
                "expired_records": [],
                "trusted_signer_fingerprints": [],
                "untrusted_signers": [],
                "expired_policy_signers": [],
            }

        trusted_keys = set(trusted_fingerprints)
        trusted_records: List[Dict[str, Any]] = []
        untrusted_records: List[Dict[str, Any]] = []
        expired_records: List[Dict[str, Any]] = []
        untrusted_signers: List[str] = []
        expired_policy_signers: List[str] = []
        seen_signers: set[str] = set()
        seen_expired_signers: set[str] = set()

        for record in records:
            fingerprints = _normalize_shared_library_trusted_signer_fingerprints(
                list(record.get("verified_signature_fingerprints") or [])
                or [record.get("signature_fingerprint")]
            )
            if not fingerprints:
                trusted_records.append(dict(record))
                continue
            trusted_matches = [
                fingerprint for fingerprint in fingerprints if fingerprint in trusted_keys
            ]
            if trusted_matches:
                active_context: Optional[Dict[str, Any]] = None
                expired_context: Optional[Dict[str, Any]] = None
                expired_fingerprint: Optional[str] = None
                for fingerprint in trusted_matches:
                    signer_context = self._shared_library_signer_context(fingerprint)
                    if signer_context.get("policy_status") == "expired":
                        if expired_context is None:
                            expired_context = signer_context
                            expired_fingerprint = fingerprint
                        continue
                    active_context = signer_context
                    break
                if active_context is None and expired_context is not None:
                    expired_records.append(
                        {
                            **dict(record),
                            **expired_context,
                        }
                    )
                    signer = str(
                        record.get("signer_display_name") or record.get("signature_signer") or ""
                    ).strip()
                    signer_label = (
                        f"{signer} ({expired_fingerprint[:12]})"
                        if signer and expired_fingerprint
                        else expired_fingerprint or signer
                    )
                    if expired_fingerprint and expired_fingerprint not in seen_expired_signers:
                        seen_expired_signers.add(expired_fingerprint)
                        expired_policy_signers.append(signer_label)
                    continue
                trusted_records.append(
                    {
                        **dict(record),
                        **(active_context or {}),
                    }
                )
                continue

            untrusted_records.append(dict(record))
            signer = str(
                record.get("signer_display_name") or record.get("signature_signer") or ""
            ).strip()
            primary_fingerprint = fingerprints[0]
            signer_label = (
                f"{signer} ({primary_fingerprint[:12]})" if signer else primary_fingerprint
            )
            signer_key = primary_fingerprint
            if signer_key in seen_signers:
                continue
            seen_signers.add(signer_key)
            untrusted_signers.append(signer_label)

        return {
            "trusted_records": trusted_records,
            "untrusted_records": untrusted_records,
            "expired_records": expired_records,
            "trusted_signer_fingerprints": trusted_fingerprints,
            "untrusted_signers": untrusted_signers,
            "expired_policy_signers": expired_policy_signers,
        }

    def filter_shared_library_records_by_rotation_policy(
        self,
        records: List[Dict[str, Any]],
        *,
        due_policy: Optional[str] = None,
        overdue_policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按签名轮换策略过滤共享记录。"""
        normalized_due_policy = _normalize_shared_library_rotation_policy(
            due_policy
            if due_policy is not None
            else self.app_config.shared_library_rotation_due_policy
        )
        normalized_overdue_policy = _normalize_shared_library_rotation_policy(
            overdue_policy
            if overdue_policy is not None
            else self.app_config.shared_library_rotation_overdue_policy
        )
        allowed_records: List[Dict[str, Any]] = []
        warning_records: List[Dict[str, Any]] = []
        approval_records: List[Dict[str, Any]] = []
        blocked_records: List[Dict[str, Any]] = []
        due_records: List[Dict[str, Any]] = []
        overdue_records: List[Dict[str, Any]] = []
        exception_records: List[Dict[str, Any]] = []
        due_signers: List[str] = []
        overdue_signers: List[str] = []
        exception_signers: List[str] = []
        seen_due_signers: set[str] = set()
        seen_overdue_signers: set[str] = set()
        seen_exception_signers: set[str] = set()

        for record in records:
            signer_context = self._shared_library_signer_context(
                record.get("signature_fingerprint")
            )
            current = {
                **dict(record),
                **signer_context,
            }
            rotation_status = str(current.get("rotation_status") or "").strip()
            fingerprint = _normalize_shared_library_signer_fingerprint(
                current.get("signature_fingerprint")
            )
            signer = str(
                current.get("signer_display_name") or current.get("signature_signer") or ""
            ).strip()
            signer_label = (
                f"{signer} ({fingerprint[:12]})"
                if signer and fingerprint
                else fingerprint or signer
            )
            if rotation_status == "due":
                matched_exception = self._match_shared_library_rotation_exception(
                    fingerprint,
                    package_type=current.get("package_type"),
                    rotation_status=rotation_status,
                )
                if matched_exception is not None:
                    current["rotation_exception"] = dict(matched_exception)
                    current["rotation_exception_note"] = matched_exception.get("note")
                    current["rotation_exception_expires_at"] = matched_exception.get("expires_at")
                    exception_records.append(dict(current))
                    allowed_records.append(dict(current))
                    if signer_label and fingerprint and fingerprint not in seen_exception_signers:
                        seen_exception_signers.add(fingerprint)
                        exception_signers.append(signer_label)
                    continue
                due_records.append(dict(current))
                if signer_label and fingerprint not in seen_due_signers:
                    seen_due_signers.add(str(fingerprint))
                    due_signers.append(signer_label)
                if normalized_due_policy == SHARED_LIBRARY_ROTATION_POLICY_WARN:
                    warning_records.append(dict(current))
                    allowed_records.append(dict(current))
                elif normalized_due_policy == SHARED_LIBRARY_ROTATION_POLICY_APPROVAL:
                    approval_records.append(dict(current))
                else:
                    blocked_records.append(dict(current))
                continue
            if rotation_status == "overdue":
                matched_exception = self._match_shared_library_rotation_exception(
                    fingerprint,
                    package_type=current.get("package_type"),
                    rotation_status=rotation_status,
                )
                if matched_exception is not None:
                    current["rotation_exception"] = dict(matched_exception)
                    current["rotation_exception_note"] = matched_exception.get("note")
                    current["rotation_exception_expires_at"] = matched_exception.get("expires_at")
                    exception_records.append(dict(current))
                    allowed_records.append(dict(current))
                    if signer_label and fingerprint and fingerprint not in seen_exception_signers:
                        seen_exception_signers.add(fingerprint)
                        exception_signers.append(signer_label)
                    continue
                overdue_records.append(dict(current))
                if signer_label and fingerprint not in seen_overdue_signers:
                    seen_overdue_signers.add(str(fingerprint))
                    overdue_signers.append(signer_label)
                if normalized_overdue_policy == SHARED_LIBRARY_ROTATION_POLICY_WARN:
                    warning_records.append(dict(current))
                    allowed_records.append(dict(current))
                elif normalized_overdue_policy == SHARED_LIBRARY_ROTATION_POLICY_APPROVAL:
                    approval_records.append(dict(current))
                else:
                    blocked_records.append(dict(current))
                continue
            allowed_records.append(dict(current))

        return {
            "allowed_records": allowed_records,
            "warning_records": warning_records,
            "approval_records": approval_records,
            "blocked_records": blocked_records,
            "due_records": due_records,
            "overdue_records": overdue_records,
            "exception_records": exception_records,
            "due_signers": due_signers,
            "overdue_signers": overdue_signers,
            "exception_signers": exception_signers,
            "due_policy": normalized_due_policy,
            "overdue_policy": normalized_overdue_policy,
        }

    @staticmethod
    def filter_shared_library_records_by_revoked_signer_fingerprints(
        records: List[Dict[str, Any]],
        revoked_signer_fingerprints: Optional[List[str]],
    ) -> Dict[str, Any]:
        """按已撤销签名指纹过滤共享记录。"""
        revoked_fingerprints = _normalize_shared_library_trusted_signer_fingerprints(
            revoked_signer_fingerprints
        )
        if not revoked_fingerprints:
            return {
                "allowed_records": [dict(record) for record in records],
                "revoked_records": [],
                "revoked_signer_fingerprints": [],
                "revoked_signers": [],
            }

        revoked_keys = set(revoked_fingerprints)
        allowed_records: List[Dict[str, Any]] = []
        revoked_records: List[Dict[str, Any]] = []
        revoked_signers: List[str] = []
        seen_signers: set[str] = set()

        for record in records:
            fingerprints = _normalize_shared_library_trusted_signer_fingerprints(
                list(record.get("verified_signature_fingerprints") or [])
                or [record.get("signature_fingerprint")]
            )
            matched_revoked = [
                fingerprint for fingerprint in fingerprints if fingerprint in revoked_keys
            ]
            if not matched_revoked:
                allowed_records.append(dict(record))
                continue
            revoked_records.append(dict(record))
            signer = str(
                record.get("signer_display_name") or record.get("signature_signer") or ""
            ).strip()
            fingerprint = matched_revoked[0]
            signer_label = f"{signer} ({fingerprint[:12]})" if signer else fingerprint
            if fingerprint in seen_signers:
                continue
            seen_signers.add(fingerprint)
            revoked_signers.append(signer_label)

        return {
            "allowed_records": allowed_records,
            "revoked_records": revoked_records,
            "revoked_signer_fingerprints": revoked_fingerprints,
            "revoked_signers": revoked_signers,
        }

    def inspect_shared_library_record_integrity(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """检查共享包记录与实际文件内容的一致性。"""

        def _base_integrity_result(
            status: str, declared_hash: Optional[str], actual_hash: Optional[str]
        ):
            return {
                "status": status,
                "declared_hash": declared_hash,
                "actual_hash": actual_hash,
                "signature_status": "missing",
                "signature_algorithm": None,
                "signature_signer": None,
                "signature_public_key": None,
                "signature_fingerprint": None,
                "primary_signature_status": "missing",
                "additional_signatures": [],
                "verified_signatures": [],
                "verified_signature_count": 0,
                "verified_signature_fingerprints": [],
                "verified_signature_signers": [],
                "invalid_signature_count": 0,
                "unsupported_signature_count": 0,
            }

        def _verify_signature_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
            algorithm = str(entry.get("signature_algorithm") or "").strip() or None
            signature = str(entry.get("signature") or "").strip() or None
            public_key = str(entry.get("signature_public_key") or "").strip() or None
            signer = str(entry.get("signature_signer") or "").strip() or None
            fingerprint = str(entry.get("signature_fingerprint") or "").strip().lower() or None
            if not fingerprint and public_key:
                try:
                    fingerprint = PackageSigner.fingerprint_from_public_key(public_key)
                except Exception:
                    fingerprint = None
            status = "missing"
            if algorithm or signature or public_key:
                if (
                    algorithm != PackageSigner.SIGNATURE_ALGORITHM
                    or not signature
                    or not public_key
                ):
                    status = "invalid"
                else:
                    try:
                        status = (
                            "verified"
                            if PackageSigner.verify_text(public_key, actual_hash, signature)
                            else "invalid"
                        )
                    except RuntimeError:
                        status = "unsupported"
                    except Exception:
                        status = "invalid"
            return {
                "signature_algorithm": algorithm,
                "signature": signature,
                "signature_public_key": public_key,
                "signature_signer": signer,
                "signature_fingerprint": fingerprint,
                "status": status,
            }

        file_path = Path(str(record.get("file_path") or ""))
        declared_hash = str(record.get("content_hash") or "").strip() or None
        package_type = str(record.get("package_type") or "").strip()
        if not file_path.exists():
            return _base_integrity_result("missing_file", declared_hash, None)

        try:
            payload = self._load_mapping(file_path)
        except Exception:
            return _base_integrity_result("unreadable", declared_hash, None)

        try:
            actual_hash = self._build_share_package_content_hash(package_type, payload)
        except Exception:
            return _base_integrity_result("unreadable", declared_hash, None)

        payload_package = dict(payload.get("package") or {})
        primary_signature = _verify_signature_entry(payload_package)
        additional_signatures = [
            _verify_signature_entry(item)
            for item in _normalize_shared_library_additional_signatures(
                payload_package.get("additional_signatures")
            )
        ]
        all_signatures = [primary_signature] + additional_signatures
        has_any_signature = any(
            item.get("signature")
            or item.get("signature_public_key")
            or item.get("signature_signer")
            for item in all_signatures
        )
        verified_signatures = [item for item in all_signatures if item.get("status") == "verified"]
        invalid_signature_count = sum(
            1 for item in all_signatures if item.get("status") == "invalid"
        )
        unsupported_signature_count = sum(
            1 for item in all_signatures if item.get("status") == "unsupported"
        )
        if invalid_signature_count > 0:
            signature_status = "invalid"
        elif verified_signatures:
            signature_status = "verified"
        elif unsupported_signature_count > 0 and has_any_signature:
            signature_status = "unsupported"
        else:
            signature_status = "missing"

        verified_fingerprints: List[str] = []
        verified_signers: List[str] = []
        seen_fingerprints: set[str] = set()
        for signature_entry in verified_signatures:
            fingerprint = _normalize_shared_library_signer_fingerprint(
                signature_entry.get("signature_fingerprint")
            )
            if fingerprint and fingerprint not in seen_fingerprints:
                seen_fingerprints.add(fingerprint)
                verified_fingerprints.append(fingerprint)
            signer = str(signature_entry.get("signature_signer") or "").strip()
            if signer and signer not in verified_signers:
                verified_signers.append(signer)

        effective_declared_hash = declared_hash or (
            str(payload_package.get("content_hash") or "").strip() or None
        )
        if not effective_declared_hash:
            result = _base_integrity_result("missing", None, actual_hash)
            result.update(
                {
                    "signature_status": signature_status,
                    "signature_algorithm": primary_signature.get("signature_algorithm"),
                    "signature_signer": primary_signature.get("signature_signer"),
                    "signature_public_key": primary_signature.get("signature_public_key"),
                    "signature_fingerprint": primary_signature.get("signature_fingerprint"),
                    "primary_signature_status": primary_signature.get("status"),
                    "additional_signatures": additional_signatures,
                    "verified_signatures": verified_signatures,
                    "verified_signature_count": len(verified_fingerprints),
                    "verified_signature_fingerprints": verified_fingerprints,
                    "verified_signature_signers": verified_signers,
                    "invalid_signature_count": invalid_signature_count,
                    "unsupported_signature_count": unsupported_signature_count,
                }
            )
            return result
        if effective_declared_hash == actual_hash:
            status = "verified"
        else:
            status = "invalid"
        result = _base_integrity_result(status, effective_declared_hash, actual_hash)
        result.update(
            {
                "signature_status": signature_status,
                "signature_algorithm": primary_signature.get("signature_algorithm"),
                "signature_signer": primary_signature.get("signature_signer"),
                "signature_public_key": primary_signature.get("signature_public_key"),
                "signature_fingerprint": primary_signature.get("signature_fingerprint"),
                "primary_signature_status": primary_signature.get("status"),
                "additional_signatures": additional_signatures,
                "verified_signatures": verified_signatures,
                "verified_signature_count": len(verified_fingerprints),
                "verified_signature_fingerprints": verified_fingerprints,
                "verified_signature_signers": verified_signers,
                "invalid_signature_count": invalid_signature_count,
                "unsupported_signature_count": unsupported_signature_count,
            }
        )
        return result

    def classify_shared_library_pull_records(
        self,
        records: List[Dict[str, Any]],
        *,
        trusted_source_apps: Optional[List[str]] = None,
        trusted_signer_fingerprints: Optional[List[str]] = None,
        revoked_signer_fingerprints: Optional[List[str]] = None,
        allowed_package_types: Optional[List[str]] = None,
        rotation_due_policy: Optional[str] = None,
        rotation_overdue_policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """对拉取记录进行来源、包类型和审批分类。"""
        integrity_blocked_records: List[Dict[str, Any]] = []
        integrity_unverified_records: List[Dict[str, Any]] = []
        signature_blocked_records: List[Dict[str, Any]] = []
        signature_unverified_records: List[Dict[str, Any]] = []
        integrity_ok_records: List[Dict[str, Any]] = []
        signature_verified_records: List[Dict[str, Any]] = []
        for record in records:
            integrity = self.inspect_shared_library_record_integrity(record)
            integrity_status = _normalize_shared_library_integrity_status(integrity.get("status"))
            signature_status = _normalize_shared_library_signature_status(
                integrity.get("signature_status")
            )
            enriched_record = {
                **dict(record),
                "integrity_status": integrity_status,
                "declared_content_hash": integrity.get("declared_hash"),
                "actual_content_hash": integrity.get("actual_hash"),
                "signature_status": signature_status,
                "signature_algorithm": integrity.get("signature_algorithm"),
                "signature_signer": integrity.get("signature_signer"),
                "signature_public_key": integrity.get("signature_public_key"),
                "signature_fingerprint": integrity.get("signature_fingerprint"),
                "primary_signature_status": integrity.get("primary_signature_status"),
                "additional_signatures": list(integrity.get("additional_signatures") or []),
                "verified_signatures": list(integrity.get("verified_signatures") or []),
                "verified_signature_count": int(integrity.get("verified_signature_count") or 0),
                "verified_signature_fingerprints": list(
                    integrity.get("verified_signature_fingerprints") or []
                ),
                "verified_signature_signers": list(
                    integrity.get("verified_signature_signers") or []
                ),
                "invalid_signature_count": int(integrity.get("invalid_signature_count") or 0),
                "unsupported_signature_count": int(
                    integrity.get("unsupported_signature_count") or 0
                ),
                **self._shared_library_signer_context(integrity.get("signature_fingerprint")),
            }
            if integrity_status in {"invalid", "missing_file", "unreadable"}:
                integrity_blocked_records.append(
                    {
                        **enriched_record,
                        "reasons": ["invalid_integrity"],
                        "verification_issue_code": "invalid_integrity",
                    }
                )
                continue
            if signature_status == "invalid":
                signature_blocked_records.append(
                    {
                        **enriched_record,
                        "reasons": ["invalid_signature"],
                        "verification_issue_code": "invalid_signature",
                    }
                )
                continue
            if integrity_status == "missing":
                integrity_unverified_records.append(
                    {
                        **enriched_record,
                        "verification_issue_code": "missing_content_hash",
                    }
                )
            elif signature_status in {"missing", "unsupported"}:
                signature_unverified_records.append(
                    {
                        **enriched_record,
                        "verification_issue_code": (
                            "missing_signature"
                            if signature_status == "missing"
                            else "unsupported_signature"
                        ),
                    }
                )
            integrity_ok_records.append(dict(enriched_record))
            if signature_status == "verified":
                signature_verified_records.append(dict(enriched_record))

        revoked_signer_result = self.filter_shared_library_records_by_revoked_signer_fingerprints(
            signature_verified_records,
            revoked_signer_fingerprints,
        )
        revoked_signer_records = list(revoked_signer_result.get("revoked_records") or [])
        revoked_signer_identities = {
            self._shared_library_approval_identity_key(record) for record in revoked_signer_records
        }
        for record in revoked_signer_records:
            signature_blocked_records.append(
                {
                    **dict(record),
                    "reasons": ["revoked_signer"],
                    "verification_issue_code": "revoked_signature",
                }
            )

        policy_candidate_records = [
            dict(record)
            for record in integrity_ok_records
            if self._shared_library_approval_identity_key(record) not in revoked_signer_identities
        ]
        signer_candidate_records = list(revoked_signer_result.get("allowed_records") or [])

        trust_result = self.filter_shared_library_records_by_source_apps(
            policy_candidate_records,
            trusted_source_apps,
        )
        package_type_result = self.filter_shared_library_records_by_package_types(
            policy_candidate_records,
            allowed_package_types,
        )
        signer_result = self.filter_shared_library_records_by_signer_fingerprints(
            signer_candidate_records,
            trusted_signer_fingerprints,
        )
        trusted_records = list(trust_result.get("trusted_records") or [])
        untrusted_records = list(trust_result.get("untrusted_records") or [])
        blocked_package_type_records = list(package_type_result.get("blocked_records") or [])
        untrusted_signer_records = list(signer_result.get("untrusted_records") or [])
        expired_signer_records = list(signer_result.get("expired_records") or [])
        rotation_result = self.filter_shared_library_records_by_rotation_policy(
            list(signer_result.get("trusted_records") or []),
            due_policy=rotation_due_policy,
            overdue_policy=rotation_overdue_policy,
        )
        rotation_warning_records = list(rotation_result.get("warning_records") or [])
        rotation_approval_records = list(rotation_result.get("approval_records") or [])
        rotation_blocked_records = list(rotation_result.get("blocked_records") or [])
        rotation_due_records = list(rotation_result.get("due_records") or [])
        rotation_overdue_records = list(rotation_result.get("overdue_records") or [])
        rotation_exception_records = list(rotation_result.get("exception_records") or [])
        rotation_blocked_identities = {
            self._shared_library_approval_identity_key(record)
            for record in rotation_blocked_records
        }
        team_rule_result = self.filter_shared_library_records_by_team_approval_rules(
            [
                dict(record)
                for record in policy_candidate_records
                if self._shared_library_approval_identity_key(record)
                not in rotation_blocked_identities
            ]
        )
        team_rule_approval_records = list(team_rule_result.get("approval_records") or [])
        team_rule_blocked_records = list(team_rule_result.get("blocked_records") or [])
        team_rule_blocked_identities = {
            self._shared_library_approval_identity_key(record)
            for record in team_rule_blocked_records
        }

        approvals = self.load_shared_library_approval_records()
        approval_candidates: Dict[tuple[str, str, str, str, int], Dict[str, Any]] = {}
        approval_required_records: List[Dict[str, Any]] = []
        approved_override_records: List[Dict[str, Any]] = []
        rejected_records: List[Dict[str, Any]] = []

        def _add_approval_reason(record: Dict[str, Any], reason: str) -> None:
            identity = self._shared_library_approval_identity_key(record)
            current = approval_candidates.get(identity)
            if current is None:
                approval_candidates[identity] = {
                    **dict(record),
                    "reasons": [reason],
                    "matched_team_approval_rules": _normalize_shared_library_team_approval_rule_matches(
                        record.get("matched_team_approval_rules")
                    ),
                    "matched_team_approval_levels": _normalize_shared_library_team_approval_rule_matches(
                        record.get("matched_team_approval_levels")
                    ),
                    "required_signature_count": max(
                        int(record.get("required_signature_count") or 0),
                        0,
                    ),
                }
                return
            approval_candidates[identity] = {
                **current,
                **dict(record),
                "reasons": _normalize_command_list(list(current.get("reasons") or []) + [reason]),
                "matched_team_approval_rules": _normalize_shared_library_team_approval_rule_matches(
                    list(current.get("matched_team_approval_rules") or [])
                    + list(record.get("matched_team_approval_rules") or [])
                ),
                "matched_team_approval_levels": _normalize_shared_library_team_approval_rule_matches(
                    list(current.get("matched_team_approval_levels") or [])
                    + list(record.get("matched_team_approval_levels") or [])
                ),
                "required_signature_count": max(
                    int(current.get("required_signature_count") or 0),
                    int(record.get("required_signature_count") or 0),
                ),
            }

        for record in untrusted_records:
            _add_approval_reason(record, "untrusted_source")
        for record in blocked_package_type_records:
            _add_approval_reason(record, "blocked_package_type")
        for record in untrusted_signer_records:
            _add_approval_reason(record, "untrusted_signer")
        for record in expired_signer_records:
            _add_approval_reason(record, "expired_signer_policy")
        for record in rotation_approval_records:
            rotation_status = str(record.get("rotation_status") or "").strip()
            _add_approval_reason(
                record,
                (
                    "rotation_overdue_signer"
                    if rotation_status == "overdue"
                    else "rotation_due_signer"
                ),
            )
        for record in rotation_blocked_records:
            rotation_status = str(record.get("rotation_status") or "").strip()
            signature_blocked_records.append(
                {
                    **dict(record),
                    "reasons": [
                        (
                            "rotation_overdue_signer"
                            if rotation_status == "overdue"
                            else "rotation_due_signer"
                        )
                    ],
                    "verification_issue_code": (
                        "rotation_overdue_signer"
                        if rotation_status == "overdue"
                        else "rotation_due_signer"
                    ),
                }
            )
        for record in team_rule_approval_records:
            for rule_name in list(record.get("matched_team_approval_rules") or []):
                _add_approval_reason(record, f"team_rule:{rule_name}")
        for record in team_rule_blocked_records:
            matched_rule_names = _normalize_shared_library_team_approval_rule_matches(
                record.get("matched_team_approval_rules")
            )
            signature_blocked_records.append(
                {
                    **dict(record),
                    "reasons": [f"team_rule_block:{rule_name}" for rule_name in matched_rule_names]
                    or ["team_rule_block"],
                    "verification_issue_code": "team_rule_block",
                }
            )

        importable_records = [
            dict(record)
            for record in policy_candidate_records
            if self._shared_library_approval_identity_key(record) not in approval_candidates
            and self._shared_library_approval_identity_key(record)
            not in rotation_blocked_identities
            and self._shared_library_approval_identity_key(record)
            not in team_rule_blocked_identities
        ]

        for record in approval_candidates.values():
            if self._shared_library_approval_identity_key(record) in team_rule_blocked_identities:
                continue
            approval_record = self.get_shared_library_approval_record(
                record,
                approval_records=approvals,
            )
            decision = str((approval_record or {}).get("decision") or "pending")
            reason_record = {
                **dict(record),
                "reasons": _normalize_command_list(record.get("reasons")),
            }
            if decision == "approved":
                importable_records.append(dict(record))
                approved_override_records.append(reason_record)
            elif decision == "rejected":
                rejected_records.append(reason_record)
            else:
                approval_required_records.append(reason_record)

        importable_signatures: set[tuple[str, str, int, str, str]] = set()
        deduplicated_importable_records: List[Dict[str, Any]] = []
        for record in importable_records:
            signature = self._shared_library_record_signature(record)
            if signature in importable_signatures:
                continue
            importable_signatures.add(signature)
            deduplicated_importable_records.append(dict(record))

        return {
            "importable_records": deduplicated_importable_records,
            "trusted_records": trusted_records,
            "untrusted_records": untrusted_records,
            "integrity_blocked_records": integrity_blocked_records,
            "integrity_unverified_records": integrity_unverified_records,
            "signature_blocked_records": signature_blocked_records,
            "signature_unverified_records": signature_unverified_records,
            "revoked_signer_records": revoked_signer_records,
            "blocked_package_type_records": blocked_package_type_records,
            "untrusted_signer_records": untrusted_signer_records,
            "expired_signer_records": expired_signer_records,
            "rotation_warning_records": rotation_warning_records,
            "rotation_approval_records": rotation_approval_records,
            "rotation_blocked_records": rotation_blocked_records,
            "rotation_due_records": rotation_due_records,
            "rotation_overdue_records": rotation_overdue_records,
            "rotation_exception_records": rotation_exception_records,
            "approval_required_records": approval_required_records,
            "approved_override_records": approved_override_records,
            "rejected_records": rejected_records,
            "trusted_source_apps": list(trust_result.get("trusted_source_apps") or []),
            "untrusted_sources": list(trust_result.get("untrusted_sources") or []),
            "trusted_signer_fingerprints": list(
                signer_result.get("trusted_signer_fingerprints") or []
            ),
            "untrusted_signers": list(signer_result.get("untrusted_signers") or []),
            "expired_policy_signers": list(signer_result.get("expired_policy_signers") or []),
            "rotation_due_signers": list(rotation_result.get("due_signers") or []),
            "rotation_overdue_signers": list(rotation_result.get("overdue_signers") or []),
            "rotation_exception_signers": list(rotation_result.get("exception_signers") or []),
            "revoked_signer_fingerprints": list(
                revoked_signer_result.get("revoked_signer_fingerprints") or []
            ),
            "revoked_signers": list(revoked_signer_result.get("revoked_signers") or []),
            "allowed_package_types": list(package_type_result.get("allowed_package_types") or []),
            "blocked_package_types": list(package_type_result.get("blocked_package_types") or []),
            "rotation_due_policy": str(rotation_result.get("due_policy") or ""),
            "rotation_overdue_policy": str(rotation_result.get("overdue_policy") or ""),
        }

    def inspect_shared_library_pull_integrity(
        self,
        sync_dir: Union[str, Path],
        *,
        trusted_source_apps: Optional[List[str]] = None,
        trusted_signer_fingerprints: Optional[List[str]] = None,
        revoked_signer_fingerprints: Optional[List[str]] = None,
        allowed_package_types: Optional[List[str]] = None,
        rotation_due_policy: Optional[str] = None,
        rotation_overdue_policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """检查共享仓库拉取阶段的完整性状态。"""
        root = Path(sync_dir)
        if not root.exists():
            raise ConfigurationError("共享仓库目录不存在")

        snapshot = self._load_external_shared_library_snapshot(root)
        external_records = list(snapshot.get("records") or [])
        if not external_records:
            external_records = self._scan_external_shared_library_packages(root)

        classification = self.classify_shared_library_pull_records(
            external_records,
            trusted_source_apps=trusted_source_apps,
            trusted_signer_fingerprints=trusted_signer_fingerprints,
            revoked_signer_fingerprints=revoked_signer_fingerprints,
            allowed_package_types=allowed_package_types,
            rotation_due_policy=rotation_due_policy,
            rotation_overdue_policy=rotation_overdue_policy,
        )
        integrity_blocked_records = list(classification.get("integrity_blocked_records") or [])
        signature_blocked_records = list(classification.get("signature_blocked_records") or [])
        blocked_records = integrity_blocked_records + signature_blocked_records
        integrity_unverified_records = list(
            classification.get("integrity_unverified_records") or []
        )
        signature_unverified_records = list(
            classification.get("signature_unverified_records") or []
        )
        unverified_records = integrity_unverified_records + signature_unverified_records
        return {
            "sync_dir": str(root),
            "index_version": max(int(snapshot.get("index_version") or 0), 0),
            "record_count": len(external_records),
            "blocked_count": len(blocked_records),
            "unverified_count": len(unverified_records),
            "blocked_records": blocked_records,
            "unverified_records": unverified_records,
            "integrity_blocked_count": len(integrity_blocked_records),
            "signature_blocked_count": len(signature_blocked_records),
            "revoked_signer_count": len(classification.get("revoked_signer_records") or []),
            "expired_signer_policy_count": len(classification.get("expired_signer_records") or []),
            "rotation_due_count": len(classification.get("rotation_due_records") or []),
            "rotation_overdue_count": len(classification.get("rotation_overdue_records") or []),
            "rotation_warning_count": len(classification.get("rotation_warning_records") or []),
            "rotation_exception_count": len(classification.get("rotation_exception_records") or []),
            "integrity_unverified_count": len(integrity_unverified_records),
            "signature_unverified_count": len(signature_unverified_records),
            "revoked_signers": list(classification.get("revoked_signers") or []),
            "expired_policy_signers": list(classification.get("expired_policy_signers") or []),
            "rotation_due_signers": list(classification.get("rotation_due_signers") or []),
            "rotation_overdue_signers": list(classification.get("rotation_overdue_signers") or []),
            "rotation_exception_signers": list(
                classification.get("rotation_exception_signers") or []
            ),
            "trusted_source_apps": list(classification.get("trusted_source_apps") or []),
            "trusted_signer_fingerprints": list(
                classification.get("trusted_signer_fingerprints") or []
            ),
            "revoked_signer_fingerprints": list(
                classification.get("revoked_signer_fingerprints") or []
            ),
            "allowed_package_types": list(classification.get("allowed_package_types") or []),
        }

    def inspect_shared_library_lock(self, sync_dir: Union[str, Path]) -> Dict[str, Any]:
        """检查共享仓库锁状态。"""
        root = Path(sync_dir)
        lock_path = self.shared_library_lock_path(root)
        if not lock_path.exists():
            return {
                "active": False,
                "stale": False,
                "exists": False,
                "lock_path": str(lock_path),
            }

        payload = self._load_mapping(lock_path)
        created_at = str(payload.get("created_at") or "").strip() or None
        expires_at = str(payload.get("expires_at") or "").strip() or None
        stale = False
        if expires_at:
            try:
                stale = datetime.now(timezone.utc) >= datetime.fromisoformat(expires_at)
            except ValueError:
                stale = True

        return {
            "active": not stale,
            "stale": stale,
            "exists": True,
            "lock_id": str(payload.get("lock_id") or "").strip() or None,
            "operation": str(payload.get("operation") or "").strip() or None,
            "owner": str(payload.get("owner") or "").strip() or None,
            "hostname": str(payload.get("hostname") or "").strip() or None,
            "pid": max(int(payload.get("pid") or 0), 0),
            "created_at": created_at,
            "expires_at": expires_at,
            "lock_path": str(lock_path),
        }

    def acquire_shared_library_lock(
        self,
        sync_dir: Union[str, Path],
        operation: str,
        *,
        force: bool = False,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取共享仓库操作锁。"""
        root = Path(sync_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._secure_directory(root)
        lock_path = self.shared_library_lock_path(root)
        timeout = _normalize_shared_library_lock_timeout(
            timeout_seconds
            if timeout_seconds is not None
            else self.app_config.shared_library_lock_timeout
        )
        lock_state = self.inspect_shared_library_lock(root)
        if lock_state.get("active") and not force:
            owner = str(lock_state.get("owner") or "未知终端")
            operation_name = str(lock_state.get("operation") or "同步任务")
            raise ConfigurationError(f"共享仓库正在被锁定: {owner} 正在执行 {operation_name}")
        if lock_state.get("stale") and not force:
            raise ConfigurationError("共享仓库存在过期锁，请确认后强制接管")

        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires_at = now.timestamp() + timeout
        payload = {
            "lock_id": str(uuid4()),
            "operation": str(operation or "sync").strip() or "sync",
            "owner": f"Neko_Shell@{socket.gethostname()}",
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "created_at": now.isoformat(),
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "timeout_seconds": timeout,
        }
        self._write_mapping(lock_path, payload)
        return {
            **payload,
            "force_takeover": bool(force and lock_state.get("exists")),
            "lock_path": str(lock_path),
        }

    def release_shared_library_lock(self, sync_dir: Union[str, Path], lock_id: str) -> None:
        """释放共享仓库操作锁。"""
        lock_path = self.shared_library_lock_path(sync_dir)
        if not lock_path.exists():
            return
        payload = self._load_mapping(lock_path)
        current_lock_id = str(payload.get("lock_id") or "").strip()
        if current_lock_id and current_lock_id != str(lock_id or "").strip():
            return
        lock_path.unlink(missing_ok=True)

    def _run_with_shared_library_lock(
        self,
        sync_dir: Union[str, Path],
        operation: str,
        callback: Any,
        *,
        force_lock: bool = False,
    ) -> Dict[str, Any]:
        """在共享仓库锁保护下执行同步操作。"""
        lock_info = self.acquire_shared_library_lock(
            sync_dir,
            operation,
            force=force_lock,
        )
        try:
            result = callback()
        finally:
            self.release_shared_library_lock(sync_dir, str(lock_info.get("lock_id") or ""))
        result["lock"] = lock_info
        return result

    @staticmethod
    def _make_unique_file_path(path: Path) -> Path:
        """为目标文件生成唯一可写路径。"""
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        counter = 2
        while True:
            candidate = path.with_name(f"{stem}-{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _load_external_shared_library_snapshot(
        self,
        sync_dir: Union[str, Path],
    ) -> Dict[str, Any]:
        """读取外部共享仓库索引快照。"""
        root = Path(sync_dir)
        index_path = root / "shared-library-index.yaml"
        if not index_path.exists():
            return {
                "index_version": 0,
                "exported_at": None,
                "records": [],
            }
        data = self._load_mapping(index_path)
        records: List[Dict[str, Any]] = []
        for record in self._extract_records(data, "shared_packages"):
            if not isinstance(record, dict):
                continue
            relative_path = str(record.get("relative_path") or "").strip()
            file_path = str(record.get("file_path") or "").strip()
            resolved_path = (
                root / relative_path if relative_path else Path(file_path) if file_path else None
            )
            if resolved_path is None:
                continue
            current = dict(record)
            current["file_path"] = str(resolved_path)
            current["relative_path"] = relative_path or None
            records.append(current)
        return {
            "index_version": max(int(data.get("index_version") or 0), 0),
            "exported_at": str(data.get("exported_at") or "").strip() or None,
            "records": self._normalize_shared_library_records(records),
        }

    def _build_shared_library_sync_preview(
        self,
        *,
        action: str,
        source_records: List[Dict[str, Any]],
        target_records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """构造共享中心同步预览摘要。"""
        target_signatures = {
            self._shared_library_record_signature(record) for record in target_records
        }
        target_by_identity: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        for record in target_records:
            target_by_identity.setdefault(self._shared_library_identity_key(record), []).append(
                record
            )
        for candidates in target_by_identity.values():
            candidates.sort(
                key=lambda item: (
                    _normalize_package_version(item.get("package_version")),
                    str(item.get("updated_at") or item.get("created_at") or ""),
                ),
                reverse=True,
            )
        preview = {
            "action": action,
            "record_count": len(source_records),
            "new_count": 0,
            "exact_match_count": 0,
            "conflict_count": 0,
            "newer_local_count": 0,
            "older_local_count": 0,
            "newer_external_count": 0,
            "older_external_count": 0,
            "skipped_missing": 0,
            "conflicts": [],
        }

        for source_record in source_records:
            source_path = Path(str(source_record.get("file_path") or ""))
            if not source_path.exists():
                preview["skipped_missing"] += 1
                continue

            source_signature = self._shared_library_record_signature(source_record)
            if source_signature in target_signatures:
                preview["exact_match_count"] += 1
                continue

            target_candidates = target_by_identity.get(
                self._shared_library_identity_key(source_record)
            )
            if not target_candidates:
                preview["new_count"] += 1
                continue

            target_record = target_candidates[0]
            source_version = _normalize_package_version(source_record.get("package_version"))
            target_version = _normalize_package_version(target_record.get("package_version"))
            source_hash = str(source_record.get("content_hash") or "").strip()
            target_hash = str(target_record.get("content_hash") or "").strip()
            if source_hash and target_hash and source_hash == target_hash:
                preview["exact_match_count"] += 1
                continue

            if action == "push":
                if source_version > target_version:
                    status = "newer_local"
                    preview["newer_local_count"] += 1
                elif source_version < target_version:
                    status = "older_local"
                    preview["older_local_count"] += 1
                else:
                    status = "conflict"
                    preview["conflict_count"] += 1
            else:
                if source_version > target_version:
                    status = "newer_external"
                    preview["newer_external_count"] += 1
                elif source_version < target_version:
                    status = "older_external"
                    preview["older_external_count"] += 1
                else:
                    status = "conflict"
                    preview["conflict_count"] += 1

            if len(preview["conflicts"]) < 10:
                preview["conflicts"].append(
                    {
                        "name": str(source_record.get("name") or "未命名共享包"),
                        "package_type": str(source_record.get("package_type") or "").strip(),
                        "status": status,
                        "local_version": source_version if action == "push" else target_version,
                        "external_version": target_version if action == "push" else source_version,
                    }
                )

        return preview

    def _load_external_shared_library_index(
        self, sync_dir: Union[str, Path]
    ) -> List[Dict[str, Any]]:
        """从外部共享目录读取共享索引。"""
        return list(self._load_external_shared_library_snapshot(sync_dir).get("records") or [])

    def _scan_external_shared_library_packages(
        self, sync_dir: Union[str, Path]
    ) -> List[Dict[str, Any]]:
        """扫描外部共享目录中的共享包。"""
        root = Path(sync_dir)
        records: List[Dict[str, Any]] = []
        for package_type in ("workspace_templates", "connection_filter_presets"):
            package_dir = root / package_type
            if not package_dir.exists():
                continue
            for path in sorted(package_dir.glob("*.y*ml")):
                try:
                    payload = self._load_mapping(path)
                    record = self._shared_library_record_from_package(package_type, path, payload)
                except Exception:
                    continue
                records.append(record)
            for path in sorted(package_dir.glob("*.json")):
                try:
                    payload = self._load_mapping(path)
                    record = self._shared_library_record_from_package(package_type, path, payload)
                except Exception:
                    continue
                records.append(record)
        return self._normalize_shared_library_records(records)

    def preview_shared_library_push(
        self,
        sync_dir: Union[str, Path],
    ) -> Dict[str, Any]:
        """预览将本地共享中心推送到外部共享仓库的结果。"""
        root = Path(sync_dir)
        local_records = self.load_shared_library_records()
        snapshot = self._load_external_shared_library_snapshot(root)
        external_records = list(snapshot.get("records") or [])
        if not external_records:
            external_records = self._scan_external_shared_library_packages(root)

        preview = self._build_shared_library_sync_preview(
            action="push",
            source_records=local_records,
            target_records=external_records,
        )
        preview["sync_dir"] = str(root)
        preview["index_version"] = max(int(snapshot.get("index_version") or 0), 0)
        return preview

    def preview_shared_library_pull(
        self,
        sync_dir: Union[str, Path],
        *,
        trusted_source_apps: Optional[List[str]] = None,
        trusted_signer_fingerprints: Optional[List[str]] = None,
        revoked_signer_fingerprints: Optional[List[str]] = None,
        allowed_package_types: Optional[List[str]] = None,
        rotation_due_policy: Optional[str] = None,
        rotation_overdue_policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """预览从外部共享仓库拉取到本地共享中心的结果。"""
        root = Path(sync_dir)
        if not root.exists():
            raise ConfigurationError("共享仓库目录不存在")

        snapshot = self._load_external_shared_library_snapshot(root)
        external_records = list(snapshot.get("records") or [])
        if not external_records:
            external_records = self._scan_external_shared_library_packages(root)

        classification = self.classify_shared_library_pull_records(
            external_records,
            trusted_source_apps=trusted_source_apps,
            trusted_signer_fingerprints=trusted_signer_fingerprints,
            revoked_signer_fingerprints=revoked_signer_fingerprints,
            allowed_package_types=allowed_package_types,
            rotation_due_policy=rotation_due_policy,
            rotation_overdue_policy=rotation_overdue_policy,
        )
        importable_records = list(classification.get("importable_records") or [])

        preview = self._build_shared_library_sync_preview(
            action="pull",
            source_records=importable_records,
            target_records=self.load_shared_library_records(),
        )
        preview["sync_dir"] = str(root)
        preview["index_version"] = max(int(snapshot.get("index_version") or 0), 0)
        preview["external_record_count"] = len(external_records)
        preview["trusted_record_count"] = len(classification.get("trusted_records") or [])
        preview["importable_record_count"] = len(importable_records)
        preview["untrusted_count"] = len(classification.get("untrusted_records") or [])
        preview["integrity_blocked_count"] = len(
            classification.get("integrity_blocked_records") or []
        )
        preview["integrity_unverified_count"] = len(
            classification.get("integrity_unverified_records") or []
        )
        preview["signature_blocked_count"] = len(
            classification.get("signature_blocked_records") or []
        )
        preview["signature_unverified_count"] = len(
            classification.get("signature_unverified_records") or []
        )
        preview["revoked_signer_count"] = len(classification.get("revoked_signer_records") or [])
        preview["expired_signer_policy_count"] = len(
            classification.get("expired_signer_records") or []
        )
        preview["rotation_due_count"] = len(classification.get("rotation_due_records") or [])
        preview["rotation_overdue_count"] = len(
            classification.get("rotation_overdue_records") or []
        )
        preview["rotation_warning_count"] = len(
            classification.get("rotation_warning_records") or []
        )
        preview["rotation_exception_count"] = len(
            classification.get("rotation_exception_records") or []
        )
        preview["untrusted_signer_count"] = len(
            classification.get("untrusted_signer_records") or []
        )
        preview["untrusted_sources"] = list(classification.get("untrusted_sources") or [])
        preview["revoked_signers"] = list(classification.get("revoked_signers") or [])
        preview["expired_policy_signers"] = list(classification.get("expired_policy_signers") or [])
        preview["rotation_due_signers"] = list(classification.get("rotation_due_signers") or [])
        preview["rotation_overdue_signers"] = list(
            classification.get("rotation_overdue_signers") or []
        )
        preview["rotation_exception_signers"] = list(
            classification.get("rotation_exception_signers") or []
        )
        preview["untrusted_signers"] = list(classification.get("untrusted_signers") or [])
        preview["trusted_source_apps"] = list(classification.get("trusted_source_apps") or [])
        preview["trusted_signer_fingerprints"] = list(
            classification.get("trusted_signer_fingerprints") or []
        )
        preview["revoked_signer_fingerprints"] = list(
            classification.get("revoked_signer_fingerprints") or []
        )
        preview["allowed_package_types"] = list(classification.get("allowed_package_types") or [])
        preview["blocked_package_type_count"] = len(
            classification.get("blocked_package_type_records") or []
        )
        preview["blocked_package_types"] = list(classification.get("blocked_package_types") or [])
        preview["approval_required_count"] = len(
            classification.get("approval_required_records") or []
        )
        preview["approved_override_count"] = len(
            classification.get("approved_override_records") or []
        )
        preview["rejected_count"] = len(classification.get("rejected_records") or [])
        preview["rotation_due_policy"] = str(classification.get("rotation_due_policy") or "")
        preview["rotation_overdue_policy"] = str(
            classification.get("rotation_overdue_policy") or ""
        )
        return preview

    def push_shared_library_to_directory(
        self,
        sync_dir: Union[str, Path],
        *,
        force_lock: bool = False,
    ) -> Dict[str, Any]:
        """将本地共享中心推送到外部共享目录。"""
        root = Path(sync_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._secure_directory(root)

        def _push() -> Dict[str, Any]:
            snapshot = self._load_external_shared_library_snapshot(root)
            preview = self.preview_shared_library_push(root)
            records = self.load_shared_library_records()
            external_records = list(snapshot.get("records") or [])
            if not external_records:
                external_records = self._scan_external_shared_library_packages(root)
            synced_records_by_signature: Dict[
                tuple[str, str, int, str, str],
                Dict[str, Any],
            ] = {
                self._shared_library_record_signature(record): dict(record)
                for record in external_records
                if Path(str(record.get("file_path") or "")).exists()
            }
            pushed_count = 0
            created_count = 0
            updated_count = 0
            skipped_missing = 0

            for record in records:
                package_type = str(record.get("package_type") or "").strip()
                source_path = Path(str(record.get("file_path") or ""))
                if not source_path.exists():
                    skipped_missing += 1
                    continue
                target_dir = root / package_type
                target_dir.mkdir(parents=True, exist_ok=True)
                target_path = target_dir / source_path.name
                if not target_path.exists() or source_path.read_bytes() != target_path.read_bytes():
                    existed = target_path.exists()
                    shutil.copy2(source_path, target_path)
                    pushed_count += 1
                    if existed:
                        updated_count += 1
                    else:
                        created_count += 1
                synced_record = {
                    **dict(record),
                    "relative_path": f"{package_type}/{target_path.name}",
                    "file_path": str(target_path),
                }
                synced_records_by_signature[
                    self._shared_library_record_signature(synced_record)
                ] = synced_record

            synced_records = list(synced_records_by_signature.values())

            payload = {
                "version": SHARED_LIBRARY_INDEX_FORMAT_VERSION,
                "index_version": max(int(snapshot.get("index_version") or 0), 0) + 1,
                "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "shared_packages": [
                    {key: value for key, value in record.items() if key != "file_path"}
                    for record in synced_records
                ],
            }
            self._write_mapping(root / "shared-library-index.yaml", payload)
            result = {
                "record_count": len(synced_records),
                "pushed_count": pushed_count,
                "created_count": created_count,
                "updated_count": updated_count,
                "exact_match_count": int(preview.get("exact_match_count") or 0),
                "new_count": int(preview.get("new_count") or 0),
                "conflict_count": int(preview.get("conflict_count") or 0),
                "newer_local_count": int(preview.get("newer_local_count") or 0),
                "older_local_count": int(preview.get("older_local_count") or 0),
                "skipped_missing": skipped_missing,
                "index_version": int(payload["index_version"]),
                "sync_dir": str(root),
            }
            self.append_shared_library_sync_history(
                {
                    "action": "push",
                    "sync_dir": str(root),
                    "record_count": result["record_count"],
                    "new_count": result["new_count"],
                    "exact_match_count": result["exact_match_count"],
                    "conflict_count": result["conflict_count"],
                    "newer_local_count": result["newer_local_count"],
                    "older_local_count": result["older_local_count"],
                    "created_count": created_count,
                    "updated_count": updated_count,
                    "pushed_count": pushed_count,
                    "skipped_missing": skipped_missing,
                    "index_version": result["index_version"],
                    "conflicts": list(preview.get("conflicts") or [])[:10],
                }
            )
            return result

        return self._run_with_shared_library_lock(
            root,
            "push",
            _push,
            force_lock=force_lock,
        )

    def pull_shared_library_from_directory(
        self,
        sync_dir: Union[str, Path],
        *,
        force_lock: bool = False,
        trusted_source_apps: Optional[List[str]] = None,
        trusted_signer_fingerprints: Optional[List[str]] = None,
        revoked_signer_fingerprints: Optional[List[str]] = None,
        allowed_package_types: Optional[List[str]] = None,
        rotation_due_policy: Optional[str] = None,
        rotation_overdue_policy: Optional[str] = None,
        queue_pending_approvals: bool = False,
    ) -> Dict[str, Any]:
        """从外部共享目录拉取共享包到本地共享中心。"""
        root = Path(sync_dir)
        if not root.exists():
            raise ConfigurationError("共享仓库目录不存在")

        def _pull() -> Dict[str, Any]:
            snapshot = self._load_external_shared_library_snapshot(root)
            external_records = list(snapshot.get("records") or [])
            if not external_records:
                external_records = self._scan_external_shared_library_packages(root)

            classification = self.classify_shared_library_pull_records(
                external_records,
                trusted_source_apps=trusted_source_apps,
                trusted_signer_fingerprints=trusted_signer_fingerprints,
                revoked_signer_fingerprints=revoked_signer_fingerprints,
                allowed_package_types=allowed_package_types,
                rotation_due_policy=rotation_due_policy,
                rotation_overdue_policy=rotation_overdue_policy,
            )
            importable_records = list(classification.get("importable_records") or [])
            preview = self.preview_shared_library_pull(
                root,
                trusted_source_apps=trusted_source_apps,
                trusted_signer_fingerprints=trusted_signer_fingerprints,
                revoked_signer_fingerprints=revoked_signer_fingerprints,
                allowed_package_types=allowed_package_types,
                rotation_due_policy=rotation_due_policy,
                rotation_overdue_policy=rotation_overdue_policy,
            )
            local_records = self.load_shared_library_records()
            known_signatures = {
                self._shared_library_record_signature(record) for record in local_records
            }

            imported_count = 0
            skipped_count = 0
            for external_record in importable_records:
                signature = self._shared_library_record_signature(external_record)
                source_path = Path(str(external_record.get("file_path") or ""))
                if signature in known_signatures or not source_path.exists():
                    skipped_count += 1
                    continue

                package_type = str(external_record.get("package_type") or "").strip()
                target_dir = self._shared_library_directory_for_type(package_type)
                target_path = self._make_unique_file_path(target_dir / source_path.name)
                shutil.copy2(source_path, target_path)
                payload = self._load_mapping(target_path)
                local_record = self._shared_library_record_from_package(
                    package_type, target_path, payload
                )
                local_record["description"] = external_record.get("description")
                local_record["source_scope"] = external_record.get("source_scope")
                local_record["exported_by"] = external_record.get("exported_by")
                local_record["labels"] = _normalize_share_labels(external_record.get("labels"))
                local_record["exported_at"] = external_record.get("exported_at")
                local_record["sample_names"] = [
                    str(name)
                    for name in (
                        external_record.get("sample_names")
                        or local_record.get("sample_names")
                        or []
                    )
                    if str(name).strip()
                ][:10]
                local_records.append(local_record)
                known_signatures.add(signature)
                imported_count += 1

            queued_pending_records: List[Dict[str, Any]] = []
            if queue_pending_approvals:
                queued_pending_records = self.queue_shared_library_approval_records(
                    root,
                    list(classification.get("approval_required_records") or []),
                )

            self.save_shared_library_records(local_records)
            result = {
                "record_count": len(importable_records),
                "imported_count": imported_count,
                "skipped_count": skipped_count,
                "new_count": int(preview.get("new_count") or 0),
                "exact_match_count": int(preview.get("exact_match_count") or 0),
                "conflict_count": int(preview.get("conflict_count") or 0),
                "newer_external_count": int(preview.get("newer_external_count") or 0),
                "older_external_count": int(preview.get("older_external_count") or 0),
                "index_version": max(int(snapshot.get("index_version") or 0), 0),
                "untrusted_count": len(classification.get("untrusted_records") or []),
                "integrity_blocked_count": len(
                    classification.get("integrity_blocked_records") or []
                ),
                "integrity_unverified_count": len(
                    classification.get("integrity_unverified_records") or []
                ),
                "signature_blocked_count": len(
                    classification.get("signature_blocked_records") or []
                ),
                "signature_unverified_count": len(
                    classification.get("signature_unverified_records") or []
                ),
                "revoked_signer_count": len(classification.get("revoked_signer_records") or []),
                "expired_signer_policy_count": len(
                    classification.get("expired_signer_records") or []
                ),
                "rotation_due_count": len(classification.get("rotation_due_records") or []),
                "rotation_overdue_count": len(classification.get("rotation_overdue_records") or []),
                "rotation_warning_count": len(classification.get("rotation_warning_records") or []),
                "rotation_exception_count": len(
                    classification.get("rotation_exception_records") or []
                ),
                "untrusted_signer_count": len(classification.get("untrusted_signer_records") or []),
                "trusted_record_count": len(classification.get("trusted_records") or []),
                "blocked_package_type_count": len(
                    classification.get("blocked_package_type_records") or []
                ),
                "blocked_package_types": list(classification.get("blocked_package_types") or []),
                "approval_required_count": len(
                    classification.get("approval_required_records") or []
                ),
                "approved_override_count": len(
                    classification.get("approved_override_records") or []
                ),
                "pending_approval_count": len(queued_pending_records),
                "sync_dir": str(root),
            }
            self.append_shared_library_sync_history(
                {
                    "action": "pull",
                    "sync_dir": str(root),
                    "record_count": result["record_count"],
                    "new_count": result["new_count"],
                    "exact_match_count": result["exact_match_count"],
                    "conflict_count": result["conflict_count"],
                    "newer_external_count": result["newer_external_count"],
                    "older_external_count": result["older_external_count"],
                    "imported_count": imported_count,
                    "skipped_count": skipped_count,
                    "index_version": result["index_version"],
                    "untrusted_count": result["untrusted_count"],
                    "integrity_blocked_count": result["integrity_blocked_count"],
                    "integrity_unverified_count": result["integrity_unverified_count"],
                    "signature_blocked_count": result["signature_blocked_count"],
                    "signature_unverified_count": result["signature_unverified_count"],
                    "revoked_signer_count": result["revoked_signer_count"],
                    "expired_signer_policy_count": result["expired_signer_policy_count"],
                    "rotation_due_count": result["rotation_due_count"],
                    "rotation_overdue_count": result["rotation_overdue_count"],
                    "rotation_warning_count": result["rotation_warning_count"],
                    "rotation_exception_count": result["rotation_exception_count"],
                    "untrusted_signer_count": result["untrusted_signer_count"],
                    "blocked_package_type_count": result["blocked_package_type_count"],
                    "approval_required_count": result["approval_required_count"],
                    "approved_override_count": result["approved_override_count"],
                    "conflicts": list(preview.get("conflicts") or [])[:10],
                }
            )
            return result

        return self._run_with_shared_library_lock(
            root,
            "pull",
            _pull,
            force_lock=force_lock,
        )

    def upsert_connection_filter_preset(
        self,
        name: str,
        filters: Dict[str, Any],
        preset_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """新增或更新连接树筛选预设。"""
        preset_name = name.strip()
        if not preset_name:
            raise ConfigurationError("筛选预设名称不能为空")

        presets = self.load_connection_filter_presets()
        existing = next(
            (
                current
                for current in presets
                if current.get("id") == preset_id or current.get("name") == preset_name
            ),
            None,
        )

        preset = {
            "id": preset_id or (existing.get("id") if existing else None) or str(uuid4()),
            "name": preset_name,
            "filters": self._normalize_connection_filter_state(filters),
            "usage_count": _normalize_usage_count(existing.get("usage_count") if existing else 0),
            "last_used_at": existing.get("last_used_at") if existing else None,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

        for index, current in enumerate(presets):
            if current.get("id") == preset["id"] or current.get("name") == preset["name"]:
                presets[index] = preset
                break
        else:
            presets.append(preset)
        self.save_connection_filter_presets(presets)
        return preset

    def remove_connection_filter_preset(self, preset_id: str) -> None:
        """删除连接树筛选预设。"""
        presets = [
            preset
            for preset in self.load_connection_filter_presets()
            if preset.get("id") != preset_id
        ]
        self.save_connection_filter_presets(presets)

    def mark_connection_filter_preset_used(
        self,
        preset_id: str,
        used_at: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """记录筛选预设被应用。"""
        presets = self.load_connection_filter_presets()
        updated: Optional[Dict[str, Any]] = None
        timestamp = used_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        for index, preset in enumerate(presets):
            if preset.get("id") != preset_id:
                continue
            current = dict(preset)
            current["usage_count"] = _normalize_usage_count(current.get("usage_count")) + 1
            current["last_used_at"] = timestamp
            presets[index] = current
            updated = current
            break

        if updated is not None:
            self.save_connection_filter_presets(presets)
        return updated

    def load_templates_for_type(
        self,
        connection_type: str,
        *,
        template_scope: str = "connection",
    ) -> List[Dict[str, Any]]:
        """按连接类型过滤模板。"""
        normalized_scope = self._normalize_connection_template_scope(template_scope)
        filtered = [
            template
            for template in self.load_connection_templates()
            if template.get("connection_type") == connection_type.lower()
            and template.get("template_scope", "connection") == normalized_scope
        ]
        filtered.sort(key=lambda template: str(template.get("name", "")).casefold())
        return filtered
