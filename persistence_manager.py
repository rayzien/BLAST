"""Syncable Persistence Manager for Blast Gateway settings and credentials.

Guaranteed zero emojis.
Provides thread-safe atomic persistence to .env and dynamic hot-synchronization
across all runtime subsystems: Config, Supabase Client, Authenticator, and Cluster Manager.
"""

import os
import re
import json
import threading
from typing import Any, Dict, List, Optional
from config import BlastConfig, config as default_config
from logger import logger


class PersistenceManager:
    """Manages atomic file persistence and live runtime synchronization for Blast."""

    def __init__(
        self,
        cfg: Optional[BlastConfig] = None,
        env_path: Optional[str] = None,
        settings_json_path: Optional[str] = None,
        authenticator: Optional[Any] = None,
        supabase_client: Optional[Any] = None,
        cluster_manager: Optional[Any] = None,
    ):
        self.cfg = cfg or default_config
        self.env_path = env_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        self.settings_json_path = settings_json_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
        self.authenticator = authenticator
        self.supabase_client = supabase_client
        self.cluster_manager = cluster_manager
        self._lock = threading.RLock()

    def get_settings(self) -> Dict[str, Any]:
        """Return current configuration in structured form for UI and API clients."""
        with self._lock:
            # Parse individual API keys
            all_keys = [k.strip() for k in self.cfg.API_KEYS if k.strip()]
            cluster_sec = getattr(self.cfg, "CLUSTER_SECRET", "")

            # Filter client keys from cluster secret
            client_keys = [k for k in all_keys if k != cluster_sec]
            key1 = client_keys[0] if len(client_keys) > 0 else (all_keys[0] if all_keys else "")
            key2 = client_keys[1] if len(client_keys) > 1 else (all_keys[1] if len(all_keys) > 1 and all_keys[1] != cluster_sec else "")

            sup_url = self.cfg.SUPABASE_URL
            sup_anon = self.cfg.SUPABASE_ANON_KEY
            sup_service = self.cfg.SUPABASE_SERVICE_ROLE_KEY

            # If not yet set in cfg, fall back to settings.json if present
            if os.path.exists(self.settings_json_path):
                try:
                    with open(self.settings_json_path, "r", encoding="utf-8") as jf:
                        s_data = json.load(jf)
                        if (not sup_url or sup_url == "https://ylzpjtzeetnvypvikiqa.supabase.co") and s_data.get("supabase_url"):
                            sup_url = s_data["supabase_url"]
                        if not sup_anon and s_data.get("supabase_anon_key"):
                            sup_anon = s_data["supabase_anon_key"]
                        if not sup_service and s_data.get("supabase_service_role_key"):
                            sup_service = s_data["supabase_service_role_key"]
                        if not key1 and s_data.get("blast_api_key_1"):
                            key1 = s_data["blast_api_key_1"]
                        if not key2 and s_data.get("blast_api_key_2"):
                            key2 = s_data["blast_api_key_2"]
                        if not cluster_sec and s_data.get("blast_cluster_secret"):
                            cluster_sec = s_data["blast_cluster_secret"]
                except Exception:
                    pass

            if not key1:
                key1 = "blast-secret-key-1"
            if not cluster_sec:
                cluster_sec = "blast-cluster-mesh-secret-key"

            return {
                # Three Key Architecture
                "blast_api_key_1": key1,
                "blast_api_key_2": key2,
                "blast_cluster_secret": cluster_sec,

                # Supabase Credentials
                "supabase_url": sup_url,
                "supabase_anon_key": sup_anon,
                "supabase_service_role_key": sup_service,

                # Gateway Operational Metrics & Settings
                "host": self.cfg.HOST,
                "port": self.cfg.PORT,
                "max_workers": self.cfg.MAX_WORKERS,
                "rate_limit_rps": self.cfg.RATE_LIMIT_RPS,
                "rate_limit_burst": self.cfg.RATE_LIMIT_BURST,
                "mesh_routing_enabled": self.cfg.MESH_ROUTING_ENABLED,
                "require_api_key": self.cfg.REQUIRE_API_KEY,
                "env_path": self.env_path,
                "settings_json_path": self.settings_json_path,
                "is_persistent": os.path.exists(self.env_path) or os.path.exists(self.settings_json_path),
                "has_settings_json": os.path.exists(self.settings_json_path),
            }

    def save_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate, persist atomically to .env, and hot-sync active runtime subsystems.
        Raises ValueError if inputs are invalid.
        """
        with self._lock:
            # 1. Validation & Extraction
            sup_url = str(payload.get("supabase_url", self.cfg.SUPABASE_URL)).strip().rstrip("/")
            if sup_url and not (sup_url.startswith("http://") or sup_url.startswith("https://")):
                raise ValueError("Supabase Project URL must start with http:// or https://")

            sup_anon = str(payload.get("supabase_anon_key", self.cfg.SUPABASE_ANON_KEY)).strip()
            sup_service = str(payload.get("supabase_service_role_key", self.cfg.SUPABASE_SERVICE_ROLE_KEY)).strip()

            key1 = str(payload.get("blast_api_key_1", "")).strip()
            key2 = str(payload.get("blast_api_key_2", "")).strip()
            cluster_secret = str(payload.get("blast_cluster_secret", "")).strip() or getattr(self.cfg, "CLUSTER_SECRET", "blast-cluster-mesh-secret-key")

            if not key1 and not key2:
                raise ValueError("At least one Blast Client API Key must be specified.")
            if not cluster_secret:
                raise ValueError("Common Cluster Mesh Secret Key cannot be empty.")

            # Compile combined keys list
            combined_keys: List[str] = []
            if key1:
                combined_keys.append(key1)
            if key2 and key2 not in combined_keys:
                combined_keys.append(key2)
            if cluster_secret and cluster_secret not in combined_keys:
                combined_keys.append(cluster_secret)

            # Client keys string for .env
            client_keys_str = ",".join([k for k in [key1, key2] if k])

            # Prepare disk updates
            env_updates: Dict[str, str] = {
                "SUPABASE_URL": sup_url,
                "SUPABASE_ANON_KEY": sup_anon,
                "SUPABASE_SERVICE_ROLE_KEY": sup_service,
                "BLAST_API_KEYS": client_keys_str,
                "BLAST_CLUSTER_SECRET": cluster_secret,
            }

            if "rate_limit_rps" in payload and payload["rate_limit_rps"] != "":
                try:
                    env_updates["BLAST_RATE_LIMIT_RPS"] = str(float(payload["rate_limit_rps"]))
                except (ValueError, TypeError):
                    pass

            if "max_workers" in payload and payload["max_workers"] != "":
                try:
                    env_updates["BLAST_MAX_WORKERS"] = str(int(payload["max_workers"]))
                except (ValueError, TypeError):
                    pass

            # 2. Atomic disk persistence to .env
            self._write_env_file(env_updates)

            # 3. Atomic disk persistence to settings.json (for private repos & free tier crash restarts)
            settings_json_payload = {
                "supabase_url": sup_url,
                "supabase_anon_key": sup_anon,
                "supabase_service_role_key": sup_service,
                "blast_api_key_1": key1,
                "blast_api_key_2": key2,
                "blast_cluster_secret": cluster_secret,
                "blast_host": getattr(self.cfg, "HOST", "0.0.0.0"),
                "blast_port": getattr(self.cfg, "PORT", 8080),
                "max_workers": getattr(self.cfg, "MAX_WORKERS", 4),
                "rate_limit_rps": getattr(self.cfg, "RATE_LIMIT_RPS", 20.0),
                "rate_limit_burst": getattr(self.cfg, "RATE_LIMIT_BURST", 50),
                "mesh_routing_enabled": getattr(self.cfg, "MESH_ROUTING_ENABLED", True),
            }
            if "rate_limit_rps" in payload and payload["rate_limit_rps"] != "":
                try:
                    settings_json_payload["rate_limit_rps"] = float(payload["rate_limit_rps"])
                except (ValueError, TypeError):
                    pass
            if "max_workers" in payload and payload["max_workers"] != "":
                try:
                    settings_json_payload["max_workers"] = int(payload["max_workers"])
                except (ValueError, TypeError):
                    pass
            self._write_settings_json(settings_json_payload)

            # 4. Hot-sync in-memory config object
            self.cfg.SUPABASE_URL = sup_url
            self.cfg.SUPABASE_ANON_KEY = sup_anon
            self.cfg.SUPABASE_SERVICE_ROLE_KEY = sup_service
            self.cfg.CLUSTER_SECRET = cluster_secret
            self.cfg.API_KEYS = combined_keys

            if "rate_limit_rps" in payload and payload["rate_limit_rps"] != "":
                try:
                    self.cfg.RATE_LIMIT_RPS = float(payload["rate_limit_rps"])
                except (ValueError, TypeError):
                    pass

            if "max_workers" in payload and payload["max_workers"] != "":
                try:
                    self.cfg.MAX_WORKERS = int(payload["max_workers"])
                except (ValueError, TypeError):
                    pass

            # Mirror to os.environ
            for k, v in env_updates.items():
                os.environ[k] = v

            # 4. Hot-sync Authenticator
            if self.authenticator:
                if hasattr(self.authenticator, "update_keys"):
                    self.authenticator.update_keys(combined_keys)
                else:
                    self.authenticator.valid_keys = set(combined_keys)
                logger.security(f"Authenticator hot-synced with {len(combined_keys)} active keys.")

            # 5. Hot-sync Supabase Client
            if self.supabase_client:
                self.supabase_client.base_url = sup_url
                if hasattr(self.supabase_client, "reload_config"):
                    self.supabase_client.reload_config()
                logger.supabase(f"Supabase Client hot-synced with target URL: {sup_url}")

            logger.info("CONFIG", "Persistence Manager: Settings successfully saved and synced across all subsystems.")

            return self.get_settings()

    def _write_env_file(self, updates: Dict[str, str]):
        """Persist key-value updates to .env file preserving existing formatting and comments."""
        lines: List[str] = []
        existing_keys = set()

        if os.path.exists(self.env_path):
            try:
                with open(self.env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#") and "=" in stripped:
                            k, _ = stripped.split("=", 1)
                            k = k.strip()
                            if k in updates:
                                lines.append(f"{k}={updates[k]}\n")
                                existing_keys.add(k)
                                continue
                        lines.append(line)
            except Exception as exc:
                logger.warn("CONFIG", f"Failed reading existing {self.env_path}: {exc}")

        # Append any new keys that did not previously exist in .env
        unseen_keys = [k for k in updates if k not in existing_keys]
        if unseen_keys:
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append("\n# Added/Updated by Blast Persistence Manager\n")
            for k in unseen_keys:
                lines.append(f"{k}={updates[k]}\n")

        # Atomic file write (temp file -> atomic rename)
        tmp_path = f"{self.env_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp_path, self.env_path)
        except Exception as exc:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            logger.error("CONFIG", f"Failed atomic write to {self.env_path}: {exc}")
            raise IOError(f"Could not write configuration to {self.env_path}: {exc}")

    def _write_settings_json(self, updates: Dict[str, Any]):
        """Persist configuration atomically to settings.json for private repo persistence across free-tier server restarts."""
        existing_data: Dict[str, Any] = {}
        if os.path.exists(self.settings_json_path):
            try:
                with open(self.settings_json_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except Exception as exc:
                logger.warn("CONFIG", f"Failed reading existing {self.settings_json_path}: {exc}")
                existing_data = {}

        existing_data.update(updates)

        tmp_path = f"{self.settings_json_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, self.settings_json_path)
            logger.info("CONFIG", f"Persistence Manager: Atomically saved settings to {self.settings_json_path}")
        except Exception as exc:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            logger.error("CONFIG", f"Failed atomic write to {self.settings_json_path}: {exc}")
            raise IOError(f"Could not write configuration to {self.settings_json_path}: {exc}")
