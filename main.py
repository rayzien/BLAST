#!/usr/bin/env python3
"""Blast - High Performance Security & Queue Gateway for Supabase.

Architecture:
    Client Application -> Blast (Security & Queue) -> Supabase
"""

import argparse
import logging
import os
import signal
import sys
from werkzeug.serving import run_simple
from config import config, BlastConfig
from job_queue.storage import SQLiteQueueStorage
from supabase.client import SupabaseClient
from worker.supervisor import WorkerSupervisor
from server import create_app

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("blast.main")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Blast: Security & Queue Gateway for Supabase (App > Blast > Supabase)"
    )
    parser.add_argument("--host", default=config.HOST, help=f"Host interface to bind (default: {config.HOST})")
    parser.add_argument("--port", type=int, default=config.PORT, help=f"Port to listen on (default: {config.PORT})")
    parser.add_argument("--supabase-url", default=config.SUPABASE_URL, help="Supabase project base URL")
    parser.add_argument("--supabase-anon-key", default=config.SUPABASE_ANON_KEY, help="Supabase anon key")
    parser.add_argument("--supabase-service-key", default=config.SUPABASE_SERVICE_ROLE_KEY, help="Supabase service role key")
    parser.add_argument("--workers", type=int, default=config.MAX_WORKERS, help="Number of background queue workers")
    parser.add_argument("--rate-limit", type=float, default=config.RATE_LIMIT_RPS, help="Max requests/sec per client")
    parser.add_argument("--no-auth", action="store_true", help="Disable API key authentication (dev mode)")
    parser.add_argument("--db-path", default=config.DB_PATH, help="Path to SQLite queue database")
    return parser.parse_args()


def print_banner(cfg: BlastConfig):
    banner = f"""
========================================================================
  ____  _        _    ____ _____ 
 | __ )| |      / \\  / ___|_   _|
 |  _ \\| |     / _ \\ \\___ \\ | |  
 | |_) | |___ / ___ \\ ___) || |  
 |____/|_____/_/   \\_\\____/ |_|  
                                 
 Secure Queue & Proxy Gateway for Supabase
 Architecture: App -> Blast -> Supabase
========================================================================
 Host:            http://{cfg.HOST}:{cfg.PORT}
 Supabase Target: {cfg.SUPABASE_URL or '[Not configured - proxy calls will fail]'}
 Workers:         {cfg.MAX_WORKERS}
 Rate Limiter:    {cfg.RATE_LIMIT_RPS} req/s (Burst: {cfg.RATE_LIMIT_BURST})
 Auth Required:   {cfg.REQUIRE_API_KEY}
 Database:        {cfg.DB_PATH}
========================================================================
"""
    print(banner)


def main():
    args = parse_arguments()

    # Update runtime configuration
    config.HOST = args.host
    config.PORT = args.port
    if args.supabase_url:
        config.SUPABASE_URL = args.supabase_url
    if args.supabase_anon_key:
        config.SUPABASE_ANON_KEY = args.supabase_anon_key
    if args.supabase_service_key:
        config.SUPABASE_SERVICE_ROLE_KEY = args.supabase_service_key
    if args.workers:
        config.MAX_WORKERS = args.workers
    if args.rate_limit:
        config.RATE_LIMIT_RPS = args.rate_limit
    if args.no_auth:
        config.REQUIRE_API_KEY = False
    if args.db_path:
        config.DB_PATH = args.db_path

    print_banner(config)

    # 1. Initialize persistent queue storage
    storage = SQLiteQueueStorage(config.DB_PATH)
    logger.info(f"SQLite queue initialized at {config.DB_PATH}")

    # 2. Initialize Supabase client
    supabase_client = SupabaseClient(config)

    # 3. Start background worker supervisor
    supervisor = WorkerSupervisor(config, storage=storage, supabase_client=supabase_client)
    supervisor.start()

    # 4. Create Flask web application
    app = create_app(
        cfg=config,
        storage=storage,
        supabase_client=supabase_client,
        worker_supervisor=supervisor,
    )

    # Signal handler for graceful shutdown
    def handle_exit(signum, frame):
        logger.info("Shutdown signal received. Stopping workers and shutting down...")
        supervisor.stop(timeout=3.0)
        supabase_client.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # 5. Run HTTP Server
    if os.getenv("PORT"):
        logger.info(f"Cloud environment PORT={os.getenv('PORT')} detected. Binding to port {config.PORT}.")
    logger.info(f"Starting Blast server on {config.HOST}:{config.PORT}...")
    run_simple(
        hostname=config.HOST,
        port=config.PORT,
        application=app,
        use_reloader=False,
        use_debugger=config.DEBUG,
        threaded=True,
    )


if __name__ == "__main__":
    main()
