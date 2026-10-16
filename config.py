"""Configuration settings for Blast security, queue, and cluster subsystems.
Guaranteed zero emojis.
"""

import os
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Path to settings.json (persistent credentials for private repos and free tier)
_settings_json_path = os.getenv(
    "BLAST_SETTINGS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json"),
)


def load_settings(path: Optional[str] = None) -> Dict[str, Any]:
    """Universal loader for settings.json available to all files and subsystems."""
    target = path or _settings_json_path
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def get_setting(key: str, default: Any = None) -> Any:
    """Universal setting retriever: checks environment first, then settings.json, then default."""
    # 1. Direct environment variable match
    env_keys = [key.upper(), f"BLAST_{key.upper()}"]
    for ek in env_keys:
        if ek in os.environ and os.environ[ek].strip():
            return os.environ[ek].strip()

    # 2. settings.json match
    s_data = load_settings()
    for sk in (key.lower(), key):
        if sk in s_data and s_data[sk] is not None:
            return s_data[sk]

    return default


def get_credentials() -> Dict[str, str]:
    """Universal credential retriever for any file in Blast.
    Returns clean dictionary of credentials loaded from settings.json and environment.
    """
    s = load_settings()
    k1 = os.getenv("BLAST_API_KEY_1") or s.get("blast_api_key_1") or ""
    k2 = os.getenv("BLAST_API_KEY_2") or s.get("blast_api_key_2") or ""
    c_sec = os.getenv("BLAST_CLUSTER_SECRET") or s.get("blast_cluster_secret") or ""

    if not k1 and not k2:
        raw_keys = os.getenv("BLAST_API_KEYS", "")
        if raw_keys:
            parts = [p.strip() for p in raw_keys.split(",") if p.strip()]
            if parts:
                k1 = parts[0]
            if len(parts) > 1:
                k2 = parts[1]

    sup_url = (os.getenv("SUPABASE_URL") or s.get("supabase_url") or "").strip().rstrip("/")
    if sup_url and not (sup_url.startswith("http://") or sup_url.startswith("https://")):
        sup_url = "https://" + sup_url

    c_secs = os.getenv("BLAST_CLUSTER_SECRETS") or s.get("blast_cluster_secrets")
    if not c_secs:
        c_secs = os.getenv("BLAST_CLUSTER_SECRET") or s.get("blast_cluster_secret") or "https://sas-the-treasure-grape-xr-prototype.onrender.com/"
    if isinstance(c_secs, list):
        c_secs = ",".join(c_secs)

    return {
        "supabase_url": sup_url,
        "supabase_anon_key": str(os.getenv("SUPABASE_ANON_KEY") or s.get("supabase_anon_key") or "").strip(),
        "supabase_service_role_key": str(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or s.get("supabase_service_role_key") or "").strip(),
        "blast_api_key_1": str(k1).strip() or "blast-secret-key-1",
        "blast_api_key_2": str(k2).strip() or "blast-dev-key",
        "blast_cluster_secrets": str(c_secs).strip(),
    }


def resolve_port() -> int:
    """Resolve active port with precedence:
    1. PORT env var (standard for Render, Heroku, Cloud Run)
    2. BLAST_PORT env var
    3. settings.json blast_port or port
    4. Default 8080
    """
    for env_var in ("PORT", "BLAST_PORT"):
        val = os.getenv(env_var)
        if val and str(val).strip():
            try:
                return int(str(val).strip())
            except ValueError:
                pass

    s = load_settings()
    for k in ("blast_port", "port"):
        if k in s and s[k] is not None:
            try:
                return int(str(s[k]).strip())
            except ValueError:
                pass

    return 8080


# Automatically populate environment defaults from settings.json if not already in env
_initial_settings = load_settings()
if _initial_settings:
    def _apply_setting_val(env_k: str, v: Any):
        if v is not None and str(v).strip():
            cur = os.environ.get(env_k)
            if cur is None or cur.strip() == "":
                os.environ[env_k] = str(v).strip()

    _apply_setting_val("SUPABASE_URL", _initial_settings.get("supabase_url"))
    _apply_setting_val("SUPABASE_ANON_KEY", _initial_settings.get("supabase_anon_key"))
    if _initial_settings.get("supabase_service_role_key"):
        _apply_setting_val("SUPABASE_SERVICE_ROLE_KEY", _initial_settings.get("supabase_service_role_key"))
    
    if "blast_cluster_secrets" in _initial_settings:
        c_val = _initial_settings["blast_cluster_secrets"]
        _apply_setting_val("BLAST_CLUSTER_SECRETS", ",".join(c_val) if isinstance(c_val, list) else str(c_val))
    else:
        _apply_setting_val("BLAST_CLUSTER_SECRET", _initial_settings.get("blast_cluster_secret"))

    _keys = []
    if _initial_settings.get("blast_api_key_1"):
        _keys.append(str(_initial_settings["blast_api_key_1"]).strip())
    if _initial_settings.get("blast_api_key_2"):
        _keys.append(str(_initial_settings["blast_api_key_2"]).strip())
    if _keys:
        _apply_setting_val("BLAST_API_KEYS", ",".join(_keys))
    elif _initial_settings.get("blast_api_keys"):
        _apply_setting_val("BLAST_API_KEYS", str(_initial_settings["blast_api_keys"]).strip())

    if "max_workers" in _initial_settings:
        _apply_setting_val("BLAST_MAX_WORKERS", str(_initial_settings["max_workers"]))
    if "rate_limit_rps" in _initial_settings:
        _apply_setting_val("BLAST_RATE_LIMIT_RPS", str(_initial_settings["rate_limit_rps"]))
    if "rate_limit_burst" in _initial_settings:
        _apply_setting_val("BLAST_RATE_LIMIT_BURST", str(_initial_settings["rate_limit_burst"]))
    if "blast_host" in _initial_settings or "host" in _initial_settings:
        _apply_setting_val("BLAST_HOST", str(_initial_settings.get("blast_host") or _initial_settings.get("host")))
    if "mesh_routing_enabled" in _initial_settings:
        _apply_setting_val("BLAST_MESH_ROUTING_ENABLED", str(_initial_settings["mesh_routing_enabled"]).lower())
    if "awake_enabled" in _initial_settings:
        _apply_setting_val("BLAST_AWAKE_ENABLED", str(_initial_settings["awake_enabled"]).lower())
    if "awake_interval_seconds" in _initial_settings:
        _apply_setting_val("BLAST_AWAKE_INTERVAL_SECONDS", str(_initial_settings["awake_interval_seconds"]))
    if "awake_ping_self" in _initial_settings:
        _apply_setting_val("BLAST_AWAKE_PING_SELF", str(_initial_settings["awake_ping_self"]).lower())
    if "awake_ping_supabase" in _initial_settings:
        _apply_setting_val("BLAST_AWAKE_PING_SUPABASE", str(_initial_settings["awake_ping_supabase"]).lower())
    if "awake_ping_peers" in _initial_settings:
        _apply_setting_val("BLAST_AWAKE_PING_PEERS", str(_initial_settings["awake_ping_peers"]).lower())
    if "advanced_security_enabled" in _initial_settings:
        _apply_setting_val("BLAST_ADVANCED_SECURITY_ENABLED", str(_initial_settings["advanced_security_enabled"]).lower())
    if "identity_protection_mode" in _initial_settings:
        _apply_setting_val("BLAST_IDENTITY_PROTECTION_MODE", str(_initial_settings["identity_protection_mode"]))
    if "strict_input_validation" in _initial_settings:
        _apply_setting_val("BLAST_STRICT_INPUT_VALIDATION", str(_initial_settings["strict_input_validation"]).lower())
    if "credit_check_enabled" in _initial_settings:
        _apply_setting_val("BLAST_CREDIT_CHECK_ENABLED", str(_initial_settings["credit_check_enabled"]).lower())
    if "default_client_credits" in _initial_settings:
        _apply_setting_val("BLAST_DEFAULT_CLIENT_CREDITS", str(_initial_settings["default_client_credits"]))
    if "credits_per_proxy_request" in _initial_settings:
        _apply_setting_val("BLAST_CREDITS_PER_PROXY_REQUEST", str(_initial_settings["credits_per_proxy_request"]))
    if "credits_per_queue_request" in _initial_settings:
        _apply_setting_val("BLAST_CREDITS_PER_QUEUE_REQUEST", str(_initial_settings["credits_per_queue_request"]))


# Automatically load .env file if present
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _v = _v.strip()
                    if not (_v.startswith('"') and _v.endswith('"')) and not (_v.startswith("'") and _v.endswith("'")):
                        _v = _v.split("#", 1)[0].strip()
                    _v = _v.strip("'\"")
                    os.environ.setdefault(_k.strip(), _v)
    except Exception:
        pass


def _get_combined_peers() -> List[str]:
    s = load_settings()
    raw_sources = [
        os.getenv("BLAST_PEER_URLS", ""),
        os.getenv("BLAST_SERVER_LINKS", ""),
        os.getenv("BLAST_CLUSTER_NODES", ""),
        os.getenv("BLAST_CLUSTER_SECRETS", ""),
        os.getenv("BLAST_CLUSTER_SECRET", ""),
    ]
    for key in ("peer_urls", "server_links", "blast_peer_urls", "blast_server_links"):
        val = s.get(key)
        if isinstance(val, list):
            raw_sources.extend([str(x) for x in val if x])
        elif isinstance(val, str) and val.strip():
            raw_sources.append(val.strip())

    c_secs = s.get("blast_cluster_secrets")
    if isinstance(c_secs, list):
        for cs in c_secs:
            if isinstance(cs, str) and cs.strip().startswith(("http://", "https://")):
                raw_sources.append(cs.strip())
    elif isinstance(c_secs, str) and c_secs.strip().startswith(("http://", "https://")):
        raw_sources.append(c_secs.strip())

    c_sec_single = s.get("blast_cluster_secret")
    if isinstance(c_sec_single, str) and c_sec_single.strip().startswith(("http://", "https://")):
        raw_sources.append(c_sec_single.strip())

    seen = set()
    res = []
    local_urls = {
        (os.getenv("BLAST_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or s.get("blast_public_url", "")).strip().rstrip("/"),
        f"http://{os.getenv('BLAST_HOST', '0.0.0.0')}:{resolve_port()}".rstrip("/"),
        f"http://127.0.0.1:{resolve_port()}".rstrip("/"),
        f"http://localhost:{resolve_port()}".rstrip("/"),
    }
    local_urls.discard("")

    for chunk in raw_sources:
        for u in str(chunk).split(","):
            clean = u.strip().rstrip("/")
            if clean and clean.startswith(("http://", "https://")) and clean not in seen and clean not in local_urls:
                seen.add(clean)
                res.append(clean)
    return res


def _resolve_api_keys() -> List[str]:
    raw = os.getenv("BLAST_API_KEYS", "")
    if raw.strip():
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if keys:
            return keys
    s = load_settings()
    keys = []
    if s.get("blast_api_key_1"):
        keys.append(str(s["blast_api_key_1"]).strip())
    if s.get("blast_api_key_2"):
        keys.append(str(s["blast_api_key_2"]).strip())
    if keys:
        return keys
    return ["blast-secret-key-1", "blast-dev-key"]


@dataclass
class BlastConfig:
    # Role Settings: Every instance is both a Worker and a Dispatcher by default
    ROLE: str = os.getenv("BLAST_ROLE", "worker+dispatcher")
    IS_WORKER: bool = os.getenv("BLAST_IS_WORKER", "true").lower() in ("true", "1", "yes")
    IS_DISPATCHER: bool = os.getenv("BLAST_IS_DISPATCHER", "true").lower() in ("true", "1", "yes")

    # Cluster and Node Identity
    NODE_ID: str = os.getenv("BLAST_NODE_ID", f"node-{uuid.uuid4().hex[:8]}")

    # Public URL and port for multi-Render deployments
    HOST: str = os.getenv("BLAST_HOST", "0.0.0.0")
    PORT: int = field(default_factory=resolve_port)
    PUBLIC_URL: str = os.getenv(
        "BLAST_PUBLIC_URL",
        os.getenv("RENDER_EXTERNAL_URL", load_settings().get("blast_public_url", "https://sas-the-treasure-grape-xr-prototype.onrender.com"))
    ).rstrip("/")

    def __post_init__(self):
        if not self.PUBLIC_URL:
            self.PUBLIC_URL = f"http://{self.HOST}:{self.PORT}"
        # Ensure PEER_URLS and SERVER_LINKS are populated and synchronized
        if not self.PEER_URLS and not self.SERVER_LINKS:
            combined = _get_combined_peers()
            self.PEER_URLS = list(combined)
            self.SERVER_LINKS = list(combined)
        elif not self.PEER_URLS:
            self.PEER_URLS = list(self.SERVER_LINKS)
        elif not self.SERVER_LINKS:
            self.SERVER_LINKS = list(self.PEER_URLS)
        db_dir = os.path.dirname(self.DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        if self.CLUSTER_SECRETS:
            for secret in self.CLUSTER_SECRETS:
                if secret and secret not in self.API_KEYS:
                    self.API_KEYS.append(secret)
                if secret and secret.startswith(("http://", "https://")):
                    clean_s = secret.rstrip("/")
                    slash_s = clean_s + "/"
                    if clean_s not in self.API_KEYS:
                        self.API_KEYS.append(clean_s)
                    if slash_s not in self.API_KEYS:
                        self.API_KEYS.append(slash_s)
        elif self.CLUSTER_SECRET and self.CLUSTER_SECRET not in self.API_KEYS:
            self.API_KEYS.append(self.CLUSTER_SECRET)
            if self.CLUSTER_SECRET.startswith(("http://", "https://")):
                clean_s = self.CLUSTER_SECRET.rstrip("/")
                slash_s = clean_s + "/"
                if clean_s not in self.API_KEYS:
                    self.API_KEYS.append(clean_s)
                if slash_s not in self.API_KEYS:
                    self.API_KEYS.append(slash_s)

        if self.SUPABASE_ANON_KEY and not self.SUPABASE_ANON_KEY.startswith("sb_"):
            self.SUPABASE_ANON_KEY = f"sb_publishable_{self.SUPABASE_ANON_KEY}"

    PEER_URLS: List[str] = field(default_factory=_get_combined_peers)
    SERVER_LINKS: List[str] = field(default_factory=_get_combined_peers)
    CLUSTER_HEARTBEAT_INTERVAL: float = float(os.getenv("BLAST_CLUSTER_HEARTBEAT_INTERVAL", "15.0"))
    MESH_ROUTING_ENABLED: bool = os.getenv("BLAST_MESH_ROUTING_ENABLED", "true").lower() in ("true", "1", "yes")

    DEBUG: bool = os.getenv("BLAST_DEBUG", "false").lower() in ("true", "1", "yes")
    TESTING: bool = os.getenv("BLAST_TESTING", "false").lower() in ("true", "1", "yes")

    # 24/7 Keep-Alive Awake Engine (prevents Render 15-min and Supabase 7-day sleep)
    AWAKE_ENABLED: bool = os.getenv("BLAST_AWAKE_ENABLED", "true").lower() in ("true", "1", "yes")
    AWAKE_INTERVAL_SECONDS: float = float(os.getenv("BLAST_AWAKE_INTERVAL_SECONDS", "540.0"))
    AWAKE_PING_SELF: bool = os.getenv("BLAST_AWAKE_PING_SELF", "true").lower() in ("true", "1", "yes")
    AWAKE_PING_SUPABASE: bool = os.getenv("BLAST_AWAKE_PING_SUPABASE", "true").lower() in ("true", "1", "yes")
    AWAKE_PING_PEERS: bool = os.getenv("BLAST_AWAKE_PING_PEERS", "true").lower() in ("true", "1", "yes")

    # Supabase backend settings (Loaded from environment or settings.json; no hardcoding)
    SUPABASE_URL: str = field(
        default_factory=lambda: ("https://" + u if (u := (os.getenv("SUPABASE_URL") or load_settings().get("supabase_url") or "").strip().rstrip("/")) and not (u.startswith("http://") or u.startswith("https://")) else u)
    )
    SUPABASE_ANON_KEY: str = field(
        default_factory=lambda: str(os.getenv("SUPABASE_ANON_KEY") or load_settings().get("supabase_anon_key") or "")
    )
    SUPABASE_SERVICE_ROLE_KEY: str = field(
        default_factory=lambda: str(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or load_settings().get("supabase_service_role_key") or "")
    )
    SUPABASE_TIMEOUT_SECONDS: float = float(os.getenv("SUPABASE_TIMEOUT_SECONDS", "15.0"))

    # Security settings
    REQUIRE_API_KEY: bool = os.getenv("BLAST_REQUIRE_API_KEY", "true").lower() in ("true", "1", "yes")
    ADVANCED_SECURITY_ENABLED: bool = os.getenv("BLAST_ADVANCED_SECURITY_ENABLED", "true").lower() in ("true", "1", "yes")
    IDENTITY_PROTECTION_MODE: str = os.getenv("BLAST_IDENTITY_PROTECTION_MODE", "strict")
    STRICT_INPUT_VALIDATION: bool = os.getenv("BLAST_STRICT_INPUT_VALIDATION", "true").lower() in ("true", "1", "yes")
    CREDIT_CHECK_ENABLED: bool = os.getenv("BLAST_CREDIT_CHECK_ENABLED", "true").lower() in ("true", "1", "yes")
    DEFAULT_CLIENT_CREDITS: int = int(os.getenv("BLAST_DEFAULT_CLIENT_CREDITS", "1000"))
    CREDITS_PER_PROXY_REQUEST: int = int(os.getenv("BLAST_CREDITS_PER_PROXY_REQUEST", "1"))
    CREDITS_PER_QUEUE_REQUEST: int = int(os.getenv("BLAST_CREDITS_PER_QUEUE_REQUEST", "2"))
    CLUSTER_SECRET: str = field(
        default_factory=lambda: os.getenv("BLAST_CLUSTER_SECRET") or load_settings().get("blast_cluster_secret") or "https://sas-the-treasure-grape-xr-prototype.onrender.com/"
    )
    CLUSTER_SECRETS: List[str] = field(
        default_factory=lambda: [k.strip() for k in str(os.getenv("BLAST_CLUSTER_SECRETS") or (",".join(load_settings().get("blast_cluster_secrets", [])) if isinstance(load_settings().get("blast_cluster_secrets"), list) else load_settings().get("blast_cluster_secrets")) or os.getenv("BLAST_CLUSTER_SECRET") or load_settings().get("blast_cluster_secret") or "https://sas-the-treasure-grape-xr-prototype.onrender.com/").split(",") if k.strip()]
    )
    API_KEYS: List[str] = field(default_factory=_resolve_api_keys)
    MAX_PAYLOAD_BYTES: int = int(os.getenv("BLAST_MAX_PAYLOAD_BYTES", str(10 * 1024 * 1024)))

    # Rate limiting (Token Bucket)
    RATE_LIMIT_ENABLED: bool = os.getenv("BLAST_RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
    RATE_LIMIT_RPS: float = float(os.getenv("BLAST_RATE_LIMIT_RPS", "20.0"))
    RATE_LIMIT_BURST: int = int(os.getenv("BLAST_RATE_LIMIT_BURST", "50"))

    # Queue & Worker settings
    REDIS_URL: str = os.getenv("REDIS_URL", "").strip()
    DB_PATH: str = os.getenv(
        "BLAST_DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "blast_queue.db"),
    )
    MAX_WORKERS: int = int(os.getenv("BLAST_MAX_WORKERS", "4"))
    WORKER_POLL_INTERVAL: float = float(os.getenv("BLAST_WORKER_POLL_INTERVAL", "0.2"))
    MAX_RETRIES: int = int(os.getenv("BLAST_MAX_RETRIES", "3"))
    INITIAL_BACKOFF_SECONDS: float = float(os.getenv("BLAST_INITIAL_BACKOFF_SECONDS", "1.0"))
    BACKOFF_MULTIPLIER: float = float(os.getenv("BLAST_BACKOFF_MULTIPLIER", "2.0"))

    # Logging settings
    LOG_FILE: str = os.getenv(
        "BLAST_LOG_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "blast.log"),
    )


# Global default configuration instance
config = BlastConfig()
