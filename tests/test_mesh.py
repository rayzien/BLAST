"""Comprehensive test suite for Blast Mesh and Fastest Route routing subsystem.
Guaranteed zero emojis.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import requests

from config import BlastConfig
from mesh.models import MeshNode, RouteDecision
from mesh.router import SmartMeshRouter
from job_queue.storage import SQLiteQueueStorage
from job_queue.manager import QueueManager
from security.checker import SecurityChecker
from server import create_app


class TestMeshModels(unittest.TestCase):
    """Test unit behavior of MeshNode and RouteDecision."""

    def test_node_score_calculation(self):
        # 1. Unhealthy node has infinite score
        node_dead = MeshNode(url="https://blast-dead.render.com", is_healthy=False)
        self.assertEqual(node_dead.compute_score(), float("inf"))

        # 2. Local node bonus: local vs remote with same metrics
        local_node = MeshNode(
            url="http://127.0.0.1:8080",
            is_local=True,
            is_healthy=True,
            latency_ms=10.0,
            ewma_latency_ms=10.0,
            queue_depth=0,
        )
        remote_node = MeshNode(
            url="https://blast-peer.render.com",
            is_local=False,
            is_healthy=True,
            latency_ms=10.0,
            ewma_latency_ms=10.0,
            queue_depth=0,
        )
        # Local score: 10 * 0.5 + 0 - 5.0 = 0.0
        # Remote score: 10 * 0.5 + 0 + 0 = 5.0
        self.assertLess(local_node.compute_score(), remote_node.compute_score())

        # 3. High queue depth penalizes score
        busy_node = MeshNode(
            url="https://blast-busy.render.com",
            is_healthy=True,
            latency_ms=10.0,
            ewma_latency_ms=10.0,
            queue_depth=10,
        )
        # Score = 5.0 (latency) + (10 * 10 * 0.5 = 50.0) = 55.0
        self.assertEqual(busy_node.compute_score(), 55.0)

        # 4. Error count penalizes score
        errored_node = MeshNode(
            url="https://blast-err.render.com",
            is_healthy=True,
            latency_ms=10.0,
            ewma_latency_ms=10.0,
            error_count=2,
        )
        # Score = 5.0 (latency) + (2 * 20.0 = 40.0) = 45.0
        self.assertEqual(errored_node.compute_score(), 45.0)

    def test_node_to_dict(self):
        node = MeshNode(
            url="https://blast-1.render.com",
            name="Blast-Alpha",
            is_local=False,
            is_healthy=True,
            latency_ms=12.34,
            ewma_latency_ms=14.56,
            queue_depth=2,
        )
        data = node.to_dict()
        self.assertEqual(data["name"], "Blast-Alpha")
        self.assertEqual(data["url"], "https://blast-1.render.com")
        self.assertFalse(data["is_local"])
        self.assertTrue(data["is_healthy"])
        self.assertEqual(data["queue_depth"], 2)
        self.assertIsNotNone(data["composite_score"])


class TestSmartMeshRouter(unittest.TestCase):
    """Test routing decisions, dynamic mesh nodes, and loop prevention."""

    def setUp(self):
        self.cfg = BlastConfig(
            HOST="127.0.0.1",
            PORT=8080,
            NODE_ID="test-local-node",
            SERVER_LINKS=[
                "https://blast-east.render.com",
                "https://blast-west.render.com",
            ],
            MESH_ROUTING_ENABLED=True,
            API_KEYS=["test-key-mesh"],
        )
        self.router = SmartMeshRouter(self.cfg)

    def tearDown(self):
        self.router.stop()

    def test_init_registers_nodes(self):
        local_url = "http://127.0.0.1:8080"
        self.assertIn(local_url, self.router.nodes)
        self.assertTrue(self.router.nodes[local_url].is_local)
        self.assertIn("https://blast-east.render.com", self.router.nodes)
        self.assertIn("https://blast-west.render.com", self.router.nodes)
        self.assertEqual(len(self.router.nodes), 3)

    def test_add_and_remove_node(self):
        # Add dynamic node
        new_url = "https://blast-tokyo.render.com"
        added = self.router.add_node(new_url, name="Blast Tokyo")
        self.assertEqual(added.url, new_url)
        self.assertIn(new_url, self.router.nodes)

        # Remove dynamic node
        removed = self.router.remove_node(new_url)
        self.assertTrue(removed)
        self.assertNotIn(new_url, self.router.nodes)

        # Attempt to remove local node should fail
        local_url = "http://127.0.0.1:8080"
        self.assertFalse(self.router.remove_node(local_url))
        self.assertIn(local_url, self.router.nodes)

    def test_select_fastest_route_winner(self):
        # Configure latencies
        self.router.nodes["http://127.0.0.1:8080"].ewma_latency_ms = 40.0
        self.router.nodes["http://127.0.0.1:8080"].queue_depth = 5

        self.router.nodes["https://blast-east.render.com"].ewma_latency_ms = 12.0
        self.router.nodes["https://blast-east.render.com"].queue_depth = 0
        self.router.nodes["https://blast-east.render.com"].is_healthy = True

        self.router.nodes["https://blast-west.render.com"].ewma_latency_ms = 80.0
        self.router.nodes["https://blast-west.render.com"].queue_depth = 12
        self.router.nodes["https://blast-west.render.com"].is_healthy = True

        decision = self.router.select_fastest_route(hop_count=0)
        self.assertEqual(decision.target_node.url, "https://blast-east.render.com")
        self.assertFalse(decision.is_local)

    def test_loop_prevention_on_hop_count(self):
        # Even if remote node has much better score, hop_count >= 1 must stay local
        self.router.nodes["https://blast-east.render.com"].ewma_latency_ms = 1.0
        self.router.nodes["https://blast-east.render.com"].queue_depth = 0
        self.router.nodes["https://blast-east.render.com"].is_healthy = True

        decision = self.router.select_fastest_route(hop_count=1)
        self.assertTrue(decision.is_local)
        self.assertEqual(decision.target_node.url, "http://127.0.0.1:8080")
        self.assertIn("hop count limit", decision.reason)

    def test_unhealthy_remote_fallback(self):
        # Mark all remote nodes unhealthy
        for url, node in self.router.nodes.items():
            if not node.is_local:
                node.is_healthy = False

        decision = self.router.select_fastest_route(hop_count=0)
        self.assertTrue(decision.is_local)
        self.assertEqual(decision.target_node.url, "http://127.0.0.1:8080")

    def test_get_mesh_topology(self):
        topology = self.router.get_mesh_topology()
        self.assertEqual(topology["local_node_id"], "test-local-node")
        self.assertEqual(topology["total_nodes"], 3)
        self.assertTrue(isinstance(topology["nodes"], list))
        self.assertEqual(topology["nodes"][0]["rank"], 1)


class TestMeshServerEndpoints(unittest.TestCase):
    """Test mesh HTTP endpoints and transparent forwarding fallback in Flask server."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_mesh_queue.db")
        self.cfg = BlastConfig(
            API_KEYS=["mesh-test-key-abc"],
            REQUIRE_API_KEY=False,
            DB_PATH=self.db_path,
            SERVER_LINKS=["https://peer-blast.render.com"],
            MESH_ROUTING_ENABLED=True,
        )
        self.storage = SQLiteQueueStorage(self.db_path)
        self.queue_mgr = QueueManager(self.cfg, storage=self.storage)
        self.mesh_router = SmartMeshRouter(self.cfg)
        self.app = create_app(
            cfg=self.cfg,
            storage=self.storage,
            mesh_router=self.mesh_router,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.mesh_router.stop()
        self.storage.close()
        self.tmp_dir.cleanup()

    def test_get_mesh_routes(self):
        resp = self.client.get("/v1/mesh/routes")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("nodes", data)
        self.assertIn("fastest_route", data)
        self.assertEqual(data["total_nodes"], 2)

    def test_post_and_delete_mesh_node(self):
        # Add node
        resp = self.client.post(
            "/v1/mesh/nodes",
            data=json.dumps({"url": "https://blast-eu.render.com", "name": "EU Node"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["status"], "registered")

        # Delete node
        resp_del = self.client.delete(
            "/v1/mesh/nodes",
            data=json.dumps({"url": "https://blast-eu.render.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp_del.status_code, 200)
        self.assertEqual(resp_del.get_json()["status"], "removed")

    def test_get_mesh_status(self):
        resp = self.client.get("/v1/mesh/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["mesh_active"])
        self.assertIn("fastest_route_url", data)

    @patch("mesh.router.requests.request")
    def test_forward_to_fastest_peer_success(self, mock_requests):
        # Configure remote peer as fastest
        peer_node = self.mesh_router.nodes["https://peer-blast.render.com"]
        peer_node.ewma_latency_ms = 5.0
        peer_node.queue_depth = 0
        peer_node.is_healthy = True

        # Local node with high load
        self.mesh_router.local_node.ewma_latency_ms = 80.0
        self.mesh_router.local_node.queue_depth = 20

        # Mock peer return
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = json.dumps({"status": "enqueued", "id": "job_remote_123"})
        mock_requests.return_value = mock_resp

        # Send queue request
        resp = self.client.post(
            "/v1/queue/rest/v1/orders",
            data=json.dumps({"order_id": 99}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.headers.get("X-Blast-Routed-Via"), "https://peer-blast.render.com")
        data = resp.get_json()
        self.assertEqual(data["id"], "job_remote_123")

    @patch("mesh.router.requests.request")
    def test_forward_peer_failure_falls_back_to_local_queue(self, mock_requests):
        # Configure remote peer as fastest
        peer_node = self.mesh_router.nodes["https://peer-blast.render.com"]
        peer_node.ewma_latency_ms = 2.0
        peer_node.queue_depth = 0
        peer_node.is_healthy = True

        self.mesh_router.local_node.ewma_latency_ms = 50.0

        # Mock network failure on remote peer
        mock_requests.side_effect = requests.RequestException("Remote server connection timed out")

        # Send queue request - should catch failure and enqueue locally
        resp = self.client.post(
            "/v1/queue/rest/v1/orders",
            data=json.dumps({"order_id": 100}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 202)
        data = resp.get_json()
        self.assertEqual(data["status"], "queued")
        self.assertIn("job_", data["job_id"])

    def test_get_and_clear_logs(self):
        # Fetch logs
        resp = self.client.get("/v1/logs?limit=50")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("logs", data)
        self.assertIn("count", data)

        # Clear logs
        resp_del = self.client.delete("/v1/logs")
        self.assertEqual(resp_del.status_code, 200)
        self.assertEqual(resp_del.get_json()["status"], "cleared")

    @patch("supabase.client.SupabaseClient.execute")
    def test_pathway_diagnostic_endpoint(self, mock_sb_execute):
        mock_sb_execute.return_value = (200, {"content-type": "application/json"}, '{"version": "1.0.0", "status": "ok"}')
        resp = self.client.post("/v1/test/pathway")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "SUCCESS")
        self.assertIn("cycle", data)
        self.assertIn("duration_ms", data)
        self.assertEqual(data["supabase_status"], 200)


if __name__ == "__main__":
    unittest.main()
