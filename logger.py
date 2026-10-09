"""Specialized structured logging system for Blast.

Guaranteed zero emojis. Clean, structured log outputs.
"""

import os
import sys
import time
import threading
from typing import Optional


class LogLevel:
    DEBUG = 10
    INFO = 20
    WARN = 30
    ERROR = 40


LEVEL_NAMES = {
    LogLevel.DEBUG: "DEBUG",
    LogLevel.INFO: "INFO",
    LogLevel.WARN: "WARN",
    LogLevel.ERROR: "ERROR",
}


class BlastLogger:
    """Thread-safe structured logger with zero emojis."""

    def __init__(self, name: str = "blast", log_file: Optional[str] = "blast.log", level: int = LogLevel.INFO):
        self.name = name
        self.log_file = log_file
        self.level = level
        self._lock = threading.Lock()

    def set_level(self, level: int):
        self.level = level

    def _format_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    def _log(self, level: int, component: str, message: str, exc: Optional[Exception] = None):
        if level < self.level:
            return

        lvl_name = LEVEL_NAMES.get(level, "INFO")
        timestamp = self._format_time()
        line = f"[{timestamp}] [{lvl_name}] [{component}] {message}"
        if exc:
            line += f" | Exception: {str(exc)}"

        with self._lock:
            # Print to stdout/stderr
            out = sys.stderr if level >= LogLevel.ERROR else sys.stdout
            out.write(line + "\n")
            out.flush()

            # Optional file persistence
            if self.log_file:
                try:
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception:
                    pass

    def debug(self, component: str, message: str):
        self._log(LogLevel.DEBUG, component, message)

    def info(self, component: str, message: str):
        self._log(LogLevel.INFO, component, message)

    def warn(self, component: str, message: str):
        self._log(LogLevel.WARN, component, message)

    def error(self, component: str, message: str, exc: Optional[Exception] = None):
        self._log(LogLevel.ERROR, component, message, exc=exc)

    def security(self, message: str):
        self._log(LogLevel.INFO, "SECURITY", message)

    def queue(self, message: str):
        self._log(LogLevel.INFO, "QUEUE", message)

    def cluster(self, message: str):
        self._log(LogLevel.INFO, "CLUSTER", message)

    def worker(self, message: str):
        self._log(LogLevel.INFO, "WORKER", message)


# Global default logger instance
logger = BlastLogger()


def get_logger(name: str = "blast") -> BlastLogger:
    """Obtain logger instance."""
    return logger
