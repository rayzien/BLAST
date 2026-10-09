"""Comprehensive test suite for Blast security, queue, and proxy subsystems."""

import json
import os
import tempfile
import time
import unittest
from config import BlastConfig
from security.auth import Authenticator
from security.rate_limiter import TokenBucketRateLimiter
from security.firewall import Firewall
from job_queue.models import JobStatus, QueueJob
from job_queue.storage import SQLiteQueueStorage
from job_queue.manager import QueueManager
from worker.dispatcher import JobDispatcher
from server import create_app


class DummySupabaseClient:
    """Mock Supabase client to verify dispatcher and proxy without external calls."""

    def __init__(self):
        self.call_history = []
        self.return_status = 200
        self.return_body = '{"success": true}'

    def execute(self, method, path, headers=None, params=None, body=None):
        self.call_history.append({
            "method": method,
            "path": path,
            "headers": headers,
            "params": params,
            "body": body,
        })
        return self.return_status, {"content-type": "application/json"}, self.return_body

    def close(self):
        pass


class TestBlastSecurity(unittest.TestCase):
    def setUp(self):
        self.cfg = BlastConfig(
            API_KEYS=["test-blast-key-123"],
            REQUIRE_API_KEY=True,
            RATE_LIMIT_RPS=2.0,
            RATE_LIMIT_BURST=3,
            MAX_PAYLOAD_BYTES=1024,
        )
        self.auth = Authenticator(self.cfg)
        self.limiter = TokenBucketRateLimiter(self.cfg)
        self.firewall = Firewall(self.cfg)

    def test_auth_success_and_failure(self):
        # Missing key
        ok, client, err = self.auth.authenticate({})
        self.assertFalse(ok)
        self.assertIn("Missing", err)

        # Wrong key
        ok, client, err = self.auth.authenticate({"x-blast-key": "invalid-key"})
        self.assertFalse(ok)
        self.assertIn("Invalid", err)

        # Valid X-Blast-Key
        ok, client, err = self.auth.authenticate({"x-blast-key": "test-blast-key-123"})
        self.assertTrue(ok)
        self.assertEqual(client, "client-test-bla")

        # Valid Bearer token
        ok, client, err = self.auth.authenticate({"authorization": "Bearer test-blast-key-123"})
        self.assertTrue(ok)

    def test_rate_limiter(self):
        client = "test-client"
        # Should allow up to burst (3)
        self.assertTrue(self.limiter.check(client)[0])
        self.assertTrue(self.limiter.check(client)[0])
        self.assertTrue(self.limiter.check(client)[0])

        # 4th immediate request should be rejected
        allowed, retry_after, remaining = self.limiter.check(client)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0.0)

    def test_firewall_validation(self):
        # Allowed method
        ok, _ = self.firewall.validate_request("POST", "/rest/v1/orders", 100)
        self.assertTrue(ok)

        # Disallowed method
        ok, err = self.firewall.validate_request("TRACE", "/rest/v1/orders", 100)
        self.assertFalse(ok)

        # Path traversal
        ok, err = self.firewall.validate_request("GET", "/rest/v1/../../etc/passwd", 100)
        self.assertFalse(ok)
        self.assertIn("traversal", err)

        # Oversized payload
        ok, err = self.firewall.validate_request("POST", "/rest/v1/orders", 5000)
        self.assertFalse(ok)
        self.assertIn("exceeds", err)


class TestBlastQueueAndStorage(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.cfg = BlastConfig(DB_PATH=self.temp_db.name, MAX_RETRIES=2)
        self.storage = SQLiteQueueStorage(self.cfg.DB_PATH)
        self.queue_mgr = QueueManager(self.cfg, self.storage)

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_enqueue_and_idempotency(self):
        key = "idemp-key-999"
        job1, is_new1 = self.queue_mgr.enqueue(
            method="POST",
            path="/rest/v1/orders",
            client_id="user1",
            idempotency_key=key,
            body='{"amount": 100}',
        )
        self.assertTrue(is_new1)

        # Second enqueue with same key should return existing job
        job2, is_new2 = self.queue_mgr.enqueue(
            method="POST",
            path="/rest/v1/orders",
            client_id="user1",
            idempotency_key=key,
            body='{"amount": 100}',
        )
        self.assertFalse(is_new2)
        self.assertEqual(job1.id, job2.id)

    def test_fetch_and_lock_pending(self):
        self.queue_mgr.enqueue(method="POST", path="/task1", client_id="u1")
        self.queue_mgr.enqueue(method="POST", path="/task2", client_id="u1")

        jobs = self.storage.fetch_and_lock_pending(limit=10)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].status, JobStatus.PROCESSING)

        # Next fetch should return empty since they are locked
        next_jobs = self.storage.fetch_and_lock_pending(limit=10)
        self.assertEqual(len(next_jobs), 0)


class TestJobDispatcherAndDLQ(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.cfg = BlastConfig(
            DB_PATH=self.temp_db.name,
            MAX_RETRIES=2,
            INITIAL_BACKOFF_SECONDS=0.01,
            BACKOFF_MULTIPLIER=1.0,
        )
        self.storage = SQLiteQueueStorage(self.cfg.DB_PATH)
        self.dummy_client = DummySupabaseClient()
        self.dispatcher = JobDispatcher(self.cfg, self.storage, self.dummy_client)

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_successful_job_execution(self):
        self.dummy_client.return_status = 201
        self.dummy_client.return_body = '{"id": 42}'

        job = QueueJob(method="POST", path="/rest/v1/todos", body='{"text": "test"}')
        self.storage.insert_job(job)

        self.dispatcher.process_job(job)
        updated_job = self.storage.get_job(job.id)

        self.assertEqual(updated_job.status, JobStatus.COMPLETED)
        self.assertEqual(updated_job.response_status, 201)
        self.assertIn("42", updated_job.response_body)

    def test_retry_and_dlq_on_server_error(self):
        self.dummy_client.return_status = 503  # Transient service unavailable
        self.dummy_client.return_body = '{"error": "Supabase overloaded"}'

        job = QueueJob(method="POST", path="/rest/v1/todos", max_retries=1)
        self.storage.insert_job(job)

        # 1st attempt: Should schedule retry
        self.dispatcher.process_job(job)
        job_after_1 = self.storage.get_job(job.id)
        self.assertEqual(job_after_1.status, JobStatus.PENDING)
        self.assertEqual(job_after_1.retry_count, 1)

        # 2nd attempt: Max retries exceeded, should move to DLQ
        self.dispatcher.process_job(job_after_1)
        job_after_2 = self.storage.get_job(job.id)
        self.assertEqual(job_after_2.status, JobStatus.DEAD_LETTER)

        dlq_items = self.storage.list_dlq()
        self.assertEqual(len(dlq_items), 1)
        self.assertEqual(dlq_items[0]["job_id"], job.id)


class TestBlastAPIIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.cfg = BlastConfig(
            DB_PATH=self.temp_db.name,
            API_KEYS=["test-key-abc"],
            REQUIRE_API_KEY=True,
            RATE_LIMIT_BURST=10,
        )
        self.storage = SQLiteQueueStorage(self.cfg.DB_PATH)
        self.dummy_client = DummySupabaseClient()
        self.app = create_app(
            cfg=self.cfg,
            storage=self.storage,
            supabase_client=self.dummy_client,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_health_check_unauthenticated(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "healthy")

    def test_enqueue_via_api(self):
        resp = self.client.post(
            "/v1/queue/rest/v1/orders",
            headers={"X-Blast-Key": "test-key-abc", "X-Idempotency-Key": "order-101"},
            data=json.dumps({"total": 250}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 202)
        data = resp.get_json()
        self.assertEqual(data["status"], "queued")
        self.assertTrue(data["is_new"])
        job_id = data["job_id"]

        # Check job status endpoint
        job_resp = self.client.get(
            f"/v1/jobs/{job_id}",
            headers={"X-Blast-Key": "test-key-abc"},
        )
        self.assertEqual(job_resp.status_code, 200)
        self.assertEqual(job_resp.get_json()["status"], "pending")

    def test_proxy_sync_call(self):
        self.dummy_client.return_body = json.dumps([{"id": 1, "name": "Item"}])
        resp = self.client.get(
            "/v1/proxy/rest/v1/items?select=*",
            headers={"X-Blast-Key": "test-key-abc"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()), 1)


if __name__ == "__main__":
    unittest.main()
