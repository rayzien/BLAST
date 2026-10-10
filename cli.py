#!/usr/bin/env python3
"""Blast Interactive CLI with Guided Y/N Questions and Instant GUI Connection.

Architecture: App -> Blast -> Supabase
Guaranteed zero emojis.
"""

import os
import sys
import secrets
import argparse
import socket
import threading
import time
import webbrowser
import json
from typing import Optional
from config import config, BlastConfig, load_settings, get_credentials
from logger import logger
from job_queue.storage import SQLiteQueueStorage
from job_queue.redis_storage import RedisQueueStorage
from supabase.client import SupabaseClient
from worker.supervisor import WorkerSupervisor
from cluster.peer_manager import ClusterManager
from server import create_app
from werkzeug.serving import run_simple


def prompt_bool(question: str, default: bool = True) -> bool:
    """Prompt user for a Yes/No (y/n) decision with default."""
    suffix = "[Y/n]" if default else "[y/N]"
    prompt_str = f"{question} {suffix}: "

    while True:
        try:
            choice = input(prompt_str).strip().lower()
            if not choice:
                return default
            if choice in ("y", "yes", "true", "1"):
                return True
            if choice in ("n", "no", "false", "0"):
                return False
            print("  Please enter 'y' for Yes or 'n' for No.")
        except (KeyboardInterrupt, EOFError):
            print("\n[BLAST] Aborted by user.")
            sys.exit(0)


def prompt_text(question: str, default: str = "", is_secret: bool = False, required: bool = False) -> str:
    """Prompt user for text input with optional default and requirement checks."""
    if default:
        display_default = f"{default[:6]}...{default[-4:]}" if is_secret and len(default) > 10 else default
        prompt_str = f"{question} [default: {display_default}]: "
    else:
        prompt_str = f"{question}: "

    while True:
        try:
            val = input(prompt_str).strip()
            if not val and default:
                return default
            if not val and required:
                print("  This field cannot be empty. Please enter a value.")
                continue
            return val
        except (KeyboardInterrupt, EOFError):
            print("\n[BLAST] Aborted by user.")
            sys.exit(0)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if server is already running on port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def open_browser_delayed(url: str, delay: float = 1.0):
    """Open browser in a detached thread after server has initialized."""
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def _resolve_env_path(filepath: str = ".env") -> str:
    if filepath == ".env":
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    return filepath


def load_env_file(filepath: str = ".env") -> dict:
    """Parse key-value pairs from .env if present."""
    target_path = _resolve_env_path(filepath)
    env_vars = {}
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip().strip("'\"")
        except Exception:
            pass
    return env_vars


def save_env_file(env_vars: dict, filepath: str = ".env"):
    """Persist environment configuration."""
    target_path = _resolve_env_path(filepath)
    try:
        lines = [
            "# BLAST CONFIGURATION\n",
            "# Architecture: App -> Blast -> Supabase\n\n",
        ]
        for k, v in env_vars.items():
            lines.append(f"{k}={v}\n")
        with open(target_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"[BLAST] Successfully saved configuration to {target_path}")
    except Exception as e:
        print(f"[WARN] Failed to write {target_path}: {e}")


def save_settings_file(data: dict):
    """Persist settings to settings.json for private repositories and crash resilience."""
    target_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
    try:
        current = load_settings()
        current.update(data)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        print(f"[BLAST] Successfully saved configuration to {target_path}")
    except Exception as e:
        print(f"[WARN] Failed to write {target_path}: {e}")


def run_guided_setup():
    """Step-by-step guided questionnaire with y/n prompts."""
    print("=" * 72)
    print("  BLAST CLI - GUIDED SETUP & RUNNER")
    print("  Architecture: App -> Blast -> Supabase")
    print("  Zero Emojis Mode: Active")
    print("=" * 72)

    settings_data = load_settings()
    existing_env = load_env_file(".env")

    # Step 0: Check if existing configuration exists in settings.json or .env
    detected_url = settings_data.get("supabase_url") or existing_env.get("SUPABASE_URL")
    if detected_url:
        src = "settings.json" if settings_data.get("supabase_url") else ".env"
        print(f"\n[FOUND] Existing configuration found in {src} (Supabase: {detected_url})")
        use_existing = prompt_bool(f"Use existing configuration from {src}?", default=True)
        if use_existing:
            creds = get_credentials()
            config.SUPABASE_URL = creds.get("supabase_url", config.SUPABASE_URL)
            config.SUPABASE_ANON_KEY = creds.get("supabase_anon_key", config.SUPABASE_ANON_KEY)
            config.SUPABASE_SERVICE_ROLE_KEY = creds.get("supabase_service_role_key", config.SUPABASE_SERVICE_ROLE_KEY)
            if creds.get("blast_api_key_1"):
                config.API_KEYS = [creds["blast_api_key_1"]]
            if settings_data.get("blast_port") or existing_env.get("BLAST_PORT"):
                try:
                    config.PORT = int(settings_data.get("blast_port") or existing_env.get("BLAST_PORT"))
                except ValueError:
                    pass
            if existing_env.get("REDIS_URL"):
                config.REDIS_URL = existing_env["REDIS_URL"]

            print("\nConfiguration loaded:")
            print(f"  Supabase URL:  {config.SUPABASE_URL}")
            print(f"  Port:          {config.PORT}")
            print(f"  Workers:       {config.MAX_WORKERS}")
            print(f"  Cluster Mode:  {'Redis' if config.REDIS_URL else 'Local SQLite'}")

            launch_gui = prompt_bool("Launch Web GUI (pages/index.html) in browser? [Y/n]", default=True)
            start_now = prompt_bool("\nStart Blast server now?", default=True)
            if start_now:
                if launch_gui:
                    open_browser_delayed(f"http://localhost:{config.PORT}/")
                start_server(config)
            else:
                print(f"[BLAST] Setup complete. Web GUI ready at http://localhost:{config.PORT}/ when you run 'blast run'.")
            return

    print("\nPlease answer the following questions to configure Blast:\n")

    # Step 1: Supabase Project URL
    has_sup_url = prompt_bool("Do you already have a live Supabase project URL?", default=True)
    if has_sup_url:
        sup_url = prompt_text(
            "Enter your Supabase Project URL (e.g. https://your-id.supabase.co)",
            default=config.SUPABASE_URL,
            required=True,
        )
    else:
        print("\n  [INFO] You can create a free Supabase project at https://supabase.com")
        use_mock = prompt_bool("Run in local development simulation mode with http://localhost:54321?", default=True)
        sup_url = "http://localhost:54321" if use_mock else prompt_text("Enter Supabase URL", default="http://localhost:54321")

    # Step 2: Supabase Anon Key
    has_anon_key = prompt_bool("\nDo you have your Supabase Anon API Key (public key)?", default=True)
    if has_anon_key:
        sup_anon = prompt_text(
            "Enter Supabase Anon Key",
            default=config.SUPABASE_ANON_KEY,
            is_secret=True,
            required=True,
        )
    else:
        sup_anon = "demo-anon-key-placeholder"
        print("  [INFO] Using placeholder anon key for now.")

    # Step 3: Supabase Service Role Key
    has_service_key = prompt_bool("\nDo you want to enable Supabase Service Role Key for admin privileges?", default=False)
    if has_service_key:
        sup_service = prompt_text(
            "Enter Supabase Service Role Key",
            default=config.SUPABASE_SERVICE_ROLE_KEY,
            is_secret=True,
        )
    else:
        sup_service = ""

    # Step 4: API Key Protection
    enable_auth = prompt_bool("\nEnable API Key security for apps connecting to Blast?", default=True)
    if enable_auth:
        auto_gen_key = prompt_bool("Auto-generate a secure random Blast API Key?", default=True)
        if auto_gen_key:
            blast_key = f"blast_sec_{secrets.token_hex(16)}"
            print(f"  [GENERATED] Your Blast API Key: {blast_key}")
        else:
            blast_key = prompt_text("Enter custom Blast API Key", default="blast-secret-key-1")
    else:
        blast_key = ""
        config.REQUIRE_API_KEY = False

    # Step 5: Multi-Instance Cluster Mode (Render / Redis)
    is_cluster = prompt_bool("\nAre you deploying in multi-instance cluster mode (Render with shared Redis)?", default=False)
    if is_cluster:
        redis_url = prompt_text(
            "Enter Redis connection URL (e.g. redis://red-xxxx:6379/0)",
            default="redis://127.0.0.1:6379/0",
            required=True,
        )
    else:
        redis_url = ""
        print("  [INFO] Standalone mode: Using durable WAL-mode SQLite queue.")

    # Step 6: Server Port
    use_default_port = prompt_bool(f"\nRun Blast on default port {config.PORT}?", default=True)
    if use_default_port:
        port = config.PORT
    else:
        port_str = prompt_text("Enter custom port number", default="8080")
        try:
            port = int(port_str)
        except ValueError:
            port = 8080

    # Step 7: Save to .env and settings.json
    should_save = prompt_bool("\nSave this configuration to .env and settings.json for automatic future runs?", default=True)
    if should_save:
        save_env_file({
            "SUPABASE_URL": sup_url.rstrip("/"),
            "SUPABASE_ANON_KEY": sup_anon,
            "SUPABASE_SERVICE_ROLE_KEY": sup_service,
            "BLAST_REQUIRE_API_KEY": str(enable_auth).lower(),
            "BLAST_API_KEYS": blast_key,
            "BLAST_PORT": str(port),
            "REDIS_URL": redis_url,
        })
        save_settings_file({
            "supabase_url": sup_url.rstrip("/"),
            "supabase_anon_key": sup_anon,
            "supabase_service_role_key": sup_service,
            "blast_api_key_1": blast_key or "blast-secret-key-1",
            "blast_port": port,
        })

    # Apply configuration
    config.SUPABASE_URL = sup_url.rstrip("/")
    config.SUPABASE_ANON_KEY = sup_anon
    config.SUPABASE_SERVICE_ROLE_KEY = sup_service
    config.REQUIRE_API_KEY = enable_auth
    config.API_KEYS = [blast_key] if blast_key else []
    config.PORT = port
    config.REDIS_URL = redis_url

    # Step 8: Launch confirmation and GUI
    launch_gui = prompt_bool("\nOpen Web GUI (pages/index.html) in browser? [Y/n]", default=True)
    start_now = prompt_bool("Ready to start Blast server now?", default=True)
    if start_now:
        if launch_gui:
            open_browser_delayed(f"http://localhost:{port}/")
        print("\n[BLAST] Launching Blast Gateway Server...")
        start_server(config)
    else:
        print("\n[BLAST] Setup saved. To start Blast later, run:")
        print("  blast run")
        print(f"  Web GUI available at: http://localhost:{port}/")


def start_server(cfg: BlastConfig):
    """Start queue, cluster, workers, and HTTP server."""
    # 1. Initialize queue engine
    if cfg.REDIS_URL:
        try:
            storage = RedisQueueStorage(cfg.REDIS_URL)
            logger.queue("Distributed Redis storage active for cluster.")
        except Exception as e:
            logger.warn("QUEUE", f"Failed connecting to Redis ({e}), falling back to SQLite.")
            storage = SQLiteQueueStorage(cfg.DB_PATH)
    else:
        storage = SQLiteQueueStorage(cfg.DB_PATH)
        logger.queue(f"Durable SQLite storage active ({cfg.DB_PATH}).")

    # 2. Supabase HTTP client
    supabase_client = SupabaseClient(cfg)

    # 3. Worker supervisor
    supervisor = WorkerSupervisor(cfg, storage=storage, supabase_client=supabase_client)
    supervisor.start()

    # 4. Cluster manager
    cluster_mgr = ClusterManager(cfg)
    cluster_mgr.start()

    # 5. Web application
    app = create_app(
        cfg=cfg,
        storage=storage,
        supabase_client=supabase_client,
        worker_supervisor=supervisor,
        cluster_manager=cluster_mgr,
    )

    print("=" * 72)
    print(f"  [STATUS] Blast is RUNNING on http://{cfg.HOST}:{cfg.PORT}")
    print(f"  [GUI]    Web Dashboard: http://localhost:{cfg.PORT}/ (pages/index.html)")
    print(f"  [TARGET] Supabase Backend: {cfg.SUPABASE_URL}")
    print(f"  [STORAGE] {'Redis (Distributed Cluster)' if cfg.REDIS_URL else 'SQLite (Durable Local)'}")
    print(f"  [WORKERS] {cfg.MAX_WORKERS} active background worker threads")
    print(f"  [CLUSTER] Node ID: {cfg.NODE_ID}")
    print("=" * 72)
    print("Press Ctrl+C to stop.\n")

    try:
        run_simple(
            hostname=cfg.HOST,
            port=cfg.PORT,
            application=app,
            use_reloader=False,
            threaded=True,
        )
    finally:
        supervisor.stop()
        cluster_mgr.stop()
        supabase_client.close()
        logger.info("MAIN", "Blast shutdown completed.")


def launch_gui_command():
    """Effortless GUI launcher command: blast gui"""
    port = config.PORT
    url = f"http://localhost:{port}/"

    print("=" * 72)
    print("  BLAST WEB GUI CONTROLLER")
    print(f"  Dashboard URL:   {url}")
    print(f"  Pages Directory: pages/index.html")
    print("=" * 72)

    if is_port_in_use(port):
        print(f"[BLAST] Gateway server is ALREADY running on port {port}.")
        print(f"[BLAST] Opening {url} in your browser...")
        open_browser_delayed(url, delay=0.2)
        print("[BLAST] Done. Dashboard is connected to your running instance.")
    else:
        print(f"[BLAST] Starting Blast Gateway and launching Web GUI...")
        open_browser_delayed(url, delay=1.0)
        start_server(config)


def main():
    parser = argparse.ArgumentParser(description="Blast CLI: Security & Queue Gateway for Supabase")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("cli", help="Start interactive guided questionnaire and run Blast")
    subparsers.add_parser("gui", help="Directly open Web GUI and connect to Blast gateway")

    run_parser = subparsers.add_parser("run", help="Run directly with existing environment / flags")
    run_parser.add_argument("--host", default=config.HOST)
    run_parser.add_argument("--port", type=int, default=config.PORT)
    run_parser.add_argument("--supabase-url", default=config.SUPABASE_URL)
    run_parser.add_argument("--workers", type=int, default=config.MAX_WORKERS)
    run_parser.add_argument("--open-gui", action="store_true", help="Automatically open web GUI in browser")

    args, unknown = parser.parse_known_args()

    if args.command == "gui":
        launch_gui_command()
    elif args.command == "run":
        if args.supabase_url:
            config.SUPABASE_URL = args.supabase_url
        config.HOST = args.host
        config.PORT = args.port
        config.MAX_WORKERS = args.workers
        if args.open_gui:
            open_browser_delayed(f"http://localhost:{args.port}/")
        start_server(config)
    else:
        # Default or 'cli' triggers guided questionnaire
        run_guided_setup()


if __name__ == "__main__":
    main()
