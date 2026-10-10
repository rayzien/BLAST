"""Data models and enums for the Blast queue subsystem."""

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass
class QueueJob:
    id: str = field(default_factory=lambda: f"job_{uuid.uuid4().hex[:16]}")
    client_id: str = "anonymous"
    idempotency_key: Optional[str] = None
    method: str = "POST"
    path: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    body: Optional[str] = None
    priority: int = 0  # Higher value = higher priority
    status: JobStatus = JobStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    scheduled_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    handled_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to a JSON-serializable dictionary."""
        return {
            "id": self.id,
            "client_id": self.client_id,
            "idempotency_key": self.idempotency_key,
            "method": self.method,
            "path": self.path,
            "headers": self.headers,
            "params": self.params,
            "body": self.body,
            "priority": self.priority,
            "status": self.status.value if isinstance(self.status, JobStatus) else self.status,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "scheduled_at": self.scheduled_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "response_status": self.response_status,
            "response_body": self.response_body,
            "error_message": self.error_message,
            "handled_by": self.handled_by,
        }

    @classmethod
    def from_row(cls, row: dict) -> "QueueJob":
        """Reconstruct job from SQLite row dictionary."""
        return cls(
            id=row["id"],
            client_id=row["client_id"],
            idempotency_key=row.get("idempotency_key"),
            method=row["method"],
            path=row["path"],
            headers=json.loads(row["headers"]) if row.get("headers") else {},
            params=json.loads(row["params"]) if row.get("params") else {},
            body=row.get("body"),
            priority=row.get("priority", 0),
            status=JobStatus(row["status"]),
            retry_count=row.get("retry_count", 0),
            max_retries=row.get("max_retries", 3),
            scheduled_at=row.get("scheduled_at", 0.0),
            created_at=row.get("created_at", 0.0),
            updated_at=row.get("updated_at", 0.0),
            response_status=row.get("response_status"),
            response_body=row.get("response_body"),
            error_message=row.get("error_message"),
            handled_by=row.get("handled_by"),
        )
