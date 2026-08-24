"""Per-tenant liability-disclaimer acceptance, recorded in and checked
against the same cryptographic WAL (core/wal.py) that already exists for
tamper-evident audit trails — not a separate "consent" database table.

This exists to close the gap a per-request "send this exact string with
every call" check couldn't actually close: that pattern only proves a
client sent a string, not that an identified person agreed to anything —
a typed client SDK would auto-inject it into every request with no human
ever seeing it. What matters for a real liability posture is a specific,
authenticated tenant affirmatively accepting a specific, versioned
disclaimer text at a specific point in time, once — like a click-through
EULA, not a per-call header. POST /legal/accept (api/routes/legal.py)
records exactly that, using the token's own subject claim (never a
client-supplied identity), and the acceptance becomes an entry in the
same hash-chained, Ed25519-signed log that already provides non-repudiation
for everything else recorded there.

DISCLAIMER_VERSION is a code constant, not a runtime setting, deliberately:
changing what a tenant is asked to agree to should be a reviewed code
change (and a version bump, so past acceptances of the old text stay
distinguishable from acceptance of the new one), not something adjustable
by an environment variable.
"""

from __future__ import annotations

from legal_engine.core.wal import WriteAheadLog

DISCLAIMER_VERSION = "v1"

DISCLAIMER_TEXT = (
    "This system performs formal verification of logical rules (via an SMT "
    "solver) and game-theoretic modeling of statutory penalties. These are "
    "abstract mathematical analyses of the inputs you provide. They do not "
    "constitute legal advice, do not evaluate whether a given clause "
    "correctly captures what any actual statute means, and are not a "
    "substitute for review by a licensed attorney."
)

_ACCEPTANCE_EVENT_TYPE = "legal_disclaimer_accepted"


def record_acceptance(wal: WriteAheadLog, tenant_id: str, subject: str) -> None:
    """Appends an acceptance entry for the current DISCLAIMER_VERSION.
    Idempotent at the call site (routes/legal.py checks
    has_accepted_current_disclaimer first) rather than here, so repeated
    acceptance attempts are visible in the log rather than silently
    swallowed — a tenant re-accepting is itself a fact worth recording."""
    wal.append(
        _ACCEPTANCE_EVENT_TYPE,
        {"tenant_id": tenant_id, "subject": subject, "disclaimer_version": DISCLAIMER_VERSION},
    )


def has_accepted_current_disclaimer(wal: WriteAheadLog, tenant_id: str) -> bool:
    return any(
        entry.event_type == _ACCEPTANCE_EVENT_TYPE
        and entry.payload.get("tenant_id") == tenant_id
        and entry.payload.get("disclaimer_version") == DISCLAIMER_VERSION
        for entry in wal.entries()
    )
