"""Unit test suite for Blast Settings & Syncable Persistence Manager.

Guaranteed zero emojis.
Tests retrieval, atomic persistence to .env, validation, 3-key architecture,
and live hot-synchronization across all subsystems.
"""

import os
import json
import tempfile
import unittest
from config import BlastConfig, resolve_port, get_credentials, get_setting, load_settings
from security.auth import Authenticator
from supabase.client import SupabaseClient
from cluster.peer_manager import ClusterManager
from persistence_manager import PersistenceManager
from server import create_app


class TestPersistenceManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.env_path = os.path.join(self.tmp_dir.name, ".env.test")
        self.settings_json_path = os.path.join(self.tmp_dir.name, "settings.json")
        self.cfg = BlastConfig(
            API_KEYS=["test-key-1", "test-key-2"],
            CLUSTER_SECRETS=["cluster-common-secret-xyz"],
            CLUSTER_SECRET="",
            SUPABASE_URL="https://initial-project.supabase.co",
            SUPABASE_ANON_KEY="initial-anon-key-123",
            SUPABASE_SERVICE_ROLE_KEY="",
        )
        self.authenticator = Authenticator(self.cfg)
        self.supabase_client = SupabaseClient(self.cfg)
        self.cluster_mgr = ClusterManager(self.cfg)
        self.manager = PersistenceManager(
            cfg=self.cfg,
            env_path=self.env_path,
            settings_json_path=self.settings_json_path,
            authenticator=self.authenticator,
            supabase_client=self.supabase_client,
            cluster_manager=self.cluster_mgr,
        )

    def tearDown(self):
        self.supabase_client.close()
        self.cluster_mgr.stop()
        self.tmp_dir.cleanup()

    def test_get_settings_structure(self):
        settings = self.manager.get_settings()
        self.assertEqual(settings["blast_api_key_1"], "test-key-1")
        self.assertEqual(settings["blast_api_key_2"], "test-key-2")
        self.assertEqual(settings["blast_cluster_secrets"], ["cluster-common-secret-xyz"])
        self.assertEqual(settings["supabase_url"], "https://initial-project.supabase.co")
        self.assertEqual(settings["supabase_anon_key"], "initial-anon-key-123")

    def test_save_and_persist_settings_to_env_and_json(self):
        payload = {
            "blast_api_key_1": "new-client-key-primary",
            "blast_api_key_2": "new-client-key-dev",
            "blast_cluster_secrets": ["common-cluster-key-shared-999"],
            "supabase_url": "https://updated-project.supabase.co",
            "supabase_anon_key": "updated-anon-456",
            "supabase_service_role_key": "service-secret-789",
            "max_workers": 8,
            "rate_limit_rps": 50.0,
        }
        res = self.manager.save_settings(payload)

        # 1. Verify returned settings
        self.assertEqual(res["blast_api_key_1"], "new-client-key-primary")
        self.assertEqual(res["blast_api_key_2"], "new-client-key-dev")
        self.assertEqual(res["blast_cluster_secrets"], ["common-cluster-key-shared-999"])
        self.assertEqual(res["supabase_url"], "https://updated-project.supabase.co")
        self.assertEqual(res["max_workers"], 8)

        # 2. Verify disk file (.env) was written
        self.assertTrue(os.path.exists(self.env_path))
        with open(self.env_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("SUPABASE_URL=https://updated-project.supabase.co", content)
        self.assertIn("BLAST_CLUSTER_SECRETS=common-cluster-key-shared-999", content)
        self.assertIn("BLAST_API_KEYS=new-client-key-primary,new-client-key-dev", content)

        # 3. Verify disk file (settings.json) was written atomically
        self.assertTrue(os.path.exists(self.settings_json_path))
        with open(self.settings_json_path, "r", encoding="utf-8") as jf:
            s_data = json.load(jf)
        self.assertEqual(s_data["supabase_url"], "https://updated-project.supabase.co")
        self.assertEqual(s_data["blast_api_key_1"], "new-client-key-primary")
        self.assertEqual(s_data["blast_cluster_secrets"], ["common-cluster-key-shared-999"])
        self.assertEqual(s_data["max_workers"], 8)

        # 4. Verify hot-sync in Authenticator
        self.assertIn("new-client-key-primary", self.authenticator.valid_keys)
        self.assertIn("common-cluster-key-shared-999", self.authenticator.valid_keys)

        # 5. Verify hot-sync in Supabase Client
        self.assertEqual(self.supabase_client.base_url, "https://updated-project.supabase.co")

    def test_settings_json_fallback_when_env_absent(self):
        # Emulate server restart where .env is absent (ephemeral container) but settings.json is present (private repo)
        custom_json_path = os.path.join(self.tmp_dir.name, "fresh_settings.json")
        with open(custom_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "supabase_url": "https://restored-after-crash.supabase.co",
                "supabase_anon_key": "restored-anon-key",
                "blast_api_key_1": "restored-client-key",
                "blast_cluster_secrets": ["restored-cluster-secret"]
            }, f)

        cfg_empty = BlastConfig(
            API_KEYS=[],
            CLUSTER_SECRETS=[],
            CLUSTER_SECRET="",
            SUPABASE_URL="",
            SUPABASE_ANON_KEY="",
        )
        mgr = PersistenceManager(
            cfg=cfg_empty,
            env_path=os.path.join(self.tmp_dir.name, "nonexistent.env"),
            settings_json_path=custom_json_path
        )
        data = mgr.get_settings()
        self.assertEqual(data["supabase_url"], "https://restored-after-crash.supabase.co")
        self.assertEqual(data["supabase_anon_key"], "restored-anon-key")
        self.assertEqual(data["blast_api_key_1"], "restored-client-key")
        self.assertEqual(data["blast_cluster_secrets"], ["restored-cluster-secret"])
        self.assertTrue(data["has_settings_json"])

    def test_save_validation_errors(self):
        # Invalid Supabase URL
        with self.assertRaises(ValueError):
            self.manager.save_settings({
                "supabase_url": "ftp://not-http-url",
                "blast_api_key_1": "k1",
                "blast_cluster_secret": "sec",
            })

        # Empty keys
        with self.assertRaises(ValueError):
            self.manager.save_settings({
                "blast_api_key_1": "",
                "blast_api_key_2": "",
                "blast_cluster_secret": "sec",
            })


class TestSettingsServerEndpoints(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "settings_test.db")
        self.env_path = os.path.join(self.tmp_dir.name, ".env.test")
        self.settings_json_path = os.path.join(self.tmp_dir.name, "settings_test.json")
        self.cfg = BlastConfig(
            API_KEYS=["primary-key-100", "dev-key-200"],
            CLUSTER_SECRETS=["cluster-mesh-shared-300"],
            CLUSTER_SECRET="",
            SUPABASE_URL="https://endpoint-test.supabase.co",
            SUPABASE_ANON_KEY="anon-test-key",
            DB_PATH=self.db_path,
        )
        self.app = create_app(cfg=self.cfg)
        # Point persistence manager to test env and settings.json
        self.app.config["BLAST_PERSISTENCE_MANAGER"].env_path = self.env_path
        self.app.config["BLAST_PERSISTENCE_MANAGER"].settings_json_path = self.settings_json_path
        self.client = self.app.test_client()

    def tearDown(self):
        if "BLAST_MESH_ROUTER" in self.app.config and self.app.config["BLAST_MESH_ROUTER"]:
            self.app.config["BLAST_MESH_ROUTER"].stop()
        if "BLAST_CLUSTER_MANAGER" in self.app.config and self.app.config["BLAST_CLUSTER_MANAGER"]:
            self.app.config["BLAST_CLUSTER_MANAGER"].stop()
        if "BLAST_STORAGE" in self.app.config and self.app.config["BLAST_STORAGE"]:
            self.app.config["BLAST_STORAGE"].close()
        self.tmp_dir.cleanup()

    def test_get_settings_endpoint(self):
        resp = self.client.get("/v1/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["blast_api_key_1"], "primary-key-100")
        self.assertEqual(data["blast_api_key_2"], "dev-key-200")
        self.assertEqual(data["blast_cluster_secrets"], ["cluster-mesh-shared-300"])
        self.assertEqual(data["supabase_url"], "https://endpoint-test.supabase.co")

    def test_post_save_settings_endpoint(self):
        payload = {
            "blast_api_key_1": "new-master-1",
            "blast_api_key_2": "new-secondary-2",
            "blast_cluster_secrets": ["common-cluster-mesh-3"],
            "supabase_url": "https://new-live-instance.supabase.co",
            "supabase_anon_key": "new-live-anon",
            "supabase_service_role_key": "new-live-service",
            "max_workers": 6,
        }
        resp = self.client.post(
            "/v1/settings",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["settings"]["blast_api_key_1"], "new-master-1")
        self.assertEqual(data["settings"]["blast_cluster_secrets"], ["common-cluster-mesh-3"])
        self.assertEqual(data["settings"]["supabase_url"], "https://new-live-instance.supabase.co")

        # Verify disk persistence to .env
        self.assertTrue(os.path.exists(self.env_path))
        with open(self.env_path, "r", encoding="utf-8") as f:
            disk_content = f.read()
        self.assertIn("SUPABASE_URL=https://new-live-instance.supabase.co", disk_content)
        self.assertIn("BLAST_CLUSTER_SECRETS=common-cluster-mesh-3", disk_content)

        # Verify disk persistence to settings.json
        self.assertTrue(os.path.exists(self.settings_json_path))
        with open(self.settings_json_path, "r", encoding="utf-8") as jf:
            json_disk_content = json.load(jf)
        self.assertEqual(json_disk_content["supabase_url"], "https://new-live-instance.supabase.co")
        self.assertEqual(json_disk_content["blast_cluster_secrets"], ["common-cluster-mesh-3"])

    def test_common_cluster_key_authenticates_peer(self):
        # The 3rd common key allows any other Blast server to authenticate requests
        resp = self.client.get(
            "/v1/mesh/routes",
            headers={"X-Blast-Key": "cluster-mesh-shared-300"}
        )
        self.assertEqual(resp.status_code, 200)


class TestUniversalSettingsAndPort(unittest.TestCase):
    """Test PORT precedence resolution and universal settings.json accessors."""

    def test_resolve_port_precedence_cloud_port(self):
        old_port = os.environ.get("PORT")
        old_blast_port = os.environ.get("BLAST_PORT")
        try:
            # When Render sets PORT=8000, resolve_port must return 8000
            os.environ["PORT"] = "8000"
            os.environ["BLAST_PORT"] = "8080"
            self.assertEqual(resolve_port(), 8000)

            # When only BLAST_PORT is set, return BLAST_PORT
            del os.environ["PORT"]
            os.environ["BLAST_PORT"] = "9090"
            self.assertEqual(resolve_port(), 9090)
        finally:
            if old_port is not None:
                os.environ["PORT"] = old_port
            elif "PORT" in os.environ:
                del os.environ["PORT"]
            if old_blast_port is not None:
                os.environ["BLAST_PORT"] = old_blast_port
            elif "BLAST_PORT" in os.environ:
                del os.environ["BLAST_PORT"]

    def test_get_credentials_and_get_setting(self):
        creds = get_credentials()
        self.assertIn("supabase_url", creds)
        self.assertIn("supabase_anon_key", creds)
        self.assertIn("blast_api_key_1", creds)
        self.assertIn("blast_cluster_secrets", creds)

        # get_setting lookup
        rate_rps = get_setting("rate_limit_rps")
        self.assertIsNotNone(rate_rps)

    def test_supabase_client_unconfigured_error(self):
        cfg = BlastConfig(SUPABASE_URL="")
        client = SupabaseClient(cfg)
        status, headers, body = client.execute("GET", "/rest/v1/test")
        self.assertEqual(status, 503)
        self.assertIn("SUPABASE_NOT_CONFIGURED", body)
        client.close()


if __name__ == "__main__":
    unittest.main()
