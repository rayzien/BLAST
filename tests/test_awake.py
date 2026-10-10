"""Unit tests for Blast Awake Engine (24/7 Keep-Alive Daemon).

Guaranteed zero emojis.
Tests anti-sleep keep-alive logic across Render, Supabase, and Cluster peers,
as well as HTTP REST API endpoints.
"""

import os
import json
import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import httpx

from config import BlastConfig
from awake.engine import AwakeEngine
from server import create_app


class TestAwakeEngineUnit(unittest.TestCase):
    def setUp(self):
        self.cfg = BlastConfig(
            PUBLIC_URL="https://blast-render-app.onrender.com",
            SUPABASE_URL="https://myproject.supabase.co",
            SUPABASE_ANON_KEY="anon-key-12345",
            PEER_URLS=["https://blast-peer-1.onrender.com"],
            CLUSTER_SECRET="cluster-secret-common",
            AWAKE_ENABLED=True,
            AWAKE_INTERVAL_SECONDS=300.0,
        )

    def test_init_defaults(self):
        engine = AwakeEngine(self.cfg)
        self.assertTrue(engine.enabled)
        self.assertEqual(engine.interval_seconds, 300.0)
        self.assertTrue(engine.ping_self)
        self.assertTrue(engine.ping_supabase)
        self.assertTrue(engine.ping_peers)
        engine.close()

    def test_ping_all_mocked_success(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_client.get.return_value = mock_resp

        engine = AwakeEngine(self.cfg, http_client=mock_client)
        result = engine.ping_all()

        self.assertTrue(result["any_success"])
        self.assertIn("render_self", result["results"])
        self.assertIn("supabase", result["results"])
        self.assertIn("peers", result["results"])
        self.assertEqual(engine.total_rounds, 1)
        self.assertEqual(engine.successful_rounds, 1)

        # Verify calls
        calls = [c[0][0] for c in mock_client.get.call_args_list]
        self.assertIn("https://blast-render-app.onrender.com/health", calls)
        self.assertIn("https://myproject.supabase.co/auth/v1/health", calls)
        self.assertIn("https://blast-peer-1.onrender.com/health", calls)
        engine.close()

    def test_ping_all_handles_exceptions_gracefully(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = httpx.ConnectTimeout("Connection timed out")

        engine = AwakeEngine(self.cfg, http_client=mock_client)
        result = engine.ping_all()

        self.assertFalse(result["any_success"])
        self.assertEqual(engine.failed_rounds, 1)
        self.assertFalse(result["results"]["render_self"]["success"])
        self.assertFalse(result["results"]["supabase"]["success"])
        engine.close()

    def test_get_status_telemetry(self):
        engine = AwakeEngine(self.cfg)
        status = engine.get_status()
        self.assertIn("status", status)
        self.assertTrue(status["enabled"])
        self.assertEqual(status["interval_seconds"], 300.0)
        self.assertIn("uptime_seconds", status)
        self.assertIn("targets_configured", status)
        engine.close()

    def test_update_config_dynamically(self):
        engine = AwakeEngine(self.cfg)
        engine.update_config(enabled=False, interval_seconds=120.0)
        self.assertFalse(engine.enabled)
        self.assertEqual(engine.interval_seconds, 120.0)
        status = engine.get_status()
        self.assertEqual(status["status"], "disabled")
        engine.close()


class TestAwakeEngineEndpoints(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "awake_test.db")
        self.cfg = BlastConfig(
            API_KEYS=["test-key-1"],
            DB_PATH=self.db_path,
            AWAKE_ENABLED=False,  # Don't auto-start background loop during test
            AWAKE_INTERVAL_SECONDS=500.0,
        )
        self.mock_client = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        self.mock_client.get.return_value = mock_resp

        self.awake_engine = AwakeEngine(self.cfg, http_client=self.mock_client)
        self.app = create_app(cfg=self.cfg, awake_engine=self.awake_engine)
        self.client = self.app.test_client()

    def tearDown(self):
        self.awake_engine.close()
        if "BLAST_MESH_ROUTER" in self.app.config and self.app.config["BLAST_MESH_ROUTER"]:
            self.app.config["BLAST_MESH_ROUTER"].stop()
        if "BLAST_CLUSTER_MANAGER" in self.app.config and self.app.config["BLAST_CLUSTER_MANAGER"]:
            self.app.config["BLAST_CLUSTER_MANAGER"].stop()
        if "BLAST_STORAGE" in self.app.config and self.app.config["BLAST_STORAGE"]:
            self.app.config["BLAST_STORAGE"].close()
        self.tmp_dir.cleanup()

    def test_get_awake_endpoint(self):
        resp = self.client.get("/v1/awake")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("status", data)
        self.assertIn("interval_seconds", data)

    def test_trigger_awake_ping_endpoint(self):
        resp = self.client.post("/v1/awake/trigger")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("data", data)
        self.assertEqual(self.awake_engine.total_rounds, 1)

    def test_update_awake_config_endpoint(self):
        payload = {"enabled": True, "interval_seconds": 450}
        resp = self.client.post(
            "/v1/awake/config",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.awake_engine.enabled)
        self.assertEqual(self.awake_engine.interval_seconds, 450.0)


if __name__ == "__main__":
    unittest.main()
