"""SHA-384 / Ed25519 cryptographic append-only write-ahead log.

Every entry is hash-chained to the one before it: ``payload_hash`` is a
SHA-384 digest over the entry's sequence number, its predecessor's hash,
and its own event type/payload/timestamp. Changing any past entry changes
its hash, which changes every subsequent entry's hash — tampering anywhere
in the chain is detectable from any later point, not just at the tampered
entry. Each entry is additionally signed with Ed25519 over its own
``payload_hash``, so an attacker with write access to the log file can't
even recompute a consistent chain without the private key.

Unlike knowledge_graph's Neo4j/Qdrant/sentence-transformers backends, there
isn't a meaningful "lightweight test double" for a cryptographic audit
log — a WAL that skips signing isn't a smaller version of this feature,
it's a different feature that doesn't provide the guarantee the WAL exists
for. So `cryptography` is a core dependency, not a lazy-imported optional
backend.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from legal_engine.core.exceptions import WALIntegrityError
from legal_engine.core.models import WALEntry

GENESIS_HASH = "0" * 96  # SHA-384 digests are 48 bytes = 96 hex chars


def generate_signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def load_or_create_signing_key(path: Path) -> Ed25519PrivateKey:
    """Loads the Ed25519 private key raw-bytes-encoded at ``path`` if it
    exists, otherwise generates a fresh one and persists it there.

    The WAL's signatures are only meaningful across process restarts if the
    same key signs every entry — regenerating a random key on every startup
    (what every caller of ``generate_signing_key()`` before this did) would
    mean every previously-signed entry fails ``verify()`` against the new
    public key the instant the process restarts, defeating the point of a
    durable audit log.

    The key is written to disk unencrypted. That's consistent with this
    codebase's other plaintext-default secrets (``settings.jwt_secret``,
    ``settings.api_client_secret`` — see their "change-me-in-production"
    defaults), not a gap unique to this file: a real deployment wants this
    in a proper secrets manager/KMS, not a bare file next to the audit log
    it signs.
    """
    if path.exists():
        return Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    key = generate_signing_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            encoding=Encoding.Raw, format=PrivateFormat.Raw, encryption_algorithm=NoEncryption()
        )
    )
    return key


def _compute_payload_hash(
    sequence: int, prev_hash: str, event_type: str, payload: dict, timestamp: datetime
) -> str:
    canonical = json.dumps(
        {
            "sequence": sequence,
            "prev_hash": prev_hash,
            "event_type": event_type,
            "payload": payload,
            "timestamp": timestamp.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha384(canonical.encode("utf-8")).hexdigest()


class WriteAheadLog:
    """An in-process, hash-chained, Ed25519-signed append-only log.

    Entries are held in memory and, if `path` is given, also persisted as
    JSON Lines (one WALEntry per line) — appended to on every ``append()``
    call and replayed on construction if the file already exists.
    """

    def __init__(self, private_key: Ed25519PrivateKey, path: Path | None = None) -> None:
        self._private_key = private_key
        self._public_key: Ed25519PublicKey = private_key.public_key()
        self._entries: list[WALEntry] = []
        self._path = path
        if path is not None and path.exists():
            self._load(path)

    def append(self, event_type: str, payload: dict) -> WALEntry:
        sequence = len(self._entries)
        prev_hash = self._entries[-1].payload_hash if self._entries else GENESIS_HASH
        timestamp = datetime.now(UTC)
        payload_hash = _compute_payload_hash(sequence, prev_hash, event_type, payload, timestamp)
        signature = self._private_key.sign(bytes.fromhex(payload_hash)).hex()

        entry = WALEntry(
            sequence=sequence,
            prev_hash=prev_hash,
            payload_hash=payload_hash,
            signature=signature,
            event_type=event_type,
            payload=payload,
            timestamp=timestamp,
        )
        self._entries.append(entry)
        if self._path is not None:
            self._persist(entry)
        return entry

    def verify(self) -> None:
        """Replays the whole chain. Raises WALIntegrityError on the first
        hash-chain break or invalid signature found."""
        expected_prev = GENESIS_HASH
        for entry in self._entries:
            if entry.prev_hash != expected_prev:
                raise WALIntegrityError(
                    f"Entry {entry.sequence}: prev_hash does not match the preceding "
                    "entry's payload_hash — the chain has been tampered with or reordered"
                )

            recomputed = _compute_payload_hash(
                entry.sequence, entry.prev_hash, entry.event_type, entry.payload, entry.timestamp
            )
            if recomputed != entry.payload_hash:
                raise WALIntegrityError(
                    f"Entry {entry.sequence}: payload_hash does not match its recomputed "
                    "hash — the entry's content has been altered after signing"
                )

            try:
                self._public_key.verify(bytes.fromhex(entry.signature), bytes.fromhex(entry.payload_hash))
            except InvalidSignature as exc:
                raise WALIntegrityError(
                    f"Entry {entry.sequence}: Ed25519 signature does not verify"
                ) from exc

            expected_prev = entry.payload_hash

    def entries(self) -> list[WALEntry]:
        return list(self._entries)

    def _persist(self, entry: WALEntry) -> None:
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def _load(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._entries.append(WALEntry.model_validate_json(line))
