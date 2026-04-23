# 工具模块
"""
Neko_Shell 工具函数和类
"""

from .exceptions import (
    NekoShellError,
    ConnectionError,
    ConnectionLostError,
    AuthenticationError,
    TimeoutError,
    ConfigurationError,
    FileTransferError,
    PermissionDeniedError,
    OperationError,
    OperationCancelledError,
)

from .logger import (
    get_logger,
    setup_logging,
    SensitiveDataFilter,
)

from .config import (
    AppConfig,
    ConfigManager,
    DEFAULT_TERMINAL_SNIPPETS,
    DEFAULT_TERMINAL_SNIPPET_GROUPS,
    DEFAULT_TERMINAL_FAVORITES,
    DEFAULT_TERMINAL_MACROS,
    dump_terminal_macro_lines,
    dump_terminal_snippet_lines,
    flatten_terminal_snippet_groups,
    normalize_terminal_macros,
    normalize_terminal_snippets,
    normalize_terminal_snippet_groups,
    normalize_terminal_favorite_snippets,
    parse_terminal_macro_lines,
    parse_terminal_snippet_lines,
)

from .validators import (
    validate_host,
    validate_port,
    validate_timeout,
    validate_baud_rate,
    validate_serial_port,
    validate_file_path,
    validate_key_file,
    validate_password_strength,
    Validator,
)

from .crypto import (
    SecureStorage,
    ConfigEncryptor,
    PackageSigner,
    generate_random_password,
    hash_password,
    verify_password,
)
from .paths import (
    get_app_translation_file,
    get_app_translations_dir,
    get_default_config_dir,
    get_linux_commands_json_path,
    get_repo_root,
)
from .shell_commands import load_command_index

__all__ = [
    # 异常
    "NekoShellError",
    "ConnectionError",
    "ConnectionLostError",
    "AuthenticationError",
    "TimeoutError",
    "ConfigurationError",
    "FileTransferError",
    "PermissionDeniedError",
    "OperationError",
    "OperationCancelledError",
    # 日志
    "get_logger",
    "setup_logging",
    "SensitiveDataFilter",
    # 配置
    "AppConfig",
    "ConfigManager",
    "DEFAULT_TERMINAL_SNIPPETS",
    "DEFAULT_TERMINAL_SNIPPET_GROUPS",
    "DEFAULT_TERMINAL_FAVORITES",
    "DEFAULT_TERMINAL_MACROS",
    "dump_terminal_macro_lines",
    "dump_terminal_snippet_lines",
    "flatten_terminal_snippet_groups",
    "normalize_terminal_macros",
    "normalize_terminal_snippets",
    "normalize_terminal_snippet_groups",
    "normalize_terminal_favorite_snippets",
    "parse_terminal_macro_lines",
    "parse_terminal_snippet_lines",
    # 验证器
    "validate_host",
    "validate_port",
    "validate_timeout",
    "validate_baud_rate",
    "validate_serial_port",
    "validate_file_path",
    "validate_key_file",
    "validate_password_strength",
    "Validator",
    # 加密
    "SecureStorage",
    "ConfigEncryptor",
    "PackageSigner",
    "generate_random_password",
    "hash_password",
    "verify_password",
    # 路径
    "get_app_translation_file",
    "get_app_translations_dir",
    "get_default_config_dir",
    "get_linux_commands_json_path",
    "get_repo_root",
    # Shell
    "load_command_index",
]
