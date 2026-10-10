"""Smart Mesh Router for dynamic fastest route selection and transparent forwarding.
Guaranteed zero emojis.
"""

import time
import threading
import requests
from typing import Any, Dict, List, Optional, Tuple
from config import BlastConfig
from logger import logger
from .models import MeshNode, RouteDecision
from .prober import MeshProber


class SmartMeshRouter:
    """Coordinates multiple Blast servers and directs traffic to the fastest route."""

    def __init__(self, cfg: BlastConfig):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.nodes: Dict[str, MeshNode] = {}
        self.prober = MeshProber(probe_interval_seconds=cfg.CLUSTER_HEARTBEAT_INTERVAL)

        # 1. Register Local Node
        local_url = f"http://{cfg.HOST}:{cfg.PORT}"
        self.local_node = MeshNode(
            url=local_url,
            name=f"{cfg.NODE_ID} (Local)",
            is_local=True,
            is_healthy=True,
            latency_ms=0.5,
            ewma_latency_ms=0.5,
            last_probe_time=time.time(),
        )
        self.nodes[local_url] = self.local_node

        # 2. Register Configured Peer Server Links
        for link in getattr(cfg, "SERVER_LINKS", []):
            if link and link.strip():
                clean_url = link.strip().rstrip("/")
                if clean_url != local_url and clean_url not in self.nodes:
                    node_name = f"Blast-Node-{abs(hash(clean_url)) % 10000:04d}"
                    self.nodes[clean_url] = MeshNode(url=clean_url, name=node_name)

    def start(self):
        """Start mesh prober and latency monitoring."""
        api_key = self.cfg.API_KEYS[0] if self.cfg.API_KEYS else ""
        self.prober.start(self.nodes, api_key=api_key)
        logger.info("MESH", f"SmartMeshRouter active with {len(self.nodes)} registered nodes.")

    def stop(self):
        """Stop mesh prober."""
        self.prober.stop()

    def add_node(self, url: str, name: str = "") -> MeshNode:
        """Dynamically add a new Blast server link to the mesh."""
        clean_url = url.strip().rstrip("/")
        with self.lock:
            if clean_url in self.nodes:
                return self.nodes[clean_url]
            node = MeshNode(url=clean_url, name=name or f"Node-{clean_url.split('//')[-1]}")
            self.nodes[clean_url] = node
            # Trigger immediate probe
            api_key = self.cfg.API_KEYS[0] if self.cfg.API_KEYS else ""
            self.prober.probe_node(node, api_key=api_key)
            logger.info("MESH", f"Added new Blast server link to mesh: {clean_url}")
            return node

    def remove_node(self, url: str) -> bool:
        """Remove a Blast server link."""
        clean_url = url.strip().rstrip("/")
        with self.lock:
            if clean_url in self.nodes and not self.nodes[clean_url].is_local:
                del self.nodes[clean_url]
                return True
        return False

    def update_local_queue_depth(self, depth: int):
        """Update active queue backlog for local node."""
        self.local_node.queue_depth = depth

    def select_fastest_route(self, hop_count: int = 0) -> RouteDecision:
        """
        Evaluate all known nodes and select the fastest route with the least pressure.
        If hop_count >= 1, we must execute locally to prevent forwarding loops.
        """
        if hop_count >= 1:
            return RouteDecision(
                target_node=self.local_node,
                is_local=True,
                score=self.local_node.compute_score(),
                reason="Direct execution (hop count limit reached)",
                evaluated_nodes_count=1,
            )

        with self.lock:
            candidates = list(self.nodes.values())

        if not candidates:
            return RouteDecision(
                target_node=self.local_node,
                is_local=True,
                score=0.0,
                reason="Default local execution (no candidates)",
                evaluated_nodes_count=1,
            )

        # Sort candidates by composite score (lowest is fastest & least loaded)
        ranked = sorted(candidates, key=lambda n: n.compute_score())
        winner = ranked[0]
        score = winner.compute_score()

        # If winner is offline or inaccessible, fallback to local node
        if not winner.is_healthy:
            return RouteDecision(
                target_node=self.local_node,
                is_local=True,
                score=self.local_node.compute_score(),
                reason="Fallback to local (no healthy remote nodes)",
                evaluated_nodes_count=len(ranked),
            )

        is_local = winner.is_local
        reason = f"Selected fastest route (Score: {score:.1f}, RTT: {winner.ewma_latency_ms:.1f}ms, Queue: {winner.queue_depth})"
        
        return RouteDecision(
            target_node=winner,
            is_local=is_local,
            score=score,
            reason=reason,
            evaluated_nodes_count=len(ranked),
        )

    def forward_to_peer(
        self,
        node: MeshNode,
        subpath: str,
        method: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
        body: Optional[str] = None,
        timeout: float = 8.0,
    ) -> Tuple[int, Dict[str, str], str]:
        """
        Transparently forward request to the selected peer Blast server.
        Returns:
            (status_code: int, response_headers: dict, response_body: str)
        """
        target_url = f"{node.url}{subpath}"
        req_headers = dict(headers)
        
        # Inject mesh forwarding telemetry headers to prevent loops
        req_headers["X-Blast-Hop-Count"] = "1"
        req_headers["X-Blast-Routed-From"] = self.local_node.url

        try:
            resp = requests.request(
                method=method.upper(),
                url=target_url,
                headers=req_headers,
                params=params or {},
                data=body.encode("utf-8") if body else None,
                timeout=timeout,
            )
            node.total_dispatched += 1
            resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "transfer-encoding")}
            resp_headers["X-Blast-Routed-Via"] = node.url
            resp_headers["X-Blast-Route-Score"] = str(round(node.compute_score(), 2))
            
            return resp.status_code, resp_headers, resp.text

        except Exception as exc:
            node.error_count += 1
            logger.warn("MESH", f"Failed forwarding to peer {node.url}: {exc}")
            raise

    def get_mesh_topology(self) -> Dict[str, Any]:
        """Return full telemetry of all nodes in the mesh."""
        with self.lock:
            node_list = [n.to_dict() for n in self.nodes.values()]

        # Sort by composite score (lowest first)
        node_list.sort(key=lambda x: x["composite_score"] if x["composite_score"] is not None else 999999.0)

        # Mark fastest
        for i, n in enumerate(node_list):
            n["rank"] = i + 1

        return {
            "local_node_id": self.cfg.NODE_ID,
            "total_nodes": len(node_list),
            "fastest_route": node_list[0]["url"] if node_list else None,
            "nodes": node_list,
        }
