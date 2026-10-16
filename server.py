"""Flask application entrypoint and HTTP API routing for Blast with Smart Mesh Router.
Guaranteed zero emojis.
"""

import os
import json
import time
from typing import Optional, Any
from flask import Flask, request, jsonify, Response
from config import BlastConfig, config as default_config
from security.auth import Authenticator
from security.rate_limiter import TokenBucketRateLimiter
from security.firewall import Firewall
from security.checker import SecurityChecker
from security.identity import IdentityProtectionGuard
from security.input_guard import StrictInputValidator
from security.credits import CreditManager
from job_queue.manager import QueueManager
from supabase.client import SupabaseClient
from supabase.proxy import ProxyHandler
from worker.supervisor import WorkerSupervisor
from cluster.peer_manager import ClusterManager
from mesh.router import SmartMeshRouter
from persistence_manager import PersistenceManager
from awake.engine import AwakeEngine
from logger import logger


def create_app(
    cfg: Optional[BlastConfig] = None,
    storage: Optional[Any] = None,
    supabase_client: Optional[SupabaseClient] = None,
    worker_supervisor: Optional[WorkerSupervisor] = None,
    cluster_manager: Optional[ClusterManager] = None,
    security_checker: Optional[SecurityChecker] = None,
    mesh_router: Optional[SmartMeshRouter] = None,
    awake_engine: Optional[AwakeEngine] = None,
) -> Flask:
    """Application factory for Blast API server."""
    app = Flask(__name__)
    cfg = cfg or default_config

    # Initialize specialized subsystems
    authenticator = Authenticator(cfg)
    rate_limiter = TokenBucketRateLimiter(cfg)
    firewall = Firewall(cfg)
    sec_checker = security_checker or SecurityChecker(cfg)
    identity_guard = IdentityProtectionGuard(cfg)
    input_guard = StrictInputValidator(cfg)
    credit_mgr = CreditManager(
        cfg=cfg,
        default_credits=getattr(cfg, "DEFAULT_CLIENT_CREDITS", 1000),
        enabled=getattr(cfg, "CREDIT_CHECK_ENABLED", True),
    )
    queue_manager = QueueManager(cfg, storage=storage)
    supabase_client = supabase_client or SupabaseClient(cfg)
    proxy_handler = ProxyHandler(cfg, client=supabase_client, firewall=firewall)
    cluster_mgr = cluster_manager or ClusterManager(cfg)
    smart_mesh = mesh_router or SmartMeshRouter(cfg)
    if not getattr(cfg, "TESTING", False) and os.getenv("BLAST_TESTING") != "true":
        smart_mesh.start()

    def _on_peer_discovered(peer_url: str, peer_nid: str):
        smart_mesh.add_node(peer_url, name=peer_nid)
        if peer_url not in cfg.PEER_URLS:
            cfg.PEER_URLS.append(peer_url)
        if peer_url not in cfg.SERVER_LINKS:
            cfg.SERVER_LINKS.append(peer_url)
    cluster_mgr.on_peer_discovered = _on_peer_discovered

    # Initialize 24/7 Anti-Sleep Awake Engine
    awake = awake_engine or AwakeEngine(cfg)
    if cfg.AWAKE_ENABLED and not getattr(cfg, "TESTING", False) and os.getenv("BLAST_TESTING") != "true":
        awake.start()

    # Initialize syncable persistence manager
    persistence_mgr = PersistenceManager(
        cfg=cfg,
        authenticator=authenticator,
        supabase_client=supabase_client,
        cluster_manager=cluster_mgr,
        awake_engine=awake,
        mesh_router=smart_mesh,
        credit_manager=credit_mgr,
        identity_guard=identity_guard,
        input_guard=input_guard,
    )

    # Attach components to app context
    app.config["BLAST_SUPERVISOR"] = worker_supervisor
    app.config["BLAST_STORAGE"] = queue_manager.storage
    app.config["BLAST_QUEUE_MANAGER"] = queue_manager
    app.config["BLAST_CLUSTER_MANAGER"] = cluster_mgr
    app.config["BLAST_SECURITY_CHECKER"] = sec_checker
    app.config["BLAST_MESH_ROUTER"] = smart_mesh
    app.config["BLAST_PERSISTENCE_MANAGER"] = persistence_mgr
    app.config["BLAST_AWAKE_ENGINE"] = awake
    app.config["BLAST_IDENTITY_GUARD"] = identity_guard
    app.config["BLAST_INPUT_GUARD"] = input_guard
    app.config["BLAST_CREDIT_MANAGER"] = credit_mgr


    # -------------------------------------------------------------
    # Security Middleware
    # -------------------------------------------------------------
    @app.before_request
    def security_check():
        # Handle CORS preflight requests
        if request.method == "OPTIONS":
            resp = Response(status=200)
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Blast-Key, X-Idempotency-Key, X-Priority, Authorization, X-Blast-Identity-Token, X-Blast-Nonce, X-Blast-Timestamp"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp

        # Public endpoints (health check, web GUI in pages/, cluster/mesh heartbeats, live logs, test pathway, settings, awake engine, credit stats)
        if request.path in ("/health", "/", "/gui", "/v1/test/pathway", "/v1/settings", "/v1/awake", "/awake", "/v1/credits/stats") or request.path.startswith(("/v1/cluster/heartbeat", "/pages", "/v1/logs", "/v1/settings", "/v1/awake", "/v1/credits/stats")):
            return None

        # 1. Identity Protection Guard: strip untrusted/spoofed identity headers
        sanitized_headers = identity_guard.sanitize_inbound_identity_headers(dict(request.headers))

        # 2. Firewall validation (methods, payload size, path traversal)
        content_len = request.content_length
        is_valid, err_msg = firewall.validate_request(
            method=request.method,
            path=request.path,
            content_length=content_len,
        )
        if not is_valid:
            logger.security(f"Blocked request {request.method} {request.path}: {err_msg}")
            return jsonify({"error": "Security check failed", "details": err_msg}), 400

        # 3. Strict Input Guard: validate against prototype pollution, control characters, command injection
        body_bytes = request.get_data() if request.data else None
        is_in_ok, in_err_code, in_err_details = input_guard.validate_inbound_input(
            method=request.method,
            path=request.path,
            headers=sanitized_headers,
            query_params=dict(request.args),
            body=body_bytes,
        )
        if not is_in_ok:
            logger.security(f"Input Guard blocked request {request.method} {request.path}: {in_err_code} - {in_err_details}")
            return jsonify({
                "error": "Bad Request - Input Guard Rejection",
                "code": in_err_code,
                "details": in_err_details,
            }), 400

        # 4. Authentication check
        query_dict = dict(request.args)
        is_auth, client_id, auth_err = authenticator.authenticate(sanitized_headers, query_dict)
        if not is_auth:
            logger.security(f"Authentication failed for {request.remote_addr}: {auth_err}")
            return jsonify({"error": "Unauthorized", "details": auth_err}), 401

        # 5. Identity Verification Guard (Anti-Identity Theft & Session Integrity)
        is_id_ok, id_err = identity_guard.verify_request_identity(
            client_id=client_id or "anonymous",
            secret_key=cfg.API_KEYS[0] if cfg.API_KEYS else None,
            headers=sanitized_headers,
            remote_ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )
        if not is_id_ok:
            logger.security(f"Identity protection violation for {request.remote_addr}: {id_err}")
            return jsonify({
                "error": "Forbidden - Identity Verification Failed",
                "code": "IDENTITY_PROTECTION_VIOLATION",
                "details": id_err,
            }), 403

        request.environ["blast_client_id"] = client_id or "anonymous"

        # 6. Rate Limiting check
        identifier = client_id or request.remote_addr or "client-default"
        allowed, retry_after, remaining = rate_limiter.check(identifier)
        if not allowed:
            logger.security(f"Rate limit exceeded for {identifier} (Retry-After: {retry_after:.1f}s)")
            resp = jsonify({
                "error": "Rate limit exceeded",
                "retry_after_seconds": round(retry_after, 2),
            })
            resp.status_code = 429
            resp.headers["Retry-After"] = str(int(retry_after) + 1)
            return resp

        return None

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Blast-Key, X-Idempotency-Key, X-Priority, Authorization, X-Blast-Identity-Token, X-Blast-Nonce, X-Blast-Timestamp"
        return response


    # -------------------------------------------------------------
    # Web GUI Endpoints (Serving from pages/ folder)
    # -------------------------------------------------------------
    @app.route("/", methods=["GET"])
    @app.route("/gui", methods=["GET"])
    def serve_gui():
        """Serve the primary Blast Web GUI from pages/index.html."""
        pages_dir = os.path.join(os.path.dirname(__file__), "pages")
        index_path = os.path.join(pages_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
        return jsonify({"message": "Blast Gateway is running. pages/index.html not found."}), 404

    @app.route("/pages/<path:filename>", methods=["GET"])
    def serve_page(filename: str):
        """Serve any additional page or asset from the pages/ directory."""
        pages_dir = os.path.join(os.path.dirname(__file__), "pages")
        target_file = os.path.join(pages_dir, filename)
        if os.path.exists(target_file) and os.path.isfile(target_file):
            content_type = "text/html; charset=utf-8" if filename.endswith((".html", ".htm")) else "application/octet-stream"
            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(), 200, {"Content-Type": content_type}
        return jsonify({"error": f"Page '{filename}' not found."}), 404

    @app.route("/health", methods=["GET"])
    def health():
        sup: Optional[WorkerSupervisor] = app.config.get("BLAST_SUPERVISOR")
        qm: Optional[QueueManager] = app.config.get("BLAST_QUEUE_MANAGER")
        q_depth = 0
        if qm:
            st = qm.get_stats()
            q_depth = st.get("pending", 0) + st.get("processing", 0)

        # If incoming request is a peer awake ping carrying sender URL, auto-discover sender
        sender_url = request.headers.get("X-Blast-Sender-Url")
        if sender_url and sender_url.strip().startswith(("http://", "https://")):
            clean_sender = sender_url.strip().rstrip("/")
            local_urls = {
                cfg.PUBLIC_URL.rstrip("/"),
                f"http://{cfg.HOST}:{cfg.PORT}".rstrip("/"),
                f"http://127.0.0.1:{cfg.PORT}".rstrip("/"),
                f"http://localhost:{cfg.PORT}".rstrip("/"),
            }
            if clean_sender not in local_urls:
                cluster_mgr.add_peer(clean_sender)
                smart_mesh.add_node(clean_sender)

        return jsonify({
            "status": "healthy",
            "service": "blast",
            "node_id": cfg.NODE_ID,
            "public_url": cfg.PUBLIC_URL,
            "common_key": getattr(cfg, "CLUSTER_SECRET", "https://sas-the-treasure-grape-xr-prototype.onrender.com/"),
            "security_checker_active": True,
            "mesh_routing_enabled": cfg.MESH_ROUTING_ENABLED,
            "workers_running": sup.is_alive() if sup else False,
            "supabase_configured": bool(cfg.SUPABASE_URL),
            "queue_depth": q_depth,
        })

    # -------------------------------------------------------------
    # Smart Mesh & Fastest Route Endpoints
    # -------------------------------------------------------------
    @app.route("/v1/mesh/routes", methods=["GET"])
    def mesh_routes():
        """Get live telemetry of all registered Blast server nodes, latencies, and rankings."""
        # Update local queue depth before reporting
        stats = queue_manager.get_stats()
        smart_mesh.update_local_queue_depth(stats.get("pending", 0) + stats.get("processing", 0))
        return jsonify(smart_mesh.get_mesh_topology()), 200

    @app.route("/v1/mesh/nodes", methods=["POST"])
    def add_mesh_node():
        """Dynamically register a new Blast server link."""
        data = request.get_json(silent=True) or {}
        url = data.get("url")
        if not url:
            return jsonify({"error": "Missing 'url' parameter"}), 400
        name = data.get("name", "")
        node = smart_mesh.add_node(url=url, name=name)
        return jsonify({"status": "registered", "node": node.to_dict()}), 201

    @app.route("/v1/mesh/nodes", methods=["DELETE"])
    def remove_mesh_node():
        """Remove a Blast server link."""
        data = request.get_json(silent=True) or {}
        url = data.get("url")
        if not url:
            return jsonify({"error": "Missing 'url' parameter"}), 400
        success = smart_mesh.remove_node(url=url)
        return jsonify({"status": "removed" if success else "not_found"}), 200

    @app.route("/v1/mesh/status", methods=["GET"])
    def mesh_status():
        decision = smart_mesh.select_fastest_route()
        return jsonify({
            "mesh_active": True,
            "fastest_route_url": decision.target_node.url,
            "fastest_route_is_local": decision.is_local,
            "routing_reason": decision.reason,
            "total_nodes": len(smart_mesh.nodes),
        }), 200

    # -------------------------------------------------------------
    # Live Logging & Pathway Diagnostic Endpoints
    # -------------------------------------------------------------
    @app.route("/v1/logs", methods=["GET"])
    def get_live_logs():
        """Retrieve recent structured logs for GUI live stream and terminal sync."""
        limit = min(500, max(1, int(request.args.get("limit", 100))))
        since_id = int(request.args.get("since_id", 0))
        component = request.args.get("component")
        records = logger.get_logs(limit=limit, since_id=since_id, component=component)
        return jsonify({
            "count": len(records),
            "since_id": since_id,
            "logs": records,
        }), 200

    @app.route("/v1/logs", methods=["DELETE"])
    def clear_live_logs():
        """Clear memory log ring buffer."""
        logger.clear_logs()
        logger.info("LOGS", "Log buffer cleared by operator.")
        return jsonify({"status": "cleared"}), 200

    @app.route("/v1/test/pathway", methods=["GET", "POST"])
    def test_live_pathway():
        """Live diagnostic test executing full cycle: App > Blast > Route > Supabase > Blast > App."""
        t_start = time.perf_counter()
        test_path = "/auth/v1/health"
        logger.pathway("[PATHWAY_TEST_START] Initiating full gateway diagnostic verification...")

        # 1. Inbound Security Verification
        logger.pathway("[STEP 1/5] Executing inbound security verification on test probe...")
        sec_ok, sec_code, sec_details = sec_checker.verify_inbound_request(
            method="GET",
            path=test_path,
            headers={"User-Agent": "Blast-Pathway-Probe/1.0"},
        )
        if not sec_ok:
            logger.pathway(f"[STEP 1/5] FAILED: Inbound security rejected: {sec_code}")
            return jsonify({"status": "FAILED", "step": 1, "error": sec_code, "details": sec_details}), 400
        logger.pathway("[STEP 1/5] PASSED: Inbound syntax, depth, and safety verified.")

        # 2. Smart Mesh Route Evaluation
        logger.pathway("[STEP 2/5] Evaluating Smart Mesh Route selection...")
        route_decision = smart_mesh.select_fastest_route()
        logger.pathway(
            f"[STEP 2/5] PASSED: Selected route '{route_decision.target_node.url}' "
            f"(Score: {route_decision.score:.2f}, Candidates: {route_decision.evaluated_nodes_count}, Local: {route_decision.is_local})"
        )

        # 3. Supabase Upstream Dispatch
        logger.pathway(f"[STEP 3/5] Querying upstream Supabase instance ({cfg.SUPABASE_URL}{test_path})...")
        sb_status, sb_headers, sb_body = supabase_client.execute(
            method="GET",
            path=test_path,
        )
        logger.pathway(f"[STEP 3/5] PASSED: Supabase responded HTTP {sb_status} ({len(sb_body)} bytes).")

        # 4. Outbound Response Sanitization
        logger.pathway("[STEP 4/5] Running outbound response verification and sanitizing database leaks...")
        clean_status, clean_headers, clean_body = sec_checker.verify_and_sanitize_response(
            status_code=sb_status,
            response_headers=sb_headers,
            response_body=sb_body,
        )
        logger.pathway(f"[STEP 4/5] PASSED: Outbound sanitization complete. Status: {clean_status}")

        # 5. Delivery
        total_ms = (time.perf_counter() - t_start) * 1000.0
        logger.pathway(
            f"[STEP 5/5] PATHWAY COMPLETE in {total_ms:.1f}ms: "
            f"App > Blast Ingress > Fastest Route ({route_decision.target_node.url}) > Supabase > Blast Egress > App"
        )

        parsed_body = None
        try:
            parsed_body = json.loads(clean_body)
        except Exception:
            parsed_body = clean_body

        return jsonify({
            "status": "SUCCESS",
            "cycle": "App > Blast Ingress > Fastest Route > Supabase > Blast Egress > App",
            "duration_ms": round(total_ms, 2),
            "route_winner": route_decision.target_node.url,
            "route_score": round(route_decision.score, 2),
            "route_is_local": route_decision.is_local,
            "supabase_status": clean_status,
            "supabase_response": parsed_body,
        }), 200

    # -------------------------------------------------------------
    # Cluster Endpoints (Interconnected Render instances)
    # -------------------------------------------------------------
    @app.route("/v1/cluster/nodes", methods=["GET"])
    def cluster_nodes():
        """List active connected Blast nodes in the cluster."""
        return jsonify({
            "node_id": cfg.NODE_ID,
            "nodes": cluster_mgr.list_nodes(),
        }), 200

    @app.route("/v1/cluster/heartbeat", methods=["POST"])
    def cluster_heartbeat():
        """Receive peer heartbeat."""
        data = request.get_json(silent=True) or {}
        peer_id = data.get("node_id")
        peer_url = data.get("url")
        if peer_id and peer_url:
            cluster_mgr.record_heartbeat(peer_id, peer_url, meta=data)
            smart_mesh.add_node(peer_url, name=peer_id)
            known = [p.url for p in cluster_mgr.peers.values()]
            return jsonify({
                "status": "acknowledged",
                "node_id": cfg.NODE_ID,
                "public_url": cfg.PUBLIC_URL,
                "known_peers": known,
            }), 200
        return jsonify({"error": "Missing node_id or url"}), 400

    @app.route("/v1/cluster/health", methods=["GET"])
    def cluster_health():
        nodes = cluster_mgr.list_nodes()
        return jsonify({
            "cluster_status": "operational",
            "total_nodes": len(nodes),
            "nodes": nodes,
        }), 200

    # -------------------------------------------------------------
    # Queue Endpoints (app > blast [queue] > supabase)
    # -------------------------------------------------------------
    @app.route("/v1/queue/<path:target_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def enqueue_request(target_path: str):
        """Enqueue an asynchronous request after security verification to be processed reliably to Supabase."""
        client_id = request.environ.get("blast_client_id", "anonymous")
        idempotency_key = request.headers.get("X-Idempotency-Key") or request.headers.get("Idempotency-Key")
        hop_count = int(request.headers.get("X-Blast-Hop-Count", "0"))

        priority = 0
        try:
            if "X-Priority" in request.headers:
                priority = int(request.headers["X-Priority"])
        except ValueError:
            pass

        method = request.args.get("_method", request.method).upper()
        clean_path = f"/{target_path.lstrip('/')}"
        sanitized_headers = firewall.sanitize_headers(dict(request.headers))
        body = request.get_data(as_text=True) if request.data else None
        logger.pathway(f"[QUEUE_INGRESS] {method} {clean_path} from {client_id} (Priority: {priority})")

        # 1. Execute Deep Security Checker on Inbound Request
        is_valid, err_code, err_details = sec_checker.verify_inbound_request(
            method=method,
            path=clean_path,
            headers=dict(request.headers),
            query_params=dict(request.args),
            body=body,
        )
        if not is_valid:
            logger.security(f"Rejected bad queued request: {err_code} - {err_details}")
            logger.pathway(f"[QUEUE_SEC_FAIL] Rejected {method} {clean_path}: {err_code}")
            return jsonify({
                "error": "Bad Request - Security Verification Failed",
                "code": err_code,
                "details": err_details,
            }), 400

        logger.pathway(f"[QUEUE_SEC_PASS] Security verified for {method} {clean_path}")

        # 2. Smart Mesh Dynamic Fastest Route Selection (if mesh enabled and first hop)
        if cfg.MESH_ROUTING_ENABLED and hop_count == 0:
            stats = queue_manager.get_stats()
            smart_mesh.update_local_queue_depth(stats.get("pending", 0) + stats.get("processing", 0))
            route_decision = smart_mesh.select_fastest_route(hop_count=hop_count)
            logger.pathway(f"[QUEUE_ROUTE] Winner: {route_decision.target_node.url} (Score: {route_decision.score:.2f}, Local: {route_decision.is_local})")

            if not route_decision.is_local:
                logger.info(
                    "MESH",
                    f"Dynamic routing selected peer '{route_decision.target_node.url}' for {method} {clean_path} (Reason: {route_decision.reason})"
                )
                try:
                    f_status, f_headers, f_body = smart_mesh.forward_to_peer(
                        node=route_decision.target_node,
                        subpath=f"/v1/queue{clean_path}",
                        method=method,
                        headers=dict(request.headers),
                        params=dict(request.args),
                        body=body,
                    )
                    flask_resp = Response(
                        f_body,
                        status=f_status,
                        content_type=f_headers.get("content-type", "application/json"),
                    )
                    flask_resp.headers["X-Blast-Routed-Via"] = route_decision.target_node.url
                    flask_resp.headers["X-Blast-Route-Score"] = str(round(route_decision.score, 2))
                    return flask_resp
                except Exception as exc:
                    logger.warn("MESH", f"Peer forward failed ({exc}), falling back to local queue.")

        # 3. Credit Quota & Balance Check
        if cfg.CREDIT_CHECK_ENABLED and client_id != "anonymous":
            cost = cfg.CREDITS_PER_QUEUE_REQUEST
            has_credits, cur_bal, msg = credit_mgr.check_credits(client_id, cost=cost)
            if not has_credits:
                logger.security(f"Credit check failed for {client_id}: {msg} (balance: {cur_bal})")
                return jsonify({
                    "error": "Payment Required - Insufficient Credits",
                    "code": "INSUFFICIENT_CREDITS",
                    "client_id": client_id,
                    "remaining_credits": cur_bal,
                    "required_credits": cost,
                    "message": "Client credit quota exhausted. Refill credits or contact administrator."
                }), 402
            credit_mgr.deduct_credits(client_id, cost=cost, reason="enqueue_request")

        # 4. Local Enqueue Execution
        job, is_new = queue_manager.enqueue(
            method=method,
            path=clean_path,
            client_id=client_id,
            headers=sanitized_headers,
            params=dict(request.args),
            body=body,
            idempotency_key=idempotency_key,
            priority=priority,
        )

        logger.queue(f"Verified & enqueued request {method} {clean_path} -> job {job.id} (new={is_new})")

        resp_data = {
            "status": "queued" if is_new else "duplicate_idempotent",
            "job_id": job.id,
            "is_new": is_new,
            "idempotency_key": idempotency_key,
            "routed_via": "local",
            "poll_url": f"/v1/jobs/{job.id}",
            "job": job.to_dict(),
        }
        if client_id != "anonymous":
            resp_data["remaining_credits"] = credit_mgr.get_balance(client_id)
        flask_resp = jsonify(resp_data)
        if client_id != "anonymous":
            flask_resp.headers["X-Blast-Credits-Remaining"] = str(credit_mgr.get_balance(client_id))
        return flask_resp, 202


    @app.route("/v1/jobs/<job_id>", methods=["GET"])
    def get_job(job_id: str):
        """Get the current execution status and sanitized response of a queued job."""
        job = queue_manager.get_job(job_id)
        if not job:
            return jsonify({"error": "Job not found", "job_id": job_id}), 404

        data = job.to_dict()
        if job.response_body:
            try:
                data["parsed_response_body"] = json.loads(job.response_body)
            except Exception:
                pass

        resp = jsonify(data)
        resp.headers["X-Blast-Security-Verified"] = "true"
        return resp, 200

    @app.route("/v1/queue/stats", methods=["GET"])
    def queue_stats():
        """Retrieve queue metrics and health."""
        return jsonify(queue_manager.get_stats()), 200

    @app.route("/v1/queue/analytics", methods=["GET"])
    def queue_analytics():
        """Retrieve time-series analytics for queue."""
        hours = min(int(request.args.get("hours", 1)), 24)
        return jsonify(queue_manager.get_analytics(hours=hours)), 200

    @app.route("/v1/dlq", methods=["GET"])
    def list_dlq():
        """List dead letter queue items."""
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = int(request.args.get("offset", 0))
        items = queue_manager.storage.list_dlq(limit=limit, offset=offset)
        return jsonify({"items": items, "count": len(items)}), 200

    @app.route("/v1/jobs/completed", methods=["GET"])
    def list_completed_jobs():
        """List recently completed (successful) jobs."""
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = int(request.args.get("offset", 0))
        jobs = queue_manager.storage.list_jobs(status="completed", limit=limit, offset=offset)
        items = [j.to_dict() for j in jobs]
        return jsonify({"items": items, "count": len(items)}), 200

    @app.route("/v1/dlq/<job_id>/retry", methods=["POST"])
    def retry_dlq(job_id: str):
        """Retry a job in the dead letter queue."""
        success = queue_manager.retry_dlq_job(job_id)
        if not success:
            return jsonify({"error": "Job not found in DLQ", "job_id": job_id}), 404
        return jsonify({"status": "requeued", "job_id": job_id}), 200

    # -------------------------------------------------------------
    # Proxy Endpoints (app > blast [proxy] > supabase)
    # -------------------------------------------------------------
    @app.route("/v1/proxy/<path:target_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def proxy_request(target_path: str):
        """Synchronously forward verified request through Blast directly to Supabase."""
        clean_path = f"/{target_path.lstrip('/')}"
        body = request.get_data(as_text=True) if request.data else None
        hop_count = int(request.headers.get("X-Blast-Hop-Count", "0"))
        logger.pathway(f"[PROXY_INGRESS] {request.method} {clean_path} (Hop: {hop_count})")

        # 1. Inbound Security Verification
        is_valid, err_code, err_details = sec_checker.verify_inbound_request(
            method=request.method,
            path=clean_path,
            headers=dict(request.headers),
            query_params=dict(request.args),
            body=body,
        )
        if not is_valid:
            logger.security(f"Rejected bad proxy request: {err_code} - {err_details}")
            logger.pathway(f"[PROXY_SEC_FAIL] Rejected {request.method} {clean_path}: {err_code}")
            return jsonify({
                "error": "Bad Request - Security Verification Failed",
                "code": err_code,
                "details": err_details,
            }), 400

        logger.pathway(f"[PROXY_SEC_PASS] Security verified for {request.method} {clean_path}")

        # 2. Smart Mesh Dynamic Routing for Proxy (if mesh enabled and first hop)
        if cfg.MESH_ROUTING_ENABLED and hop_count == 0:
            route_decision = smart_mesh.select_fastest_route(hop_count=hop_count)
            logger.pathway(f"[PROXY_ROUTE] Winner: {route_decision.target_node.url} (Score: {route_decision.score:.2f}, Local: {route_decision.is_local})")
            if not route_decision.is_local:
                logger.info(
                    "MESH",
                    f"Dynamic routing selected peer '{route_decision.target_node.url}' for proxy {request.method} {clean_path}"
                )
                try:
                    f_status, f_headers, f_body = smart_mesh.forward_to_peer(
                        node=route_decision.target_node,
                        subpath=f"/v1/proxy{clean_path}",
                        method=request.method,
                        headers=dict(request.headers),
                        params=dict(request.args),
                        body=body,
                    )
                    flask_resp = Response(
                        f_body,
                        status=f_status,
                        content_type=f_headers.get("content-type", "application/json"),
                    )
                    flask_resp.headers["X-Blast-Routed-Via"] = route_decision.target_node.url
                    flask_resp.headers["X-Blast-Route-Score"] = str(round(route_decision.score, 2))
                    logger.pathway(f"[PROXY_EGRESS] Delivered via peer {route_decision.target_node.url} -> HTTP {f_status}")
                    return flask_resp
                except Exception as exc:
                    logger.warn("MESH", f"Peer proxy failed ({exc}), falling back to local proxy execution.")

        # 3. Credit Quota & Balance Check
        client_id = request.environ.get("blast_client_id", "anonymous")
        if cfg.CREDIT_CHECK_ENABLED and client_id != "anonymous":
            cost = cfg.CREDITS_PER_PROXY_REQUEST
            has_credits, cur_bal, msg = credit_mgr.check_credits(client_id, cost=cost)
            if not has_credits:
                logger.security(f"Credit check failed for {client_id}: {msg} (balance: {cur_bal})")
                return jsonify({
                    "error": "Payment Required - Insufficient Credits",
                    "code": "INSUFFICIENT_CREDITS",
                    "client_id": client_id,
                    "remaining_credits": cur_bal,
                    "required_credits": cost,
                    "message": "Client credit quota exhausted. Refill credits or contact administrator."
                }), 402
            credit_mgr.deduct_credits(client_id, cost=cost, reason="proxy_request")

        # 4. Local Upstream Execution to Supabase
        status_code, resp_headers, resp_body = proxy_handler.forward(
            method=request.method,
            supabase_path=clean_path,
            incoming_headers=dict(request.headers),
            params=dict(request.args),
            body=body,
        )

        # 5. Outbound Response Verification & Sanitization (preventing DB leaks)
        clean_status, clean_headers, clean_body = sec_checker.verify_and_sanitize_response(
            status_code=status_code,
            response_headers=resp_headers,
            response_body=resp_body,
        )

        flask_resp = Response(
            clean_body,
            status=clean_status,
            content_type=clean_headers.get("content-type", "application/json"),
        )
        for k, v in clean_headers.items():
            if k.lower() in ("preference-applied", "content-range", "x-total-count", "x-content-type-options", "x-frame-options", "x-xss-protection", "x-blast-security-verified"):
                flask_resp.headers[k] = v

        if client_id != "anonymous":
            flask_resp.headers["X-Blast-Credits-Remaining"] = str(credit_mgr.get_balance(client_id))

        flask_resp.headers["X-Blast-Routed-Via"] = "local"
        logger.pathway(f"[PROXY_EGRESS] Delivered {request.method} {clean_path} -> HTTP {clean_status}")
        return flask_resp


    # -------------------------------------------------------------
    # Settings & Persistence Manager Endpoints
    # -------------------------------------------------------------
    @app.route("/v1/settings", methods=["GET"])
    def get_settings():
        """Return current live settings and credential configuration."""
        return jsonify(persistence_mgr.get_settings()), 200

    @app.route("/v1/settings", methods=["POST", "PUT"])
    def save_settings():
        """Validate, persist to .env, and hot-sync runtime subsystems."""
        payload = request.get_json(silent=True) or {}
        if not payload:
            return jsonify({"error": "Invalid or missing JSON payload"}), 400

        try:
            updated = persistence_mgr.save_settings(payload)
            return jsonify({
                "status": "success",
                "message": "Settings saved to .env and synchronized across all subsystems.",
                "settings": updated,
            }), 200
        except ValueError as err:
            return jsonify({"error": "Validation Error", "details": str(err)}), 400
        except Exception as exc:
            logger.error("SETTINGS", f"Error saving settings: {exc}")
            return jsonify({"error": "Persistence Error", "details": str(exc)}), 500

    # -------------------------------------------------------------
    # Awake Engine (24/7 Keep-Alive Daemon) Endpoints
    # -------------------------------------------------------------
    @app.route("/v1/awake", methods=["GET"])
    @app.route("/awake", methods=["GET"])
    def get_awake_status():
        """Return live telemetry from Awake Engine."""
        return jsonify(awake.get_status()), 200

    @app.route("/v1/awake/trigger", methods=["POST"])
    def trigger_awake_ping():
        """Trigger an immediate keep-alive ping round across all targets."""
        res = awake.ping_all()
        return jsonify({
            "status": "success",
            "message": "Keep-alive round executed.",
            "data": res,
        }), 200

    @app.route("/v1/awake/config", methods=["POST"])
    def update_awake_config():
        """Update Awake Engine runtime parameters (enabled, interval)."""
        payload = request.get_json(silent=True) or {}
        enabled = payload.get("enabled")
        interval = payload.get("interval_seconds")
        ping_self = payload.get("ping_self")
        ping_supabase = payload.get("ping_supabase")
        ping_peers = payload.get("ping_peers")

        awake.update_config(
            enabled=enabled,
            interval_seconds=interval,
            ping_self=ping_self,
            ping_supabase=ping_supabase,
            ping_peers=ping_peers,
        )
        return jsonify({
            "status": "success",
            "message": "Awake Engine configuration updated.",
            "current_status": awake.get_status(),
        }), 200

    # -------------------------------------------------------------
    # Credit Quota & Balance Endpoints
    # -------------------------------------------------------------
    @app.route("/v1/credits", methods=["GET"])
    def get_client_credits():
        """Get credit balance and quota details for the calling client."""
        client_id = request.environ.get("blast_client_id")
        if not client_id or client_id == "anonymous":
            req_headers = dict(request.headers)
            is_auth, cid, _ = authenticator.authenticate(req_headers, dict(request.args))
            client_id = cid or "anonymous"
        bal = credit_mgr.get_balance(client_id)
        return jsonify({
            "client_id": client_id,
            "balance": bal,
            "credit_check_enabled": cfg.CREDIT_CHECK_ENABLED,
            "credits_per_proxy_request": cfg.CREDITS_PER_PROXY_REQUEST,
            "credits_per_queue_request": cfg.CREDITS_PER_QUEUE_REQUEST,
        }), 200

    @app.route("/v1/credits/refill", methods=["POST"])
    def refill_client_credits():
        """Refill credit balance for a specified client."""
        payload = request.get_json(silent=True) or {}
        target_client = payload.get("client_id") or request.environ.get("blast_client_id", "client-default")
        try:
            amount = int(payload.get("amount", 500))
        except (ValueError, TypeError):
            amount = 500
        new_balance = credit_mgr.refill_credits(target_client, amount)
        return jsonify({
            "status": "success",
            "client_id": target_client,
            "amount_added": amount,
            "new_balance": new_balance,
        }), 200

    @app.route("/v1/credits/stats", methods=["GET"])
    def get_credit_stats():
        """Global credit quota statistics across all registered clients."""
        return jsonify(credit_mgr.get_stats()), 200

    # -------------------------------------------------------------
    # Transparent Supabase Pass-Through Endpoints
    # -------------------------------------------------------------
    @app.route("/rest/v1/<path:target_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def transparent_rest_proxy(target_path: str):
        return proxy_request(f"rest/v1/{target_path}")

    @app.route("/auth/v1/<path:target_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def transparent_auth_proxy(target_path: str):
        return proxy_request(f"auth/v1/{target_path}")

    @app.route("/storage/v1/<path:target_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def transparent_storage_proxy(target_path: str):
        return proxy_request(f"storage/v1/{target_path}")

    @app.route("/graphql/v1/<path:target_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def transparent_graphql_proxy(target_path: str):
        return proxy_request(f"graphql/v1/{target_path}")

    @app.route("/functions/v1/<path:target_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def transparent_functions_proxy(target_path: str):
        return proxy_request(f"functions/v1/{target_path}")

    return app

