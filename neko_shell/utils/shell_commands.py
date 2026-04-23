#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shell 命令索引工具。
"""

from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List, Set

from .paths import get_linux_commands_json_path


def _extract_options(option_text: str) -> Set[str]:
    """从描述文本提取命令选项。"""
    if not option_text:
        return set()
    options: Set[str] = set()
    for match in re.finditer(r"(?m)^\s*(--?[A-Za-z0-9][\w\-]*)", option_text):
        options.add(match.group(1))
    for match in re.finditer(r"\b(--?[A-Za-z0-9][\w\-]*)\b", option_text):
        options.add(match.group(1))
    return options


def _walk_tree(nodes: List[dict]) -> Iterable[dict]:
    """遍历命令树节点。"""
    for node in nodes or []:
        yield node
        children = node.get("children") or []
        if isinstance(children, list):
            yield from _walk_tree(children)


def load_command_index() -> Dict[str, object]:
    """加载命令和选项索引。"""
    builtin_commands = {
        "ls", "cd", "pwd", "cat", "echo", "touch", "mkdir", "rm", "rmdir", "cp", "mv", "ln", "find",
        "tail", "head", "less", "more", "wc", "du", "df", "file", "diff", "sed", "awk", "sort", "uniq",
        "tar", "zip", "unzip", "gzip", "gunzip", "bzip2", "xz", "ssh", "scp", "rsync", "ping", "curl",
        "wget", "nc", "ss", "ip", "chmod", "chown", "sudo", "su", "ps", "kill", "killall", "pkill",
        "systemctl", "journalctl", "top", "htop", "free", "uptime", "docker", "git", "python3", "node",
        "npm", "java", "gcc", "make", "hostname", "hostnamectl", "timedatectl", "dmesg", "lsblk", "mount",
        "umount", "cut", "paste", "tr", "grep",
    }
    builtin_options = {
        "ls": {"-l", "-a", "-h", "-t", "-r", "-R", "--color=auto"},
        "rm": {"-f", "-r", "-i", "-v"},
        "cp": {"-r", "-f", "-i", "-v", "-p"},
        "mv": {"-f", "-i", "-v", "-u"},
        "mkdir": {"-p", "-v", "-m"},
        "find": {"-name", "-type", "-size", "-mtime", "-exec", "-print", "-maxdepth"},
        "grep": {"-n", "-i", "-r", "-E", "-F", "-C", "-v", "-l", "-c", "-w", "--color=auto"},
        "tail": {"-n", "-f", "-F"},
        "ssh": {"-p", "-i", "-o", "-t", "-v", "-X", "-Y", "-N", "-f"},
        "scp": {"-P", "-i", "-r", "-v", "-p", "-C"},
        "curl": {"-L", "-I", "-s", "-S", "-o", "-O", "-X", "-H", "-d", "-u", "-k", "-v"},
        "docker": {"ps", "images", "pull", "run", "exec", "logs", "compose", "build", "rm", "stop", "start"},
        "systemctl": {"start", "stop", "restart", "status", "enable", "disable", "reload"},
    }

    commands = set(builtin_commands)
    options: Dict[str, Set[str]] = {name: set(values) for name, values in builtin_options.items()}

    try:
        with get_linux_commands_json_path().open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        for node in _walk_tree(data.get("treeData") or []):
            command = (node.get("command") or "").strip()
            if not command or " " in command:
                continue
            commands.add(command)
            option_set = _extract_options(node.get("option") or "")
            if option_set:
                options.setdefault(command, set()).update(option_set)
    except Exception:
        pass

    return {
        "commands": sorted(commands),
        "options": {name: sorted(values) for name, values in options.items()},
    }
