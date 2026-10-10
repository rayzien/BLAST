# Release Notes v1.2.2

## Features & UI Polish
* **Dynamic Multi-Node Common Keys**: Updated the UI and backend Persistence Manager to support adding *multiple* Cluster Common Keys. You can now use a dynamic "Automake form" to input multiple Render URLs or any string identifier as verified cluster peers.
* **Symbol-Only UI (No Emojis)**: Removed all emojis from the web interface for a strictly professional, cyberpunk text/symbol aesthetic (e.g. `[SHOW]`, `[COPY]`). 

## Bug Fixes
* **Supabase 502 DNS Fix**: Resolved a core bug returning `[Errno -2] Name or service not known`. Blast now automatically detects and prepends `https://` if users misconfigure or manually insert domain names without protocol prefixes in the configuration. 
* **Awake Engine & Docker Stabilization**: Verified Dockerfile integrity and `awake/engine.py` background processes run cleanly, preventing Supabase free tiers and Render instances from freezing.

## Test Coverage
* Updated 49 comprehensive unit tests across mesh, configuration persistence, and job queueing. All passing perfectly against Python 3.12 containers.
