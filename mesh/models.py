"""Data models and metrics for Blast Mesh and Fastest Route routing.
Guaranteed zero emojis.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MeshNode:
    """Represents a configured Blast server node in the interconnected mesh."""
    url: str
    name: str = ""
    is_local: bool = False
    is_healthy: bool = True
    latency_ms: float = 0.0
    ewma_latency_ms: float = 0.0  # Exponential Weighted Moving Average
    queue_depth: int = 0          # Active pending + processing jobs
    total_dispatched: int = 0
    error_count: int = 0
    last_probe_time: float = 0.0

    def compute_score(self) -> float:
        """
        Compute route suitability score.
        Lower score is better (fastest route with lowest queue pressure).
        Score = (latency_ms * 0.5) + (queue_depth * 10 * 0.5)
        """
        if not self.is_healthy:
            return float("inf")

        # Prioritize local node slightly to save network hop if latency is close
        local_bonus = -5.0 if self.is_local else 0.0
        
        # Penalize error rate
        error_penalty = self.error_count * 20.0

        latency_component = max(1.0, self.ewma_latency_ms or self.latency_ms) * 0.5
        load_component = (self.queue_depth * 10.0) * 0.5

        return latency_component + load_component + error_penalty + local_bonus

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name or self.url,
            "url": self.url,
            "is_local": self.is_local,
            "is_healthy": self.is_healthy,
            "latency_ms": round(self.latency_ms, 2),
            "ewma_latency_ms": round(self.ewma_latency_ms, 2),
            "queue_depth": self.queue_depth,
            "composite_score": round(self.compute_score(), 2) if self.is_healthy else None,
            "total_dispatched": self.total_dispatched,
            "error_count": self.error_count,
            "seconds_since_probe": round(time.time() - self.last_probe_time, 1) if self.last_probe_time else None,
        }


@dataclass
class RouteDecision:
    """Outcome of fastest route evaluation."""
    target_node: MeshNode
    is_local: bool
    score: float
    reason: str
    evaluated_nodes_count: int
