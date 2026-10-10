"""Durable SQLite storage engine for the Blast request queue."""

import json
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional
from .models import JobStatus, QueueJob


class SQLiteQueueStorage:
    """Thread-safe SQLite storage engine with WAL mode and robust indexing."""

    def __init__(self, db_path: str = "blast_queue.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._all_connections = set()
        self._lock = threading.Lock()
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or initialize a thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,
                check_same_thread=False,
                isolation_level=None,  # Autocommit mode
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and optimal pragmas
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            self._local.conn = conn
            with self._lock:
                self._all_connections.add(conn)
        return self._local.conn

    def init_db(self):
        """Create tables and indexes if they do not exist."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                idempotency_key TEXT,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                headers TEXT NOT NULL,
                params TEXT NOT NULL,
                body TEXT,
                priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                scheduled_at REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                response_status INTEGER,
                response_body TEXT,
                error_message TEXT,
                handled_by TEXT
            );
        """)

        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN handled_by TEXT")
        except sqlite3.OperationalError:
            pass  # Column exists

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_fetch 
            ON jobs(status, scheduled_at, priority DESC);
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency 
            ON jobs(client_id, idempotency_key) 
            WHERE idempotency_key IS NOT NULL;
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS dlq (
                job_id TEXT PRIMARY KEY,
                original_job_data TEXT NOT NULL,
                reason TEXT NOT NULL,
                moved_at REAL NOT NULL
            );
        """)

    def insert_job(self, job: QueueJob) -> bool:
        """Insert a newly queued job. Returns False if duplicate idempotency key."""
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO jobs (
                    id, client_id, idempotency_key, method, path, headers,
                    params, body, priority, status, retry_count, max_retries,
                    scheduled_at, created_at, updated_at, response_status,
                    response_body, error_message, handled_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id,
                job.client_id,
                job.idempotency_key,
                job.method,
                job.path,
                json.dumps(job.headers),
                json.dumps(job.params),
                job.body,
                job.priority,
                job.status.value if isinstance(job.status, JobStatus) else job.status,
                job.retry_count,
                job.max_retries,
                job.scheduled_at,
                job.created_at,
                job.updated_at,
                job.response_status,
                job.response_body,
                job.error_message,
                job.handled_by,
            ))
            return True
        except sqlite3.IntegrityError:
            return False

    def get_job(self, job_id: str) -> Optional[QueueJob]:
        """Fetch a job by its unique ID."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return QueueJob.from_row(dict(row))

    def get_by_idempotency(self, client_id: str, idempotency_key: str) -> Optional[QueueJob]:
        """Fetch existing job with the given idempotency key for this client."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM jobs WHERE client_id = ? AND idempotency_key = ?",
            (client_id, idempotency_key),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return QueueJob.from_row(dict(row))

    def fetch_and_lock_pending(self, node_id: str, limit: int = 10) -> List[QueueJob]:
        """
        Fetch jobs ready to execute (status=pending and scheduled_at <= now).
        Marks them as 'processing' atomically to avoid double-processing.
        """
        conn = self._get_connection()
        now = time.time()
        # Find candidates
        cursor = conn.execute("""
            SELECT id FROM jobs 
            WHERE status = ? AND scheduled_at <= ? 
            ORDER BY priority DESC, scheduled_at ASC 
            LIMIT ?
        """, (JobStatus.PENDING.value, now, limit))
        candidate_ids = [row["id"] for row in cursor.fetchall()]

        if not candidate_ids:
            return []

        # Lock them
        placeholders = ",".join("?" for _ in candidate_ids)
        conn.execute(f"""
            UPDATE jobs 
            SET status = ?, updated_at = ?, handled_by = ?
            WHERE id IN ({placeholders}) AND status = ?
        """, [JobStatus.PROCESSING.value, now, node_id, *candidate_ids, JobStatus.PENDING.value])

        # Return locked jobs
        cursor = conn.execute(f"""
            SELECT * FROM jobs WHERE id IN ({placeholders})
        """, candidate_ids)

        return [QueueJob.from_row(dict(row)) for row in cursor.fetchall()]

    def mark_completed(
        self,
        job_id: str,
        response_status: int,
        response_body: Optional[str] = None,
    ):
        """Mark a job as successfully completed."""
        conn = self._get_connection()
        now = time.time()
        conn.execute("""
            UPDATE jobs 
            SET status = ?, response_status = ?, response_body = ?, error_message = NULL, updated_at = ?
            WHERE id = ?
        """, (JobStatus.COMPLETED.value, response_status, response_body, now, job_id))

    def mark_retry(
        self,
        job_id: str,
        retry_delay_seconds: float,
        error_message: str,
    ):
        """Reschedule a job for retry after backoff."""
        conn = self._get_connection()
        now = time.time()
        next_run = now + retry_delay_seconds
        conn.execute("""
            UPDATE jobs 
            SET status = ?, retry_count = retry_count + 1, scheduled_at = ?, error_message = ?, updated_at = ?
            WHERE id = ?
        """, (JobStatus.PENDING.value, next_run, error_message, now, job_id))

    def move_to_dlq(self, job_id: str, reason: str):
        """Move an unrecoverable or exhausted job to the Dead Letter Queue."""
        conn = self._get_connection()
        job = self.get_job(job_id)
        if not job:
            return

        now = time.time()
        job_dict = job.to_dict()
        job_dict["status"] = JobStatus.DEAD_LETTER.value
        job_dict["error_message"] = reason

        conn.execute("""
            UPDATE jobs 
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ?
        """, (JobStatus.DEAD_LETTER.value, reason, now, job_id))

        conn.execute("""
            INSERT OR REPLACE INTO dlq (job_id, original_job_data, reason, moved_at)
            VALUES (?, ?, ?, ?)
        """, (job_id, json.dumps(job_dict), reason, now))

    def retry_dlq_job(self, job_id: str) -> bool:
        """Move a job from DLQ back to PENDING status with reset retries."""
        conn = self._get_connection()
        now = time.time()
        cursor = conn.execute("SELECT job_id FROM dlq WHERE job_id = ?", (job_id,))
        if not cursor.fetchone():
            return False

        conn.execute("""
            UPDATE jobs 
            SET status = ?, retry_count = 0, scheduled_at = ?, error_message = NULL, updated_at = ?
            WHERE id = ?
        """, (JobStatus.PENDING.value, now, now, job_id))

        conn.execute("DELETE FROM dlq WHERE job_id = ?", (job_id,))
        return True

    def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[QueueJob]:
        """List jobs with optional status filter and pagination."""
        conn = self._get_connection()
        if status:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [QueueJob.from_row(dict(r)) for r in cursor.fetchall()]

    def list_dlq(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List items in the dead letter queue."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM dlq ORDER BY moved_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        results = []
        for row in cursor.fetchall():
            results.append({
                "job_id": row["job_id"],
                "reason": row["reason"],
                "moved_at": row["moved_at"],
                "data": json.loads(row["original_job_data"]),
            })
        return results

    def get_metrics(self) -> Dict[str, Any]:
        """Get aggregate counts across all queue states."""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count 
            FROM jobs 
            GROUP BY status
        """)
        counts = {row["status"]: row["count"] for row in cursor.fetchall()}
        dlq_cursor = conn.execute("SELECT COUNT(*) as count FROM dlq")
        dlq_count = dlq_cursor.fetchone()["count"]

        return {
            "pending": counts.get(JobStatus.PENDING.value, 0),
            "processing": counts.get(JobStatus.PROCESSING.value, 0),
            "completed": counts.get(JobStatus.COMPLETED.value, 0),
            "failed": counts.get(JobStatus.FAILED.value, 0),
            "dead_letter": dlq_count,
            "total_jobs": sum(counts.values()),
        }

    def get_analytics_timeseries(self, hours: int = 1) -> Dict[str, Any]:
        """Get time-series analytics (throughput, errors, latency)."""
        conn = self._get_connection()
        now = time.time()
        start_time = now - (hours * 3600)
        
        # We will group by minutes. SQLite doesn't have a direct DATETIME from unix epoch without formatting,
        # but we can do integer division by 60 to group by minute.
        cursor = conn.execute("""
            SELECT 
                CAST(updated_at / 60 AS INTEGER) * 60 as time_bucket,
                status,
                COUNT(*) as count,
                AVG(updated_at - created_at) as avg_latency
            FROM jobs
            WHERE updated_at >= ?
            GROUP BY time_bucket, status
            ORDER BY time_bucket ASC
        """, (start_time,))
        
        rows = cursor.fetchall()
        
        buckets = {}
        for row in rows:
            bucket = row["time_bucket"]
            if bucket not in buckets:
                buckets[bucket] = {"time": bucket, "success": 0, "failed": 0, "latency_sum": 0.0, "latency_count": 0}
            
            st = row["status"]
            if st == JobStatus.COMPLETED.value:
                buckets[bucket]["success"] += row["count"]
                buckets[bucket]["latency_sum"] += (row["avg_latency"] or 0) * row["count"]
                buckets[bucket]["latency_count"] += row["count"]
            elif st in (JobStatus.FAILED.value, JobStatus.DEAD_LETTER.value):
                buckets[bucket]["failed"] += row["count"]

        # Format output
        timeseries = []
        for b in sorted(buckets.keys()):
            data = buckets[b]
            avg_lat = data["latency_sum"] / data["latency_count"] if data["latency_count"] > 0 else 0
            timeseries.append({
                "timestamp": data["time"],
                "success_count": data["success"],
                "error_count": data["failed"],
                "avg_latency_sec": avg_lat
            })
            
        return {"timeseries": timeseries}

    def close(self):
        """Close all opened SQLite connections across all threads."""
        with self._lock:
            for conn in list(self._all_connections):
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_connections.clear()
        if hasattr(self._local, "conn"):
            self._local.conn = None
