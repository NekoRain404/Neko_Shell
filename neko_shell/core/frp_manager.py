#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FRP 管理器模块。

提供按需下载 frpc/frps，并在远端服务器上部署 frps 的能力。
该实现尽量保持依赖轻量：只用标准库 + Neko_Shell 自身工具。
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.request import urlopen

from neko_shell.utils import get_default_config_dir, get_logger

logger = get_logger("frp_manager")

FRP_VERSION = "0.61.1"
FRP_GITHUB_BASE = f"https://github.com/fatedier/frp/releases/download/v{FRP_VERSION}"


def _platform_key() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine()
    return system, machine


def _archive_for_local_platform() -> str:
    system, machine = _platform_key()
    mapping = {
        ("Darwin", "x86_64"): f"frp_{FRP_VERSION}_darwin_amd64.tar.gz",
        ("Darwin", "arm64"): f"frp_{FRP_VERSION}_darwin_arm64.tar.gz",
        ("Linux", "x86_64"): f"frp_{FRP_VERSION}_linux_amd64.tar.gz",
        ("Linux", "aarch64"): f"frp_{FRP_VERSION}_linux_arm64.tar.gz",
        ("Linux", "arm64"): f"frp_{FRP_VERSION}_linux_arm64.tar.gz",
        ("Linux", "armv7l"): f"frp_{FRP_VERSION}_linux_arm.tar.gz",
        ("Windows", "AMD64"): f"frp_{FRP_VERSION}_windows_amd64.zip",
        ("Windows", "x86"): f"frp_{FRP_VERSION}_windows_386.zip",
        ("Windows", "arm64"): f"frp_{FRP_VERSION}_windows_arm64.zip",
    }
    archive = mapping.get((system, machine))
    if not archive:
        raise RuntimeError(f"不支持的平台: {system} / {machine}")
    return archive


def _archive_for_server_arch(arch: str) -> str:
    normalized = (arch or "").strip().lower()
    mapping = {
        "x86_64": f"frp_{FRP_VERSION}_linux_amd64.tar.gz",
        "amd64": f"frp_{FRP_VERSION}_linux_amd64.tar.gz",
        "aarch64": f"frp_{FRP_VERSION}_linux_arm64.tar.gz",
        "arm64": f"frp_{FRP_VERSION}_linux_arm64.tar.gz",
        "armv7l": f"frp_{FRP_VERSION}_linux_arm.tar.gz",
    }
    archive = mapping.get(normalized)
    if not archive:
        raise RuntimeError(f"不支持的服务器架构: {arch}")
    return archive


def get_frp_dir() -> Path:
    frp_dir = get_default_config_dir() / "frp"
    frp_dir.mkdir(parents=True, exist_ok=True)
    return frp_dir


def get_local_frpc_path() -> Path:
    if platform.system() == "Windows":
        return get_frp_dir() / "frpc.exe"
    return get_frp_dir() / "frpc"


def get_local_frps_path() -> Path:
    # 本地的 frps 只用于上传到服务器端
    if platform.system() == "Windows":
        return get_frp_dir() / "frps.exe"
    return get_frp_dir() / "frps"


def _is_executable(path: Path) -> bool:
    if not path.exists():
        return False
    if os.name == "nt":
        return True
    return os.access(path, os.X_OK)


def _download_file(
    url: str,
    dest: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    status_callback: Optional[Callable[[str], None]] = None,
) -> None:
    if status_callback:
        status_callback(f"下载: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    with urlopen(url) as response:  # nosec - url comes from fixed GitHub release base
        total = int(response.headers.get("Content-Length") or 0)
        with open(dest, "wb") as file_handle:
            while True:
                chunk = response.read(1024 * 128)
                if not chunk:
                    break
                file_handle.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)


def _extract_binary_from_tar(archive_path: Path, binary_name: str, dest: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as tar:
        member = next(
            (
                m
                for m in tar.getmembers()
                if m.isfile() and (m.name.endswith(f"/{binary_name}") or m.name == binary_name)
            ),
            None,
        )
        if member is None:
            raise RuntimeError(f"压缩包中未找到 {binary_name}")
        extracted = tar.extractfile(member)
        if extracted is None:
            raise RuntimeError(f"无法读取 {binary_name}")
        with extracted:
            with open(dest, "wb") as out:
                shutil.copyfileobj(extracted, out)


def _extract_binary_from_zip(archive_path: Path, binary_name: str, dest: Path) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        name = next(
            (n for n in zf.namelist() if n.endswith(f"/{binary_name}") or n.endswith(binary_name)),
            None,
        )
        if not name:
            raise RuntimeError(f"压缩包中未找到 {binary_name}")
        with zf.open(name) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)


def _ensure_executable(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download_and_extract(
    archive_name: str,
    binary_name: str,
    dest_path: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    status_callback: Optional[Callable[[str], None]] = None,
) -> None:
    url = f"{FRP_GITHUB_BASE}/{archive_name}"
    with tempfile.TemporaryDirectory(prefix="neko_shell_frp_") as tmpdir:
        tmp_archive = Path(tmpdir) / archive_name
        _download_file(url, tmp_archive, progress_callback=progress_callback, status_callback=status_callback)

        if status_callback:
            status_callback(f"解压: {binary_name}")

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if tmp_archive.suffix == ".zip":
            _extract_binary_from_zip(tmp_archive, binary_name, dest_path)
        else:
            _extract_binary_from_tar(tmp_archive, binary_name, dest_path)
        _ensure_executable(dest_path)


class FRPInstallError(RuntimeError):
    """FRP 安装/部署错误。"""


@dataclass
class FRPManager:
    """FRP 管理器。"""

    _download_in_progress: bool = False

    @property
    def frpc_path(self) -> Path:
        return get_local_frpc_path()

    @property
    def frps_path(self) -> Path:
        return get_local_frps_path()

    def is_frpc_ready(self) -> bool:
        return _is_executable(self.frpc_path)

    def ensure_frpc(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        if self.is_frpc_ready():
            return True
        if self._download_in_progress:
            return False
        self._download_in_progress = True
        try:
            archive = _archive_for_local_platform()
            binary = "frpc.exe" if platform.system() == "Windows" else "frpc"
            _download_and_extract(
                archive,
                binary,
                self.frpc_path,
                progress_callback=progress_callback,
                status_callback=status_callback,
            )
            return True
        except Exception as exc:
            logger.error("准备 frpc 失败: %s", exc)
            if status_callback:
                status_callback(f"准备 frpc 失败: {exc}")
            return False
        finally:
            self._download_in_progress = False

    def ensure_frps_on_server(
        self,
        ssh_conn,
        sftp,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        # 远端默认部署到 $HOME/frp
        try:
            exists = ssh_conn.exec("test -f $HOME/frp/frps && echo exists || true", pty=False)
            if exists and "exists" in exists:
                return True
        except Exception:
            pass

        try:
            arch = ssh_conn.exec("uname -m 2>/dev/null || echo unknown", pty=False).strip()
            archive = _archive_for_server_arch(arch)
        except Exception as exc:
            raise FRPInstallError(str(exc)) from exc

        # 下载对应 Linux 架构的 frps 到本地临时目录，再上传
        try:
            with tempfile.TemporaryDirectory(prefix="neko_shell_frps_") as tmpdir:
                tmp_frps = Path(tmpdir) / "frps"
                _download_and_extract(
                    archive,
                    "frps",
                    tmp_frps,
                    progress_callback=progress_callback,
                    status_callback=status_callback,
                )
                if status_callback:
                    status_callback("上传 frps 到远端...")
                home = ssh_conn.exec("echo $HOME", pty=False).strip() or "."
                remote_dir = f"{home}/frp"
                remote_frps = f"{remote_dir}/frps"
                ssh_conn.exec(f"mkdir -p {remote_dir}", pty=False)
                sftp.put(str(tmp_frps), remote_frps)
                ssh_conn.exec(f"chmod +x {remote_frps}", pty=False)
            return True
        except Exception as exc:
            logger.error("部署 frps 失败: %s", exc)
            if status_callback:
                status_callback(f"部署 frps 失败: {exc}")
            return False


_frp_manager: Optional[FRPManager] = None


def get_frp_manager() -> FRPManager:
    global _frp_manager
    if _frp_manager is None:
        _frp_manager = FRPManager()
    return _frp_manager
