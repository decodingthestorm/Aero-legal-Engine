import pytest

from legal_engine.compliance.consent import (
    DISCLAIMER_VERSION,
    has_accepted_current_disclaimer,
    record_acceptance,
)
from legal_engine.core.exceptions import WALIntegrityError
from legal_engine.core.wal import WriteAheadLog, generate_signing_key

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


@pytest.fixture
def wal() -> WriteAheadLog:
    return WriteAheadLog(generate_signing_key())


class TestConsent:
    def test_unaccepted_tenant_has_not_accepted(self, wal):
        assert has_accepted_current_disclaimer(wal, TENANT_A) is False

    def test_accepting_makes_it_true(self, wal):
        record_acceptance(wal, TENANT_A, subject="test-client-a")
        assert has_accepted_current_disclaimer(wal, TENANT_A) is True

    def test_acceptance_does_not_leak_across_tenants(self, wal):
        record_acceptance(wal, TENANT_A, subject="test-client-a")
        assert has_accepted_current_disclaimer(wal, TENANT_B) is False

    def test_acceptance_records_the_subject_and_version(self, wal):
        record_acceptance(wal, TENANT_A, subject="test-client-a")
        [entry] = wal.entries()
        assert entry.event_type == "legal_disclaimer_accepted"
        assert entry.payload["tenant_id"] == TENANT_A
        assert entry.payload["subject"] == "test-client-a"
        assert entry.payload["disclaimer_version"] == DISCLAIMER_VERSION

    def test_acceptance_is_tamper_evident(self, wal):
        """The whole point of recording this in the WAL rather than a plain
        table: forging or backdating an acceptance after the fact is
        detectable the same way forging any other WAL entry is."""
        record_acceptance(wal, TENANT_A, subject="test-client-a")
        wal.verify()  # should not raise

        wal.entries()[0].payload["tenant_id"] = TENANT_B  # forge it onto tenant B
        with pytest.raises(WALIntegrityError, match="payload_hash"):
            wal.verify()

    def test_other_wal_entries_do_not_count_as_acceptance(self, wal):
        wal.append("statute_ingested", {"tenant_id": TENANT_A, "disclaimer_version": DISCLAIMER_VERSION})
        assert has_accepted_current_disclaimer(wal, TENANT_A) is False
