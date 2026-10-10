# BLAST MULTI-SERVER MESH ARCHITECTURE MAP
## Dynamic Latency & Load-Aware Routing for Supabase

Authors: rayzien and pheonix14

```
========================================================================================
                          HIGH CONCURRENCY TRAFFIC LIFECYCLE
========================================================================================

    [1,000s OF CONCURRENT APP USERS]
                    │
                    ▼  (Requests sent to Blast server link)
    ┌─────────────────────────────────────────────────────────┐
    │              BLAST INGRESS SERVER LINK                  │
    │  - Authenticates API Key & Validates Security           │
    │  - Checks Inbound Path, Payload & Anti-Injection Rules  │
    └─────────────────────────────────────────────────────────┘
                    │
                    ▼  (Evaluates live latency & queue depth across mesh)
    ┌─────────────────────────────────────────────────────────┐
    │          SMART MESH DYNAMIC ROUTE OPTIMIZER             │
    │  Score = (EWMA_RTT_ms * 0.5) + (Queue_Depth * 10 * 0.5) │
    │  Selects Node with Lowest Pressure & Fastest Path       │
    └─────────────────────────────────────────────────────────┘
                    │
         ┌──────────┴──────────┐
         │                     │
         ▼                     ▼
┌──────────────────┐  ┌──────────────────┐
│ BLAST SERVER #1  │  │ BLAST SERVER #2  │   ... (N Configured Blast Nodes)
│ (Fastest Route)  │  │ (Alternate Route)│
└──────────────────┘  └──────────────────┘
         │
         ▼  (Controlled, pooled dispatch with rate-limiting & backoff retries)
┌─────────────────────────────────────────────────────────┐
│                    SUPABASE BACKEND                     │
│  - PostgREST API / Auth / Storage Engine                │
│  - ZERO Connection Pool Saturation                      │
│  - ZERO HTTP 429 Rate-Limit Bans                        │
└─────────────────────────────────────────────────────────┘
         │
         ▼  (Response verified, database leaks scrubbed, security headers added)
    [FASTEST ROUTE RESPONSE RETURNED SAFELY TO APP]
========================================================================================
```

---

## 1. The Core Problem: Why Direct App -> Supabase Fails at Scale

When hundreds or thousands of users connect directly to Supabase (`App > Supabase`):
1. **Connection Exhaustion**: PostgreSQL has finite connection pools (typically 60-100 max connections on cloud tiers). Burst concurrent traffic exhausts pgBouncer and drops writes.
2. **HTTP 429 Rate Limiting**: Heavy mobile/web app traffic spikes trigger Supabase API Gateway rate limits, dropping orders, events, and transactions.
3. **Network Jitter & High Latency**: Users far from the Supabase region experience high latency and dropped network connections.

---

## 2. The Blast Solution: Multi-Server Mesh & Fastest Route Selection

Blast transforms this into an interconnected cluster of Blast servers:
`App > Blast Server Link > Fastest Route > Supabase > Fastest Route Return > App`

### Key Capabilities:
- **Multiple Blast Server Links**: You can configure multiple server links across regions (e.g. US, EU, Asia, Render instances, local servers).
- **Proactive Latency Probing**: Each Blast node actively pings peer nodes and measures Round-Trip Time (RTT in ms) using Exponential Weighted Moving Average (EWMA) smoothing.
- **Queue Backpressure Awareness**: Blast tracks the active queue depth (pending + processing jobs) of every node.
- **Composite Scoring Formula**:
  ```text
  Composite Score = (EWMA_Latency_ms * 0.5) + (Queue_Depth * 10.0 * 0.5) + Error_Penalty + Local_Bonus
  ```
  - Lower score indicates a faster route with less pressure.
  - A slightly loaded node with 2ms latency will beat a zero-load node with 300ms latency.
  - A node with 500 queued jobs is heavily penalized so traffic automatically diverts to idle nodes.
- **Loop Prevention & Automatic Failover**:
  - Transparent forward requests inject `X-Blast-Hop-Count: 1`.
  - If a peer node experiences network timeout, Blast instantly falls back to local execution. Zero requests are lost.

---

## 3. Configuration & Multi-Link Setup

### Environment Variables:
```bash
# Comma-separated list of peer Blast server links
BLAST_SERVER_LINKS=https://blast-node-1.onrender.com,https://blast-node-2.onrender.com,http://localhost:8081

# Enable Smart Mesh Routing
BLAST_MESH_ROUTING_ENABLED=true

# Mesh Probing Interval
BLAST_CLUSTER_HEARTBEAT_INTERVAL=5.0
```

### Runtime Dynamic Node Management:
Add a new Blast server link at runtime:
```bash
curl -X POST http://localhost:8080/v1/mesh/nodes \
  -H "Content-Type: application/json" \
  -d '{"url": "https://blast-asia.onrender.com", "name": "Render Asia Gateway"}'
```

Inspect active mesh routes and real-time rankings:
```bash
curl http://localhost:8080/v1/mesh/routes
```

Response:
```json
{
  "local_node_id": "node-f977465a",
  "total_nodes": 3,
  "fastest_route": "http://localhost:8080",
  "nodes": [
    {
      "rank": 1,
      "name": "Local Node",
      "url": "http://localhost:8080",
      "latency_ms": 0.5,
      "queue_depth": 0,
      "composite_score": -4.75,
      "is_healthy": true
    },
    {
      "rank": 2,
      "name": "Render Worker 1",
      "url": "https://blast-node-1.onrender.com",
      "latency_ms": 22.4,
      "queue_depth": 2,
      "composite_score": 21.2,
      "is_healthy": true
    }
  ]
}
```

---

## 4. End-to-End Request Cycle

1. **App Sends Request**:
   Dispatches mutation to `http://blast-gateway.domain.com/v1/queue/rest/v1/orders`.
2. **Blast Ingress Inspection**:
   Validates `X-Blast-Key`, sanitizes parameters, enforces JSON nesting limits.
3. **Route Optimizer**:
   Queries SmartMeshRouter; selects Node with the lowest composite score.
4. **Execution**:
   The selected fastest Blast node enqueues or executes to Supabase with connection pooling.
5. **Response Sanitization**:
   Postgres schema error traces are scrubbed; security headers are injected.
6. **Return to App**:
   App receives clean, verified response with `X-Blast-Routed-Via` telemetry header.
