#!/usr/bin/env python3
"""
CODING Maven 制品库迁移工具主程序
"""

import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

# 导入新版本的 CLI
from coding_migrator.cli import cli


if __name__ == '__main__':
    cli()