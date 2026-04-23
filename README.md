<div align="center">

# 🐱 Neko Shell

**现代化的 Linux 服务器远程运维管理平台**

[![License](https://img.shields.io/badge/license-GPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.5+-green.svg)](https://www.qt.io/qt-for-python)

[English](README.en.md) | 简体中文

</div>

---

## ✨ 简介

Neko Shell 是一个面向个人使用的 Linux 远程连接与运维工作台。它把 SSH 终端、SFTP 文件管理、VNC、系统监控、Docker、SSH 隧道和常用巡检能力整合到一个本地桌面界面里，目标是提供一个顺手、稳定、可长期演进的个人工具，而不是依赖服务端的平台。

设计理念：**简洁而不简单** 🎯 —— 摒弃冗余的菜单与复杂配置，聚焦运维工作的核心需求。

当前 `0.1` 预览版定位：

- 优先交付 **Linux 可直接解压运行的二进制包**
- 优先打磨 **个人工作流**：连接、终端、文件、监控、巡检
- 保持 **源码可运行**，便于继续二次开发和定制

## 🚀 核心特性

### 🔌 多协议连接支持

| 协议 | 说明 |
|:----:|------|
| 🔐 **SSH** | 支持密码/密钥认证、代理命令、交互式 Shell、命令执行与基础监控 |
| 📁 **SFTP** | 支持目录浏览、上传下载、文本编辑、压缩解压、复制移动、权限修改 |
| 📤 **FTP/FTPS** | 传统文件传输协议，支持主动/被动模式及 SSL/TLS 加密 |
| 🔧 **Serial** | 串口通信，适用于嵌入式设备调试 |
| 🌐 **TCP/UDP** | 原始套接字连接，网络调试利器 |
| 🖥️ **VNC** | 远程桌面协议，支持帧缓冲渲染、键盘鼠标交互与剪贴板事件 |

### 💻 终端体验

- 📑 **多标签工作区**：支持并行打开多个连接与视图
- 🪟 **终端分屏**：在同一工作区内快速拆分终端
- 🎨 **主题与配色**：支持深色、浅色、护眼、跟随系统，以及可切换终端主题
- 🏠 **本地终端**：不连接远程主机也能直接打开本地终端
- ⚡ **同步输入**：批量操作多台机器时可统一发送输入
- 📋 **右键动作**：复制、粘贴、搜索、发送记录、快捷命令与巡检入口集中在终端上下文菜单
- 🔗 **面板联动**：终端、文件面板与连接工作区共享上下文

### 📂 文件管理

- 🌳 可视化目录树浏览
- ⬆️ 上传下载任务队列，支持失败重试与进度统计
- 📦 压缩/解压（zip、tar.gz 等格式）
- 🔐 权限管理（chmod、chown）
- ✏️ 内置文本/代码编辑器
- 📋 批量复制、移动、删除
- 🖥️ 从 SFTP 视图派生 SSH 终端，快速回到命令操作

### 📊 个人运维工具箱

- 📊 **系统监控**：CPU、内存、交换、磁盘、网络速率、负载、进程与系统信息
- 🚇 **SSH 隧道**：本地转发、远程转发、动态端口转发
- 🐳 **Docker 管理**：容器列表、生命周期操作、日志与终端入口
- 🌍 **FRP 管理**：常用穿透配置与运行状态查看
- 📋 **快捷命令中心**：沉淀常用命令、收藏命令和命令宏
- ✅ **任务预设**：快速巡检、系统巡检、网络巡检、磁盘巡检
- 🗂️ **工作区模板与筛选预设**：更适合个人用户沉淀常用布局和连接视图

### 🌐 国际化

当前 `0.1 Preview` 默认提供 **简体中文** 界面，运行时会按实际语言资源动态显示可选项；English 翻译资源后续再补齐。

## 🏗️ 技术架构

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

### 📦 技术栈

| 组件 | 说明 |
|------|------|
| 🐍 Python 3.9+ | 核心运行时，支持至 3.12 |
| 🎨 PySide6 6.5+ | Qt 官方 Python 绑定，跨平台 GUI |
| 🔐 paramiko | SSH/SFTP 协议实现 |
| 🖥️ qtermwidget | 终端渲染与终端主题能力 |
| 🔌 pyserial | 串口通信 |
| 🔑 keyring | 系统密钥环集成 |
| 🔒 cryptography | 配置加密与签名能力（可选） |
| 🔐 pycryptodome | VNC DES 认证支持（可选） |

## 📥 安装

### 🐧 Linux 二进制预览包

当前 `0.1` 预览版优先提供 Linux 二进制目录包。下载发布页中的 `neko-shell-0.1.0-preview-linux-<arch>-binary.tar.gz` 后：

```bash
tar -xzf neko-shell-0.1.0-preview-linux-<arch>-binary.tar.gz
cd neko-shell-0.1.0-preview-linux-<arch>-binary
./neko-shell/neko-shell
```

如需离屏验证：

```bash
QT_QPA_PLATFORM=offscreen ./neko-shell/neko-shell --smoke-test
```

### 🔨 从源码运行

```bash
git clone https://github.com/neko-shell/Neko_Shell.git
cd Neko_Shell
pip install -e ".[crypto,vnc]"
python -m neko_shell
```

### 🧪 开发者模式

```bash
pip install -e ".[dev,crypto,vnc]"
pytest
```

## 🎮 快速开始

### 命令行

```bash
# 默认启动
neko-shell

# 指定主题
neko-shell --theme dark
neko-shell --theme light
neko-shell --theme eye_care
neko-shell --theme auto

# 指定配置目录
neko-shell --config-dir /path/to/config

# 调试模式
neko-shell --debug

# 加密配置文件
neko-shell --encrypt-config

# 解密配置文件
neko-shell --decrypt-config

# 输出运行摘要
neko-shell --runtime-summary

# 执行预览版自检
neko-shell --self-check

# 输出 0.1 预览版验收清单
neko-shell --acceptance-checklist

# 导出 0.1 预览版验收清单
neko-shell --export-acceptance-checklist ./neko-shell-acceptance.md

# 输出问题反馈模板
neko-shell --issue-template

# 导出问题反馈模板
neko-shell --export-issue-template ./neko-shell-issue.md

# 导出预览版支持包
neko-shell --export-support-bundle ./neko-shell-support-bundle.zip

# 导出诊断报告
neko-shell --export-diagnostic ./neko-shell-diagnostics.txt

# GUI 启动 smoke test
neko-shell --smoke-test

# 查看版本
neko-shell --version
```

### 代码调用

```python
from neko_shell import create_connection, SSHConfig

# 创建 SSH 连接
config = SSHConfig(
    name="my-server",
    host="192.168.1.100",
    port=22,
    username="admin"
)

conn = create_connection(config)
conn.connect()

# 执行命令
stdout, stderr = conn.execute("ls -la")
print(stdout)

# 获取系统监控数据
monitor_data = conn.get_monitor_data()
print(f"CPU: {monitor_data['cpu_percent']}%")

conn.disconnect()
```

## 📁 项目结构

```
Neko_Shell/
├── neko_shell/           # 主包
│   ├── core/             # 核心连接层
│   │   ├── connection/   # 连接实现 (SSH/SFTP/FTP/Serial/TCP/UDP/VNC)
│   │   ├── docker/       # Docker 管理
│   │   └── forwarder.py  # 端口转发
│   ├── ui/               # 用户界面
│   │   ├── widgets/      # UI 组件
│   │   ├── dialogs/      # 对话框
│   │   └── styles/       # 样式表
│   ├── models/           # 数据模型
│   ├── utils/            # 工具函数
│   └── i18n/             # 国际化
├── qtermwidget/          # 终端组件
├── conf/                 # 配置文件模板
├── docs/                 # 运行时帮助文档
├── README.md             # 中文说明
├── README.en.md          # 英文说明
├── LICENSE               # 许可证
└── pyproject.toml        # 项目元数据
```

## 🛠️ 开发

### 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 生成覆盖率报告
pytest --cov=neko_shell --cov-report=html
```

### 代码规范

项目使用以下工具保持代码质量：

| 工具 | 用途 |
|------|------|
| 🧪 pytest | 测试框架 |
| 🖤 black | 代码格式化 |
| 📦 isort | 导入排序 |
| 🔍 mypy | 类型检查 |
| ⚠️ pylint | 代码检查 |

## ✅ 0.1 Preview 验收状态

`0.1` 预览版的目标不是“功能全部完成”，而是先交付一个可解压、可启动、可诊断、可反馈的 Linux 个人工具包。当前发布前会固定执行：

- 编译检查与发布相关 pytest 回归
- PyInstaller `onedir` 二进制构建
- 离屏 GUI smoke test
- `--self-check` 运行自检
- `--acceptance-checklist` 验收清单导出
- `--issue-template` 问题模板导出
- `--export-diagnostic` 诊断报告导出
- `--export-support-bundle` 支持包导出
- `preview-manifest.json` 与 `SHA256SUMS` 生成

发布包中会包含可执行目录、用户手册、发布说明、桌面文件、应用图标、构建清单、校验文件、预览版自检结果、诊断报告、验收清单、问题模板和支持包。

### 适合现在试用的人

- 主要在 Linux 上管理个人服务器、虚拟机、开发机或实验环境
- 希望把 SSH 终端、SFTP 文件浏览、系统监控和常用巡检放在一个桌面工具里
- 能接受 `0.1 Preview` 仍有体验粗糙处，并愿意通过支持包反馈问题

### 当前不承诺的范围

- 不提供 Windows / macOS 正式预览包
- 不提供 AppImage、deb/rpm 或自动更新
- 不做企业级权限、团队后台或云同步服务
- English UI 资源尚未作为 `0.1 Preview` 的发布承诺

## 🐛 预览版反馈

如果你在 `0.1` 预览版中遇到问题，建议优先导出一份支持包，再提交反馈：

```bash
neko-shell --export-support-bundle ./neko-shell-support-bundle.zip
neko-shell --self-check
neko-shell --acceptance-checklist
neko-shell --export-acceptance-checklist ./neko-shell-acceptance.md
neko-shell --issue-template
neko-shell --export-issue-template ./neko-shell-issue.md
neko-shell --export-diagnostic ./neko-shell-diagnostics.txt
```

GUI 内也可以通过 `帮助 -> 关于` 或关于页中的“导出支持包”按钮一次性整理反馈材料。若仍需手动整理，也可以继续使用“复制验收清单”“导出验收清单”“复制反馈模板”“导出反馈模板”“导出诊断报告”等动作。反馈时建议一并附上：

- 复现步骤
- 截图
- 诊断报告
- 配置目录或日志目录中的关键内容

## 🤝 贡献

欢迎参与项目贡献！

1. 🍴 Fork 本仓库
2. 🌿 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. ✅ 提交更改 (`git commit -m 'feat: add amazing feature'`)
4. 📤 推送分支 (`git push origin feature/amazing-feature`)
5. 🔀 创建 Pull Request

## 📄 许可证

本项目基于 [GNU GPL v3 License](LICENSE) 开源。

## 💝 致谢

本项目借鉴了终端仿真、远程连接和 Qt 桌面应用领域的若干优秀实践。

- 🎨 图标来源：[icons8](https://icons8.com/icons/color) / [iconfont](https://www.iconfont.cn/)
- 💻 终端组件参考：[qtermwidget](https://github.com/lxqt/qtermwidget)

---

<div align="center">

**💬 交流群**

社区入口整理中。

</div>
