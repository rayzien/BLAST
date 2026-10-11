"""Peer discovery, gossip interconnect, and cluster management for multi-instance Blast Render deployments.
Guaranteed zero emojis.
"""

import time
import threading
import requests
from typing import Any, Callable, Dict, List, Optional
from config import BlastConfig
from logger import logger


class NodeInfo:
    def __init__(self, node_id: str, url: str, last_seen: float = 0.0, meta: Optional[Dict[str, Any]] = None):
        self.node_id = node_id
        self.url = url.rstrip("/")
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
    """Coordinates interconnected Blast Render instances as workers and dispatchers."""

    def __init__(self, cfg: BlastConfig):
        self.cfg = cfg
        self.node_id = cfg.NODE_ID
        self.peers: Dict[str, NodeInfo] = {}
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self.on_peer_discovered: Optional[Callable[[str, str], None]] = None

        # Pre-seed configured peer URLs
        local_urls = {
            cfg.PUBLIC_URL.rstrip("/"),
            f"http://{cfg.HOST}:{cfg.PORT}".rstrip("/"),
            f"http://127.0.0.1:{cfg.PORT}".rstrip("/"),
            f"http://localhost:{cfg.PORT}".rstrip("/"),
        }
        local_urls.discard("")
        for url in cfg.PEER_URLS:
            if url:
                clean_url = url.strip().rstrip("/")
                if clean_url not in local_urls:
                    peer_id = f"peer-{abs(hash(clean_url)) % 10000:04d}"
                    if peer_id not in self.peers and not any(p.url == clean_url for p in self.peers.values()):
                        self.peers[peer_id] = NodeInfo(node_id=peer_id, url=clean_url, last_seen=0.0)

    def record_heartbeat(self, node_id: str, url: str, meta: Optional[Dict[str, Any]] = None):
        """Record heartbeat received from a peer instance, auto-registering new nodes."""
        clean_url = url.strip().rstrip("/")
        local_urls = {
            self.cfg.PUBLIC_URL.rstrip("/"),
            f"http://{self.cfg.HOST}:{self.cfg.PORT}".rstrip("/"),
            f"http://127.0.0.1:{self.cfg.PORT}".rstrip("/"),
            f"http://localhost:{self.cfg.PORT}".rstrip("/"),
        }
        local_urls.discard("")
        if clean_url in local_urls or node_id == self.node_id:
            return

        is_new = False
        with self.lock:
            if node_id not in self.peers and not any(p.url == clean_url for p in self.peers.values()):
                is_new = True
            self.peers[node_id] = NodeInfo(
                node_id=node_id,
                url=clean_url,
                last_seen=time.time(),
                meta=meta or {},
            )

        if is_new:
            logger.cluster(f"Discovered new peer node '{node_id}' at {clean_url}")
            if self.on_peer_discovered:
                try:
                    self.on_peer_discovered(clean_url, node_id)
                except Exception as exc:
                    logger.warn("CLUSTER", f"Peer discovery callback error: {exc}")
        else:
            logger.cluster(f"Heartbeat received from node '{node_id}' at {clean_url}")

    def add_peer(self, url: str, node_id: Optional[str] = None) -> Optional[NodeInfo]:
        """Manually or dynamically add a peer node."""
        clean_url = url.strip().rstrip("/")
        local_urls = {
            self.cfg.PUBLIC_URL.rstrip("/"),
            f"http://{self.cfg.HOST}:{self.cfg.PORT}".rstrip("/"),
            f"http://127.0.0.1:{self.cfg.PORT}".rstrip("/"),
            f"http://localhost:{self.cfg.PORT}".rstrip("/"),
        }
        local_urls.discard("")
        if clean_url in local_urls:
            return None

        nid = node_id or f"peer-{abs(hash(clean_url)) % 10000:04d}"
        is_new = False
        with self.lock:
            # Check if peer with same URL already exists
            for p in self.peers.values():
                if p.url == clean_url:
                    p.last_seen = time.time()
                    return p
            info = NodeInfo(node_id=nid, url=clean_url, last_seen=time.time())
            self.peers[nid] = info
            is_new = True

        if is_new and self.on_peer_discovered:
            try:
                self.on_peer_discovered(clean_url, nid)
            except Exception:
                pass
        return info

    def list_nodes(self) -> List[Dict[str, Any]]:
        """Return list of known active cluster nodes with roles."""
        with self.lock:
            # Self entry
            nodes = [{
                "node_id": self.node_id,
                "url": self.cfg.PUBLIC_URL,
                "role": self.cfg.ROLE,
                "is_worker": self.cfg.IS_WORKER,
                "is_dispatcher": self.cfg.IS_DISPATCHER,
                "last_seen": time.time(),
                "seconds_ago": 0.0,
            }]
            for p in self.peers.values():
                d = p.to_dict()
                d["role"] = p.meta.get("role", "worker+dispatcher")
                d["is_worker"] = p.meta.get("is_worker", True)
                d["is_dispatcher"] = p.meta.get("is_dispatcher", True)
                nodes.append(d)
            return nodes

    def _heartbeat_worker(self):
        """Background thread sending periodic heartbeats and gossiping peer info."""
        logger.cluster("Cluster interconnect heartbeat loop started.")
        while not self._stop_event.is_set():
            with self.lock:
                peer_list = list(self.peers.values())

            headers = {}
            cluster_sec = getattr(self.cfg, "CLUSTER_SECRET", "")
            if cluster_sec:
                headers["X-Blast-Cluster-Secret"] = cluster_sec
                headers["X-Blast-Key"] = cluster_sec
            elif self.cfg.API_KEYS:
                headers["X-Blast-Key"] = self.cfg.API_KEYS[0]

            for peer in peer_list:
                if self._stop_event.is_set():
                    break
                try:
                    all_known = [p.url for p in peer_list if p.url != peer.url]
                    resp = requests.post(
                        f"{peer.url}/v1/cluster/heartbeat",
                        headers=headers,
                        json={
                            "node_id": self.node_id,
                            "url": self.cfg.PUBLIC_URL,
                            "role": self.cfg.ROLE,
                            "is_worker": self.cfg.IS_WORKER,
                            "is_dispatcher": self.cfg.IS_DISPATCHER,
                            "timestamp": time.time(),
                            "known_peers": all_known,
                        },
                        timeout=4.0,
                    )
                    if resp.status_code == 200:
                        peer.last_seen = time.time()
                        # Gossip: ingest any newly announced peers from the peer response
                        try:
                            data = resp.json()
                            for gossip_url in data.get("known_peers", []):
                                if gossip_url:
                                    self.add_peer(gossip_url)
                        except Exception:
                            pass
                except Exception:
                    pass

            # Sleep in slices so stop event can interrupt promptly
            for _ in range(int(self.cfg.CLUSTER_HEARTBEAT_INTERVAL * 5)):
                if self._stop_event.is_set():
                    break
                time.sleep(0.2)

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
        logger.cluster(f"Cluster manager initialized for node ID: {self.node_id} (Public URL: {self.cfg.PUBLIC_URL})")

    def stop(self):
        """Stop cluster synchronization."""
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2.0)
