"""Per-token revocation and refresh-token redemption, tracked in the same
WAL-backed-projection shape as compliance/consent.py's ConsentLedger: the
WAL is the sole source of truth, this is an O(1) index over it, exactly
re-derivable by replaying wal.entries() from scratch. Kept alongside
ConsentLedger rather than in a new package, for the identical reason —
this is another O(1) index over WAL-recorded trust facts, not a
conceptually different kind of thing.

Every issued token (api/security.py's create_token) now carries a jti
(unique per token, not per user — sub alone can't identify *which* token
to revoke), a token_type claim ("access"/"refresh"/etc), and a family_id
shared by an access+refresh pair issued together and carried forward
through every POST /auth/refresh rotation. api/dependencies.py's
require_auth/get_current_tenant reject a token whose jti is_revoked(), or
whose family_id is_family_revoked(), or whose token_type isn't "access".

A single jti's revocation isn't enough to actually kill a hijacked
session: if an attacker steals a refresh token and redeems it, the victim
still holds the *previous* access token from their own legitimate
rotation, which stays valid on jti-revocation alone. Reusing an already-
redeemed refresh token (redeem_refresh_token detects this) instead
revokes the whole family_id — every token, past and future, that shares
it — which is what actually invalidates the sibling access token too,
not just the one reused refresh token.

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
_FAMILY_REVOKED_EVENT_TYPE = "token_family_revoked"


class TokenLedger:
    def __init__(self, wal: WriteAheadLog) -> None:
        self._wal = wal
        self._revoked_jtis: set[str] = set()
        self._redeemed_refresh_jtis: set[str] = set()
        self._revoked_families: set[str] = set()
        for entry in wal.entries():
            self._index(entry)

    def _index(self, entry: WALEntry) -> None:
        if entry.event_type == _FAMILY_REVOKED_EVENT_TYPE:
            family_id = entry.payload.get("family_id")
            if family_id:
                self._revoked_families.add(family_id)
            return

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

    def revoke_family(self, family_id: str, tenant_id: str, reason: str = "") -> None:
        """Revokes every token — issued or yet to be issued — that shares
        this family_id. See the module docstring for why a single jti's
        revocation can't actually kill a hijacked session on its own."""
        entry = self._wal.append(
            _FAMILY_REVOKED_EVENT_TYPE, {"family_id": family_id, "tenant_id": tenant_id, "reason": reason}
        )
        self._index(entry)

    def is_family_revoked(self, family_id: str) -> bool:
        return family_id in self._revoked_families

    def redeem_refresh_token(self, jti: str, tenant_id: str, family_id: str) -> bool:
        """Marks a refresh-token jti as redeemed (single-use rotation).

        Returns False if the jti (or its family) is already revoked. If
        the jti was already *redeemed* — someone is reusing a spent
        refresh token, a real theft signal — this also revokes the whole
        family (see revoke_family) rather than just failing this one
        request, since the legitimate holder's already-rotated tokens are
        exactly what a real attacker's reuse attempt would be racing
        against. Returns True (after recording the redemption) only on a
        genuine first use.
        """
        if self.is_revoked(jti) or self.is_family_revoked(family_id):
            return False
        if jti in self._redeemed_refresh_jtis:
            self.revoke_family(family_id, tenant_id, reason="refresh token reuse detected")
            return False
        entry = self._wal.append(
            _REDEEMED_EVENT_TYPE, {"jti": jti, "tenant_id": tenant_id, "family_id": family_id}
        )
        self._index(entry)
        return True
