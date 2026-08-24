"""Settings-driven factory for the WAL's KeySigner, mirroring
knowledge_graph/factory.py's pattern for the graph/vector/embedder
backends: callers (api/main.py's lifespan) don't need to know which
signer backend they're getting, just call the factory.

Selecting "aws_kms"/"vault_transit" without the `kms` install extra
actually installed doesn't fail here — it fails inside
AwsKmsKeySigner/VaultTransitKeySigner's own lazily-imported constructor,
with a message naming the exact `pip install` needed. Same reasoning as
knowledge_graph/factory.py: a clearer error at the point of actual use
beats a vague one here.
"""

from __future__ import annotations

from pathlib import Path

from legal_engine.core.config import settings
from legal_engine.core.key_signer import (
    AwsKmsKeySigner,
    Ed25519FileKeySigner,
    KeySigner,
    VaultTransitKeySigner,
)


def build_key_signer() -> KeySigner:
    if settings.wal_signer_backend == "aws_kms":
        return AwsKmsKeySigner(key_id=settings.wal_kms_key_id)
    if settings.wal_signer_backend == "vault_transit":
        return VaultTransitKeySigner(
            key_name=settings.wal_vault_key_name,
            vault_url=settings.wal_vault_url,
            vault_token=settings.wal_vault_token or None,
        )
    return Ed25519FileKeySigner.load_or_create(Path(settings.wal_path) / "signing_key.bin")
