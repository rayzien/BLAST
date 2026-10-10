"""Authentication and key validation module for Blast."""

import hmac
from typing import Optional, Tuple
from config import BlastConfig


class Authenticator:
    """Manages API key authentication for incoming Blast requests."""

    def __init__(self, cfg: BlastConfig):
        self.cfg = cfg
        # Store valid keys in a set for O(1) lookup
        self.valid_keys = set(cfg.API_KEYS)

    def update_keys(self, new_keys):
        """Hot-reload valid keys dynamically."""
        self.valid_keys = set(new_keys)

    def extract_api_key(self, headers: dict, query_params: Optional[dict] = None) -> Optional[str]:
        """Extract API key from headers or query parameters."""
        # Check standard custom header
        key = headers.get("x-blast-key") or headers.get("X-Blast-Key")
        if key:
            return key.strip()

        # Check Bearer authorization token
        auth_header = headers.get("authorization") or headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            # If the bearer matches one of our blast keys, use it
            if token in self.valid_keys or not self.cfg.REQUIRE_API_KEY:
                return token

        # Fallback to query param
        if query_params and "blast_key" in query_params:
            return query_params["blast_key"].strip()

        return None

    def authenticate(self, headers: dict, query_params: Optional[dict] = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Authenticate request.
        Returns:
            (is_authenticated: bool, client_id: Optional[str], error_message: Optional[str])
        """
        if not self.cfg.REQUIRE_API_KEY:
            return True, "anonymous", None

        provided_key = self.extract_api_key(headers, query_params)
        if not provided_key:
            return False, None, "Missing authentication key. Provide 'X-Blast-Key' header or 'Bearer' token."

        # Constant-time comparison across allowed keys to prevent timing attacks
        for valid_key in self.valid_keys:
            if hmac.compare_digest(provided_key, valid_key):
                # Derive a safe client ID from key prefix
                client_id = f"client-{provided_key[:8]}"
                return True, client_id, None

        return False, None, "Invalid API key provided."
