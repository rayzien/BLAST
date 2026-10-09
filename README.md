# BLAST

A High-Performance Security, Queue, and Clustering Gateway for Supabase.

Authors: rayzien and pheonix14

```
Traditional Architecture:
  [Client App] ------------------------------------------> [Supabase]

Blast Architecture:
  [Client App] --------> [Blast Render Cluster] ---------> [Supabase]
                          |-- Security & Auth Guardrails
                          |-- Token Bucket Rate Limiting
                          |-- Distributed Redis / Durable SQLite Queue
                          |-- Cross-Instance Peer Interconnect
                          |-- Auto-Retry & Exponential Backoff
                          `-- Dead Letter Queue (DLQ)
```

---

## Overview

Connecting client applications directly to Supabase can expose projects to traffic spikes, connection exhaustion, rate-limit bans (HTTP 429), and client-side credential exposure.

Blast functions as an intelligent gateway layer deployed on Render or Docker:
- Absorbs write spikes and bursts into a durable or distributed queue.
- Dispatches writes to Supabase at a safe, controlled rate.
- Interconnects multiple Render instances with shared Redis queuing and peer health sync.
- Protects Supabase keys and enforces rate limits and firewall validation per client.
- Provides zero-loss reliability with automatic retries, backoff, and Dead Letter Queues (DLQ).

---

## Directory Structure

```
blast/
|-- main.py                     # CLI entrypoint and worker supervisor
|-- cli.py                      # Interactive setup wizard and runner
|-- logger.py                   # Specialized zero-emoji structured logger
|-- config.py                   # Central configuration
|-- server.py                   # Flask routing and API endpoints
|-- Dockerfile                  # Container definition
|-- docker-compose.yml          # Multi-instance cluster and Redis in one command
|-- render.yaml                 # Render Blueprint configuration
|-- requirements.txt            # Python dependencies
|-- security/
|   |-- auth.py                 # Constant-time API key validation
|   |-- rate_limiter.py         # Thread-safe Token Bucket rate limiter
|   `-- firewall.py             # Request sanitization and size limits
|-- job_queue/
|   |-- models.py               # QueueJob model and JobStatus enum
|   |-- storage.py              # WAL-mode SQLite storage engine
|   |-- redis_storage.py        # Distributed Redis storage for cluster deployments
|   `-- manager.py              # Deduplication and queue coordination
|-- cluster/
|   `-- peer_manager.py         # Node registration, peer discovery, and heartbeats
|-- worker/
|   |-- dispatcher.py           # Job executor with backoff retry and DLQ
|   `-- supervisor.py           # Worker thread pool supervisor
|-- supabase/
|   |-- client.py               # Pooled HTTP client with auth injection
|   `-- proxy.py                # Synchronous pass-through proxy
|-- sdk/
|   `-- blast_client.py         # Python SDK for client apps
|-- examples/
|   `-- app_demo.py             # Sample client integration script
`-- tests/
    `-- test_blast.py           # Unit and integration test suite
```

---

## Quickstart via CLI

Blast includes a dedicated CLI installed in your system PATH.

### 1. Interactive Setup
Run the CLI wizard:
```bash
blast cli
```
Or simply:
```bash
blast
```
The wizard prompts for:
- Supabase Project URL
- Supabase Anon Key
- Supabase Service Role Key (optional)
- Blast Master Key
- Server Port
- Redis URL (optional, for distributed clustering)

Credentials can be saved to `.env` automatically.

### 2. Direct Execution
```bash
blast run --port 8080 --workers 4
```

---

## Docker Deployment

Run an interconnected two-node cluster with Redis in a single command:

```bash
docker compose up --build
```

This starts:
- `blast-redis` on port 6379
- `blast-node-1` on port 8081
- `blast-node-2` on port 8082

Both nodes share the distributed Redis queue and sync via the cluster interconnect.

---

## Deployment on Render

Blast includes a native `render.yaml` blueprint.

1. Connect this repository to your Render account.
2. Render detects `render.yaml` and deploys:
   - `blast-gateway`: Dockerized web service running the Blast gateway.
   - `blast-redis`: Managed Redis instance providing distributed queue storage.
3. Configure the environment variables on the Render Dashboard:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `BLAST_API_KEYS`

Multiple Render instances automatically interconnect and pull from the shared Redis queue.

---

## API Reference

### 1. Queue Request (Asynchronous)
```bash
curl -X POST http://localhost:8080/v1/queue/rest/v1/orders \
  -H "X-Blast-Key: blast-secret-key-1" \
  -H "X-Idempotency-Key: order-abc-123" \
  -H "Content-Type: application/json" \
  -d '{"customer": "Alice", "amount": 99.0}'
```
Response:
```json
{
  "status": "queued",
  "job_id": "job_0123456789abcdef",
  "is_new": true,
  "poll_url": "/v1/jobs/job_0123456789abcdef"
}
```

### 2. Poll Job Status
```bash
curl http://localhost:8080/v1/jobs/job_0123456789abcdef \
  -H "X-Blast-Key: blast-secret-key-1"
```

### 3. Synchronous Proxy
```bash
curl "http://localhost:8080/v1/proxy/rest/v1/orders?select=*" \
  -H "X-Blast-Key: blast-secret-key-1"
```

### 4. Cluster Health and Nodes
```bash
curl http://localhost:8080/v1/cluster/nodes
```

### 5. Queue Statistics
```bash
curl http://localhost:8080/v1/queue/stats \
  -H "X-Blast-Key: blast-secret-key-1"
```

---

## Testing

Run the test suite:
```bash
python3 -m unittest tests/test_blast.py
```
