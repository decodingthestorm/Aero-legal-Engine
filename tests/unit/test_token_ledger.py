import pytest

from legal_engine.compliance.token_ledger import TokenLedger
from legal_engine.core.exceptions import WALIntegrityError
from legal_engine.core.key_signer import generate_signing_key
from legal_engine.core.wal import WriteAheadLog

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


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
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A) is True

    def test_redeeming_the_same_token_twice_fails_the_second_time(self, ledger):
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A) is True
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A) is False

    def test_reuse_attempt_does_not_record_a_new_wal_entry(self, wal, ledger):
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A)
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A)  # reuse — should be a no-op
        assert len(wal.entries()) == 1

    def test_a_revoked_jti_cannot_be_redeemed(self, ledger):
        ledger.revoke("refresh-jti-1", TENANT_A)
        assert ledger.redeem_refresh_token("refresh-jti-1", TENANT_A) is False

    def test_redemption_does_not_affect_other_jtis(self, ledger):
        ledger.redeem_refresh_token("refresh-jti-1", TENANT_A)
        assert ledger.redeem_refresh_token("refresh-jti-2", TENANT_A) is True


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
        TokenLedger(wal).redeem_refresh_token("refresh-jti-1", TENANT_A)

        replayed = TokenLedger(wal)
        assert replayed.redeem_refresh_token("refresh-jti-1", TENANT_A) is False  # already redeemed

    def test_replay_reconstructs_multiple_tenants_independently(self):
        wal = WriteAheadLog(generate_signing_key())
        original = TokenLedger(wal)
        original.revoke("jti-a", TENANT_A)
        original.redeem_refresh_token("refresh-jti-b", TENANT_B)

        replayed = TokenLedger(wal)
        assert replayed.is_revoked("jti-a") is True
        assert replayed.redeem_refresh_token("refresh-jti-b", TENANT_B) is False
