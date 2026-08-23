"""Polite crawling policy. Not yet implemented — Phase 3.

Deliberate deviation from the original spec's anti_blocking.py (JA3/JA4 TLS
fingerprint impersonation + jitter to evade WAF rate-limiting): this module
will instead implement honest, well-behaved crawling —

- robots.txt compliance (checked before any fetch)
- a truthful, identifying User-Agent with a contact URL/email
- bounded concurrency (settings.ingestion_max_concurrency)
- a minimum delay between requests to the same host
  (settings.ingestion_min_delay_seconds)
- exponential backoff on 429/503 honoring any Retry-After header

Public government/legal-statute sources are the ingestion target, so there's
no legitimate need for fingerprint spoofing or anti-detection tooling here —
being a good, identifiable citizen crawler is both simpler and the right
call.
"""
