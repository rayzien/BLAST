"""Peer discovery and interconnect management for multi-instance Blast Render deployments.
Guaranteed zero emojis.
"""

import time
import threading
import requests
from typing import Any, Dict, List, Optional
from config import BlastConfig
from logger import logger


class NodeInfo:
    def __init__(self, node_id: str, url: str, last_seen: float = 0.0, meta: Optional[Dict[str, Any]] = None):
        self.node_id = node_id
        self.url = url
        self.last_seen = last_seen or time.time()
        self.meta = meta or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "url": self.url,
            "last_seen": self.last_seen,
            "seconds_ago": round(time.time() - self.last_seen, 1),
            "meta": self.meta,
        }


class ClusterManager:
    """Coordinates interconnected Blast Render instances."""

    def __init__(self, cfg: BlastConfig):
        self.cfg = cfg
        self.node_id = cfg.NODE_ID
        self.peers: Dict[str, NodeInfo] = {}
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

        # Pre-seed configured peer URLs
        for url in cfg.PEER_URLS:
            if url:
                peer_id = f"peer-{abs(hash(url)) % 10000:04d}"
                self.peers[peer_id] = NodeInfo(node_id=peer_id, url=url, last_seen=0.0)

    def record_heartbeat(self, node_id: str, url: str, meta: Optional[Dict[str, Any]] = None):
        """Record heartbeat received from a peer instance."""
        with self.lock:
            self.peers[node_id] = NodeInfo(
                node_id=node_id,
                url=url,
                last_seen=time.time(),
                meta=meta or {},
            )
            logger.cluster(f"Heartbeat received from node '{node_id}' at {url}")

    def list_nodes(self) -> List[Dict[str, Any]]:
        """Return list of known active cluster nodes."""
        with self.lock:
            # Self entry
            nodes = [{
                "node_id": self.node_id,
                "url": f"http://{self.cfg.HOST}:{self.cfg.PORT}",
                "role": "local_node",
                "last_seen": time.time(),
                "seconds_ago": 0.0,
            }]
            for p in self.peers.values():
                d = p.to_dict()
                d["role"] = "peer_node"
                nodes.append(d)
            return nodes

    def _heartbeat_worker(self):
        """Background thread sending periodic heartbeats to known peers."""
        logger.cluster("Cluster interconnect heartbeat loop started.")
        while not self._stop_event.is_set():
            with self.lock:
                peer_list = list(self.peers.values())

            for peer in peer_list:
                if self._stop_event.is_set():
                    break
                try:
                    resp = requests.post(
                        f"{peer.url}/v1/cluster/heartbeat",
                        json={
                            "node_id": self.node_id,
                            "url": f"http://{self.cfg.HOST}:{self.cfg.PORT}",
                            "timestamp": time.time(),
                        },
                        timeout=3.0,
                    )
                    if resp.status_code == 200:
                        peer.last_seen = time.time()
                except Exception:
                    pass

            time.sleep(self.cfg.CLUSTER_HEARTBEAT_INTERVAL)

    def start(self):
        """Start cluster synchronization."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_worker,
            name="blast-cluster-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.cluster(f"Cluster manager initialized for node ID: {self.node_id}")

    def stop(self):
        """Stop cluster synchronization."""
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2.0)
