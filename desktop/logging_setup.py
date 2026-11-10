"""Rotating UTF-8 application logs and export helpers."""
from __future__ import annotations

import logging
import logging.handlers
import threading
import uuid
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from .config import default_data_dir

_LOCK = threading.RLock()


def setup_logging(base=None, level=logging.INFO):
    base = Path(base).expanduser().resolve() if base is not None else default_data_dir()
    directory = base / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "chatbridge.log"
    with _LOCK:
        logger = logging.getLogger()
        existing = next((handler for handler in logger.handlers if getattr(handler, "_chatbridge_path", None) == str(path)), None)
        if existing is None:
            existing = logging.handlers.RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
            existing._chatbridge_path = str(path)
            existing.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logger.addHandler(existing)
        existing.setLevel(level)
        logger.setLevel(level)
    return path


def recent_lines(base=None, limit=500):
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError("Log line limit must be between 1 and 10000")
    base = Path(base).expanduser().resolve() if base is not None else default_data_dir()
    path = base / "logs" / "chatbridge.log"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as stream:
        return list(deque((line.rstrip("\r\n") for line in stream), maxlen=limit))


def export_logs(base=None):
    base = Path(base).expanduser().resolve() if base is not None else default_data_dir()
    directory = base / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    target = base / f"logs-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.zip"
    with _LOCK, zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.glob("chatbridge.log*")):
            if path.is_file() and not path.is_symlink():
                archive.write(path, arcname=f"logs/{path.name}")
    return target


# Small aliases keep call sites readable without introducing another logger.
logs_get = recent_lines
logs_export = export_logs
