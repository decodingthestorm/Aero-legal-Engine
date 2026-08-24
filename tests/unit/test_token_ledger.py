import pytest

from legal_engine.compliance.token_ledger import TokenLedger
from legal_engine.core.exceptions import WALIntegrityError
from legal_engine.core.key_signer import generate_signing_key
from legal_engine.core.wal import WriteAheadLog

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
FAMILY_A = "family-a"
FAMILY_B = "family-b"
SUBJECT_A = "alice@example.com"
SUBJECT_B = "bob@example.com"


@pytest.fixture
def wal() -> WriteAheadLog:
    return WriteAheadLog(generate_signing_key())


@pytest.fixture
def ledger(wal) -> TokenLedger:
    return TokenLedger(wal)


class TestRevocation:
    def test_unrevoked_jti_is_not_revoked(self, ledger):
        assert ledger.is_revoked("some-jti") is False

    def test_revoking_makes_it_true(self, ledger):
        ledger.revoke("jti-1", TENANT_A)
        assert ledger.is_revoked("jti-1") is True

    def test_revocation_does_not_affect_other_jtis(self, ledger):
        ledger.revoke("jti-1", TENANT_A)
        assert ledger.is_revoked("jti-2") is False

    def test_revoking_twice_is_idempotent_but_recorded_both_times(self, wal, ledger):
        ledger.revoke("jti-1", TENANT_A, reason="first")
        ledger.revoke("jti-1", TENANT_A, reason="second")
        assert ledger.is_revoked("jti-1") is True
        assert len(wal.entries()) == 2

    def test_revocation_is_tamper_evident(self, wal, ledger):
        ledger.revoke("jti-1", TENANT_A)
        wal.verify()  # should not raise

        wal.entries()[0].payload["jti"] = "jti-2"  # forge the revocation onto a different jti
        with pytest.raises(WALIntegrityError, match="payload_hash"):
            wal.verify()


class TestRefreshTokenRedemption:
    def test_redeeming_an_unused_token_succeeds(self, ledger):
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A) is True

    def test_redeeming_the_same_token_twice_fails_the_second_time(self, ledger):
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A) is True
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A) is False

    def test_a_revoked_jti_cannot_be_redeemed(self, ledger):
        ledger.revoke("refresh-jti-1", TENANT_A)
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A) is False

    def test_redemption_does_not_affect_other_jtis(self, ledger):
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)
        assert ledger.redeem_refresh_token("refresh-jti-2", TENANT_A, FAMILY_A) is True

    def test_a_family_revoked_token_cannot_be_redeemed(self, ledger):
        ledger.revoke_family(FAMILY_A, TENANT_A)
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A) is False


class TestFamilyRevocationOnReuse:
    """The actual point of family_id existing: a single jti's revocation
    isn't enough to kill a hijacked session (the victim's already-rotated
    sibling access token would stay valid on jti-revocation alone) — reuse
    of a spent refresh token has to cascade to the whole family."""

    def test_first_redemption_does_not_revoke_the_family(self, ledger):
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)
        assert ledger.is_family_revoked(FAMILY_A) is False

    def test_reuse_revokes_the_whole_family(self, ledger):
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)  # reuse
        assert ledger.is_family_revoked(FAMILY_A) is True

    def test_reuse_in_one_family_does_not_revoke_a_different_family(self, ledger):
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)  # reuse in FAMILY_A
        assert ledger.is_family_revoked(FAMILY_B) is False

    def test_family_revocation_blocks_a_different_jti_in_the_same_family(self, ledger):
        """The real cascade property: revoking the family blocks *every*
        jti tagged with it, not just the one that was reused."""
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)  # reuse -> revokes FAMILY_A
        assert ledger.redeem_refresh_token("refresh-jti-2", TENANT_A, FAMILY_A) is False

    def test_explicit_family_revocation_is_tamper_evident(self, wal, ledger):
        ledger.revoke_family(FAMILY_A, TENANT_A)
        wal.verify()  # should not raise

        wal.entries()[0].payload["family_id"] = FAMILY_B  # forge the revocation onto a different family
        with pytest.raises(WALIntegrityError, match="payload_hash"):
            wal.verify()


class TestSessionTrackingAndCascadeRevocation:
    """record_session_started / revoke_all_sessions_for_subject: the
    mechanism a password reset (or removing a member from a tenant) uses
    to kill *every* session a subject holds, not just one token at a
    time."""

    def test_subject_with_no_sessions_has_nothing_to_revoke(self, ledger):
        ledger.revoke_all_sessions_for_subject(SUBJECT_A, TENANT_A)  # should not raise
        assert ledger.is_family_revoked(FAMILY_A) is False

    def test_revoking_kills_the_tracked_session(self, ledger):
        ledger.record_session_started(SUBJECT_A, TENANT_A, FAMILY_A)
        ledger.revoke_all_sessions_for_subject(SUBJECT_A, TENANT_A)
        assert ledger.is_family_revoked(FAMILY_A) is True

    def test_revoking_kills_every_tracked_session_for_that_subject(self, ledger):
        ledger.record_session_started(SUBJECT_A, TENANT_A, FAMILY_A)
        ledger.record_session_started(SUBJECT_A, TENANT_A, FAMILY_B)
        ledger.revoke_all_sessions_for_subject(SUBJECT_A, TENANT_A)
        assert ledger.is_family_revoked(FAMILY_A) is True
        assert ledger.is_family_revoked(FAMILY_B) is True

    def test_revoking_one_subjects_sessions_does_not_touch_anothers(self, ledger):
        ledger.record_session_started(SUBJECT_A, TENANT_A, FAMILY_A)
        ledger.record_session_started(SUBJECT_B, TENANT_A, FAMILY_B)
        ledger.revoke_all_sessions_for_subject(SUBJECT_A, TENANT_A)
        assert ledger.is_family_revoked(FAMILY_A) is True
        assert ledger.is_family_revoked(FAMILY_B) is False

    def test_session_start_is_tamper_evident(self, wal, ledger):
        ledger.record_session_started(SUBJECT_A, TENANT_A, FAMILY_A)
        wal.verify()  # should not raise

        wal.entries()[0].payload["family_id"] = FAMILY_B  # forge onto a different family
        with pytest.raises(WALIntegrityError, match="payload_hash"):
            wal.verify()


class TestTokenLedgerReplay:
    """Same property compliance/consent.py's TestConsentLedgerReplay
    proves for ConsentLedger: the index must be exactly re-derivable from
    the WAL alone, so a fresh TokenLedger built over a WAL that already
    has entries (the real case after a process restart) reconstructs
    identical state to one that was live for every write."""

    def test_replay_reconstructs_revoked_state(self):
        wal = WriteAheadLog(generate_signing_key())
        TokenLedger(wal).revoke("jti-1", TENANT_A)

        replayed = TokenLedger(wal)
        assert replayed.is_revoked("jti-1") is True

    def test_replay_reconstructs_redeemed_refresh_token_state(self):
        wal = WriteAheadLog(generate_signing_key())
        TokenLedger(wal).redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)

        replayed = TokenLedger(wal)
        assert replayed.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A) is False  # already redeemed

    def test_replay_reconstructs_family_revoked_state(self):
        wal = WriteAheadLog(generate_signing_key())
        original = TokenLedger(wal)
        original.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)
        original.redeem_refresh_token("refresh-jti-1", TENANT_A, FAMILY_A)  # reuse -> revokes FAMILY_A

        replayed = TokenLedger(wal)
        assert replayed.is_family_revoked(FAMILY_A) is True

    def test_replay_reconstructs_multiple_tenants_independently(self):
        wal = WriteAheadLog(generate_signing_key())
        original = TokenLedger(wal)
        original.revoke("jti-a", TENANT_A)
        original.redeem_refresh_token("refresh-jti-b", TENANT_B, FAMILY_B)

        replayed = TokenLedger(wal)
        assert replayed.is_revoked("jti-a") is True
        assert replayed.redeem_refresh_token("refresh-jti-b", TENANT_B, FAMILY_B) is False

    def test_replay_reconstructs_tracked_sessions(self):
        wal = WriteAheadLog(generate_signing_key())
        original = TokenLedger(wal)
        original.record_session_started(SUBJECT_A, TENANT_A, FAMILY_A)
        original.record_session_started(SUBJECT_A, TENANT_A, FAMILY_B)

        replayed = TokenLedger(wal)
        replayed.revoke_all_sessions_for_subject(SUBJECT_A, TENANT_A)
        assert replayed.is_family_revoked(FAMILY_A) is True
        assert replayed.is_family_revoked(FAMILY_B) is True
