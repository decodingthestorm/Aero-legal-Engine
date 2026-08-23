"""SHA-384 / Ed25519 cryptographic append-only write-ahead log. Not yet implemented — Phase 4.

Planned: append-only WALEntry records (see core/models.py) chained by
SHA-384 hash of the previous entry, each signed with Ed25519
(cryptography.hazmat.primitives.asymmetric.ed25519), verified on read via
WALIntegrityError on any hash-chain or signature mismatch.
"""
