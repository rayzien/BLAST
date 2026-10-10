"""Configuration settings for Blast security, queue, and cluster subsystems.
Guaranteed zero emojis.
"""

import os
import json
import uuid
from dataclasses import dataclass, field
from typing import List


# Automatically load settings.json if present (persistent credentials for private repos & free tier)
_settings_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
if os.path.exists(_settings_json_path):
    try:
        def _apply_setting_val(env_k: str, v: Any):
            if v is not None and str(v).strip():
                cur = os.environ.get(env_k)
                if cur is None or cur.strip() == "":
                    os.environ[env_k] = str(v).strip()

        with open(_settings_json_path, "r", encoding="utf-8") as _jf:
            _s_data = json.load(_jf)
            _apply_setting_val("SUPABASE_URL", _s_data.get("supabase_url"))
            _apply_setting_val("SUPABASE_ANON_KEY", _s_data.get("supabase_anon_key"))
            if _s_data.get("supabase_service_role_key"):
                _apply_setting_val("SUPABASE_SERVICE_ROLE_KEY", _s_data.get("supabase_service_role_key"))
            _apply_setting_val("BLAST_CLUSTER_SECRET", _s_data.get("blast_cluster_secret"))

            _keys = []
            if _s_data.get("blast_api_key_1"):
                _keys.append(str(_s_data["blast_api_key_1"]).strip())
            if _s_data.get("blast_api_key_2"):
                _keys.append(str(_s_data["blast_api_key_2"]).strip())
            if _keys:
                _apply_setting_val("BLAST_API_KEYS", ",".join(_keys))
            elif _s_data.get("blast_api_keys"):
                _apply_setting_val("BLAST_API_KEYS", str(_s_data["blast_api_keys"]).strip())

            if "max_workers" in _s_data:
                _apply_setting_val("BLAST_MAX_WORKERS", str(_s_data["max_workers"]))
            if "rate_limit_rps" in _s_data:
                _apply_setting_val("BLAST_RATE_LIMIT_RPS", str(_s_data["rate_limit_rps"]))
            if "rate_limit_burst" in _s_data:
                _apply_setting_val("BLAST_RATE_LIMIT_BURST", str(_s_data["rate_limit_burst"]))
            if "blast_port" in _s_data or "port" in _s_data:
                _apply_setting_val("BLAST_PORT", str(_s_data.get("blast_port") or _s_data.get("port")))
            if "blast_host" in _s_data or "host" in _s_data:
                _apply_setting_val("BLAST_HOST", str(_s_data.get("blast_host") or _s_data.get("host")))
            if "mesh_routing_enabled" in _s_data:
                _apply_setting_val("BLAST_MESH_ROUTING_ENABLED", str(_s_data["mesh_routing_enabled"]).lower())
            if "awake_enabled" in _s_data:
                _apply_setting_val("BLAST_AWAKE_ENABLED", str(_s_data["awake_enabled"]).lower())
            if "awake_interval_seconds" in _s_data:
                _apply_setting_val("BLAST_AWAKE_INTERVAL_SECONDS", str(_s_data["awake_interval_seconds"]))
            if "awake_ping_self" in _s_data:
                _apply_setting_val("BLAST_AWAKE_PING_SELF", str(_s_data["awake_ping_self"]).lower())
            if "awake_ping_supabase" in _s_data:
                _apply_setting_val("BLAST_AWAKE_PING_SUPABASE", str(_s_data["awake_ping_supabase"]).lower())
            if "awake_ping_peers" in _s_data:
                _apply_setting_val("BLAST_AWAKE_PING_PEERS", str(_s_data["awake_ping_peers"]).lower())
    except Exception:
        pass


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
    raw = f"{os.getenv('BLAST_PEER_URLS', '')},{os.getenv('BLAST_SERVER_LINKS', '')},{os.getenv('BLAST_CLUSTER_NODES', '')}"
    seen = set()
    res = []
    for u in raw.split(","):
        clean = u.strip().rstrip("/")
        if clean and clean not in seen:
            seen.add(clean)
            res.append(clean)
    return res


@dataclass
class BlastConfig:
    # Role Settings: Every instance is both a Worker and a Dispatcher by default
    ROLE: str = os.getenv("BLAST_ROLE", "worker+dispatcher")
    IS_WORKER: bool = os.getenv("BLAST_IS_WORKER", "true").lower() in ("true", "1", "yes")
    IS_DISPATCHER: bool = os.getenv("BLAST_IS_DISPATCHER", "true").lower() in ("true", "1", "yes")

    # Cluster and Node Identity
    NODE_ID: str = os.getenv("BLAST_NODE_ID", f"node-{uuid.uuid4().hex[:8]}")
    
    # Public URL for multi-Render deployments (Render automatically supplies RENDER_EXTERNAL_URL)
    HOST: str = os.getenv("BLAST_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("BLAST_PORT", os.getenv("PORT", "8080")))
    PUBLIC_URL: str = os.getenv("BLAST_PUBLIC_URL", os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")

    def __post_init__(self):
        if not self.PUBLIC_URL:
            # Fallback to host:port if public URL not explicitly supplied
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
        if self.CLUSTER_SECRET and self.CLUSTER_SECRET not in self.API_KEYS:
            self.API_KEYS.append(self.CLUSTER_SECRET)

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

    # Supabase backend settings
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://ylzpjtzeetnvypvikiqa.supabase.co").rstrip("/")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "sb_publishable_mvS1x5C11_f5uIC9mpGukA_7vsP1jDQ")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_TIMEOUT_SECONDS: float = float(os.getenv("SUPABASE_TIMEOUT_SECONDS", "15.0"))

    # Security settings
    REQUIRE_API_KEY: bool = os.getenv("BLAST_REQUIRE_API_KEY", "true").lower() in ("true", "1", "yes")
    CLUSTER_SECRET: str = os.getenv("BLAST_CLUSTER_SECRET", "blast-cluster-mesh-secret-key")
    API_KEYS: List[str] = field(
        default_factory=lambda: [
            k.strip() for k in os.getenv("BLAST_API_KEYS", "blast-secret-key-1,blast-dev-key").split(",") if k.strip()
        ]
    )
    MAX_PAYLOAD_BYTES: int = int(os.getenv("BLAST_MAX_PAYLOAD_BYTES", str(10 * 1024 * 1024)))  # 10 MB default

    # Rate limiting (Token Bucket)
    RATE_LIMIT_ENABLED: bool = os.getenv("BLAST_RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
    RATE_LIMIT_RPS: float = float(os.getenv("BLAST_RATE_LIMIT_RPS", "20.0"))  # Refill rate per second
    RATE_LIMIT_BURST: int = int(os.getenv("BLAST_RATE_LIMIT_BURST", "50"))     # Max burst capacity

    # Queue & Worker settings
    REDIS_URL: str = os.getenv("REDIS_URL", "").strip()  # If set, uses shared distributed Redis queue
    DB_PATH: str = os.getenv(
        "BLAST_DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "blast_queue.db"),
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
