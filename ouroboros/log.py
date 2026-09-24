"""Minimal timestamped logger. Thread-safe."""

import sys
import threading
from datetime import datetime

_lock = threading.Lock()
_min_level = 20  # INFO

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


def set_level(name: str) -> None:
    global _min_level
    _min_level = _LEVELS.get(name.upper(), 20)


def _emit(level: str, module: str, message: str) -> None:
    if _LEVELS.get(level, 20) < _min_level:
        return
    with _lock:
        ts = datetime.now().strftime("%H:%M:%S")
        sys.stdout.write(f"[{ts}] [{level}] [{module}] {message}\n")
        sys.stdout.flush()


class Logger:
    def __init__(self, module: str) -> None:
        self.module = module

    def debug(self, msg: str) -> None:
        _emit("DEBUG", self.module, msg)

    def info(self, msg: str) -> None:
        _emit("INFO", self.module, msg)

    def warn(self, msg: str) -> None:
        _emit("WARNING", self.module, msg)

    def error(self, msg: str) -> None:
        _emit("ERROR", self.module, msg)