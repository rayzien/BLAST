import time
import httpx
from typing import Any, Dict, Optional, Tuple
from config import BlastConfig
from logger import logger


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

    def reload_config(self):
        """Reload base_url and timeout when config changes dynamically."""
        self.base_url = self.cfg.SUPABASE_URL.rstrip("/")
        self.timeout = self.cfg.SUPABASE_TIMEOUT_SECONDS

    def prepare_headers(self, incoming_headers: Dict[str, str], body: Optional[str] = None) -> Dict[str, str]:
        """Inject required Supabase keys while preserving caller JWT tokens."""
        out_headers = dict(incoming_headers)

        # If body appears to be JSON and content-type is missing or text/plain, set to application/json
        ct_key = next((k for k in out_headers if k.lower() == "content-type"), None)
        if body and body.strip().startswith(("{", "[")):
            if not ct_key or out_headers[ct_key].lower().startswith("text/plain"):
                out_headers["Content-Type"] = "application/json"

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

        # Strip BLAST gateway auth parameters from forwarding to upstream Supabase
        cleaned_params = {
            k: v for k, v in params.items()
            if k.lower() not in ("blast_key", "blast_token", "api_key", "_method")
        }

        # Normalize relative path
        if not path.startswith("/"):
            path = "/" + path

        if not self.base_url:
            return 503, {"content-type": "application/json"}, '{"error": "SUPABASE_NOT_CONFIGURED", "message": "Supabase target URL is not configured. Set supabase_url in settings.json or through the Web GUI."}'

        target_url = f"{self.base_url}{path}"
        effective_headers = self.prepare_headers(headers, body=body)
        if method.upper() == "POST" and not any(k.lower() == "prefer" for k in effective_headers):
            effective_headers["Prefer"] = "return=representation"
        start_time = time.perf_counter()

        try:
            response = self._client.request(
                method=method.upper(),
                url=target_url,
                headers=effective_headers,
                params=cleaned_params,
                content=body.encode("utf-8") if body is not None else None,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            # Convert response headers to simple dictionary
            resp_headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-encoding")}

            logger.supabase(
                f"{method.upper()} {path} -> HTTP {response.status_code} ({elapsed_ms:.1f}ms, {len(response.text)} bytes)"
            )
            return response.status_code, resp_headers, response.text

        except httpx.TimeoutException as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error("SUPABASE", f"{method.upper()} {path} -> Timeout after {elapsed_ms:.1f}ms: {exc}")
            return 504, {}, f'{{"error": "Supabase gateway timeout", "details": "{str(exc)}"}}'
        except httpx.RequestError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error("SUPABASE", f"{method.upper()} {path} -> Request Error after {elapsed_ms:.1f}ms: {exc}")
            return 502, {}, f'{{"error": "Supabase gateway connection error", "details": "{str(exc)}"}}'
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error("SUPABASE", f"{method.upper()} {path} -> Unexpected Exception after {elapsed_ms:.1f}ms: {exc}", exc=exc)
            return 500, {}, f'{{"error": "Internal proxy error", "details": "{str(exc)}"}}'

    def close(self):
        """Close connection pool."""
        self._client.close()
