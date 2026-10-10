"""Proxy handler bridging client requests directly to Supabase."""

from typing import Any, Dict, Optional, Tuple
from config import BlastConfig
from security.firewall import Firewall
from .client import SupabaseClient


class ProxyHandler:
    """Manages synchronous proxy execution from client to Supabase."""

    def __init__(self, cfg: BlastConfig, client: Optional[SupabaseClient] = None, firewall: Optional[Firewall] = None):
        self.cfg = cfg
        self.client = client or SupabaseClient(cfg)
        self.firewall = firewall or Firewall(cfg)

    def forward(
        self,
        method: str,
        supabase_path: str,
        incoming_headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
        body: Optional[str] = None,
    ) -> Tuple[int, Dict[str, str], str]:
        """
        Sanitize and synchronously forward a request to Supabase.
        Returns:
            (status_code: int, response_headers: dict, response_body: str)
        """
        # Strip hop-by-hop & blast headers
        sanitized_headers = self.firewall.sanitize_headers(incoming_headers)

        return self.client.execute(
            method=method,
            path=supabase_path,
            headers=sanitized_headers,
            params=params or {},
            body=body,
        )
