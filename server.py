"""Flask application entrypoint and HTTP API routing for Blast with Smart Mesh Router.
Guaranteed zero emojis.
"""

import os
import json
from typing import Optional, Any
from flask import Flask, request, jsonify, Response
from config import BlastConfig, config as default_config
from security.auth import Authenticator
from security.rate_limiter import TokenBucketRateLimiter
from security.firewall import Firewall
from security.checker import SecurityChecker
from job_queue.manager import QueueManager
from supabase.client import SupabaseClient
from supabase.proxy import ProxyHandler
from worker.supervisor import WorkerSupervisor
from cluster.peer_manager import ClusterManager
from mesh.router import SmartMeshRouter
from logger import logger


def create_app(
    cfg: Optional[BlastConfig] = None,
    storage: Optional[Any] = None,
    supabase_client: Optional[SupabaseClient] = None,
    worker_supervisor: Optional[WorkerSupervisor] = None,
    cluster_manager: Optional[ClusterManager] = None,
    security_checker: Optional[SecurityChecker] = None,
    mesh_router: Optional[SmartMeshRouter] = None,
) -> Flask:
    """Application factory for Blast API server."""
    app = Flask(__name__)
    cfg = cfg or default_config

    # Initialize specialized subsystems
    authenticator = Authenticator(cfg)
    rate_limiter = TokenBucketRateLimiter(cfg)
    firewall = Firewall(cfg)
    sec_checker = security_checker or SecurityChecker(cfg)
    queue_manager = QueueManager(cfg, storage=storage)
    supabase_client = supabase_client or SupabaseClient(cfg)
    proxy_handler = ProxyHandler(cfg, client=supabase_client, firewall=firewall)
    cluster_mgr = cluster_manager or ClusterManager(cfg)
    smart_mesh = mesh_router or SmartMeshRouter(cfg)
    smart_mesh.start()

    # Attach components to app context
    app.config["BLAST_SUPERVISOR"] = worker_supervisor
    app.config["BLAST_STORAGE"] = queue_manager.storage
    app.config["BLAST_QUEUE_MANAGER"] = queue_manager
    app.config["BLAST_CLUSTER_MANAGER"] = cluster_mgr
    app.config["BLAST_SECURITY_CHECKER"] = sec_checker
    app.config["BLAST_MESH_ROUTER"] = smart_mesh

    # -------------------------------------------------------------
    # Security Middleware
    # -------------------------------------------------------------
    @app.before_request
    def security_check():
        # Public endpoints (health check, web GUI in pages/, and cluster/mesh heartbeats)
        if request.path in ("/health", "/", "/gui") or request.path.startswith(("/v1/cluster/heartbeat", "/pages")):
            return None

        # 1. Firewall validation (methods, payload size, path traversal)
        content_len = request.content_length
        is_valid, err_msg = firewall.validate_request(
            method=request.method,
            path=request.path,
            content_length=content_len,
        )
        if not is_valid:
            logger.security(f"Blocked request {request.method} {request.path}: {err_msg}")
            return jsonify({"error": "Security check failed", "details": err_msg}), 400

        # 2. Authentication check
        req_headers = dict(request.headers)
        query_dict = dict(request.args)
        is_auth, client_id, auth_err = authenticator.authenticate(req_headers, query_dict)
        if not is_auth:
            logger.security(f"Authentication failed for {request.remote_addr}: {auth_err}")
            return jsonify({"error": "Unauthorized", "details": auth_err}), 401

        request.environ["blast_client_id"] = client_id or "anonymous"

        # 3. Rate Limiting check
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
        return jsonify({
            "status": "healthy",
            "service": "blast",
            "node_id": cfg.NODE_ID,
            "security_checker_active": True,
            "mesh_routing_enabled": cfg.MESH_ROUTING_ENABLED,
            "workers_running": sup.is_alive() if sup else False,
            "supabase_configured": bool(cfg.SUPABASE_URL),
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
            return jsonify({"status": "acknowledged", "node_id": cfg.NODE_ID}), 200
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
            return jsonify({
                "error": "Bad Request - Security Verification Failed",
                "code": err_code,
                "details": err_details,
            }), 400

        # 2. Smart Mesh Dynamic Fastest Route Selection (if mesh enabled and first hop)
        if cfg.MESH_ROUTING_ENABLED and hop_count == 0:
            stats = queue_manager.get_stats()
            smart_mesh.update_local_queue_depth(stats.get("pending", 0) + stats.get("processing", 0))
            route_decision = smart_mesh.select_fastest_route(hop_count=hop_count)

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

        # 3. Local Enqueue Execution
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

        return jsonify({
            "status": "queued" if is_new else "duplicate_idempotent",
            "job_id": job.id,
            "is_new": is_new,
            "idempotency_key": idempotency_key,
            "routed_via": "local",
            "poll_url": f"/v1/jobs/{job.id}",
            "job": job.to_dict(),
        }), 202

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

    @app.route("/v1/dlq", methods=["GET"])
    def list_dlq():
        """List dead letter queue items."""
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = int(request.args.get("offset", 0))
        items = queue_manager.storage.list_dlq(limit=limit, offset=offset)
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
            return jsonify({
                "error": "Bad Request - Security Verification Failed",
                "code": err_code,
                "details": err_details,
            }), 400

        # 2. Smart Mesh Dynamic Routing for Proxy (if mesh enabled and first hop)
        if cfg.MESH_ROUTING_ENABLED and hop_count == 0:
            route_decision = smart_mesh.select_fastest_route(hop_count=hop_count)
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
                    return flask_resp
                except Exception as exc:
                    logger.warn("MESH", f"Peer proxy failed ({exc}), falling back to local proxy execution.")

        # 3. Local Upstream Execution to Supabase
        status_code, resp_headers, resp_body = proxy_handler.forward(
            method=request.method,
            supabase_path=clean_path,
            incoming_headers=dict(request.headers),
            params=dict(request.args),
            body=body,
        )

        # 4. Outbound Response Verification & Sanitization (preventing DB leaks)
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

        flask_resp.headers["X-Blast-Routed-Via"] = "local"
        return flask_resp

    return app
