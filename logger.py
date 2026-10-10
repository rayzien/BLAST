"""Specialized structured logging system for Blast.

Guaranteed zero emojis. Clean, high-resolution structured log outputs for
terminal and GUI telemetry stream.
"""

import os
import re
import sys
import time
import threading
from collections import deque
from typing import Any, Dict, List, Optional


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

# ANSI terminal formatting codes
ANSI_RESET = "\033[0m"
ANSI_DIM = "\033[90m"
ANSI_BOLD = "\033[1m"

LEVEL_COLORS = {
    "DEBUG": "\033[36m",    # Cyan
    "INFO": "\033[32m",     # Green
    "WARN": "\033[33m",     # Yellow
    "ERROR": "\033[31m",    # Red
}

COMPONENT_COLORS = {
    "PATHWAY": "\033[1;35m",   # Bold Magenta
    "SUPABASE": "\033[1;36m",  # Bold Cyan
    "MESH": "\033[1;34m",      # Bold Blue
    "SECURITY": "\033[1;33m",  # Bold Yellow
    "QUEUE": "\033[1;32m",     # Bold Green
    "WORKER": "\033[1;37m",    # Bold White
    "CLUSTER": "\033[1;34m",   # Bold Blue
    "FIREWALL": "\033[1;31m",  # Bold Red
}


class BlastLogger:
    """Thread-safe structured logger with terminal colorization and in-memory ring buffer."""

    def __init__(
        self,
        name: str = "blast",
        log_file: Optional[str] = "blast.log",
        level: int = LogLevel.INFO,
        buffer_size: int = 600,
    ):
        self.name = name
        self.log_file = log_file
        self.level = level
        self._lock = threading.Lock()
        self._buffer: deque = deque(maxlen=buffer_size)
        self._counter: int = 0
        self._color_enabled: bool = (
            os.getenv("BLAST_COLOR_LOGS", "true").lower() in ("true", "1", "yes")
            and (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
        )

    def set_level(self, level: int):
        self.level = level

    def _format_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    def _log(self, level: int, component: str, message: str, exc: Optional[Exception] = None):
        if level < self.level:
            return

        lvl_name = LEVEL_NAMES.get(level, "INFO")
        timestamp = self._format_time()
        plain_line = f"[{timestamp}] [{lvl_name}] [{component}] {message}"
        if exc:
            plain_line += f" | Exception: {str(exc)}"

        with self._lock:
            self._counter += 1
            current_id = self._counter

            # 1. Append structured entry to memory ring buffer for GUI stream
            log_record = {
                "id": current_id,
                "timestamp": timestamp,
                "level": lvl_name,
                "component": component,
                "message": message + (f" | Exception: {str(exc)}" if exc else ""),
                "time": time.time(),
            }
            self._buffer.append(log_record)

            # 2. Format line for terminal (with color if enabled)
            if self._color_enabled:
                lvl_col = LEVEL_COLORS.get(lvl_name, ANSI_RESET)
                cmp_col = COMPONENT_COLORS.get(component.upper(), ANSI_BOLD)
                term_line = (
                    f"{ANSI_DIM}[{timestamp}]{ANSI_RESET} "
                    f"{lvl_col}[{lvl_name}]{ANSI_RESET} "
                    f"{cmp_col}[{component}]{ANSI_RESET} "
                    f"{message}"
                )
                if exc:
                    term_line += f" {ANSI_DIM}| Exception: {str(exc)}{ANSI_RESET}"
            else:
                term_line = plain_line

            # Write to stdout/stderr
            out = sys.stderr if level >= LogLevel.ERROR else sys.stdout
            out.write(term_line + "\n")
            out.flush()

            # 3. Write plain uncolored text to persistent log file
            if self.log_file:
                try:
                    clean_for_file = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", plain_line)
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        f.write(clean_for_file + "\n")
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

    def pathway(self, message: str):
        """Log end-to-end request lifecycle through the Blast gateway."""
        self._log(LogLevel.INFO, "PATHWAY", message)

    def supabase(self, message: str):
        """Log direct interactions with Supabase backend."""
        self._log(LogLevel.INFO, "SUPABASE", message)

    def mesh(self, message: str):
        """Log mesh route scoring and fastest route selections."""
        self._log(LogLevel.INFO, "MESH", message)

    def security(self, message: str):
        self._log(LogLevel.INFO, "SECURITY", message)

    def queue(self, message: str):
        self._log(LogLevel.INFO, "QUEUE", message)

    def cluster(self, message: str):
        self._log(LogLevel.INFO, "CLUSTER", message)

    def worker(self, message: str):
        self._log(LogLevel.INFO, "WORKER", message)

    def get_logs(
        self,
        limit: int = 100,
        since_id: int = 0,
        component: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent structured logs for GUI streaming."""
        with self._lock:
            records = list(self._buffer)

        # Filter by since_id if polling incrementally
        if since_id > 0:
            records = [r for r in records if r["id"] > since_id]

        # Filter by component if requested
        if component and component.strip().upper() != "ALL":
            target = component.strip().upper()
            records = [r for r in records if r["component"].upper() == target]

        # Slice limit
        if len(records) > limit:
            records = records[-limit:]

        return records

    def clear_logs(self):
        """Clear memory buffer."""
        with self._lock:
            self._buffer.clear()


# Global default logger instance
logger = BlastLogger()


def get_logger(name: str = "blast") -> BlastLogger:
    """Obtain logger instance."""
    return logger
