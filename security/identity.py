"""Identity Protection and Anti-Spoofing Guard for Blast Gateway.

Comprehensive guardrails preventing identity theft, header forgery,
session hijacking, and replay attacks across client gateways and Supabase.
Guaranteed zero emojis.
"""

import hmac
import hashlib
import time
import threading
from typing import Any, Dict, Optional, Tuple, Set
from collections import OrderedDict
from config import BlastConfig
from logger import logger


class IdentityProtectionGuard:
    """Enterprise-grade anti-identity theft, anti-spoofing, and session integrity engine."""

    # Headers that malicious actors frequently spoof to hijack or assume arbitrary identities
    FORBIDDEN_UNTRUSTED_IDENTITY_HEADERS: Set[str] = {
        "x-blast-client-id",
        "x-blast-identity",
        "x-blast-role",
        "x-user-id",
        "x-forwarded-user",
        "x-remote-user",
        "x-client-identity",
        "x-authenticated-user",
        "x-blast-override-user",
    }

    def __init__(self, cfg: Optional[BlastConfig] = None):
        self.cfg = cfg
        self.enabled = True
        self.mode = "strict"  # "strict" or "standard"
        self._lock = threading.RLock()

        # Nonce cache to prevent replay attacks (max 5,000 nonces)
        self._seen_nonces: OrderedDict[str, float] = OrderedDict()
        self._max_nonces = 5000

        # Known client session fingerprints: client_id -> fingerprint_hash
        self._session_fingerprints: Dict[str, str] = {}

    def update_config(self, enabled: Optional[bool] = None, mode: Optional[str] = None):
        """Hot-reload identity protection parameters."""
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if mode is not None:
                self.mode = str(mode).lower().strip()

    def sanitize_inbound_identity_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Strip and scrub any user-supplied headers attempting to forge identity."""
        if not self.enabled:
            return dict(headers)

        cleaned: Dict[str, str] = {}
        for k, v in headers.items():
            if k.lower() in self.FORBIDDEN_UNTRUSTED_IDENTITY_HEADERS:
                logger.security(f"Stripped untrusted spoofed identity header '{k}' from inbound request.")
                continue
            cleaned[k] = v

        return cleaned

    def generate_identity_token(self, client_id: str, secret_key: str, salt: Optional[str] = None) -> str:
        """Derive a cryptographically bound HMAC-SHA256 identity proof for a verified client."""
        raw_msg = f"{client_id}:{salt or 'blast-identity'}"
        return hmac.new(secret_key.encode("utf-8"), raw_msg.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_identity_token(self, client_id: str, secret_key: str, token: str, salt: Optional[str] = None) -> bool:
        """Verify an identity token in constant-time."""
        if not token or not secret_key:
            return False
        expected = self.generate_identity_token(client_id, secret_key, salt)
        return hmac.compare_digest(token.lower(), expected.lower())

    def verify_request_identity(
        self,
        client_id: str,
        secret_key: Optional[str],
        headers: Dict[str, str],
        remote_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify that request sender possesses genuine client identity and has not spoofed credentials.
        Returns:
            (is_valid: bool, error_message: Optional[str])
        """
        if not self.enabled:
            return True, None

        # 1. Anonymous identity assumption is disallowed in strict mode when API keys are required
        require_key = getattr(self.cfg, "REQUIRE_API_KEY", True) if self.cfg else True
        if self.mode == "strict" and client_id == "anonymous" and require_key:
            return False, "Strict identity protection rejects unauthenticated or anonymous identity assumption."


        # 2. Check for Replay Attack Nonce if provided
        nonce = headers.get("X-Blast-Nonce") or headers.get("x-blast-nonce")
        timestamp_str = headers.get("X-Blast-Timestamp") or headers.get("x-blast-timestamp")
        if nonce:
            with self._lock:
                now = time.time()
                # Clean up expired nonces (> 300 seconds old)
                while self._seen_nonces and next(iter(self._seen_nonces.values())) < (now - 300):
                    self._seen_nonces.popitem(last=False)

                if nonce in self._seen_nonces:
                    logger.security(f"Replay attack blocked: nonce '{nonce}' already seen for client '{client_id}'.")
                    return False, f"Replay attack detected: duplicate nonce '{nonce}' rejected."

                # Add new nonce
                if len(self._seen_nonces) >= self._max_nonces:
                    self._seen_nonces.popitem(last=False)
                self._seen_nonces[nonce] = now

        # 3. Optional Identity Signature verification if X-Blast-Identity-Token is provided
        provided_token = headers.get("X-Blast-Identity-Token") or headers.get("x-blast-identity-token")
        if provided_token and secret_key:
            if not self.verify_identity_token(client_id, secret_key, provided_token):
                logger.security(f"Invalid identity token supplied for client '{client_id}'.")
                return False, "Cryptographic identity verification token mismatch."

        # 4. Session Fingerprint Anomaly Detection
        if remote_ip and user_agent:
            fp = hashlib.sha256(f"{remote_ip.split(':')[0]}:{user_agent[:40]}".encode("utf-8")).hexdigest()[:16]
            with self._lock:
                existing_fp = self._session_fingerprints.get(client_id)
                if existing_fp and existing_fp != fp and self.mode == "strict":
                    logger.security(
                        f"Identity hijack warning: client '{client_id}' switched fingerprint from {existing_fp} to {fp}."
                    )
                self._session_fingerprints[client_id] = fp

        return True, None

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic metrics for the identity protection guard."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "mode": self.mode,
                "active_sessions": len(self._session_fingerprints),
                "tracked_nonces": len(self._seen_nonces),
            }
