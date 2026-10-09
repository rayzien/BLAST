"""Request firewall, sanitization, and security guardrails."""

import re
from typing import Optional, Tuple, Dict
from config import BlastConfig


class Firewall:
    """Inspects and sanitizes inbound requests before they reach the queue or proxy."""

    # Disallowed HTTP methods
    ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

    # Suspicious path traversal pattern
    PATH_TRAVERSAL_PATTERN = re.compile(r"(\.\./|\.\.\\)")

    # Hop-by-hop headers that should not be forwarded
    FORBIDDEN_FORWARD_HEADERS = {
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }

    def __init__(self, cfg: BlastConfig):
        self.max_payload_bytes = cfg.MAX_PAYLOAD_BYTES

    def validate_request(
        self,
        method: str,
        path: str,
        content_length: Optional[int] = None,
        raw_body: Optional[bytes] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate request metadata and body against security policies.
        Returns:
            (is_valid: bool, error_reason: Optional[str])
        """
        # 1. Method check
        if method.upper() not in self.ALLOWED_METHODS:
            return False, f"HTTP method '{method}' is not allowed."

        # 2. Path traversal check
        if self.PATH_TRAVERSAL_PATTERN.search(path):
            return False, "Dangerous path traversal sequence detected."

        # 3. Payload size check
        if content_length is not None and content_length > self.max_payload_bytes:
            return False, f"Payload size {content_length} bytes exceeds maximum limit ({self.max_payload_bytes} bytes)."

        if raw_body is not None and len(raw_body) > self.max_payload_bytes:
            return False, f"Body size {len(raw_body)} bytes exceeds maximum limit ({self.max_payload_bytes} bytes)."

        # 4. Null byte injection check in path
        if "\0" in path:
            return False, "Null byte character detected in request path."

        return True, None

    def sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Strip hop-by-hop headers and internal Blast headers before forwarding."""
        sanitized = {}
        for key, value in headers.items():
            lower_k = key.lower()
            if lower_k in self.FORBIDDEN_FORWARD_HEADERS:
                continue
            # Strip internal Blast management headers
            if lower_k.startswith("x-blast-"):
                continue
            sanitized[key] = value
        return sanitized
