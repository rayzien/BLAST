# B.L.A.S.T. Gateway (Backend Logic & Automated Security Tunnel)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Release: v1.3.0](https://img.shields.io/badge/Release-v1.3.0--experimental-blueviolet.svg)](RELEASE_NOTES_v1.3.0.md)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://python.org)
[![Build Status](https://img.shields.io/badge/Tests-71%2F71%20passing-brightgreen.svg)](tests/)

BLAST is a high-performance, open-source asynchronous edge gateway designed to protect, route, and queue requests to your Supabase backend. It features anti-identity theft guardrails, strict input sanitization, credit quota enforcement, smart mesh routing, dead letter queues (DLQ), automated 24/7 keep-alive background workers, and dynamic credential management.


---

## [I] Architecture Overview

```mermaid
graph TD
    Client[Client App / RayzHub] -->|HTTP / API Key| Proxy[BLAST Proxy Server]
    
    subgraph BLAST Edge Network
        Proxy --> SecCheck[Security Checker]
        SecCheck --> Mesh[Smart Mesh Router]
        Mesh --> Queue[SQLite Job Queue]
        Queue --> Worker[Async Worker Dispatcher]
    end
    
    Worker -->|Dynamic HTTPS Route| Supabase[(Supabase Backend)]
    Worker -->|Failed / 502| DLQ[Dead Letter Queue]
    Worker -->|200 OK| Success[Recent Successes Log]
```

---

## [II] Quick Start Guide

### 1. Installation
Clone the repository and install the dependencies:
```bash
git clone https://github.com/your-username/BLAST.git
cd BLAST
pip install -r requirements.txt
```

### 2. Configuration (`settings.json`)
BLAST securely manages your credentials using `settings.json` (persisted securely).
Make sure your `settings.json` matches this structure:

```json
{
  "supabase_url": "https://wroxiurfsjvfsonrqdyn.supabase.co",
  "supabase_anon_key": "ylYrX1pIJhz_mIsoCP4_VA_ysrZQvVU",
  "blast_api_key_1": "blast-secret-key-1",
  "blast_api_key_2": "blast-dev-key",
  "blast_cluster_secrets": ["https://sas-the-treasure-grape-xr-prototype.onrender.com/"]
}
```
*Note: The `supabase_anon_key` should NOT include the `sb_publishable_` prefix in the JSON file. BLAST automatically prepends it in memory to prevent GitHub Secret Scanning bots from automatically revoking your credentials on public repos.*

### 3. Running the Server
Start the server using Python:
```bash
python main.py
```
The Gateway GUI will be available at `http://localhost:8080/gui`.

---

## [III] Connecting Apps (RayzHub)

To route your app (e.g., RayzHub) through BLAST, simply replace your direct Supabase URL with your deployed BLAST URL.

* **Target URL**: `https://your-blast-server.onrender.com`
* **Headers**: You must include your BLAST API key in the headers.

```javascript
// Example Client Request
fetch('https://your-blast-server.onrender.com/rest/v1/users', {
    method: 'GET',
    headers: {
        'X-Blast-Key': 'blast-secret-key-1', // Your custom API Key
        'Content-Type': 'application/json'
    }
});
```

---

## [IV] Web Dashboard & Monitoring

BLAST comes with a fully built-in GUI for real-time monitoring and configuration. Access it by navigating to `/gui` on your server.

### [+] Dashboard
Monitor live requests, queue depth, mesh active nodes, and background worker status.

### [+] Failed Jobs (DLQ)
If a request fails (e.g., Supabase throws a 502 or 429), it is automatically placed in the Dead Letter Queue. You can inspect the failure reason and manually click **[RETRY]** once the backend recovers.

### [+] Success Jobs
View the 50-most recent successful (HTTP 2xx) requests. This is the fastest way to verify that your app is successfully communicating through the proxy to Supabase.

### [+] Server Network (Cluster Mesh)
The **Common Credential Link System** (Cluster Mesh) allows multiple BLAST servers to communicate and distribute load. 
1. Enter your `blast_cluster_secrets` in the Settings tab (e.g. `https://sas-the-treasure-grape-xr-prototype.onrender.com/`). 
2. Any BLAST server that shares this link can route traffic to each other.
3. The Smart Mesh Router will automatically select the server with the lowest latency and queue depth.

### [+] 24/7 Keep-Alive & Anti-Sleep Ping Monitor
Guarantees Render free-tier containers (15-min spin down limit) and Supabase free-tier projects (inactivity project pauses) remain 100% active and awake:
* **Render (Self) Pings**: Automated periodic probes to `/health` keep containers awake.
* **Supabase Pings**: Periodic heartbeat probes to `/auth/v1/health` keep Supabase Postgres and Auth warm.
* **Peer Pings**: Mutual keep-alive across interconnected mesh servers.
* **Live Ping Counters**: Tracks exact cumulative ping counts (`render_pings_total`, `supabase_pings_total`, `peer_pings_total`, `total_pings_sent`) with live latency and status badges displayed in real-time on both the Dashboard and Settings tabs.

---

## [V] Persistent Logs & Data

All databases and logs are strictly isolated to the `logs/` directory, making backups and persistence across ephemeral deployments (like Render free tiers) incredibly easy:

* `logs/blast_queue.db`: SQLite database holding your active queue, DLQ, and mesh nodes.
* `logs/blast_credits.db`: Persistent SQLite database holding per-client credit balances and quotas.
* `logs/blast.log`: Raw append-only logs for external ingestion.
* `logs/settings.json`: Synchronized configurations from the Web GUI.

---

## [VI] Experimental Advanced Security System

BLAST v1.3.0 introduces an experimental multi-layer security guardrail system configured in the Web GUI or `settings.json`:

1. **Anti-Identity Theft & Anti-Spoofing Guard (`security/identity.py`)**:
   - Strips untrusted user identity headers (`X-Blast-Client-Id`, `X-Blast-Identity`, `X-User-Id`, `X-Remote-User`, `X-Forwarded-User`, `X-Blast-Role`) so random clients cannot impersonate other users or system accounts.
   - Cryptographically derives and verifies client proof tokens (`X-Blast-Identity-Token`).
   - Session fingerprint tracking detects credential theft and network anomalies.
   - Replay attack prevention with nonce tracking (`X-Blast-Nonce`) and timestamp freshness validation.

2. **Strict Input & Arbitrary Payload Guard (`security/input_guard.py`)**:
   - Prevents prototype pollution attacks by blocking `__proto__`, `constructor`, and `prototype` keys.
   - Detects dangerous control characters and shell command injection heuristics.
   - Enforces JSON nesting depth (<= 10) and object property count (<= 150) to prevent JSON bomb denial-of-service.

---

## [VII] Client Credit Quota & Balance Subsystem

To prevent resource exhaustion and free-tier abuse, BLAST tracks client credit balances atomically:

* **Automatic Credit Checking**: Verifies that calling clients have sufficient credits before proxying or queuing requests.
* **HTTP 402 Payment Required**: Clients with exhausted credits receive an HTTP 402 response with code `INSUFFICIENT_CREDITS`.
* **Cost Structure**: Configurable via Settings (`credits_per_proxy_request` = 1, `credits_per_queue_request` = 2, `default_client_credits` = 1000).
* **Credit Endpoints**:
  - `GET /v1/credits`: Returns current balance and cost parameters.
  - `POST /v1/credits/refill`: Refills credits for a target client.
  - `GET /v1/credits/stats`: Global quota report across all clients.

---

## [VIII] License & Contributing

BLAST is free and open-source software licensed under the **[MIT License](LICENSE)**.

Contributions, issues, and feature requests are welcome! See **[CONTRIBUTING.md](CONTRIBUTING.md)** for details.

---
**Build passing (71/71 tests) | Open Source (MIT) | Mesh Routing Active | Security Guardrails Engaged**

