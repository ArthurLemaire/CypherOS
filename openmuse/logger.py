"""Logging setup (loguru)."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_configured = False


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Configure loguru once: stderr sink + optional rotating file sink."""
    global _configured
    if _configured:
        return
    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}</cyan> - <level>{message}</level>",
        backtrace=False,
        diagnose=False,
    )
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "openmuse.log",
            level="DEBUG",
            rotation="10 MB",
            retention=5,
            encoding="utf-8",
            backtrace=False,
            diagnose=False,
        )
    _configured = True


__all__ = ["logger", "setup_logging"]
