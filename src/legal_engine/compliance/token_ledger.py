"""Per-token revocation and refresh-token redemption, tracked in the same
WAL-backed-projection shape as compliance/consent.py's ConsentLedger: the
WAL is the sole source of truth, this is an O(1) index over it, exactly
re-derivable by replaying wal.entries() from scratch. Kept alongside
ConsentLedger rather than in a new package, for the identical reason —
this is another O(1) index over WAL-recorded trust facts, not a
conceptually different kind of thing.

Every issued access/refresh token (api/security.py's create_token) now
carries a jti (unique per token, not per user — sub alone can't identify
*which* token to revoke) and a token_type claim ("access" or "refresh").
api/dependencies.py's require_auth/get_current_tenant reject a token
whose jti is_revoked() here, or whose token_type isn't "access" (a
refresh token must never work as a regular bearer token — it's only ever
redeemed at POST /auth/refresh).

There's no "was this jti ever legitimately issued" tracking here — the
JWT signature itself is that proof (only the server's secret key could
have produced a valid one), so recording issuance separately would be
bookkeeping nothing downstream ever needs to query.
"""

from __future__ import annotations

from legal_engine.core.models import WALEntry
from legal_engine.core.wal import WriteAheadLog

_REVOKED_EVENT_TYPE = "token_revoked"
_REDEEMED_EVENT_TYPE = "refresh_token_redeemed"


class TokenLedger:
    def __init__(self, wal: WriteAheadLog) -> None:
        self._wal = wal
        self._revoked_jtis: set[str] = set()
        self._redeemed_refresh_jtis: set[str] = set()
        for entry in wal.entries():
            self._index(entry)

    def _index(self, entry: WALEntry) -> None:
        jti = entry.payload.get("jti")
        if not jti:
            return
        if entry.event_type == _REVOKED_EVENT_TYPE:
            self._revoked_jtis.add(jti)
        elif entry.event_type == _REDEEMED_EVENT_TYPE:
            self._redeemed_refresh_jtis.add(jti)

    def revoke(self, jti: str, tenant_id: str, reason: str = "") -> None:
        """Idempotent at the WAL level the same way ConsentLedger's
        record_acceptance is: revoking an already-revoked jti is still
        recorded as its own fact rather than silently swallowed."""
        entry = self._wal.append(_REVOKED_EVENT_TYPE, {"jti": jti, "tenant_id": tenant_id, "reason": reason})
        self._index(entry)

    def is_revoked(self, jti: str) -> bool:
        return jti in self._revoked_jtis

    def redeem_refresh_token(self, jti: str, tenant_id: str) -> bool:
        """Marks a refresh-token jti as redeemed (single-use rotation).
        Returns False — and records nothing new — if it was already
        redeemed (reuse of a spent refresh token is a real signal worth
        rejecting, not silently allowing) or already revoked; True
        (after recording the redemption) otherwise."""
        if self.is_revoked(jti) or jti in self._redeemed_refresh_jtis:
            return False
        entry = self._wal.append(_REDEEMED_EVENT_TYPE, {"jti": jti, "tenant_id": tenant_id})
        self._index(entry)
        return True
