"""Configuration settings for Blast security, queue, and cluster subsystems.
Guaranteed zero emojis.
"""

import os
import uuid
from dataclasses import dataclass, field
from typing import List


@dataclass
class BlastConfig:
    # Cluster and Node Identity
    NODE_ID: str = os.getenv("BLAST_NODE_ID", f"node-{uuid.uuid4().hex[:8]}")
    PEER_URLS: List[str] = field(
        default_factory=lambda: [
            u.strip().rstrip("/") for u in os.getenv("BLAST_PEER_URLS", "").split(",") if u.strip()
        ]
    )
    CLUSTER_HEARTBEAT_INTERVAL: float = float(os.getenv("BLAST_CLUSTER_HEARTBEAT_INTERVAL", "15.0"))

    # Server settings
    HOST: str = os.getenv("BLAST_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("BLAST_PORT", "8080"))
    DEBUG: bool = os.getenv("BLAST_DEBUG", "false").lower() in ("true", "1", "yes")

    # Supabase backend settings
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_TIMEOUT_SECONDS: float = float(os.getenv("SUPABASE_TIMEOUT_SECONDS", "15.0"))

    # Security settings
    REQUIRE_API_KEY: bool = os.getenv("BLAST_REQUIRE_API_KEY", "true").lower() in ("true", "1", "yes")
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
    DB_PATH: str = os.getenv("BLAST_DB_PATH", "blast_queue.db")
    MAX_WORKERS: int = int(os.getenv("BLAST_MAX_WORKERS", "4"))
    WORKER_POLL_INTERVAL: float = float(os.getenv("BLAST_WORKER_POLL_INTERVAL", "0.2"))
    MAX_RETRIES: int = int(os.getenv("BLAST_MAX_RETRIES", "3"))
    INITIAL_BACKOFF_SECONDS: float = float(os.getenv("BLAST_INITIAL_BACKOFF_SECONDS", "1.0"))
    BACKOFF_MULTIPLIER: float = float(os.getenv("BLAST_BACKOFF_MULTIPLIER", "2.0"))

    # Logging settings
    LOG_FILE: str = os.getenv("BLAST_LOG_FILE", "blast.log")


# Global default configuration instance
config = BlastConfig()
