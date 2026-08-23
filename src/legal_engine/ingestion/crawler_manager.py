"""Async ingestion dispatcher & worker pool. Not yet implemented — Phase 3.

Planned shape: an httpx.AsyncClient-based dispatcher that pulls source URLs
from a queue, respects rate_limiter.py's concurrency/backoff policy, and
hands parsed results to the appropriate parser in ingestion/parsers/.
"""
