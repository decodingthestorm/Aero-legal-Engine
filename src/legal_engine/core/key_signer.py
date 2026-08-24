"""KeySigner abstracts WAL entry signing behind ``sign()``/``verify()``, so
``WriteAheadLog`` (wal.py) doesn't need to know whether it's backed by a
local Ed25519 key file, AWS KMS, or HashiCorp Vault's Transit engine —
only that whatever implements this can sign a digest and later verify a
signature against it.

``Ed25519FileKeySigner`` is the default, always-available implementation:
exactly what ``WriteAheadLog`` used directly before this abstraction
existed (a raw ``Ed25519PrivateKey``), pulled out into its own class
purely so it conforms to the same interface a real KMS/HSM-backed signer
does.

``AwsKmsKeySigner`` and ``VaultTransitKeySigner`` are lazy-imported
optional backends (the ``kms`` install extra: boto3, hvac) matching every
other "real backend" in this codebase (knowledge_graph's
Neo4j/Qdrant/sentence-transformers, ingestion's Tesseract OCR,
refactoring's cvxpy). Both accept an already-constructed client via
dependency injection (``client=...``), which the Neo4j/Qdrant backends
don't offer — added specifically so their ``sign()``/``verify()`` request
shape and response parsing can be genuinely unit-tested against an
injected mock (tests/unit/test_key_signer.py), not just asserted to fail
closed with an install hint. Neither has been exercised against a real
AWS account or Vault instance, neither of which is available in this
environment; the request/response field names below were verified by
introspecting the installed boto3/hvac packages' actual service models
and method signatures (not from memory) — see each class's own docstring
for specifics and for what that verification does and doesn't establish.

A deployment picks exactly one KeySigner implementation for a WAL's
entire lifetime (matching every other backend-selection setting in this
codebase, e.g. graph_backend/vector_backend) — mixing signers within one
WAL's history is out of scope, and WriteAheadLog has no mechanism for it.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat


class KeySigner(Protocol):
    def sign(self, data: bytes) -> bytes: ...

    def verify(self, data: bytes, signature: bytes) -> bool: ...


def generate_signing_key() -> Ed25519FileKeySigner:
    """A fresh, ephemeral (not persisted to disk) signer — a new random
    Ed25519 keypair every call. For one whose key survives a process
    restart, use ``Ed25519FileKeySigner.load_or_create`` instead."""
    return Ed25519FileKeySigner(Ed25519PrivateKey.generate())


class Ed25519FileKeySigner:
    """The default KeySigner: a local Ed25519 keypair, optionally
    persisted unencrypted to disk via ``load_or_create``.

    The key is written to disk unencrypted when persisted. That's
    consistent with this codebase's other plaintext-default secrets
    (``settings.jwt_secret``, ``settings.api_client_secret`` — see their
    "change-me-in-production" defaults), not a gap unique to this class:
    a real deployment wants ``AwsKmsKeySigner``/``VaultTransitKeySigner``
    below, or a real HSM, not a bare key file next to the audit log it
    signs.
    """

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self._public_key: Ed25519PublicKey = private_key.public_key()

    def sign(self, data: bytes) -> bytes:
        return self._private_key.sign(data)

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            self._public_key.verify(signature, data)
            return True
        except InvalidSignature:
            return False

    @property
    def public_key_bytes(self) -> bytes:
        """Raw Ed25519 public key bytes — exposed for callers (tests,
        operational tooling) that need to compare "is this the same
        keypair" without reaching into private key material."""
        return self._public_key.public_bytes_raw()

    @classmethod
    def load_or_create(cls, path: Path) -> Ed25519FileKeySigner:
        """Loads the Ed25519 private key raw-bytes-encoded at ``path`` if
        it exists, otherwise generates a fresh one and persists it there.

        The WAL's signatures are only meaningful across process restarts
        if the same key signs every entry — regenerating a random key on
        every startup would mean every previously-signed entry fails
        ``verify()`` against the new public key the instant the process
        restarts, defeating the point of a durable audit log.
        """
        if path.exists():
            return cls(Ed25519PrivateKey.from_private_bytes(path.read_bytes()))
        signer = cls(Ed25519PrivateKey.generate())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            signer._private_key.private_bytes(
                encoding=Encoding.Raw, format=PrivateFormat.Raw, encryption_algorithm=NoEncryption()
            )
        )
        return signer


class AwsKmsKeySigner:
    """KeySigner backed by an AWS KMS asymmetric signing key
    (``kms:Sign``/``kms:Verify``). Requires the ``kms`` install extra
    (boto3) and a real KMS key ARN/alias with signing permission granted
    to whatever credentials boto3 resolves.

    Uses ``ED25519_SHA_512`` over an ``ECC_NIST_EDWARDS25519`` KMS key —
    matching Ed25519FileKeySigner's algorithm, not switching to RSA/ECDSA.
    (AWS KMS's asymmetric key spec support is broader than RSA/NIST-ECC
    alone; ``ECC_NIST_EDWARDS25519`` — Ed25519 — is a real, current
    ``KeySpec``, confirmed by introspecting botocore 1.43.78's actual KMS
    service model rather than assumed from general AWS familiarity.) The
    KMS key used with this class must actually be created with that key
    spec — this class doesn't create the key, only signs/verifies with
    whichever one ``key_id`` names.

    ``verify()``'s False-vs-exception split is deliberate, not a guess:
    per KMS's own ``Verify`` operation documentation (again read from the
    installed botocore package's embedded service docs, not memory) — "If
    the signature is verified, the value of the SignatureValid field in
    the response is True. If the signature verification fails, the Verify
    operation fails with a KMSInvalidSignatureException exception." So a
    genuinely invalid signature is caught and turned into ``False``; every
    other exception (permissions, network, wrong key, throttling) is left
    to propagate as a real error rather than being misreported as "this
    signature doesn't match."
    """

    def __init__(self, key_id: str, client: Any = None) -> None:
        if client is None:
            try:
                import boto3
            except Exception as exc:
                raise ImportError(
                    "AwsKmsKeySigner needs boto3, which failed to import "
                    f"({type(exc).__name__}: {exc}). Install it with "
                    "`pip install -e '.[kms]'`."
                ) from exc
            client = boto3.client("kms")
        self._key_id = key_id
        self._client = client

    def sign(self, data: bytes) -> bytes:
        response = self._client.sign(
            KeyId=self._key_id,
            Message=data,
            MessageType="RAW",
            SigningAlgorithm="ED25519_SHA_512",
        )
        return bytes(response["Signature"])

    def verify(self, data: bytes, signature: bytes) -> bool:
        try:
            response = self._client.verify(
                KeyId=self._key_id,
                Message=data,
                MessageType="RAW",
                Signature=signature,
                SigningAlgorithm="ED25519_SHA_512",
            )
        except self._client.exceptions.KMSInvalidSignatureException:
            return False
        return bool(response["SignatureValid"])


class VaultTransitKeySigner:
    """KeySigner backed by HashiCorp Vault's Transit secrets engine
    (``sign_data``/``verify_signed_data``). Requires the ``kms`` install
    extra (hvac) and a running, unsealed Vault instance with a Transit
    key already created — ``key_type="ed25519"``, matching
    Ed25519FileKeySigner's algorithm; this class doesn't create the key,
    only signs/verifies with whichever one ``key_name`` names.

    Vault Transit's sign/verify API is base64-and-string-based, not raw
    bytes: ``hash_input`` must be base64-encoded (hvac 2.4.0 does not
    encode it for you — confirmed by reading the installed package's own
    method docstring, not assumed), and a Transit signature is itself a
    string like ``"vault:v1:<base64>"`` — the ``"vault:v1:"`` prefix
    encodes the key version Vault needs to verify against, so the whole
    string must round-trip through ``sign()``/``verify()`` unchanged, not
    just the base64 portion. ``sign()`` still returns ``bytes`` and
    ``verify()`` still takes ``bytes``, to satisfy KeySigner — this class
    just ASCII-encodes/decodes that signature string at its own boundary
    rather than trying to extract "real" bytes out of a value that's
    fundamentally a versioned string in Vault's own API.
    """

    def __init__(
        self,
        key_name: str,
        client: Any = None,
        vault_url: str | None = None,
        vault_token: str | None = None,
    ) -> None:
        if client is None:
            try:
                import hvac
            except Exception as exc:
                raise ImportError(
                    "VaultTransitKeySigner needs hvac, which failed to import "
                    f"({type(exc).__name__}: {exc}). Install it with "
                    "`pip install -e '.[kms]'`."
                ) from exc
            client = hvac.Client(url=vault_url, token=vault_token)
        self._key_name = key_name
        self._client = client

    def sign(self, data: bytes) -> bytes:
        encoded_input = base64.b64encode(data).decode("ascii")
        response = self._client.secrets.transit.sign_data(name=self._key_name, hash_input=encoded_input)
        signature: str = response["data"]["signature"]
        return signature.encode("ascii")

    def verify(self, data: bytes, signature: bytes) -> bool:
        encoded_input = base64.b64encode(data).decode("ascii")
        response = self._client.secrets.transit.verify_signed_data(
            name=self._key_name, hash_input=encoded_input, signature=signature.decode("ascii")
        )
        return bool(response["data"]["valid"])
