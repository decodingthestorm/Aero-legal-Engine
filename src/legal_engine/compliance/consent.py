"""Per-tenant liability-disclaimer acceptance, recorded in and indexed
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

ConsentLedger below replaces this module's original implementation, which
answered "has this tenant accepted?" by scanning every entry in the WAL on
every gated request (require_consent runs on every /verification and
/simulation call). That was fine at this system's current scale and
honestly documented as untested beyond it (see README's Known
limitations) — but it's an O(n) scan of the entire audit history on the
hot path of every gated request, which was never going to hold up. This
replaces it with a read-optimized in-memory projection: tenant_id -> most
recent acceptance, giving an O(1) lookup instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from legal_engine.core.models import WALEntry
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
_REVOCATION_EVENT_TYPE = "legal_disclaimer_revoked"


@dataclass(frozen=True)
class ConsentRecord:
    """A tenant's most recent disclaimer acceptance, as projected from the
    WAL. ``wal_sequence`` is the log-sequence-number (WALEntry.sequence) of
    the exact entry this was derived from — so a cached "yes, this tenant
    accepted" answer is always traceable back to, and re-verifiable
    against, one specific signed WAL entry, not just trusted at face
    value."""

    tenant_id: str
    subject: str
    disclaimer_version: str
    wal_sequence: int


class ConsentLedger:
    """A read-optimized projection over the WAL's
    ``legal_disclaimer_accepted`` entries, giving O(1)
    ``has_accepted_current_disclaimer`` lookups instead of a linear scan.

    The WAL remains the sole source of truth for this — nothing here is
    ever written except by replaying or appending to it. The index is
    built by replaying ``wal.entries()`` once at construction (so it's
    always exactly re-derivable from the WAL — losing this object and
    rebuilding a new one from the same WAL reproduces identical state),
    and updated incrementally, in the same call, whenever
    ``record_acceptance`` appends a new entry — never by re-scanning.

    Only the *most recent* acceptance per tenant is retained (older ones
    are superseded, not deleted — they're still in the WAL itself for a
    genuine audit trail, just not in this projection). That's equivalent
    to "has this tenant ever accepted the current version" for how this is
    actually used: DISCLAIMER_VERSION only ever moves forward as a code
    constant over calendar time, entries are replayed in the WAL's own
    monotonically increasing sequence order, so the latest entry for a
    tenant is always at least as current as any earlier one.

    Not thread-safe beyond what this single-process, single-event-loop
    FastAPI deployment already assumes — same assumption WriteAheadLog
    itself makes.
    """

    def __init__(self, wal: WriteAheadLog) -> None:
        self._wal = wal
        self._latest_by_tenant: dict[str, ConsentRecord] = {}
        for entry in wal.entries():
            self._index(entry)

    def _index(self, entry: WALEntry) -> None:
        if entry.event_type == _REVOCATION_EVENT_TYPE:
            tenant_id = entry.payload.get("tenant_id")
            if tenant_id:
                self._latest_by_tenant.pop(tenant_id, None)
            return
        if entry.event_type != _ACCEPTANCE_EVENT_TYPE:
            return
        tenant_id = entry.payload.get("tenant_id")
        if not tenant_id:
            return
        self._latest_by_tenant[tenant_id] = ConsentRecord(
            tenant_id=tenant_id,
            subject=entry.payload.get("subject", ""),
            disclaimer_version=entry.payload.get("disclaimer_version", ""),
            wal_sequence=entry.sequence,
        )

    def record_acceptance(self, tenant_id: str, subject: str) -> ConsentRecord:
        """Appends an acceptance entry for the current DISCLAIMER_VERSION
        and updates the index in the same call. Idempotent at the call
        site (routes/legal.py checks has_accepted_current_disclaimer
        first), not here, so a repeat acceptance is still recorded as its
        own fact in the WAL rather than silently swallowed."""
        entry = self._wal.append(
            _ACCEPTANCE_EVENT_TYPE,
            {"tenant_id": tenant_id, "subject": subject, "disclaimer_version": DISCLAIMER_VERSION},
        )
        self._index(entry)
        return self._latest_by_tenant[tenant_id]

    def revoke_acceptance(self, tenant_id: str, reason: str = "") -> None:
        """Appends a revocation entry and clears the tenant's projected
        entry in the same call — has_accepted_current_disclaimer answers
        False immediately afterward, with no other route or gate needing
        to know this happened: require_consent (api/dependencies.py)
        already re-checks has_accepted_current_disclaimer fresh on every
        gated request. A later record_acceptance call re-establishes
        acceptance from scratch; replaying the WAL from the start
        reproduces the same end state either way, since entries are
        indexed strictly in the WAL's own chronological order."""
        entry = self._wal.append(_REVOCATION_EVENT_TYPE, {"tenant_id": tenant_id, "reason": reason})
        self._index(entry)

    def has_accepted_current_disclaimer(self, tenant_id: str) -> bool:
        record = self._latest_by_tenant.get(tenant_id)
        return record is not None and record.disclaimer_version == DISCLAIMER_VERSION

    def latest_acceptance(self, tenant_id: str) -> ConsentRecord | None:
        return self._latest_by_tenant.get(tenant_id)
