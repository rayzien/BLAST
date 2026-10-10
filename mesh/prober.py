"""Background prober calculating real-time latency and queue load for Blast Mesh nodes.
Guaranteed zero emojis.
"""

import time
import threading
import requests
from typing import Dict, Optional
from logger import logger
from .models import MeshNode


class MeshProber:
    """Probes registered Blast servers to track latency and queue backlog."""

    def __init__(self, probe_interval_seconds: float = 5.0, alpha: float = 0.3):
        self.probe_interval = probe_interval_seconds
        self.alpha = alpha  # EWMA smoothing factor
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def probe_node(self, node: MeshNode, api_key: str = "") -> bool:
        """Probe a single node for RTT latency and queue depth."""
        if node.is_local:
            node.latency_ms = 0.5
            node.ewma_latency_ms = 0.5
            node.is_healthy = True
            node.last_probe_time = time.time()
            return True

        headers = {}
        if api_key:
            headers["X-Blast-Key"] = api_key

        start = time.perf_counter()
        try:
            # 1. Health & RTT Ping
            health_url = f"{node.url}/health"
            resp = requests.get(health_url, headers=headers, timeout=3.0)
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            if resp.status_code == 200:
                node.latency_ms = elapsed_ms
                if node.ewma_latency_ms == 0.0:
                    node.ewma_latency_ms = elapsed_ms
                else:
                    node.ewma_latency_ms = (self.alpha * elapsed_ms) + ((1.0 - self.alpha) * node.ewma_latency_ms)

                node.is_healthy = True
                node.last_probe_time = time.time()

                # Read queue_depth directly from /health response (zero extra round-trips)
                found_depth = False
                try:
                    h_data = resp.json()
                    if "queue_depth" in h_data:
                        node.queue_depth = int(h_data["queue_depth"])
                        found_depth = True
                except Exception:
                    pass

                # Fallback to /v1/queue/stats if queue_depth was not present
                if not found_depth:
                    try:
                        stats_url = f"{node.url}/v1/queue/stats"
                        stats_resp = requests.get(stats_url, headers=headers, timeout=2.0)
                        if stats_resp.status_code == 200:
                            s_data = stats_resp.json()
                            node.queue_depth = int(s_data.get("pending", 0)) + int(s_data.get("processing", 0))
                    except Exception:
                        pass

                return True
            else:
                node.is_healthy = False
                node.error_count += 1
                return False

        except Exception as e:
            node.is_healthy = False
            node.error_count += 1
            node.latency_ms = 9999.0
            return False

    def start(self, nodes_dict: Dict[str, MeshNode], api_key: str = ""):
        """Start background polling thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()

        def _loop():
            logger.info("MESH", "Mesh prober background thread started.")
            while not self._stop_event.is_set():
                nodes_snapshot = list(nodes_dict.values())
                for node in nodes_snapshot:
                    if self._stop_event.is_set():
                        break
                    self.probe_node(node, api_key=api_key)
                
                # Sleep in increments to allow fast stop
                for _ in range(int(self.probe_interval * 10)):
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.1)

            logger.info("MESH", "Mesh prober background thread stopped.")

        self._thread = threading.Thread(target=_loop, name="blast-mesh-prober", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop background probing."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
