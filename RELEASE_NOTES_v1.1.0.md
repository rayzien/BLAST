# BLAST v1.1.0 - Release Notes

Blast v1.1.0 introduces the **3-Key Interconnect Architecture**, **Syncable Persistence Manager**, **settings.json Private-Repo Crash Recovery**, and a **Clear-Text Credentials UI**.

---

## What's New in v1.1.0

### 1. 3-Key Gateway & Cluster Architecture
Blast now features a dedicated multi-tier key system:
- **Key #1 (Primary Client API Key)**: Primary key passed in `X-Blast-Key` by production client applications (Next.js, Python, Flutter, Node).
- **Key #2 (Secondary / Dev API Key)**: Secondary key for staging environments, development instances, or worker services.
- **Key #3 (Cluster Common Interconnect Secret Key)**: Shared cluster secret allowing all Blast gateway instances across your network, cloud providers, or Render instances to authenticate and peer with one another automatically.

### 2. `settings.json` Persistence & Free-Tier Crash Recovery
- **Private Repository Persistence**: When deploying to free-tier cloud containers (such as Render) where disk storage is ephemeral across container spin-downs, `settings.json` is committed directly to your private repository.
- **Zero-Config Reboot**: On container startup or reboot, Blast automatically checks for `settings.json` and loads all Supabase credentials and API keys into memory and `os.environ` before initializing.
- **Atomic Disk Synchronization**: Persistence operations write via atomic temporary file swap (`.tmp` -> `os.replace`), eliminating file corruption risks.

### 3. Clear-Text Credentials UI
- Input fields for all API keys, cluster secrets, and Supabase credentials in the Web GUI are displayed in plain clear text (`type="text"`) without obscuring masks, dots, or blurring.
- Built-in one-click copy buttons (`📋`) and automated cluster secret generator (`GEN`) provide instant access.

### 4. Real-Time Subsystem Hot-Synchronization
- Changes saved in the Web GUI or through `POST /v1/settings` are hot-synced immediately across all runtime subsystems:
  - `Authenticator`: Immediately updates accepted validation sets.
  - `SupabaseClient`: Instantly switches target endpoints and connection pools.
  - `ClusterManager`: Dynamic cluster secret synchronization.

### 5. Global CLI Execution
- `blast` CLI can now be invoked globally from any directory (`blast cli`, `blast gui`, `blast run`).
- Robust directory-agnostic project root path resolution for all local database files, static assets, and configurations.

---

## Upgrade Instructions

```bash
git pull origin main
pip install -e .
blast run
```
