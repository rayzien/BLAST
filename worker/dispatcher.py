"""Job execution dispatcher and retry scheduler with security verification.
Guaranteed zero emojis.
"""

from typing import Any, Optional
from config import BlastConfig
from job_queue.models import QueueJob
from supabase.client import SupabaseClient
from security.checker import SecurityChecker
from logger import logger


class JobDispatcher:
    """Dispatches a single queue job against Supabase and manages retry/DLQ states."""

    # HTTP status codes that represent transient errors suitable for automatic retry
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        cfg: BlastConfig,
        storage: Any,
        supabase_client: SupabaseClient,
        security_checker: Optional[SecurityChecker] = None,
    ):
        self.cfg = cfg
        self.storage = storage
        self.supabase_client = supabase_client
        self.security_checker = security_checker or SecurityChecker(cfg)

    def process_job(self, job: QueueJob):
        """Execute the job against Supabase, verify security, and sanitize responses."""
        # 1. Pre-execution Security Verification
        is_valid, err_code, err_details = self.security_checker.verify_inbound_request(
            method=job.method,
            path=job.path,
            headers=job.headers,
            query_params=job.params,
            body=job.body,
        )
        if not is_valid:
            reason = f"Security verification rejected job: {err_code} - {err_details.get('message', '')}"
            logger.security(f"[Job {job.id}] {reason}")
            self.storage.move_to_dlq(job.id, reason)
            return

        # 2. Upstream Execution
        try:
            status_code, resp_headers, resp_body = self.supabase_client.execute(
                method=job.method,
                path=job.path,
                headers=job.headers,
                params=job.params,
                body=job.body,
            )

            # 3. Outbound Response Verification & Sanitization
            clean_status, clean_headers, clean_body = self.security_checker.verify_and_sanitize_response(
                status_code=status_code,
                response_headers=resp_headers,
                response_body=resp_body,
            )

            # Permanent success or permanent client error (2xx, 3xx, 4xx except 429)
            if clean_status not in self.RETRYABLE_STATUS_CODES:
                self.storage.mark_completed(
                    job_id=job.id,
                    response_status=clean_status,
                    response_body=clean_body,
                )
                logger.worker(f"Job {job.id} completed with HTTP {clean_status}")
                return

            # Transient error, schedule retry
            err_msg = f"Transient Supabase HTTP {clean_status}: {clean_body[:200]}"
            self._handle_retry_or_dlq(job, err_msg)

        except Exception as exc:
            err_msg = f"Unexpected execution exception: {str(exc)}"
            logger.error("WORKER", f"Job {job.id} failed: {err_msg}", exc=exc)
            self._handle_retry_or_dlq(job, err_msg)

    def _handle_retry_or_dlq(self, job: QueueJob, error_message: str):
        """Schedule next retry attempt or exhaust into Dead Letter Queue."""
        if job.retry_count < job.max_retries:
            delay = self.cfg.INITIAL_BACKOFF_SECONDS * (self.cfg.BACKOFF_MULTIPLIER ** job.retry_count)
            self.storage.mark_retry(
                job_id=job.id,
                retry_delay_seconds=delay,
                error_message=error_message,
            )
            logger.worker(
                f"Job {job.id} retry {job.retry_count + 1}/{job.max_retries} scheduled in {delay:.1f}s. Reason: {error_message}"
            )
        else:
            reason = f"Max retries ({job.max_retries}) exceeded. Last error: {error_message}"
            self.storage.move_to_dlq(job.id, reason)
            logger.worker(f"Job {job.id} moved to DLQ: {reason}")
