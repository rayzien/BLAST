"""Blast Client SDK for Python applications.

Enables seamless integration with Blast proxy and queue endpoints.
Drop-in architectural replacement for direct Supabase clients:
    App -> Blast -> Supabase
"""

import time
import uuid
import requests
from typing import Any, Dict, List, Optional, Union


class TableQueryBuilder:
    """Fluent query builder for Supabase PostgREST tables through Blast."""

    def __init__(self, client: "BlastClient", table: str):
        self.client = client
        self.table = table
        self.params: Dict[str, Any] = {}
        self.headers: Dict[str, str] = {}

    def select(self, columns: str = "*") -> "TableQueryBuilder":
        self.params["select"] = columns
        return self

    def eq(self, column: str, value: Any) -> "TableQueryBuilder":
        self.params[column] = f"eq.{value}"
        return self

    def order(self, column: str, ascending: bool = True) -> "TableQueryBuilder":
        direction = "asc" if ascending else "desc"
        self.params["order"] = f"{column}.{direction}"
        return self

    def limit(self, count: int) -> "TableQueryBuilder":
        self.params["limit"] = count
        return self

    # --- Synchronous Proxy Methods ---
    def execute(self) -> Any:
        """Execute query synchronously via Blast proxy."""
        path = f"/rest/v1/{self.table}"
        return self.client.proxy("GET", path, params=self.params, headers=self.headers)

    # --- Asynchronous Queue Methods ---
    def queue_insert(
        self,
        records: Union[Dict[str, Any], List[Dict[str, Any]]],
        idempotency_key: Optional[str] = None,
        priority: int = 0,
    ) -> Dict[str, Any]:
        """Queue an insert mutation to be processed reliably through Blast workers."""
        path = f"/rest/v1/{self.table}"
        headers = dict(self.headers)
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=representation"

        return self.client.enqueue(
            method="POST",
            path=path,
            json_data=records,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            priority=priority,
            headers=headers,
        )

    def queue_update(
        self,
        values: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        priority: int = 0,
    ) -> Dict[str, Any]:
        """Queue an update mutation through Blast."""
        path = f"/rest/v1/{self.table}"
        headers = dict(self.headers)
        headers["Content-Type"] = "application/json"

        return self.client.enqueue(
            method="PATCH",
            path=path,
            json_data=values,
            params=self.params,
            idempotency_key=idempotency_key,
            priority=priority,
            headers=headers,
        )

    def queue_delete(
        self,
        idempotency_key: Optional[str] = None,
        priority: int = 0,
    ) -> Dict[str, Any]:
        """Queue a delete mutation through Blast."""
        path = f"/rest/v1/{self.table}"
        return self.client.enqueue(
            method="DELETE",
            path=path,
            params=self.params,
            idempotency_key=idempotency_key,
            priority=priority,
            headers=self.headers,
        )


class BlastClient:
    """Client for connecting apps to Blast security and queue proxy."""

    def __init__(self, blast_url: str = "http://localhost:8080", blast_key: str = "blast-secret-key-1"):
        self.blast_url = blast_url.rstrip("/")
        self.blast_key = blast_key
        self.session = requests.Session()
        self.session.headers.update({
            "X-Blast-Key": self.blast_key,
            "User-Agent": "Blast-Python-SDK/1.0",
        })

    def table(self, table_name: str) -> TableQueryBuilder:
        """Create query builder for a table."""
        return TableQueryBuilder(self, table_name)

    def enqueue(
        self,
        method: str,
        path: str,
        json_data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
        priority: int = 0,
    ) -> Dict[str, Any]:
        """
        Enqueue an arbitrary HTTP request to Blast queue:
        POST /v1/queue/<path>
        """
        req_headers = dict(headers or {})
        if idempotency_key:
            req_headers["X-Idempotency-Key"] = idempotency_key
        if priority:
            req_headers["X-Priority"] = str(priority)

        url = f"{self.blast_url}/v1/queue{path}"
        response = self.session.request(
            method=method.upper(),
            url=url,
            json=json_data,
            params=params,
            headers=req_headers,
        )
        response.raise_for_status()
        return response.json()

    def proxy(
        self,
        method: str,
        path: str,
        json_data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Synchronously execute a request through Blast proxy."""
        url = f"{self.blast_url}/v1/proxy{path}"
        response = self.session.request(
            method=method.upper(),
            url=url,
            json=json_data,
            params=params,
            headers=headers,
        )
        response.raise_for_status()
        try:
            return response.json()
        except Exception:
            return response.text

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Check status of a queued job."""
        url = f"{self.blast_url}/v1/jobs/{job_id}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def wait_for_job(self, job_id: str, timeout: float = 10.0, poll_interval: float = 0.2) -> Dict[str, Any]:
        """Poll until job is completed or failed."""
        start = time.time()
        while time.time() - start < timeout:
            job = self.get_job(job_id)
            status = job.get("status")
            if status in ("completed", "failed", "dead_letter"):
                return job
            time.sleep(poll_interval)
        raise TimeoutError(f"Job {job_id} did not finish within {timeout} seconds.")

    def get_stats(self) -> Dict[str, Any]:
        """Get queue stats."""
        url = f"{self.blast_url}/v1/queue/stats"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
