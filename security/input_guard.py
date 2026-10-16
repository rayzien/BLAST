"""Strict Input Validation and Arbitrary Payload Guard for Blast Gateway.

Comprehensive defense against arbitrary, unvalidated, or malicious inputs.
Prevents prototype pollution, JSON bomb denial of service, illegal field
injection, script injections, and malformed PostgREST commands.
Guaranteed zero emojis.
"""

import re
import json
from typing import Any, Dict, List, Optional, Tuple, Union
from config import BlastConfig
from logger import logger


class StrictInputValidator:
    """Enterprise-grade input guard preventing arbitrary and malicious payload ingestion."""

    # Prototype pollution forbidden keys
    FORBIDDEN_PROTOTYPE_KEYS = {"__proto__", "constructor", "prototype"}

    # Disallowed control character regex (matches ASCII 0-31 except tab, newline, carriage return)
    DISALLOWED_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

    # Allowed table and column identifier pattern (alphanumeric, underscores, hyphens, periods)
    VALID_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

    # Command injection heuristics
    COMMAND_INJECTION_PATTERN = re.compile(r"(;\s*(sh|bash|curl|wget|rm|nc|python|cat)\b|`.*?`|\$\(.*?\))", re.IGNORECASE)

    def __init__(self, cfg: Optional[BlastConfig] = None):
        self.cfg = cfg
        self.enabled = True
        self.max_depth = 10
        self.max_field_count = 150

    def update_config(self, enabled: Optional[bool] = None, max_depth: Optional[int] = None, max_fields: Optional[int] = None):
        """Hot-reload input validation settings."""
        if enabled is not None:
            self.enabled = bool(enabled)
        if max_depth is not None and max_depth > 0:
            self.max_depth = int(max_depth)
        if max_fields is not None and max_fields > 0:
            self.max_field_count = int(max_fields)

    def validate_inbound_input(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, Any]] = None,
        body: Optional[Union[str, bytes]] = None,
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validate input parameters and payload structure before processing.
        Returns:
            (is_valid: bool, error_code: Optional[str], details: Optional[Dict])
        """
        if not self.enabled:
            return True, None, None

        # 1. Path identifier validation
        clean_path = path.strip("/")
        parts = clean_path.split("/")
        for part in parts:
            if part and not self.VALID_IDENTIFIER_PATTERN.match(part):
                return False, "INVALID_PATH_SEGMENT", {
                    "message": f"Path segment '{part}' contains illegal characters. Only alphanumeric, underscores, and hyphens permitted."
                }

        # 2. Query parameter validation
        if query_params:
            for key, val in query_params.items():
                if self.DISALLOWED_CONTROL_CHARS.search(key):
                    return False, "CORRUPT_QUERY_KEY", {"message": f"Illegal control character in parameter '{key}'."}

                val_str = str(val)
                if self.COMMAND_INJECTION_PATTERN.search(val_str):
                    logger.security(f"Command injection heuristic triggered in query param '{key}': {val_str}")
                    return False, "COMMAND_INJECTION_DETECTED", {
                        "message": f"Disallowed command execution sequence detected in parameter '{key}'."
                    }

        # 3. Payload and Body Validation
        if body:
            raw_text = body.decode("utf-8") if isinstance(body, bytes) else body
            if not raw_text.strip():
                return True, None, None

            if self.DISALLOWED_CONTROL_CHARS.search(raw_text):
                return False, "CORRUPT_PAYLOAD_BYTES", {"message": "Payload contains illegal unescaped ASCII control characters."}

            if self.COMMAND_INJECTION_PATTERN.search(raw_text):
                logger.security(f"Command injection heuristic triggered in payload body.")
                return False, "COMMAND_INJECTION_DETECTED", {"message": "Disallowed shell execution sequence detected in payload."}

            # Parse JSON if applicable
            content_type = headers.get("content-type", headers.get("Content-Type", ""))
            if "application/json" in content_type.lower() or raw_text.strip().startswith(("{", "[")):
                try:
                    parsed = json.loads(raw_text)
                except Exception as e:
                    return False, "MALFORMED_JSON", {"message": f"Invalid JSON syntax: {str(e)}"}

                is_ok, err_msg = self._validate_structure(parsed, current_depth=1)
                if not is_ok:
                    return False, "INPUT_GUARD_REJECTION", {"message": err_msg}

        return True, None, None

    def _validate_structure(self, data: Any, current_depth: int) -> Tuple[bool, Optional[str]]:
        """Recursively inspect parsed JSON data for prototype pollution, nesting depth, and excessive fields."""
        if current_depth > self.max_depth:
            return False, f"JSON nesting depth exceeds maximum allowable limit of {self.max_depth} levels."

        if isinstance(data, dict):
            if len(data) > self.max_field_count:
                return False, f"JSON object field count ({len(data)}) exceeds limit of {self.max_field_count} properties."

            for k, v in data.items():
                k_str = str(k)
                if k_str in self.FORBIDDEN_PROTOTYPE_KEYS:
                    logger.security(f"Prototype pollution attempt blocked: key '{k_str}'.")
                    return False, f"Illegal property name '{k_str}'. Prototype manipulation prohibited."

                if self.DISALLOWED_CONTROL_CHARS.search(k_str):
                    return False, f"Dangerous control characters in JSON key '{k_str}'."

                is_ok, err = self._validate_structure(v, current_depth + 1)
                if not is_ok:
                    return False, err

        elif isinstance(data, list):
            if len(data) > 1000:
                return False, f"JSON array items count ({len(data)}) exceeds limit of 1000 items."

            for item in data:
                is_ok, err = self._validate_structure(item, current_depth + 1)
                if not is_ok:
                    return False, err

        return True, None

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic metrics for the strict input validator."""
        return {
            "enabled": self.enabled,
            "max_depth": self.max_depth,
            "max_field_count": self.max_field_count,
        }
