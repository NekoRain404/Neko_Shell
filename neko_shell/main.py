#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Neko_Shell 主入口

启动 Neko_Shell 应用程序。

Usage:
    python -m neko_shell.main [OPTIONS]

Options:
    --config-dir DIR    指定配置目录
    --theme THEME       指定主题 (dark/light/eye_care/auto)
    --encrypt-config    使用主密码加密配置文件
    --decrypt-config    使用主密码解密配置文件
    --runtime-summary   输出当前运行摘要
    --self-check        执行预览版自检
    --acceptance-checklist
                       输出 0.1 预览版验收清单
    --export-acceptance-checklist FILE
                       导出 0.1 预览版验收清单
    --issue-template    输出问题反馈模板
    --export-issue-template FILE
                       导出问题反馈模板
    --export-support-bundle FILE
                       导出预览版支持包
    --export-diagnostic FILE
                       导出运行诊断报告
    --smoke-test        执行一次 GUI 启动 smoke test
    --debug             启用调试模式
    --help              显示帮助信息
"""

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Optional

from neko_shell.release import (
    APP_NAME,
    build_issue_feedback_template,
    build_preview_acceptance_checklist,
    collect_runtime_diagnostic_report,
    collect_runtime_summary,
    export_preview_acceptance_checklist,
    export_issue_feedback_template,
    export_runtime_diagnostic_report,
    export_support_bundle,
    format_cli_version,
)
from neko_shell.utils import get_default_config_dir


def parse_args(argv=None):
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} - 远程连接管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  neko-shell                     # 使用默认配置启动
  neko-shell --theme light       # 使用亮色主题
  neko-shell --theme eye_care    # 使用护眼主题
  neko-shell --config-dir ./conf # 使用指定配置目录
  neko-shell --encrypt-config    # 使用主密码加密配置
  neko-shell --decrypt-config    # 使用主密码解密配置
  neko-shell --runtime-summary   # 输出运行摘要
  neko-shell --self-check        # 执行预览版自检
  neko-shell --acceptance-checklist  # 输出 0.1 预览版验收清单
  neko-shell --export-acceptance-checklist ./acceptance.md  # 导出验收清单
  neko-shell --issue-template    # 输出问题反馈模板
  neko-shell --export-issue-template ./issue.md  # 导出问题反馈模板
  neko-shell --export-support-bundle ./support.zip  # 导出预览版支持包
  neko-shell --export-diagnostic ./diagnostics.txt  # 导出诊断报告
  neko-shell --smoke-test        # 执行一次 GUI 启动 smoke test
  neko-shell --debug             # 启用调试模式
        """,
    )

    parser.add_argument("--config-dir", type=str, default=None, help="指定配置目录路径")

    parser.add_argument(
        "--theme",
        type=str,
        choices=["dark", "light", "eye_care", "auto"],
        default=None,
        help="指定界面主题",
    )

    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="创建主窗口并完成一次启动 smoke test 后退出",
    )

    diagnostic_group = parser.add_mutually_exclusive_group()
    diagnostic_group.add_argument(
        "--runtime-summary",
        action="store_true",
        help="输出当前运行摘要后退出",
    )
    diagnostic_group.add_argument(
        "--self-check",
        action="store_true",
        help="执行预览版自检并输出诊断结果后退出",
    )
    diagnostic_group.add_argument(
        "--acceptance-checklist",
        action="store_true",
        help="输出 0.1 预览版验收清单后退出",
    )
    diagnostic_group.add_argument(
        "--export-acceptance-checklist",
        type=str,
        default=None,
        metavar="FILE",
        help="导出 0.1 预览版验收清单到指定文件后退出",
    )
    diagnostic_group.add_argument(
        "--issue-template",
        action="store_true",
        help="输出可直接填写的问题反馈模板后退出",
    )
    diagnostic_group.add_argument(
        "--export-issue-template",
        type=str,
        default=None,
        metavar="FILE",
        help="导出问题反馈模板到指定文件后退出",
    )
    diagnostic_group.add_argument(
        "--export-support-bundle",
        type=str,
        default=None,
        metavar="FILE",
        help="导出预览版支持包到指定文件后退出",
    )
    diagnostic_group.add_argument(
        "--export-diagnostic",
        type=str,
        default=None,
        metavar="FILE",
        help="导出运行诊断报告到指定文件后退出",
    )

    config_crypto_group = parser.add_mutually_exclusive_group()
    config_crypto_group.add_argument(
        "--encrypt-config",
        action="store_true",
        help="使用主密码加密配置文件后退出",
    )
    config_crypto_group.add_argument(
        "--decrypt-config",
        action="store_true",
        help="使用主密码解密配置文件后退出",
    )

    parser.add_argument("--version", action="version", version=format_cli_version())

    return parser.parse_args(argv)


def _prompt_master_password(confirm: bool = False) -> str:
    """读取主密码。"""
    password = getpass.getpass("主密码: ")
    if not password:
        raise ValueError("主密码不能为空")
    if confirm:
        confirmation = getpass.getpass("确认主密码: ")
        if password != confirmation:
            raise ValueError("两次输入的主密码不一致")
    return password


def _handle_config_crypto_action(args, config_dir: Path) -> Optional[int]:
    """处理配置文件加密/解密 CLI 操作。"""
    if not args.encrypt_config and not args.decrypt_config:
        return None

    from neko_shell.utils import ConfigManager

    manager = ConfigManager(config_dir)
    try:
        if args.encrypt_config:
            paths = manager.encrypt_config_files(_prompt_master_password(confirm=True))
            print(f"已加密配置文件: {len(paths)}")
            return 0

        paths = manager.decrypt_config_files(_prompt_master_password(confirm=False))
        print(f"已解密配置文件: {len(paths)}")
        return 0
    except Exception as exc:
        print(f"配置加密操作失败: {exc}", file=sys.stderr)
        return 1


def _load_cli_app_config(config_dir: Path):
    """尝试为 CLI 诊断读取应用配置。"""
    try:
        from neko_shell.utils import ConfigManager

        manager = ConfigManager(config_dir)
        return manager.app_config
    except Exception:
        return None


def _handle_diagnostic_cli_actions(args, config_dir: Path) -> Optional[int]:
    """处理运行摘要与自检 CLI 操作。"""
    if (
        not args.runtime_summary
        and not args.self_check
        and not args.acceptance_checklist
        and not args.export_acceptance_checklist
        and not args.issue_template
        and not args.export_issue_template
        and not args.export_support_bundle
        and not args.export_diagnostic
    ):
        return None

    app_config = _load_cli_app_config(config_dir)
    if args.runtime_summary:
        print(collect_runtime_summary(config_dir=config_dir, app_config=app_config).to_text())
        return 0

    if args.issue_template:
        report = collect_runtime_diagnostic_report(config_dir=config_dir, app_config=app_config)
        print(build_issue_feedback_template(report))
        return 0

    if args.acceptance_checklist:
        report = collect_runtime_diagnostic_report(config_dir=config_dir, app_config=app_config)
        print(build_preview_acceptance_checklist(report))
        return 0

    if args.export_acceptance_checklist:
        output_path = Path(args.export_acceptance_checklist)
        try:
            report = export_preview_acceptance_checklist(
                output_path,
                config_dir=config_dir,
                app_config=app_config,
            )
        except OSError as exc:
            print(f"导出验收清单失败: {exc}", file=sys.stderr)
            return 1
        print(f"验收清单已导出: {output_path}")
        print(f"综合结果: {'通过' if report.ok else '失败'}")
        return 0 if report.ok else 1

    if args.export_issue_template:
        output_path = Path(args.export_issue_template)
        try:
            report = export_issue_feedback_template(
                output_path,
                config_dir=config_dir,
                app_config=app_config,
            )
        except OSError as exc:
            print(f"导出问题反馈模板失败: {exc}", file=sys.stderr)
            return 1
        print(f"问题反馈模板已导出: {output_path}")
        print(f"综合结果: {'通过' if report.ok else '失败'}")
        return 0 if report.ok else 1

    if args.export_support_bundle:
        output_path = Path(args.export_support_bundle)
        try:
            report = export_support_bundle(
                output_path,
                config_dir=config_dir,
                app_config=app_config,
            )
        except OSError as exc:
            print(f"导出支持包失败: {exc}", file=sys.stderr)
            return 1
        print(f"预览版支持包已导出: {output_path}")
        print(f"综合结果: {'通过' if report.ok else '失败'}")
        return 0 if report.ok else 1

    if args.export_diagnostic:
        output_path = Path(args.export_diagnostic)
        try:
            report = export_runtime_diagnostic_report(
                output_path,
                config_dir=config_dir,
                app_config=app_config,
            )
        except OSError as exc:
            print(f"导出诊断报告失败: {exc}", file=sys.stderr)
            return 1
        print(f"诊断报告已导出: {output_path}")
        print(f"综合结果: {'通过' if report.ok else '失败'}")
        return 0 if report.ok else 1

    report = collect_runtime_diagnostic_report(config_dir=config_dir, app_config=app_config)
    print(report.to_text())
    return 0 if report.ok else 1


def _prepare_qt_platform_for_smoke_test() -> None:
    """在无图形环境下为 smoke test 选择离屏后端。"""
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _create_main_window(app, window_cls):
    """创建并初始化主窗口。"""
    window = window_cls()
    window.setWindowTitle(APP_NAME)
    window.resize(1200, 800)
    window.set_config_manager(app.config_manager)
    return window


def _run_gui_smoke_test(app, window_cls, logger) -> int:
    """执行一次 GUI smoke test。"""
    window = _create_main_window(app, window_cls)
    window.show()
    app.processEvents()
    app.processEvents()
    window.close()
    app.processEvents()
    logger.info("GUI smoke test 通过")
    print("GUI smoke test passed")
    return 0


def main(argv=None):
    """主函数"""
    # 解析参数
    args = parse_args(argv)

    if args.smoke_test:
        _prepare_qt_platform_for_smoke_test()

    # 设置配置目录
    if args.config_dir:
        config_dir = Path(args.config_dir)
    else:
        config_dir = get_default_config_dir()

    crypto_exit_code = _handle_config_crypto_action(args, config_dir)
    if crypto_exit_code is not None:
        return crypto_exit_code

    diagnostic_exit_code = _handle_diagnostic_cli_actions(args, config_dir)
    if diagnostic_exit_code is not None:
        return diagnostic_exit_code

    # 导入应用程序
    from neko_shell.app import Application
    from neko_shell.ui import MainWindow
    from neko_shell.ui.styles import ThemeManager
    from neko_shell.utils import get_logger
    from PySide6.QtWidgets import QMessageBox

    # 创建应用程序
    app = Application.instance()
    try:
        app.initialize(config_dir)
    except Exception as exc:
        QMessageBox.critical(None, "启动失败", str(exc))
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1

    logger = get_logger("main")
    logger.info("=" * 50)
    logger.info("%s 启动", APP_NAME)
    logger.info(f"Python: {sys.version}")
    logger.info(f"配置目录: {config_dir}")
    logger.info("=" * 50)

    # 应用命令行指定的主题
    if args.theme:
        ThemeManager.apply_theme(app, args.theme)

    # 调试模式
    if args.debug:
        import logging

        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("调试模式已启用")

    if args.smoke_test:
        return _run_gui_smoke_test(app, MainWindow, logger)

    # 创建主窗口
    window = _create_main_window(app, MainWindow)

    # 显示窗口
    window.show()

    # 运行应用程序
    exit_code = app.run()

    logger.info(f"应用程序退出，代码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        _prepare_qt_platform_for_smoke_test()
    sys.exit(main())
