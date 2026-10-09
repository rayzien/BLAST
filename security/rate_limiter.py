"""Thread-safe Token Bucket Rate Limiter."""

import time
import threading
from typing import Dict, Tuple
from config import BlastConfig


class TokenBucket:
    def __init__(self, rate: float, capacity: float):
        self.rate = rate          # Tokens added per second
        self.capacity = capacity  # Maximum bucket capacity
        self.tokens = capacity    # Current token count
        self.last_update = time.time()

    def consume(self, amount: float = 1.0) -> Tuple[bool, float, int]:
        """
        Attempt to consume tokens.
        Returns:
            (allowed: bool, retry_after_seconds: float, remaining_tokens: int)
        """
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now

        # Refill tokens based on elapsed time
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0.0, int(self.tokens)
        else:
            needed = amount - self.tokens
            retry_after = needed / self.rate if self.rate > 0 else 1.0
            return False, retry_after, 0


class TokenBucketRateLimiter:
    """Per-client thread-safe rate limiter with automatic stale key cleanup."""

    def __init__(self, cfg: BlastConfig):
        self.enabled = cfg.RATE_LIMIT_ENABLED
        self.rate = cfg.RATE_LIMIT_RPS
        self.burst = float(cfg.RATE_LIMIT_BURST)
        self.buckets: Dict[str, TokenBucket] = {}
        self.lock = threading.Lock()
        self.last_cleanup = time.time()

    def check(self, identifier: str) -> Tuple[bool, float, int]:
        """
        Check if identifier has quota.
        Returns:
            (allowed: bool, retry_after: float, remaining: int)
        """
        if not self.enabled:
            return True, 0.0, int(self.burst)

        with self.lock:
            now = time.time()
            # Periodic cleanup of buckets inactive for over 1 hour
            if now - self.last_cleanup > 300:
                self._cleanup_stale(now)
                self.last_cleanup = now

            if identifier not in self.buckets:
                self.buckets[identifier] = TokenBucket(rate=self.rate, capacity=self.burst)

            bucket = self.buckets[identifier]
            return bucket.consume(1.0)

    def _cleanup_stale(self, now: float, max_idle: float = 3600.0):
        stale_keys = [
            k for k, b in self.buckets.items()
            if (now - b.last_update) > max_idle
        ]
        for k in stale_keys:
            del self.buckets[k]
