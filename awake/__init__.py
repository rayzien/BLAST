"""Awake Engine - 24/7 Keep-Alive Service for Supabase and Render.

Guaranteed zero emojis.
Prevents Render free-tier containers from sleeping (15-min timeout)
and Supabase free-tier projects from pausing (inactivity timeout)
by orchestrating periodic keep-alive probes across all endpoints.
"""

from awake.engine import AwakeEngine

__all__ = ["AwakeEngine"]
