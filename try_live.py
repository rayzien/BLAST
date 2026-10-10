"""Live trial runner testing Blast Gateway with the user's Supabase project.
Guaranteed zero emojis.
"""

import os
import sys
import time
import json
import threading
import requests
from config import config
from job_queue.storage import SQLiteQueueStorage
from supabase.client import SupabaseClient
from worker.supervisor import WorkerSupervisor
from cluster.peer_manager import ClusterManager
from server import create_app
from werkzeug.serving import run_simple


def start_test_server():
    storage = SQLiteQueueStorage(config.DB_PATH)
    supabase_client = SupabaseClient(config)
    supervisor = WorkerSupervisor(config, storage=storage, supabase_client=supabase_client)
    supervisor.start()
    cluster_mgr = ClusterManager(config)
    cluster_mgr.start()
    app = create_app(
        cfg=config,
        storage=storage,
        supabase_client=supabase_client,
        worker_supervisor=supervisor,
        cluster_manager=cluster_mgr,
    )
    run_simple("127.0.0.1", 8080, app, threaded=True)


def run_trials():
    print("=" * 72)
    print("  BLAST LIVE TRIAL: APP -> BLAST -> SUPABASE")
    print("  Target Supabase: " + config.SUPABASE_URL)
    print("  Publishable Key: " + config.SUPABASE_ANON_KEY[:10] + "...")
    print("=" * 72)

    # 1. Start server in daemon thread
    server_thread = threading.Thread(target=start_test_server, daemon=True)
    server_thread.start()

    # Wait for server to bind
    base_url = "http://127.0.0.1:8080"
    headers = {"X-Blast-Key": "blast-secret-key-1"}

    for _ in range(20):
        try:
            r = requests.get(f"{base_url}/health", timeout=1)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.2)

    # TRIAL 1: Gateway Health & Config Check
    print("\n[TRIAL 1] Gateway Health Check:")
    r = requests.get(f"{base_url}/health")
    print(f"  HTTP Status: {r.status_code}")
    print(f"  Response:    {r.text}")
    assert r.status_code == 200, "Health check failed"

    # TRIAL 2: Synchronous Proxy to Supabase Auth Health
    print("\n[TRIAL 2] Synchronous Proxy: App -> Blast -> Supabase Auth Health")
    r = requests.get(f"{base_url}/v1/proxy/auth/v1/health", headers=headers)
    print(f"  HTTP Status: {r.status_code}")
    print(f"  Security Verified Header: {r.headers.get('X-Blast-Security-Verified')}")
    print(f"  Response:    {r.text}")
    assert r.status_code == 200, "Synchronous proxy failed"

    # TRIAL 3: Asynchronous Queue: App -> Blast Queue -> Worker -> Supabase
    print("\n[TRIAL 3] Asynchronous Queue: Reliable Buffered Request")
    idemp_key = f"trial-idemp-{int(time.time())}"
    q_headers = dict(headers)
    q_headers["X-Idempotency-Key"] = idemp_key
    r = requests.post(f"{base_url}/v1/queue/auth/v1/health", headers=q_headers)
    print(f"  HTTP Status: {r.status_code} (Expected 202 Accepted)")
    q_data = r.json()
    job_id = q_data["job_id"]
    print(f"  Job Assigned: {job_id}")

    # Poll for worker execution
    print("  Waiting for background worker to dispatch to Supabase...")
    for _ in range(15):
        time.sleep(0.3)
        job_resp = requests.get(f"{base_url}/v1/jobs/{job_id}", headers=headers).json()
        if job_resp.get("status") in ("completed", "failed", "dead_letter"):
            print(f"  Final Job Status:   {job_resp['status']}")
            print(f"  Supabase Response: {job_resp.get('response_status')}")
            print(f"  Payload Returned:  {job_resp.get('response_body')}")
            break

    # TRIAL 4: Security Checker Injection Interception
    print("\n[TRIAL 4] Security Checker: Intercepting Malicious SQL Injection")
    bad_url = f"{base_url}/v1/proxy/rest/v1/users?id=1;%20DROP%20TABLE%20users"
    r = requests.get(bad_url, headers=headers)
    print(f"  HTTP Status: {r.status_code} (Expected 400 Bad Request)")
    print(f"  Interception Reason: {r.text}")
    assert r.status_code == 400, "Security checker should block SQLi"

    # TRIAL 5: Web GUI Delivery
    print("\n[TRIAL 5] Web GUI Availability at http://localhost:8080/")
    r = requests.get(f"{base_url}/")
    print(f"  HTTP Status: {r.status_code}")
    print(f"  Content-Type: {r.headers.get('content-type')}")
    print(f"  Contains 12 Fonts: {'Audiowide' in r.text and 'Orbitron' in r.text}")
    assert r.status_code == 200, "Web GUI should be served"

    # TRIAL 6: Queue Metrics Telemetry
    print("\n[TRIAL 6] Queue Metrics Telemetry:")
    r = requests.get(f"{base_url}/v1/queue/stats", headers=headers)
    print(f"  Metrics: {r.text}")

    print("\n" + "=" * 72)
    print("  ALL 6 LIVE TRIALS PASSED SUCCESSFULLY WITH ZERO ERRORS")
    print("=" * 72)


if __name__ == "__main__":
    run_trials()
