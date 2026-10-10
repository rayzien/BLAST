"""Queue manager business logic handling enqueueing, deduplication, and storage abstraction.
Guaranteed zero emojis.
"""

from typing import Any, Dict, Optional, Tuple, Union
from config import BlastConfig
from .models import JobStatus, QueueJob
from .storage import SQLiteQueueStorage
from .redis_storage import RedisQueueStorage
from logger import logger


class QueueManager:
    """High-level request queue coordinator supporting local SQLite and distributed Redis."""

    def __init__(self, cfg: BlastConfig, storage: Optional[Union[SQLiteQueueStorage, RedisQueueStorage]] = None):
        self.cfg = cfg
        if storage:
            self.storage = storage
        elif cfg.REDIS_URL:
            try:
                self.storage = RedisQueueStorage(cfg.REDIS_URL)
                logger.queue("Initialized distributed Redis queue engine.")
            except Exception as e:
                logger.warn("QUEUE", f"Failed to connect to Redis ({e}), falling back to SQLite queue.")
                self.storage = SQLiteQueueStorage(cfg.DB_PATH)
        else:
            self.storage = SQLiteQueueStorage(cfg.DB_PATH)

    def enqueue(
        self,
        method: str,
        path: str,
        client_id: str = "anonymous",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        priority: int = 0,
    ) -> Tuple[QueueJob, bool]:
        """
        Enqueue an inbound request.
        Returns:
            (job: QueueJob, is_new: bool)
        """
        headers = headers or {}
        params = params or {}

        # Check idempotency deduplication
        if idempotency_key:
            existing = self.storage.get_by_idempotency(client_id, idempotency_key)
            if existing:
                return existing, False

        job = QueueJob(
            client_id=client_id,
            idempotency_key=idempotency_key,
            method=method.upper(),
            path=path,
            headers=headers,
            params=params,
            body=body,
            priority=priority,
            max_retries=self.cfg.MAX_RETRIES,
        )

        success = self.storage.insert_job(job)
        if not success and idempotency_key:
            existing = self.storage.get_by_idempotency(client_id, idempotency_key)
            if existing:
                return existing, False

        return job, True

    def get_job(self, job_id: str) -> Optional[QueueJob]:
        """Retrieve job by ID."""
        return self.storage.get_job(job_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get queue performance and count metrics."""
        return self.storage.get_metrics()

    def get_analytics(self, hours: int = 1) -> Dict[str, Any]:
        """Get queue time-series analytics."""
        if hasattr(self.storage, 'get_analytics_timeseries'):
            return self.storage.get_analytics_timeseries(hours=hours)
        return {"timeseries": []}

    def retry_dlq_job(self, job_id: str) -> bool:
        """Retry a job stored in DLQ."""
        return self.storage.retry_dlq_job(job_id)

    def close(self):
        """Close storage resources."""
        if hasattr(self.storage, "close"):
            self.storage.close()
