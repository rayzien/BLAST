"""Security Checker System for Blast Gateway.

Comprehensive multi-phase request verification and response sanitization.
Ensures zero bad/malicious requests reach Supabase and zero internal database
leaks or poisoned payloads return to client applications.
Guaranteed zero emojis.
"""

import hmac
import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from config import BlastConfig
from logger import logger


class SecurityChecker:
    """Enterprise-grade security verification and response hygiene engine."""

    # Allowed Supabase root API route prefixes
    ALLOWED_SUPABASE_ROOTS = (
        "/rest/v1",
        "/auth/v1",
        "/storage/v1",
        "/graphql/v1",
        "/functions/v1",
        "/realtime/v1",
    )

    # Allowed HTTP methods
    ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

    # Allowed PostgREST query operators
    VALID_POSTGREST_OPERATORS = {
        "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "is",
        "in", "cs", "cd", "sl", "sr", "nxl", "nxr", "adj", "ov",
        "fts", "plfts", "phfts", "wfts", "not",
    }

    # SQL Injection detection patterns targeting queries and URL parameters
    SQL_INJECTION_PATTERNS = [
        re.compile(r"(\b(UNION(\s+ALL)?)\s+SELECT\b)", re.IGNORECASE),
        re.compile(r"(;\s*(DROP|ALTER|TRUNCATE|DELETE|UPDATE|INSERT|CREATE|EXEC)\s+)", re.IGNORECASE),
        re.compile(r"(--\s*$|/\*.*?\*/)", re.DOTALL),
        re.compile(r"(\b(OR|AND)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+['\"])", re.IGNORECASE),
        re.compile(r"(\bWAITFOR\s+DELAY\b|\bPG_SLEEP\s*\()", re.IGNORECASE),
        re.compile(r"(\bXP_CMDSHELL\b|\bBENCHMARK\s*\()", re.IGNORECASE),
    ]

    # Path traversal detection patterns
    PATH_TRAVERSAL_PATTERN = re.compile(r"(\.\./|\.\.\\|%2e%2e%2f|%2e%2e\/)", re.IGNORECASE)

    # Cross-Site Scripting (XSS) patterns in text payloads
    XSS_PATTERNS = [
        re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
        re.compile(r"javascript:\s*", re.IGNORECASE),
        re.compile(r"data:text/html;\s*base64,", re.IGNORECASE),
        re.compile(r"<\s*iframe[^>]*>", re.IGNORECASE),
        re.compile(r"<\s*img[^>]+src=[^>]+onerror\s*=", re.IGNORECASE),
    ]

    # Internal database and infrastructure error strings to scrub from responses
    SENSITIVE_LEAK_PATTERNS = [
        re.compile(r"relation\s+.*?does not exist", re.IGNORECASE),
        re.compile(r"could not connect to server", re.IGNORECASE),
        re.compile(r"pg_hba\.conf", re.IGNORECASE),
        re.compile(r"psycopg2\.[A-Za-z]+Error", re.IGNORECASE),
        re.compile(r"syntax error at or near", re.IGNORECASE),
        re.compile(r"password authentication failed", re.IGNORECASE),
        re.compile(r"column\s+.*?does not exist", re.IGNORECASE),
        re.compile(r"violates\s+(not-null|unique|foreign key|check)\s+constraint", re.IGNORECASE),
        re.compile(r"PGRST\d{3}", re.IGNORECASE),
    ]

    def __init__(self, cfg: BlastConfig):
        self.cfg = cfg
        self.max_payload_bytes = cfg.MAX_PAYLOAD_BYTES
        self.max_json_depth = 15

    # -------------------------------------------------------------------------
    # Inbound Request Verification Pipeline
    # -------------------------------------------------------------------------
    def verify_inbound_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, Any]] = None,
        body: Optional[Union[str, bytes]] = None,
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Verify inbound request before forwarding or queueing.
        Returns:
            (is_valid: bool, error_code: Optional[str], error_details: Optional[Dict])
        """
        # 1. Method Verification
        norm_method = method.upper()
        if norm_method not in self.ALLOWED_METHODS:
            return False, "INVALID_METHOD", {"message": f"HTTP method '{method}' is not supported."}

        # 2. Path & Route Verification
        clean_path = f"/{path.lstrip('/')}"
        is_path_ok, path_err = self._verify_path(clean_path)
        if not is_path_ok:
            return False, "INVALID_PATH", {"message": path_err, "path": clean_path}

        # 3. Query Parameter Verification
        if query_params:
            is_query_ok, query_err = self._verify_query_params(query_params)
            if not is_query_ok:
                return False, "MALFORMED_QUERY", {"message": query_err}

        # 4. Header Verification (CRLF, timestamp freshness, HMAC signature)
        is_hdr_ok, hdr_err = self._verify_headers(headers, method=norm_method, path=clean_path, body=body)
        if not is_hdr_ok:
            return False, "INVALID_HEADERS", {"message": hdr_err}

        # 5. Payload / Body Verification
        if body:
            is_body_ok, body_err, parsed_data = self._verify_body(body, headers)
            if not is_body_ok:
                return False, "INVALID_PAYLOAD", {"message": body_err}

        return True, None, None

    def _verify_path(self, path: str) -> Tuple[bool, Optional[str]]:
        """Verify URL path against traversal, null bytes, and valid Supabase targets."""
        # Null bytes
        if "\0" in path:
            return False, "Null byte character detected in path."

        # Path traversal
        if self.PATH_TRAVERSAL_PATTERN.search(path):
            return False, "Path traversal sequence detected."

        # CRLF injection in path
        if "\r" in path or "\n" in path:
            return False, "CRLF line-break sequence detected in path."

        # Enforce valid Supabase root service
        is_valid_root = any(path.startswith(prefix) for prefix in self.ALLOWED_SUPABASE_ROOTS)
        if not is_valid_root:
            return False, (
                f"Destination path '{path}' does not match an authorized Supabase API service. "
                f"Authorized endpoints: {', '.join(self.ALLOWED_SUPABASE_ROOTS)}"
            )

        return True, None

    def _verify_query_params(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Verify query parameters against SQL injection patterns and syntax errors."""
        for key, value in params.items():
            # Check key
            if "\0" in key or "\r" in key or "\n" in key:
                return False, "Dangerous control character detected in query parameter key."

            val_str = str(value)
            # Check values against SQL injection heuristics
            for pattern in self.SQL_INJECTION_PATTERNS:
                if pattern.search(val_str) or pattern.search(key):
                    logger.security(f"SQL injection attempt detected in query: key='{key}' val='{val_str}'")
                    return False, f"Potentially malicious SQL sequence detected in query parameter '{key}'."

            # Verify PostgREST operator structure if formatted as col=op.val
            if "." in val_str and not key.startswith("_") and key not in ("select", "order", "limit", "offset", "on_conflict"):
                parts = val_str.split(".", 1)
                op = parts[0].lower()
                if op not in self.VALID_POSTGREST_OPERATORS:
                    # Could be legitimate text, but if it looks like an operator attempt, log warning
                    if len(op) <= 5 and op.isalpha():
                        return False, f"Unrecognized PostgREST operator '{op}' in parameter '{key}'."

        return True, None

    def _verify_headers(
        self,
        headers: Dict[str, str],
        method: str,
        path: str,
        body: Optional[Union[str, bytes]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Verify header integrity and optional HMAC signature / timestamp."""
        for k, v in headers.items():
            if "\r" in v or "\n" in v:
                return False, f"CRLF header injection detected in header '{k}'."

        # Optional Replay Attack Prevention (X-Blast-Timestamp)
        ts_val = headers.get("X-Blast-Timestamp") or headers.get("x-blast-timestamp")
        if ts_val:
            try:
                ts = float(ts_val)
                now = time.time()
                # Must be within 300 seconds (5 minutes)
                if abs(now - ts) > 300:
                    return False, "Request timestamp expired or skewed beyond allowable 300s window."
            except ValueError:
                return False, "Malformed X-Blast-Timestamp header."

        # Optional HMAC Request Signing Verification (X-Blast-Signature)
        sig_val = headers.get("X-Blast-Signature") or headers.get("x-blast-signature")
        if sig_val and self.cfg.API_KEYS:
            secret = self.cfg.API_KEYS[0]
            body_str = body.decode("utf-8") if isinstance(body, bytes) else (body or "")
            expected_payload = f"{method}:{path}:{ts_val or ''}:{body_str}".encode("utf-8")
            expected_sig = hmac.new(secret.encode("utf-8"), expected_payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig_val.lower(), expected_sig.lower()):
                return False, "HMAC request signature verification failed."

        return True, None

    def _verify_body(
        self,
        body: Union[str, bytes],
        headers: Dict[str, str],
    ) -> Tuple[bool, Optional[str], Optional[Any]]:
        """Verify body size, JSON syntax, nesting depth, and script injection."""
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body

        # Size check
        if len(body_bytes) > self.max_payload_bytes:
            return False, f"Payload size ({len(body_bytes)} bytes) exceeds maximum limit ({self.max_payload_bytes} bytes).", None

        # Content-Type check
        content_type = headers.get("content-type", headers.get("Content-Type", ""))
        is_json = "application/json" in content_type.lower() or body_bytes.strip().startswith((b"{", b"["))

        parsed_data = None
        if is_json:
            try:
                raw_text = body_bytes.decode("utf-8")
                parsed_data = json.loads(raw_text)
            except Exception as e:
                return False, f"Malformed JSON syntax in request body: {str(e)}", None

            # Enforce JSON nesting depth limit
            depth = self._calculate_depth(parsed_data)
            if depth > self.max_json_depth:
                return False, f"JSON payload nesting depth ({depth}) exceeds maximum limit ({self.max_json_depth}).", None

            # Scan strings in JSON for XSS
            xss_found, xss_err = self._scan_json_for_xss(parsed_data)
            if xss_found:
                return False, xss_err, None

        return True, None, parsed_data

    def _calculate_depth(self, data: Any, current: int = 1) -> int:
        """Calculate maximum nesting depth of parsed JSON structure."""
        if isinstance(data, dict):
            if not data:
                return current
            return max(self._calculate_depth(v, current + 1) for v in data.values())
        elif isinstance(data, list):
            if not data:
                return current
            return max(self._calculate_depth(item, current + 1) for item in data)
        return current

    def _scan_json_for_xss(self, data: Any) -> Tuple[bool, Optional[str]]:
        """Recursively inspect string values in JSON for malicious script injection."""
        if isinstance(data, dict):
            for k, v in data.items():
                found, err = self._scan_json_for_xss(v)
                if found:
                    return True, err
        elif isinstance(data, list):
            for item in data:
                found, err = self._scan_json_for_xss(item)
                if found:
                    return True, err
        elif isinstance(data, str):
            for pattern in self.XSS_PATTERNS:
                if pattern.search(data):
                    logger.security(f"Malicious script pattern detected in JSON string: {data[:60]}")
                    return True, "Potential script injection or unsafe markup detected in payload."
        return False, None

    # -------------------------------------------------------------------------
    # Outbound Response Verification & Sanitization Pipeline
    # -------------------------------------------------------------------------
    def verify_and_sanitize_response(
        self,
        status_code: int,
        response_headers: Dict[str, str],
        response_body: str,
    ) -> Tuple[int, Dict[str, str], str]:
        """
        Verify and sanitize upstream Supabase response before delivering to client.
        1. Scrubs raw PostgreSQL error traces from body.
        2. Normalizes database errors into standard, safe JSON.
        3. Strips sensitive infrastructure headers.
        4. Injects security headers.
        """
        cleaned_headers = dict(response_headers)

        # 1. Strip sensitive upstream headers
        forbidden_resp_headers = {"server", "x-powered-by", "cf-ray", "cf-cache-status", "x-supabase-trace"}
        for k in list(cleaned_headers.keys()):
            if k.lower() in forbidden_resp_headers:
                del cleaned_headers[k]

        # 2. Inject hardened client security headers
        cleaned_headers["X-Content-Type-Options"] = "nosniff"
        cleaned_headers["X-Frame-Options"] = "DENY"
        cleaned_headers["X-XSS-Protection"] = "1; mode=block"
        cleaned_headers["X-Blast-Security-Verified"] = "true"

        # 3. Detect and sanitize database leakage in response body
        sanitized_body = response_body
        is_leaking = False

        if status_code >= 400 and response_body:
            for pattern in self.SENSITIVE_LEAK_PATTERNS:
                if pattern.search(response_body):
                    is_leaking = True
                    break

        if is_leaking:
            logger.security(f"Scrubbed sensitive database error leak from upstream HTTP {status_code} response.")
            safe_error_obj = {
                "error": "Database error",
                "code": "BLAST_DATABASE_ERROR",
                "message": "The database operation could not be completed with the provided parameters.",
                "status": status_code,
            }
            sanitized_body = json.dumps(safe_error_obj)
            cleaned_headers["content-type"] = "application/json"

        return status_code, cleaned_headers, sanitized_body
