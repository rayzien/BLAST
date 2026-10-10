# GEMINI AI SYSTEM PROMPT: CONNECTING ANY APP TO BLAST GATEWAY

Copy and paste the entire prompt below directly into your Gemini AI chat when you want it to connect your frontend, backend, or mobile application to your deployed Blast Gateway.

---

```markdown
You are an expert full-stack developer. I need you to integrate my application with my deployed BLAST Gateway.

### WHAT IS BLAST?
Blast is a high-performance Security, Queue, and Clustering Gateway deployed on Render/Docker that sits between my client applications and Supabase:
    [My Application] --------> [Blast Gateway] ---------> [Supabase]
                                |-- API Key Security Verification
                                |-- Token Bucket Rate Limiting
                                |-- Durable & Distributed Write Queues
                                |-- 24/7 Keep-Alive Awake Engine
                                `-- Smart Mesh Fastest Route Routing

My Blast Gateway URL: <REPLACE_WITH_YOUR_BLAST_URL> (e.g., https://your-blast-service.onrender.com or http://localhost:8080)
My Blast Client API Key: <REPLACE_WITH_YOUR_BLAST_KEY_1_OR_KEY_2> (e.g., blast-secret-key-1)
My Supabase Project URL: <REPLACE_WITH_YOUR_SUPABASE_PROJECT_URL> (e.g., https://xyzcompany.supabase.co)
My Supabase Anon Key: <REPLACE_WITH_YOUR_SUPABASE_ANON_KEY> (e.g., sb_publishable_...)

---

### INSTRUCTIONS FOR INTEGRATION:

Please update my application to route all database requests through Blast instead of going directly to Supabase. Follow the instructions for my technology stack below:

#### 1. If using the official @supabase/supabase-js Client (JavaScript / TypeScript / Next.js / React / Node):
Instead of initializing Supabase with the direct Supabase URL, point the URL to my Blast Gateway and inject the `X-Blast-Key` header:

```typescript
import { createClient } from '@supabase/supabase-js';

const BLAST_URL = process.env.NEXT_PUBLIC_BLAST_URL || 'https://your-blast-service.onrender.com';
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'your-supabase-anon-key';
const BLAST_API_KEY = process.env.NEXT_PUBLIC_BLAST_API_KEY || 'blast-secret-key-1';

export const supabase = createClient(BLAST_URL, SUPABASE_ANON_KEY, {
  global: {
    headers: {
      'X-Blast-Key': BLAST_API_KEY,
    },
  },
  auth: {
    persistSession: true,
    autoRefreshToken: true,
  },
});
```

*Note*: Because Blast provides transparent pass-through proxies for `/rest/v1`, `/auth/v1`, `/storage/v1`, and `/graphql/v1`, all existing queries (`supabase.from('table').select()`, `supabase.auth.signInWithPassword()`, etc.) will continue to work normally with zero code rewrites, while gaining Blast's queueing, security firewall, and rate limiting!

---

#### 2. If using Direct REST API Calls (fetch / axios / curl):
Send all Supabase REST queries to Blast instead of Supabase, including both headers:
- `X-Blast-Key`: Your Blast API key (for Blast gateway authentication)
- `apikey`: Your Supabase anon key (injected or passed through)

Example:
```typescript
const response = await fetch(`${BLAST_URL}/rest/v1/todos?select=*`, {
  headers: {
    'X-Blast-Key': BLAST_API_KEY,
    'apikey': SUPABASE_ANON_KEY,
    'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
  },
});
const data = await response.json();
```

---

#### 3. For High-Volume Write Spikes (Queued Ingress):
When saving bursts of data (like analytics events, telemetry, bulk orders, or rapid clickstreams) that would normally exceed Supabase connection limits, send them to Blast's queue endpoint:

- **Endpoint**: `POST ${BLAST_URL}/v1/queue/rest/v1/<table_name>`
- **Headers**:
  - `X-Blast-Key`: `<BLAST_API_KEY>`
  - `Content-Type`: `application/json`
  - `X-Blast-Priority`: `1` (Optional: 0=High, 1=Normal, 2=Low)
  - `X-Blast-Idempotency-Key`: `<unique-id>` (Optional: prevents duplicate inserts)
- **Body**: JSON payload of the record to insert.

Example:
```typescript
const enqueueResponse = await fetch(`${BLAST_URL}/v1/queue/rest/v1/orders`, {
  method: 'POST',
  headers: {
    'X-Blast-Key': BLAST_API_KEY,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ item: 'Widget', quantity: 2, price: 19.99 }),
});
// Returns HTTP 202 with job tracking status: {"status": "enqueued", "id": "job_...", "queue_depth": 1}
```

---

#### 4. If using Python (requests / httpx / FastAPI):
```python
import os
import requests

BLAST_URL = os.getenv("BLAST_URL", "https://your-blast-service.onrender.com")
BLAST_KEY = os.getenv("BLAST_API_KEY", "blast-secret-key-1")
SUPABASE_ANON = os.getenv("SUPABASE_ANON_KEY", "your-anon-key")

headers = {
    "X-Blast-Key": BLAST_KEY,
    "apikey": SUPABASE_ANON,
    "Authorization": f"Bearer {SUPABASE_ANON}",
    "Content-Type": "application/json",
}

# 1. Direct query through Blast security layer
res = requests.get(f"{BLAST_URL}/rest/v1/todos?select=*", headers=headers)
print("Data:", res.json())

# 2. Spike-protected queued write
write_res = requests.post(
    f"{BLAST_URL}/v1/queue/rest/v1/todos",
    headers={"X-Blast-Key": BLAST_KEY, "Content-Type": "application/json"},
    json={"title": "Spike-protected todo", "is_complete": False}
)
print("Enqueued:", write_res.status_code, write_res.json())
```

---

#### 5. Verify Gateway Health:
You can verify the connection anytime by calling:
- `GET ${BLAST_URL}/health` -> Returns `{"status": "ok", "service": "blast-gateway"}`
- `GET ${BLAST_URL}/v1/awake` -> Returns live status of the 24/7 keep-alive anti-sleep daemon.

Please apply this architecture to my project now, configure the environment variables, and show me the updated code!
```
