<div align="center">

# 🐱 Neko Shell

**A Modern Remote Operations Platform for Linux Servers**

[![License](https://img.shields.io/badge/license-GPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.5+-green.svg)](https://www.qt.io/qt-for-python)

English | [简体中文](README.md)

</div>

---

## ✨ Overview

Neko Shell is a personal Linux remote-operations workspace. It combines SSH terminals, SFTP file management, VNC, system monitoring, Docker, SSH tunneling, and day-to-day inspection tools in one desktop interface. The goal is to be a dependable personal tool that feels fast and practical, not a server-dependent platform.

Design Philosophy: **Simple yet Powerful** 🎯 — eliminating redundant menus and complex configurations to focus on core operational needs.

Current `0.1` preview priorities:

- ship a **portable Linux binary** that can run right after extraction
- optimize for **personal workflows**: connections, terminals, files, monitoring, inspections
- keep the **source tree runnable** for further customization

## 🚀 Key Features

### 🔌 Multi-Protocol Support

| Protocol | Description |
|:--------:|-------------|
| 🔐 **SSH** | Password/key authentication, proxy command, interactive shell, command execution, basic monitoring |
| 📁 **SFTP** | Directory browsing, upload/download, text editing, archive actions, copy/move, permission changes |
| 📤 **FTP/FTPS** | Traditional file transfer with active/passive modes and SSL/TLS encryption |
| 🔧 **Serial** | Serial port communication for embedded device debugging |
| 🌐 **TCP/UDP** | Raw socket connections for network debugging |
| 🖥️ **VNC** | Framebuffer rendering with keyboard/mouse interaction and clipboard events |

### 💻 Terminal Experience

- 📑 **Multi-tab Workspace** — work with multiple connections and views side by side
- 🪟 **Split Terminal** — quickly split the active terminal area
- 🎨 **Theme Options** — dark, light, eye-care, system-follow, plus switchable terminal color schemes
- 🏠 **Local Terminal** — launch a local shell without opening a remote connection
- ⚡ **Sync Input** — broadcast input to multiple terminals when operating in batch
- 📋 **Context Menu Actions** — copy, paste, search, send history, quick commands, and inspection entry points
- 🔗 **Workspace Linkage** — terminals, file views, and the active connection share context

### 📂 File Management

- 🌳 Visual directory tree navigation
- ⬆️ Upload/download task queue with retry and progress summaries
- 📦 Compress/Extract (zip, tar.gz, etc.)
- 🔐 Permission management (chmod, chown)
- ✏️ Built-in text/code editor
- 📋 Batch copy, move, delete
- 🖥️ Open a derived SSH terminal directly from the SFTP workspace

### 📊 Personal Operations Toolbox

- 📊 **System Monitoring** — CPU, memory, swap, disks, network speed, load, processes, and host info
- 🚇 **SSH Tunneling** — local, remote, and dynamic forwarding
- 🐳 **Docker Management** — container list, lifecycle actions, logs, and terminal entry points
- 🌍 **FRP Management** — common tunneling settings and runtime status
- 📋 **Quick Command Center** — reusable commands, favorites, and command macros
- ✅ **Task Presets** — quick inspection, system inspection, network inspection, disk inspection
- 🗂️ **Workspace Templates & Filters** — useful for personal layouts and recurring connection views

### 🌐 Internationalization

The current `0.1 Preview` ships with **Simplified Chinese** UI by default. Language choices are now exposed dynamically based on real runtime resources, and a full English UI translation can be added later.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        🐱 Neko Shell                             │
├─────────────────────────────────────────────────────────────────┤
│  UI Layer (PySide6)                                             │
│  ├── MainWindow           ─── ConnectionTree                    │
│  ├── TerminalWidget       ─── FileBrowser                       │
│  ├── SystemMonitor        ─── DockerManager                     │
│  └── VNCWidget            ─── TunnelManager / FRPWidget         │
├─────────────────────────────────────────────────────────────────┤
│  Core Layer                                                     │
│  ├── Connection Factory   ─── Protocol Handlers                 │
│  ├── SSH / SFTP / FTP     ─── Serial / TCP / UDP / VNC          │
│  ├── Tunnel Forwarder     ─── FRP Manager                       │
│  └── Docker Manager       ─── Automation Engine                 │
├─────────────────────────────────────────────────────────────────┤
│  Service Layer                                                  │
│  ├── Config Manager         ─── Logger (sensitive filter)       │
│  ├── Theme Manager          ─── Runtime Path Resolver           │
│  └── Crypto Utils           ─── Keyring Integration             │
└─────────────────────────────────────────────────────────────────┘
```

### 📦 Tech Stack

| Component | Description |
|-----------|-------------|
| 🐍 Python 3.9+ | Core runtime, supports up to 3.12 |
| 🎨 PySide6 6.5+ | Official Qt Python binding, cross-platform GUI |
| 🔐 paramiko | SSH/SFTP protocol implementation |
| 🖥️ qtermwidget | Terminal rendering and terminal color schemes |
| 🔌 pyserial | Serial communication |
| 🔑 keyring | System keyring integration |
| 🔒 cryptography | Config encryption and signing support (optional) |
| 🔐 pycryptodome | Optional VNC DES authentication support |

## 📥 Installation

### 🐧 Linux Preview Binary

The `0.1` preview is centered on a portable Linux binary bundle. After downloading `neko-shell-0.1.0-preview-linux-<arch>-binary.tar.gz` from the release page:

```bash
tar -xzf neko-shell-0.1.0-preview-linux-<arch>-binary.tar.gz
cd neko-shell-0.1.0-preview-linux-<arch>-binary
./neko-shell/neko-shell
```

For an offscreen validation run:

```bash
QT_QPA_PLATFORM=offscreen ./neko-shell/neko-shell --smoke-test
```

### 🔨 Run from Source

```bash
git clone https://github.com/neko-shell/Neko_Shell.git
cd Neko_Shell
pip install -e ".[crypto,vnc]"
python -m neko_shell
```

### 🧪 Developer Mode

```bash
pip install -e ".[dev,crypto,vnc]"
pytest
```

## 🎮 Quick Start

### Command Line

```bash
# Default launch
neko-shell

# Specify theme
neko-shell --theme dark
neko-shell --theme light
neko-shell --theme eye_care
neko-shell --theme auto

# Specify config directory
neko-shell --config-dir /path/to/config

# Debug mode
neko-shell --debug

# Encrypt config files
neko-shell --encrypt-config

# Decrypt config files
neko-shell --decrypt-config

# Print runtime summary
neko-shell --runtime-summary

# Run preview self-check
neko-shell --self-check

# Print the 0.1 preview acceptance checklist
neko-shell --acceptance-checklist

# Export the 0.1 preview acceptance checklist
neko-shell --export-acceptance-checklist ./neko-shell-acceptance.md

# Print an issue template
neko-shell --issue-template

# Export an issue template
neko-shell --export-issue-template ./neko-shell-issue.md

# Export a preview support bundle
neko-shell --export-support-bundle ./neko-shell-support-bundle.zip

# Export a diagnostic report
neko-shell --export-diagnostic ./neko-shell-diagnostics.txt

# GUI smoke test
neko-shell --smoke-test

# Show version
neko-shell --version
```

### Programmatic Usage

```python
from neko_shell import create_connection, SSHConfig

# Create SSH connection
config = SSHConfig(
    name="my-server",
    host="192.168.1.100",
    port=22,
    username="admin"
)

conn = create_connection(config)
conn.connect()

# Execute command
stdout, stderr = conn.execute("ls -la")
print(stdout)

# Get system monitor data
monitor_data = conn.get_monitor_data()
print(f"CPU: {monitor_data['cpu_percent']}%")

conn.disconnect()
```

## 📁 Project Structure

```
Neko_Shell/
├── neko_shell/           # Main package
│   ├── core/             # Core connection layer
│   │   ├── connection/   # Connection implementations
│   │   ├── docker/       # Docker management
│   │   └── forwarder.py  # Port forwarding
│   ├── ui/               # User interface
│   │   ├── widgets/      # UI components
│   │   ├── dialogs/      # Dialogs
│   │   └── styles/       # Stylesheets
│   ├── models/           # Data models
│   ├── utils/            # Utilities
│   └── i18n/             # Internationalization
├── qtermwidget/          # Terminal widget
├── conf/                 # Configuration templates
├── docs/                 # Runtime help documents
├── README.md             # Chinese README
├── README.en.md          # English README
├── LICENSE               # License
└── pyproject.toml        # Project metadata
```

## 🛠️ Development

### Running Tests

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Generate coverage report
pytest --cov=neko_shell --cov-report=html
```

### Code Standards

| Tool | Purpose |
|------|---------|
| 🧪 pytest | Testing framework |
| 🖤 black | Code formatting |
| 📦 isort | Import sorting |
| 🔍 mypy | Type checking |
| ⚠️ pylint | Linting |

## ✅ 0.1 Preview Validation Status

The `0.1` preview is not intended to mean "everything is finished". Its release goal is to provide a Linux personal-tool bundle that can be extracted, launched, diagnosed, and reported on. Before packaging, the release flow runs:

- compile checks and release-focused pytest regression tests
- PyInstaller `onedir` binary build
- offscreen GUI smoke test
- `--self-check` runtime diagnostics
- `--acceptance-checklist` export
- `--issue-template` export
- `--export-diagnostic` diagnostics export
- `--export-support-bundle` support bundle export
- `preview-manifest.json` and `SHA256SUMS` generation

The preview bundle includes the executable directory, user guide, release notes, desktop file, application icon, build manifest, checksum file, self-check output, diagnostics report, acceptance checklist, issue template, and support bundle.

### Good Fit for Early Use

- You mainly manage personal Linux servers, VMs, development machines, or lab environments.
- You want SSH terminals, SFTP browsing, monitoring, and inspection commands in one desktop tool.
- You can tolerate rough edges in `0.1 Preview` and report issues with the support bundle.

### Not Promised in This Preview

- No official Windows or macOS preview package.
- No AppImage, deb/rpm package, or auto-updater.
- No enterprise permissions, team backend, or cloud sync service.
- Full English UI resources are not a `0.1 Preview` release promise yet.

## 🐛 Preview Feedback

If you hit a problem in the `0.1` preview, export a support bundle before opening an issue:

```bash
neko-shell --export-support-bundle ./neko-shell-support-bundle.zip
neko-shell --self-check
neko-shell --acceptance-checklist
neko-shell --export-acceptance-checklist ./neko-shell-acceptance.md
neko-shell --issue-template
neko-shell --export-issue-template ./neko-shell-issue.md
neko-shell --export-diagnostic ./neko-shell-diagnostics.txt
```

You can also use `Help -> About` in the GUI to export a support bundle, or manually copy/export the acceptance checklist, issue template, and diagnostics. When reporting an issue, include:

- reproduction steps
- screenshots
- the diagnostic report
- relevant content from the config directory or log directory

## 🤝 Contributing

Contributions are welcome!

1. 🍴 Fork the repository
2. 🌿 Create a feature branch (`git checkout -b feature/amazing-feature`)
3. ✅ Commit changes (`git commit -m 'feat: add amazing feature'`)
4. 📤 Push to branch (`git push origin feature/amazing-feature`)
5. 🔀 Open a Pull Request

## 📄 License

This project is licensed under the [GNU GPL v3 License](LICENSE).

## 💝 Acknowledgments

This project draws on a number of good practices from terminal emulation, remote access, and Qt desktop tooling.

- 🎨 Icons: [icons8](https://icons8.com/icons/color) / [iconfont](https://www.iconfont.cn/)
- 💻 Terminal component reference: [qtermwidget](https://github.com/lxqt/qtermwidget)

---

<div align="center">

**💬 Community**

Community entry is being reorganized.

</div>
