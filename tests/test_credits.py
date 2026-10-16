"""Unit tests for Client Credit and Quota Verification Subsystem.
Guaranteed zero emojis.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock
from config import BlastConfig
from security.credits import CreditManager
from server import create_app
from job_queue.storage import SQLiteQueueStorage


class TestCreditManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_credits.db")
        self.mgr = CreditManager(
            db_path=self.db_path,
            default_credits=100,
            enabled=True,
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_default_credit_initialization(self):
        balance = self.mgr.get_balance("client-alpha")
        self.assertEqual(balance, 100)

    def test_check_credits_pass_and_fail(self):
        has_credits, bal, msg = self.mgr.check_credits("client-alpha", cost=50)
        self.assertTrue(has_credits)
        self.assertEqual(bal, 100)

        # Insufficient credits
        has_credits, bal, msg = self.mgr.check_credits("client-alpha", cost=150)
        self.assertFalse(has_credits)
        self.assertIn("Insufficient credits", msg)

    def test_deduct_and_refill_credits(self):
        success, new_bal = self.mgr.deduct_credits("client-alpha", cost=30, reason="test_operation")
        self.assertTrue(success)
        self.assertEqual(new_bal, 70)
        self.assertEqual(self.mgr.get_balance("client-alpha"), 70)

        # Refill credits
        after_refill = self.mgr.refill_credits("client-alpha", 50)
        self.assertEqual(after_refill, 120)
        self.assertEqual(self.mgr.get_balance("client-alpha"), 120)

    def test_sqlite_persistence_across_instances(self):
        self.mgr.deduct_credits("client-persistent", cost=45)
        # Create new manager pointing to same SQLite database
        mgr2 = CreditManager(
            db_path=self.db_path,
            default_credits=100,
            enabled=True,
        )
        self.assertEqual(mgr2.get_balance("client-persistent"), 55)


class TestCreditServerEndpoints(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "queue.db")
        self.credits_db_path = os.path.join(self.tmp_dir.name, "credits.db")
        self.cfg = BlastConfig(
            API_KEYS=["test-credit-api-key"],
            REQUIRE_API_KEY=True,
            CREDIT_CHECK_ENABLED=True,
            DEFAULT_CLIENT_CREDITS=10,
            CREDITS_PER_PROXY_REQUEST=2,
            CREDITS_PER_QUEUE_REQUEST=3,
            DB_PATH=self.db_path,
            TESTING=True,
        )
        self.storage = SQLiteQueueStorage(self.db_path)
        self.mock_supabase = MagicMock()
        self.mock_supabase.base_url = "https://mock.supabase.co"
        self.mock_supabase.execute.return_value = (200, {"content-type": "application/json"}, '{"ok": true}')


        self.app = create_app(
            cfg=self.cfg,
            storage=self.storage,
            supabase_client=self.mock_supabase,
        )
        # Override credit db path
        self.credit_mgr = self.app.config["BLAST_CREDIT_MANAGER"]
        self.credit_mgr.db_path = self.credits_db_path
        self.credit_mgr._init_db()
        self.client = self.app.test_client()

    def tearDown(self):
        if "BLAST_AWAKE_ENGINE" in self.app.config and self.app.config["BLAST_AWAKE_ENGINE"]:
            self.app.config["BLAST_AWAKE_ENGINE"].stop()
        if "BLAST_CLUSTER_MANAGER" in self.app.config and self.app.config["BLAST_CLUSTER_MANAGER"]:
            self.app.config["BLAST_CLUSTER_MANAGER"].stop()
        self.storage.close()
        self.tmp_dir.cleanup()

    def test_get_credits_endpoint(self):
        resp = self.client.get(
            "/v1/credits",
            headers={"X-Blast-Key": "test-credit-api-key"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("balance", data)
        self.assertEqual(data["balance"], 10)

    def test_credit_deduction_on_proxy_request(self):
        resp = self.client.get(
            "/v1/proxy/rest/v1/users",
            headers={"X-Blast-Key": "test-credit-api-key"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Blast-Credits-Remaining"), "8")

    def test_insufficient_credits_blocks_request_with_http_402(self):
        client_id = "client-test-cre"
        # Reset balance to 1
        self.credit_mgr.reset_credits(client_id, amount=1)

        # Requires 2 credits for proxy
        resp = self.client.get(
            "/v1/proxy/rest/v1/users",
            headers={"X-Blast-Key": "test-credit-api-key"},
        )
        self.assertEqual(resp.status_code, 402)
        data = resp.get_json()
        self.assertEqual(data["code"], "INSUFFICIENT_CREDITS")
        self.assertEqual(data["remaining_credits"], 1)

    def test_refill_credits_endpoint(self):
        client_id = "client-test-cre"
        self.credit_mgr.reset_credits(client_id, amount=5)

        resp = self.client.post(
            "/v1/credits/refill",
            headers={"X-Blast-Key": "test-credit-api-key"},
            data=json.dumps({"client_id": client_id, "amount": 25}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["new_balance"], 30)


if __name__ == "__main__":
    unittest.main()
