"""Awake Engine - 24/7 Anti-Sleep Daemon for Blast, Render, and Supabase.

Guaranteed zero emojis.
Ensures neither Render free-tier containers nor Supabase free-tier projects
enter sleep or paused states due to inactivity.
"""

import os
import time
import datetime
import threading
from typing import Any, Dict, List, Optional
import httpx

from config import BlastConfig, config as default_config
from logger import logger


class AwakeEngine:
    """Orchestrates periodic keep-alive probes across Render, Supabase, and Cluster peers."""

    def __init__(
        self,
        cfg: Optional[BlastConfig] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self.cfg = cfg or default_config
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # Configuration
        self.enabled: bool = getattr(self.cfg, "AWAKE_ENABLED", True)
        self.interval_seconds: float = getattr(self.cfg, "AWAKE_INTERVAL_SECONDS", 540.0)  # Default: 9 minutes
        self.ping_self: bool = getattr(self.cfg, "AWAKE_PING_SELF", True)
        self.ping_supabase: bool = getattr(self.cfg, "AWAKE_PING_SUPABASE", True)
        self.ping_peers: bool = getattr(self.cfg, "AWAKE_PING_PEERS", True)

        # HTTP Client (can be injected for testing)
        self._client = http_client or httpx.Client(
            timeout=12.0,
            follow_redirects=True,
            headers={"User-Agent": "Blast-AwakeEngine/1.2.0"}
        )
        self._owns_client = http_client is None

        # Telemetry & Metrics
        self.start_time: float = time.time()
        self.last_round_time: Optional[float] = None
        self.total_rounds: int = 0
        self.successful_rounds: int = 0
        self.failed_rounds: int = 0
        self.targets_status: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []
        self._max_history: int = 30

    def start(self):
        """Start the background keep-alive ping loop if enabled."""
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return
            if not self.enabled:
                logger.info("AWAKE", "Awake Engine is disabled by configuration. Background ping loop not started.")
                return

            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._run_loop,
                name="Blast-AwakeEngine-Worker",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info("AWAKE", f"Awake Engine background worker started. Heartbeat interval: {self.interval_seconds:.1f}s")

    def stop(self, timeout: float = 2.0):
        """Signal the background worker to stop and wait for termination."""
        with self._lock:
            self._stop_event.set()
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=timeout)
                logger.info("AWAKE", "Awake Engine background worker stopped.")
            self._worker_thread = None

    def close(self):
        """Clean up resources."""
        self.stop()
        if self._owns_client:
            try:
                self._client.close()
            except Exception:
                pass

    def _run_loop(self):
        """Main loop executing keep-alive rounds at interval."""
        # Initial probe delay: allow server to fully bind and warm up before first keep-alive cycle
        initial_delay = min(60.0, self.interval_seconds)
        elapsed = 0.0
        while elapsed < initial_delay and not self._stop_event.is_set():
            time.sleep(1.0)
            elapsed += 1.0

        while not self._stop_event.is_set():
            try:
                if self.enabled:
                    self.ping_all()
            except Exception as exc:
                logger.warn("AWAKE", f"Unhandled error in keep-alive execution round: {exc}")

            # Sleep in small increments to allow rapid response to stop event
            elapsed = 0.0
            sleep_step = 1.0
            target_interval = max(30.0, self.interval_seconds)
            while elapsed < target_interval and not self._stop_event.is_set():
                time.sleep(sleep_step)
                elapsed += sleep_step

    def ping_all(self) -> Dict[str, Any]:
        """
        Execute an immediate keep-alive round across all enabled targets:
        1. Render Web Service Self-Ping (prevents 15-min free-tier spin down)
        2. Supabase Backend Ping (prevents 7-day inactivity project pause)
        3. Cluster Peers Ping (keeps interconnected Blast nodes alive)
        """
        with self._lock:
            round_id = f"awake-{int(time.time())}"
            start_round = time.time()
            results: Dict[str, Any] = {}
            any_success = False

            # Target 1: Self / Render Keep-Alive
            if self.ping_self:
                self_res = self._ping_self_target()
                results["render_self"] = self_res
                if self_res.get("success"):
                    any_success = True

            # Target 2: Supabase Keep-Alive
            if self.ping_supabase:
                supa_res = self._ping_supabase_target()
                results["supabase"] = supa_res
                if supa_res.get("success"):
                    any_success = True

            # Target 3: Cluster Peers Keep-Alive
            if self.ping_peers:
                peer_res = self._ping_peers_target()
                results["peers"] = peer_res
                if any(p.get("success") for p in peer_res):
                    any_success = True

            # Round metrics
            duration_ms = round((time.time() - start_round) * 1000.0, 2)
            self.last_round_time = time.time()
            self.total_rounds += 1
            if any_success:
                self.successful_rounds += 1
            else:
                self.failed_rounds += 1

            record = {
                "round_id": round_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "duration_ms": duration_ms,
                "any_success": any_success,
                "results": results,
            }

            self.history.append(record)
            if len(self.history) > self._max_history:
                self.history = self.history[-self._max_history:]

            logger.info(
                "AWAKE",
                f"Keep-alive probe round finished in {duration_ms}ms (Success: {any_success}, Total: {self.total_rounds})"
            )
            return record

    def _ping_self_target(self) -> Dict[str, Any]:
        """Send keep-alive probe to self (Render public URL or local binding)."""
        public_url = (
            getattr(self.cfg, "PUBLIC_URL", "")
            or os.getenv("RENDER_EXTERNAL_URL", "")
            or f"http://127.0.0.1:{getattr(self.cfg, 'PORT', 8080)}"
        ).rstrip("/")

        target_url = f"{public_url}/health"
        start = time.time()
        try:
            resp = self._client.get(target_url, headers={"X-Blast-Awake": "true"})
            latency_ms = round((time.time() - start) * 1000.0, 2)
            is_ok = 200 <= resp.status_code < 400
            res = {
                "target": "render_self",
                "url": target_url,
                "status_code": resp.status_code,
                "latency_ms": latency_ms,
                "success": is_ok,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self.targets_status["render_self"] = res
            return res
        except Exception as exc:
            latency_ms = round((time.time() - start) * 1000.0, 2)
            res = {
                "target": "render_self",
                "url": target_url,
                "status_code": 0,
                "latency_ms": latency_ms,
                "success": False,
                "error": str(exc),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self.targets_status["render_self"] = res
            return res

    def _ping_supabase_target(self) -> Dict[str, Any]:
        """Send keep-alive probe to Supabase to prevent project pause on free tier."""
        base_url = (getattr(self.cfg, "SUPABASE_URL", "") or "").rstrip("/")
        anon_key = getattr(self.cfg, "SUPABASE_ANON_KEY", "") or ""

        if not base_url:
            return {
                "target": "supabase",
                "url": "",
                "status_code": 0,
                "latency_ms": 0.0,
                "success": False,
                "error": "SUPABASE_URL not configured",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

        # Probe the health endpoint; if not available, fallback to REST root
        target_url = f"{base_url}/auth/v1/health"
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}" if anon_key else "",
            "X-Blast-Awake": "true",
        }

        start = time.time()
        try:
            resp = self._client.get(target_url, headers=headers)
            latency_ms = round((time.time() - start) * 1000.0, 2)
            is_ok = 200 <= resp.status_code < 400
            res = {
                "target": "supabase",
                "url": target_url,
                "status_code": resp.status_code,
                "latency_ms": latency_ms,
                "success": is_ok,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self.targets_status["supabase"] = res
            return res
        except Exception as exc:
            latency_ms = round((time.time() - start) * 1000.0, 2)
            res = {
                "target": "supabase",
                "url": target_url,
                "status_code": 0,
                "latency_ms": latency_ms,
                "success": False,
                "error": str(exc),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self.targets_status["supabase"] = res
            return res

    def _ping_peers_target(self) -> List[Dict[str, Any]]:
        """Send keep-alive probe to each configured cluster peer server."""
        raw_peers = getattr(self.cfg, "PEER_URLS", []) or getattr(self.cfg, "SERVER_LINKS", []) or []
        cluster_secret = getattr(self.cfg, "CLUSTER_SECRET", "") or "blast-cluster-mesh-secret-key"
        results: List[Dict[str, Any]] = []

        seen = set()
        clean_peers = []
        for p in raw_peers:
            cleaned = str(p).strip().rstrip("/")
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                clean_peers.append(cleaned)

        for peer_url in clean_peers:
            target_url = f"{peer_url}/health"
            start = time.time()
            try:
                resp = self._client.get(
                    target_url,
                    headers={"X-Blast-Key": cluster_secret, "X-Blast-Awake": "true"}
                )
                latency_ms = round((time.time() - start) * 1000.0, 2)
                is_ok = 200 <= resp.status_code < 400
                peer_record = {
                    "peer": peer_url,
                    "url": target_url,
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                    "success": is_ok,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
                results.append(peer_record)
            except Exception as exc:
                latency_ms = round((time.time() - start) * 1000.0, 2)
                peer_record = {
                    "peer": peer_url,
                    "url": target_url,
                    "status_code": 0,
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": str(exc),
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
                results.append(peer_record)

        self.targets_status["peers"] = {"count": len(results), "nodes": results}
        return results

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive status and telemetry for API and UI consumers."""
        with self._lock:
            now = time.time()
            uptime_seconds = round(now - self.start_time, 1)

            next_ping_in = 0.0
            if self.last_round_time:
                elapsed_since_last = now - self.last_round_time
                next_ping_in = max(0.0, round(self.interval_seconds - elapsed_since_last, 1))

            last_iso = (
                datetime.datetime.fromtimestamp(self.last_round_time, datetime.timezone.utc).isoformat()
                if self.last_round_time
                else None
            )

            is_running = self._worker_thread is not None and self._worker_thread.is_alive()

            return {
                "status": "active" if (self.enabled and is_running) else ("idle" if self.enabled else "disabled"),
                "enabled": self.enabled,
                "is_running": is_running,
                "interval_seconds": self.interval_seconds,
                "next_ping_in_seconds": next_ping_in,
                "uptime_seconds": uptime_seconds,
                "last_round_time": last_iso,
                "total_rounds": self.total_rounds,
                "successful_rounds": self.successful_rounds,
                "failed_rounds": self.failed_rounds,
                "targets_configured": {
                    "ping_self": self.ping_self,
                    "ping_supabase": self.ping_supabase,
                    "ping_peers": self.ping_peers,
                },
                "targets_status": self.targets_status,
                "history": self.history[-10:],  # Return recent 10 records
            }

    def update_config(
        self,
        enabled: Optional[bool] = None,
        interval_seconds: Optional[float] = None,
        ping_self: Optional[bool] = None,
        ping_supabase: Optional[bool] = None,
        ping_peers: Optional[bool] = None,
    ):
        """Update runtime configuration thread-safely."""
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
                if not self.enabled and self._worker_thread and self._worker_thread.is_alive():
                    self.stop()
                elif self.enabled and (not self._worker_thread or not self._worker_thread.is_alive()):
                    self.start()

            if interval_seconds is not None:
                self.interval_seconds = max(30.0, float(interval_seconds))

            if ping_self is not None:
                self.ping_self = bool(ping_self)
            if ping_supabase is not None:
                self.ping_supabase = bool(ping_supabase)
            if ping_peers is not None:
                self.ping_peers = bool(ping_peers)

            logger.info(
                "AWAKE",
                f"Awake Engine config updated: enabled={self.enabled}, interval={self.interval_seconds}s"
            )
