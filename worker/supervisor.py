"""Background worker supervisor managing thread pools and execution loops.
Guaranteed zero emojis.
"""

import threading
import time
from typing import Any, List, Optional
from config import BlastConfig
from supabase.client import SupabaseClient
from .dispatcher import JobDispatcher
from logger import logger


class WorkerSupervisor:
    """Oversees background worker threads that process queued requests."""

    def __init__(
        self,
        cfg: BlastConfig,
        storage: Any,
        supabase_client: Optional[SupabaseClient] = None,
    ):
        self.cfg = cfg
        self.storage = storage
        self.supabase_client = supabase_client or SupabaseClient(cfg)
        self.dispatcher = JobDispatcher(cfg, self.storage, self.supabase_client)

        self._threads: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._is_running = False

    def _worker_loop(self, worker_id: int):
        """Worker execution loop polling for pending jobs."""
        logger.worker(f"Worker thread #{worker_id} started.")
        while not self._stop_event.is_set():
            try:
                jobs = self.storage.fetch_and_lock_pending(node_id=self.cfg.NODE_ID, limit=5)
                if not jobs:
                    time.sleep(self.cfg.WORKER_POLL_INTERVAL)
                    continue

                for job in jobs:
                    if self._stop_event.is_set():
                        break
                    self.dispatcher.process_job(job)

            except Exception as exc:
                logger.error("WORKER", f"Worker #{worker_id} loop exception: {exc}", exc=exc)
                time.sleep(1.0)

        logger.worker(f"Worker thread #{worker_id} stopped.")

    def start(self):
        """Start worker threads."""
        if self._is_running:
            return

        self._stop_event.clear()
        self._threads = []
        num_workers = max(1, self.cfg.MAX_WORKERS)

        for i in range(num_workers):
            t = threading.Thread(
                target=self._worker_loop,
                args=(i + 1,),
                name=f"blast-worker-{i + 1}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

        self._is_running = True
        logger.worker(f"WorkerSupervisor started {num_workers} background workers.")

    def stop(self, timeout: float = 5.0):
        """Gracefully stop worker threads."""
        if not self._is_running:
            return

        logger.worker("Stopping WorkerSupervisor...")
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=timeout)

        self._is_running = False
        logger.worker("WorkerSupervisor stopped.")

    def is_alive(self) -> bool:
        """Check if workers are running."""
        return self._is_running and any(t.is_alive() for t in self._threads)
