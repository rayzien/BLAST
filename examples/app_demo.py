"""Example demonstration script showing how an application connects to Blast.

Architecture:
    App -> Blast -> Supabase
"""

import time
from sdk.blast_client import BlastClient


def run_demo():
    print("=" * 60)
    print(" Blast Client Demo: App -> Blast -> Supabase")
    print("=" * 60)

    # Initialize client targeting Blast gateway
    client = BlastClient(
        blast_url="http://localhost:8080",
        blast_key="blast-secret-key-1",
    )

    # 1. Check queue statistics
    print("\n1. Fetching current queue statistics:")
    try:
        stats = client.get_stats()
        print(f"   Queue status: {stats}")
    except Exception as e:
        print(f"   [Notice] Could not connect to running server: {e}")
        print("   (Ensure 'python3 main.py' is running in another terminal)")
        return

    # 2. Queue an asynchronous write (Insert mutation)
    print("\n2. Queueing an order insert to Supabase:")
    sample_order = {
        "customer": "Alice",
        "item": "Mechanical Keyboard",
        "amount": 120.50,
        "timestamp": time.time(),
    }

    job_info = client.table("orders").queue_insert(
        records=sample_order,
        idempotency_key="order-uniq-2026-10-09-01",
        priority=1,
    )
    print(f"   Job queued with status: {job_info['status']}")
    print(f"   Assigned Job ID: {job_info['job_id']}")

    # 3. Wait for background worker to execute the request to Supabase
    print("\n3. Waiting for background worker to process the job...")
    try:
        completed_job = client.wait_for_job(job_info["job_id"], timeout=5.0)
        print(f"   Job finished with status: {completed_job['status']}")
        print(f"   Supabase Response Code: {completed_job.get('response_status')}")
    except TimeoutError:
        print("   Job still in progress or scheduled.")


if __name__ == "__main__":
    run_demo()
