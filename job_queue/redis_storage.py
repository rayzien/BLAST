"""Distributed Redis storage engine for multi-node Blast Render deployments.
Guaranteed zero emojis.
"""

import json
import time
from typing import Any, Dict, List, Optional
import redis
from .models import JobStatus, QueueJob
from logger import logger


class RedisQueueStorage:
    """Distributed Redis-backed queue engine for interconnected multi-instance deployments."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.r = redis.from_url(redis_url, decode_responses=True)
        # Test connection
        self.r.ping()
        logger.queue(f"Connected to distributed Redis queue at {redis_url.split('@')[-1]}")

    def _job_key(self, job_id: str) -> str:
        return f"blast:job:{job_id}"

    def insert_job(self, job: QueueJob) -> bool:
        """Insert job into distributed Redis storage."""
        # Idempotency deduplication check
        if job.idempotency_key:
            idemp_key = f"blast:idemp:{job.client_id}:{job.idempotency_key}"
            # SET NX with 24-hour expiration
            was_set = self.r.set(idemp_key, job.id, nx=True, ex=86400)
            if not was_set:
                return False

        job_data = json.dumps(job.to_dict())
        pipeline = self.r.pipeline()
        # Save raw job payload
        pipeline.set(self._job_key(job.id), job_data)
        # Add to pending sorted set (score = scheduled_at)
        pipeline.zadd("blast:pending", {job.id: job.scheduled_at})
        pipeline.execute()
        return True

    def get_job(self, job_id: str) -> Optional[QueueJob]:
        """Fetch job by ID."""
        data = self.r.get(self._job_key(job_id))
        if not data:
            return None
        d = json.loads(data)
        d["status"] = JobStatus(d["status"])
        return QueueJob(**d)

    def get_by_idempotency(self, client_id: str, idempotency_key: str) -> Optional[QueueJob]:
        """Fetch job by idempotency key."""
        idemp_key = f"blast:idemp:{client_id}:{idempotency_key}"
        job_id = self.r.get(idemp_key)
        if not job_id:
            return None
        return self.get_job(job_id)

    def fetch_and_lock_pending(self, limit: int = 5) -> List[QueueJob]:
        """Atomically fetch and lock pending jobs ready for execution."""
        now = time.time()
        # Retrieve candidate IDs whose scheduled_at <= now
        candidate_ids = self.r.zrangebyscore("blast:pending", 0, now, start=0, num=limit)
        if not candidate_ids:
            return []

        locked_jobs = []
        for jid in candidate_ids:
            # Atomically remove from pending to lock
            removed = self.r.zrem("blast:pending", jid)
            if removed:
                job = self.get_job(jid)
                if job:
                    job.status = JobStatus.PROCESSING
                    job.updated_at = time.time()
                    self.r.set(self._job_key(jid), json.dumps(job.to_dict()))
                    self.r.sadd("blast:processing", jid)
                    locked_jobs.append(job)

        return locked_jobs

    def mark_completed(self, job_id: str, response_status: int, response_body: Optional[str] = None):
        """Mark job as completed."""
        job = self.get_job(job_id)
        if not job:
            return

        now = time.time()
        job.status = JobStatus.COMPLETED
        job.response_status = response_status
        job.response_body = response_body
        job.error_message = None
        job.updated_at = now

        pipeline = self.r.pipeline()
        pipeline.srem("blast:processing", job_id)
        pipeline.set(self._job_key(job_id), json.dumps(job.to_dict()), ex=86400 * 3)  # Expire after 3 days
        pipeline.incr("blast:stats:completed")
        pipeline.execute()

    def mark_retry(self, job_id: str, retry_delay_seconds: float, error_message: str):
        """Reschedule job for retry with backoff."""
        job = self.get_job(job_id)
        if not job:
            return

        now = time.time()
        next_run = now + retry_delay_seconds
        job.status = JobStatus.PENDING
        job.retry_count += 1
        job.scheduled_at = next_run
        job.error_message = error_message
        job.updated_at = now

        pipeline = self.r.pipeline()
        pipeline.srem("blast:processing", job_id)
        pipeline.set(self._job_key(job_id), json.dumps(job.to_dict()))
        pipeline.zadd("blast:pending", {job_id: next_run})
        pipeline.incr("blast:stats:retries")
        pipeline.execute()

    def move_to_dlq(self, job_id: str, reason: str):
        """Move unrecoverable job to DLQ."""
        job = self.get_job(job_id)
        if not job:
            return

        now = time.time()
        job.status = JobStatus.DEAD_LETTER
        job.error_message = reason
        job.updated_at = now

        dlq_entry = {
            "job_id": job_id,
            "reason": reason,
            "moved_at": now,
            "data": job.to_dict(),
        }

        pipeline = self.r.pipeline()
        pipeline.srem("blast:processing", job_id)
        pipeline.set(self._job_key(job_id), json.dumps(job.to_dict()))
        pipeline.lpush("blast:dlq", json.dumps(dlq_entry))
        pipeline.incr("blast:stats:dlq")
        pipeline.execute()

    def retry_dlq_job(self, job_id: str) -> bool:
        """Retry a job currently in the DLQ."""
        job = self.get_job(job_id)
        if not job or job.status != JobStatus.DEAD_LETTER:
            return False

        now = time.time()
        job.status = JobStatus.PENDING
        job.retry_count = 0
        job.scheduled_at = now
        job.error_message = None
        job.updated_at = now

        pipeline = self.r.pipeline()
        pipeline.set(self._job_key(job_id), json.dumps(job.to_dict()))
        pipeline.zadd("blast:pending", {job_id: now})
        pipeline.execute()
        return True

    def list_jobs(self, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[QueueJob]:
        """List jobs."""
        # For Redis, list jobs from pending and processing
        job_ids = self.r.zrange("blast:pending", offset, offset + limit - 1)
        results = []
        for jid in job_ids:
            j = self.get_job(jid)
            if j:
                results.append(j)
        return results

    def list_dlq(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List DLQ records."""
        entries = self.r.lrange("blast:dlq", offset, offset + limit - 1)
        return [json.loads(e) for e in entries]

    def get_metrics(self) -> Dict[str, Any]:
        """Aggregate queue metrics."""
        now = time.time()
        pending_count = self.r.zcount("blast:pending", 0, "+inf")
        processing_count = self.r.scard("blast:processing")
        dlq_count = self.r.llen("blast:dlq")
        completed_count = int(self.r.get("blast:stats:completed") or 0)

        return {
            "storage_type": "redis_distributed",
            "pending": pending_count,
            "processing": processing_count,
            "completed": completed_count,
            "dead_letter": dlq_count,
            "total_jobs": pending_count + processing_count + completed_count,
        }
