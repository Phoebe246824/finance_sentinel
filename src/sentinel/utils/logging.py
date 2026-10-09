"""
两套独立的输出系统：
1. print_* → 终端 stdout only（简洁，面向用户）
2. logger.* → 文件 only（详细，面向开发者）
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console

_console = Console()

_LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def print_info(*args, **kwargs):
    _console.print(" ".join(str(a) for a in args), style="green", **kwargs)


def print_warn(*args, **kwargs):
    _console.print(" ".join(str(a) for a in args), style="yellow", **kwargs)


def print_error(*args, **kwargs):
    _console.print(" ".join(str(a) for a in args), style="red", **kwargs)


def print_banner(title: str, char: str = "=", width: int = 70):
    _console.print()
    _console.print(char * width, style="cyan")
    _console.print(f"  {title}", style="cyan")
    _console.print(char * width, style="cyan")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def setup_file_logging(log_dir: str | None = None) -> str:
    log_dir = log_dir or str(Path.cwd() / "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(
        log_dir, f"sentinel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return log_path

    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    for noisy in ("neo4j", "httpx", "urllib3", "httpcore", "crewai", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_path
