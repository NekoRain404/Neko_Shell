#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Neko_Shell 包入口

允许使用 python -m neko_shell 运行。
"""

from .main import main
import sys

if __name__ == '__main__':
    sys.exit(main())
