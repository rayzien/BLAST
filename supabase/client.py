"""Low-level HTTP client for communicating with Supabase backend."""

import httpx
from typing import Any, Dict, Optional, Tuple
from config import BlastConfig


class SupabaseClient:
    """Handles communication with Supabase endpoints with connection pooling and auth injection."""

    def __init__(self, cfg: BlastConfig):
        self.cfg = cfg
        self.base_url = cfg.SUPABASE_URL.rstrip("/")
        self.timeout = cfg.SUPABASE_TIMEOUT_SECONDS

        # Thread-safe persistent connection pool
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=5.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    def prepare_headers(self, incoming_headers: Dict[str, str]) -> Dict[str, str]:
        """Inject required Supabase keys while preserving caller JWT tokens."""
        out_headers = dict(incoming_headers)

        # Ensure apikey is present
        if "apikey" not in out_headers and self.cfg.SUPABASE_ANON_KEY:
            out_headers["apikey"] = self.cfg.SUPABASE_ANON_KEY

        # Ensure Authorization Bearer is present
        if "authorization" not in out_headers and "Authorization" not in out_headers:
            # Fallback to anon key or service role key
            auth_key = self.cfg.SUPABASE_SERVICE_ROLE_KEY or self.cfg.SUPABASE_ANON_KEY
            if auth_key:
                out_headers["Authorization"] = f"Bearer {auth_key}"

        return out_headers

    def execute(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[str] = None,
    ) -> Tuple[int, Dict[str, str], str]:
        """
        Execute request against Supabase.
        Returns:
            (status_code: int, response_headers: dict, response_text: str)
        """
        headers = headers or {}
        params = params or {}

        # Normalize relative path
        if not path.startswith("/"):
            path = "/" + path

        target_url = f"{self.base_url}{path}"
        effective_headers = self.prepare_headers(headers)

        try:
            response = self._client.request(
                method=method.upper(),
                url=target_url,
                headers=effective_headers,
                params=params,
                content=body.encode("utf-8") if body is not None else None,
            )

            # Convert response headers to simple dictionary
            resp_headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-encoding")}

            return response.status_code, resp_headers, response.text

        except httpx.TimeoutException as exc:
            return 504, {}, f'{{"error": "Supabase gateway timeout", "details": "{str(exc)}"}}'
        except httpx.RequestError as exc:
            return 502, {}, f'{{"error": "Supabase gateway connection error", "details": "{str(exc)}"}}'
        except Exception as exc:
            return 500, {}, f'{{"error": "Internal proxy error", "details": "{str(exc)}"}}'

    def close(self):
        """Close connection pool."""
        self._client.close()
