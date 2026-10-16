"""Client Credit and Quota Verification Subsystem for Blast Gateway.

Enforces per-client credit balances, quota checks, and atomic deductions
to prevent resource abuse, free-tier exhaustion, and spamming.
Guaranteed zero emojis.
"""

import os
import sqlite3
import time
import threading
from typing import Any, Dict, Optional, Tuple
from config import BlastConfig
from logger import logger


class CreditManager:
    """Thread-safe persistent credit quota and balance verification engine."""

    def __init__(
        self,
        cfg: Optional[BlastConfig] = None,
        db_path: Optional[str] = None,
        default_credits: int = 1000,
        enabled: bool = True,
    ):
        self.cfg = cfg
        self.enabled = enabled
        self.default_credits = default_credits
        self.credits_per_proxy = 1
        self.credits_per_queue = 2
        self._lock = threading.RLock()

        # Database path: default to logs/blast_credits.db or alongside blast_queue.db
        if db_path:
            self.db_path = db_path
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(base_dir)
            logs_dir = os.path.join(parent_dir, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            self.db_path = os.path.join(logs_dir, "blast_credits.db")

        # In-memory fast cache: client_id -> {"balance": int, "lifetime_spent": int}
        self._cache: Dict[str, Dict[str, int]] = {}
        self._init_db()
        self._load_cache()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with WAL mode and busy timeout."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self):
        """Initialize the persistent credit balance table."""
        with self._lock:
            try:
                conn = self._get_connection()
                try:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS blast_client_credits (
                            client_id TEXT PRIMARY KEY,
                            balance INTEGER NOT NULL,
                            lifetime_spent INTEGER NOT NULL DEFAULT 0,
                            last_updated REAL NOT NULL
                        )
                    """)
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                logger.error("CREDITS", f"Failed initializing credit SQLite database: {e}")

    def _load_cache(self):
        """Populate memory cache from SQLite database."""
        with self._lock:
            try:
                conn = self._get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT client_id, balance, lifetime_spent FROM blast_client_credits")
                    rows = cursor.fetchall()
                    for cid, bal, spent in rows:
                        self._cache[cid] = {"balance": int(bal), "lifetime_spent": int(spent)}
                finally:
                    conn.close()
            except Exception as e:
                logger.warn("CREDITS", f"Could not pre-load credit cache: {e}")

    def update_config(
        self,
        enabled: Optional[bool] = None,
        default_credits: Optional[int] = None,
        credits_per_proxy: Optional[int] = None,
        credits_per_queue: Optional[int] = None,
    ):
        """Hot-reload runtime credit configuration parameters."""
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if default_credits is not None and default_credits >= 0:
                self.default_credits = int(default_credits)
            if credits_per_proxy is not None and credits_per_proxy >= 0:
                self.credits_per_proxy = int(credits_per_proxy)
            if credits_per_queue is not None and credits_per_queue >= 0:
                self.credits_per_queue = int(credits_per_queue)

    def get_balance(self, client_id: str) -> int:
        """Get current credit balance for client, initializing if first time seen."""
        with self._lock:
            if client_id not in self._cache:
                self._cache[client_id] = {
                    "balance": self.default_credits,
                    "lifetime_spent": 0,
                }
                self._persist_client(client_id, self.default_credits, 0)
            return self._cache[client_id]["balance"]

    def check_credits(self, client_id: str, cost: int = 1) -> Tuple[bool, int, str]:
        """
        Verify if client has sufficient credit balance to execute operation.
        Returns:
            (has_sufficient_credits: bool, current_balance: int, message: str)
        """
        if not self.enabled:
            return True, 999999, "Credit check disabled."

        with self._lock:
            balance = self.get_balance(client_id)
            if balance < cost:
                return False, balance, f"Insufficient credits: required {cost}, current balance {balance}."
            return True, balance, "Credit check passed."

    def deduct_credits(self, client_id: str, cost: int = 1, reason: str = "request") -> Tuple[bool, int]:
        """
        Atomically deduct credits from client balance.
        Returns:
            (success: bool, new_balance: int)
        """
        if not self.enabled:
            return True, 999999

        with self._lock:
            balance = self.get_balance(client_id)
            if balance < cost:
                return False, balance

            new_balance = balance - cost
            lifetime = self._cache[client_id].get("lifetime_spent", 0) + cost
            self._cache[client_id]["balance"] = new_balance
            self._cache[client_id]["lifetime_spent"] = lifetime
            self._persist_client(client_id, new_balance, lifetime)

            logger.info("CREDITS", f"Deducted {cost} credit(s) from {client_id} for '{reason}'. Balance: {new_balance}")
            return True, new_balance

    def refill_credits(self, client_id: str, amount: int) -> int:
        """Add credits to client balance and persist."""
        with self._lock:
            current = self.get_balance(client_id)
            new_balance = max(0, current + amount)
            lifetime = self._cache[client_id].get("lifetime_spent", 0)
            self._cache[client_id]["balance"] = new_balance
            self._persist_client(client_id, new_balance, lifetime)
            logger.info("CREDITS", f"Refilled {amount} credits for {client_id}. New balance: {new_balance}")
            return new_balance

    def reset_credits(self, client_id: str, amount: Optional[int] = None) -> int:
        """Reset client credits to default or specified amount."""
        with self._lock:
            target = self.default_credits if amount is None else max(0, amount)
            lifetime = self._cache.get(client_id, {}).get("lifetime_spent", 0)
            self._cache[client_id] = {"balance": target, "lifetime_spent": lifetime}
            self._persist_client(client_id, target, lifetime)
            return target

    def _persist_client(self, client_id: str, balance: int, lifetime: int):
        """Persist client credit balance to SQLite."""
        try:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO blast_client_credits (client_id, balance, lifetime_spent, last_updated)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(client_id) DO UPDATE SET
                        balance = excluded.balance,
                        lifetime_spent = excluded.lifetime_spent,
                        last_updated = excluded.last_updated
                    """,
                    (client_id, balance, lifetime, time.time()),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error("CREDITS", f"Failed persisting credits to SQLite: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Return diagnostic metrics and summary of all client credits."""
        with self._lock:
            total_clients = len(self._cache)
            total_balance = sum(v["balance"] for v in self._cache.values())
            total_spent = sum(v["lifetime_spent"] for v in self._cache.values())
            return {
                "enabled": self.enabled,
                "default_credits": self.default_credits,
                "credits_per_proxy": self.credits_per_proxy,
                "credits_per_queue": self.credits_per_queue,
                "total_registered_clients": total_clients,
                "total_circulating_credits": total_balance,
                "total_lifetime_spent_credits": total_spent,
                "clients": {
                    cid: {
                        "balance": data["balance"],
                        "lifetime_spent": data["lifetime_spent"],
                    }
                    for cid, data in self._cache.items()
                },
            }
