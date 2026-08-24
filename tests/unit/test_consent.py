import pytest

from legal_engine.compliance.consent import DISCLAIMER_VERSION, ConsentLedger
from legal_engine.core.exceptions import WALIntegrityError
from legal_engine.core.wal import WriteAheadLog, generate_signing_key

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


@pytest.fixture
def wal() -> WriteAheadLog:
    return WriteAheadLog(generate_signing_key())


@pytest.fixture
def ledger(wal) -> ConsentLedger:
    return ConsentLedger(wal)


class TestConsentLedger:
    def test_unaccepted_tenant_has_not_accepted(self, ledger):
        assert ledger.has_accepted_current_disclaimer(TENANT_A) is False
        assert ledger.latest_acceptance(TENANT_A) is None

    def test_accepting_makes_it_true(self, ledger):
        ledger.record_acceptance(TENANT_A, subject="test-client-a")
        assert ledger.has_accepted_current_disclaimer(TENANT_A) is True

    def test_acceptance_does_not_leak_across_tenants(self, ledger):
        ledger.record_acceptance(TENANT_A, subject="test-client-a")
        assert ledger.has_accepted_current_disclaimer(TENANT_B) is False

    def test_record_acceptance_returns_the_record(self, ledger):
        record = ledger.record_acceptance(TENANT_A, subject="test-client-a")
        assert record.tenant_id == TENANT_A
        assert record.subject == "test-client-a"
        assert record.disclaimer_version == DISCLAIMER_VERSION

    def test_latest_acceptance_carries_the_wal_sequence_back_reference(self, wal, ledger):
        ledger.record_acceptance(TENANT_A, subject="test-client-a")
        [entry] = wal.entries()

        record = ledger.latest_acceptance(TENANT_A)
        assert record.wal_sequence == entry.sequence

    def test_re_accepting_updates_the_index_to_the_newer_entry(self, wal, ledger):
        ledger.record_acceptance(TENANT_A, subject="first-login")
        ledger.record_acceptance(TENANT_A, subject="second-login")

        record = ledger.latest_acceptance(TENANT_A)
        assert record.subject == "second-login"
        assert record.wal_sequence == 1  # the second WAL entry, not the first

    def test_the_underlying_wal_still_has_both_entries(self, wal, ledger):
        """record_acceptance is documented as non-deduplicating at the WAL
        level — a repeat acceptance is its own fact, even though the index
        only tracks the latest."""
        ledger.record_acceptance(TENANT_A, subject="first-login")
        ledger.record_acceptance(TENANT_A, subject="second-login")
        assert len(wal.entries()) == 2

    def test_acceptance_is_tamper_evident(self, wal, ledger):
        """The whole point of recording this in the WAL rather than a plain
        table: forging or backdating an acceptance after the fact is
        detectable the same way forging any other WAL entry is."""
        ledger.record_acceptance(TENANT_A, subject="test-client-a")
        wal.verify()  # should not raise

        wal.entries()[0].payload["tenant_id"] = TENANT_B  # forge it onto tenant B
        with pytest.raises(WALIntegrityError, match="payload_hash"):
            wal.verify()

    def test_other_wal_entries_do_not_count_as_acceptance(self, wal, ledger):
        wal.append("statute_ingested", {"tenant_id": TENANT_A, "disclaimer_version": DISCLAIMER_VERSION})
        assert ledger.has_accepted_current_disclaimer(TENANT_A) is False


class TestConsentLedgerReplay:
    """The index must be exactly re-derivable from the WAL alone — the
    property that actually justifies calling it a "projection" rather than
    a second source of truth. Constructing a fresh ConsentLedger over a WAL
    that already has entries (the real startup case, after a restart) must
    reproduce the same state a ledger that was live for every one of those
    writes would have."""

    def test_replaying_an_existing_wal_reconstructs_accepted_state(self):
        wal = WriteAheadLog(generate_signing_key())
        original_ledger = ConsentLedger(wal)
        original_ledger.record_acceptance(TENANT_A, subject="test-client-a")

        replayed_ledger = ConsentLedger(wal)  # simulates a fresh process restart
        assert replayed_ledger.has_accepted_current_disclaimer(TENANT_A) is True

    def test_replay_reconstructs_the_correct_wal_sequence(self):
        wal = WriteAheadLog(generate_signing_key())
        wal.append("statute_ingested", {"citation": "Sec. 1"})  # unrelated earlier entry
        original_ledger = ConsentLedger(wal)
        original_ledger.record_acceptance(TENANT_A, subject="test-client-a")

        replayed_ledger = ConsentLedger(wal)
        record = replayed_ledger.latest_acceptance(TENANT_A)
        assert record.wal_sequence == 1  # the second entry (index 0 was unrelated)

    def test_replay_keeps_only_the_latest_acceptance_per_tenant(self):
        wal = WriteAheadLog(generate_signing_key())
        original_ledger = ConsentLedger(wal)
        original_ledger.record_acceptance(TENANT_A, subject="first-login")
        original_ledger.record_acceptance(TENANT_A, subject="second-login")

        replayed_ledger = ConsentLedger(wal)
        assert replayed_ledger.latest_acceptance(TENANT_A).subject == "second-login"

    def test_replay_reconstructs_multiple_tenants_independently(self):
        wal = WriteAheadLog(generate_signing_key())
        original_ledger = ConsentLedger(wal)
        original_ledger.record_acceptance(TENANT_A, subject="client-a")
        original_ledger.record_acceptance(TENANT_B, subject="client-b")

        replayed_ledger = ConsentLedger(wal)
        assert replayed_ledger.has_accepted_current_disclaimer(TENANT_A) is True
        assert replayed_ledger.has_accepted_current_disclaimer(TENANT_B) is True
        assert replayed_ledger.latest_acceptance(TENANT_A).subject == "client-a"
        assert replayed_ledger.latest_acceptance(TENANT_B).subject == "client-b"
