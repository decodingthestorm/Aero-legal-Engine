"""Settings-driven factory for Timestamper, mirroring
core/key_signer_factory.py and core/email_sender_factory.py.

Unlike those two, selecting the real backend here needs a URL as well as
an install extra — a TSA is a specific external service, not a local
capability — so a misconfigured ``timestamp_backend = "rfc3161"`` with no
``tsa_url`` fails at construction with that stated, rather than at the
first anchor attempt against an empty URL.
"""

from __future__ import annotations

from legal_engine.core.config import settings
from legal_engine.core.timestamper import LocalTimestamper, Rfc3161Timestamper, Timestamper


def build_timestamper() -> Timestamper:
    if settings.timestamp_backend == "rfc3161":
        if not settings.tsa_url:
            raise ValueError(
                "timestamp_backend='rfc3161' requires settings.tsa_url "
                "(LEGAL_ENGINE_TSA_URL) to point at a Time-Stamp Authority"
            )
        return Rfc3161Timestamper(
            url=settings.tsa_url,
            hash_algorithm=settings.timestamp_hash_algorithm,
            timeout_seconds=settings.tsa_timeout_seconds,
        )
    return LocalTimestamper(hash_algorithm=settings.timestamp_hash_algorithm)
