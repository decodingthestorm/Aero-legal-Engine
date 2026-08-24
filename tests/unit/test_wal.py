import pytest

from legal_engine.core.exceptions import WALIntegrityError
from legal_engine.core.key_signer import Ed25519FileKeySigner, generate_signing_key
from legal_engine.core.wal import GENESIS_HASH, WriteAheadLog


class TestWriteAheadLog:
    def test_empty_log_verifies(self):
        wal = WriteAheadLog(generate_signing_key())
        wal.verify()  # should not raise

    def test_first_entry_chains_to_genesis(self):
        wal = WriteAheadLog(generate_signing_key())
        entry = wal.append("statute_ingested", {"citation": "Sec. 1"})
        assert entry.sequence == 0
        assert entry.prev_hash == GENESIS_HASH

    def test_chain_links_sequential_entries(self):
        wal = WriteAheadLog(generate_signing_key())
        first = wal.append("statute_ingested", {"citation": "Sec. 1"})
        second = wal.append("statute_ingested", {"citation": "Sec. 2"})
        assert second.prev_hash == first.payload_hash
        assert second.sequence == 1

    def test_valid_chain_verifies(self):
        wal = WriteAheadLog(generate_signing_key())
        for i in range(5):
            wal.append("event", {"i": i})
        wal.verify()  # should not raise

    def test_tampered_payload_is_detected(self):
        wal = WriteAheadLog(generate_signing_key())
        wal.append("statute_ingested", {"citation": "Sec. 1"})
        wal.append("statute_ingested", {"citation": "Sec. 2"})

        wal.entries()[0].payload["citation"] = "Sec. 999 (forged)"

        with pytest.raises(WALIntegrityError, match="payload_hash"):
            wal.verify()

    def test_tampered_prev_hash_is_detected(self):
        wal = WriteAheadLog(generate_signing_key())
        wal.append("event", {"i": 0})
        wal.append("event", {"i": 1})

        wal.entries()[1].prev_hash = "f" * 96

        with pytest.raises(WALIntegrityError, match="prev_hash"):
            wal.verify()

    def test_forged_signature_is_detected(self):
        wal = WriteAheadLog(generate_signing_key())
        entry = wal.append("event", {"i": 0})
        entry.signature = "00" * 64  # syntactically valid hex, wrong signature

        with pytest.raises(WALIntegrityError, match="signature"):
            wal.verify()

    def test_verifying_with_a_different_public_key_fails(self):
        wal = WriteAheadLog(generate_signing_key())
        wal.append("event", {"i": 0})

        impostor = WriteAheadLog(generate_signing_key())
        impostor._entries = wal.entries()  # same entries, wrong keypair

        with pytest.raises(WALIntegrityError, match="signature"):
            impostor.verify()

    def test_persists_and_reloads_from_disk(self, tmp_path):
        key = generate_signing_key()
        wal_path = tmp_path / "wal.jsonl"

        wal = WriteAheadLog(key, path=wal_path)
        wal.append("statute_ingested", {"citation": "Sec. 1"})
        wal.append("statute_ingested", {"citation": "Sec. 2"})

        reloaded = WriteAheadLog(key, path=wal_path)
        assert len(reloaded.entries()) == 2
        assert [e.payload["citation"] for e in reloaded.entries()] == ["Sec. 1", "Sec. 2"]
        reloaded.verify()

    def test_reload_still_detects_tampering_after_persistence(self, tmp_path):
        key = generate_signing_key()
        wal_path = tmp_path / "wal.jsonl"

        wal = WriteAheadLog(key, path=wal_path)
        wal.append("event", {"i": 0})

        # Tamper with the persisted file directly, as an attacker with disk access would.
        contents = wal_path.read_text(encoding="utf-8")
        tampered = contents.replace('"i":0', '"i":999')
        wal_path.write_text(tampered, encoding="utf-8")

        reloaded = WriteAheadLog(key, path=wal_path)
        with pytest.raises(WALIntegrityError, match="payload_hash"):
            reloaded.verify()


class TestEd25519FileKeySignerLoadOrCreate:
    def test_generates_and_persists_a_key_when_none_exists(self, tmp_path):
        key_path = tmp_path / "signing_key.bin"
        assert not key_path.exists()

        Ed25519FileKeySigner.load_or_create(key_path)

        assert key_path.exists()
        assert len(key_path.read_bytes()) == 32  # raw Ed25519 private key

    def test_reloading_returns_the_same_key(self, tmp_path):
        key_path = tmp_path / "signing_key.bin"
        first = Ed25519FileKeySigner.load_or_create(key_path)
        second = Ed25519FileKeySigner.load_or_create(key_path)

        assert first.public_key_bytes == second.public_key_bytes

    def test_entries_signed_before_a_restart_still_verify_after(self, tmp_path):
        """The actual property this exists for: a WAL reloaded across a
        simulated process restart, using the persisted key, must still
        verify everything it signed before that restart. Regenerating a
        random key on every startup (the pre-existing generate_signing_key
        alone) would break this."""
        key_path = tmp_path / "signing_key.bin"
        wal_path = tmp_path / "audit.jsonl"

        first_run_signer = Ed25519FileKeySigner.load_or_create(key_path)
        first_run = WriteAheadLog(first_run_signer, path=wal_path)
        first_run.append("legal_disclaimer_accepted", {"tenant_id": "tenant-a"})

        second_run_signer = Ed25519FileKeySigner.load_or_create(key_path)
        second_run = WriteAheadLog(second_run_signer, path=wal_path)
        second_run.verify()  # should not raise

    def test_different_paths_get_independent_keys(self, tmp_path):
        signer_a = Ed25519FileKeySigner.load_or_create(tmp_path / "a.bin")
        signer_b = Ed25519FileKeySigner.load_or_create(tmp_path / "b.bin")

        assert signer_a.public_key_bytes != signer_b.public_key_bytes
