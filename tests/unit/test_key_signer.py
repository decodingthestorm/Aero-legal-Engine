"""Exercises core/key_signer.py.

Ed25519FileKeySigner is exercised for real (no mocking needed — it's the
default, always-available backend). AwsKmsKeySigner/VaultTransitKeySigner
are exercised against an injected mock client (unittest.mock), proving
this module's own request-shape/response-parsing logic is correct against
the real boto3/hvac API contracts (verified by introspecting the
installed packages when this was written — see key_signer.py's module
and class docstrings) — not proof that a real AWS account or Vault
instance behaves as assumed, which nothing in this environment can
provide.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from legal_engine.core.key_signer import (
    AwsKmsKeySigner,
    VaultTransitKeySigner,
    generate_signing_key,
)


class TestEd25519FileKeySigner:
    def test_sign_then_verify_roundtrips(self):
        signer = generate_signing_key()
        signature = signer.sign(b"some payload hash bytes")
        assert signer.verify(b"some payload hash bytes", signature) is True

    def test_verify_rejects_tampered_data(self):
        signer = generate_signing_key()
        signature = signer.sign(b"original")
        assert signer.verify(b"tampered", signature) is False

    def test_verify_rejects_wrong_signers_signature(self):
        signer_a = generate_signing_key()
        signer_b = generate_signing_key()
        signature = signer_a.sign(b"payload")
        assert signer_b.verify(b"payload", signature) is False

    def test_verify_rejects_garbage_signature_bytes(self):
        signer = generate_signing_key()
        assert signer.verify(b"payload", b"not a real signature") is False

    def test_public_key_bytes_is_stable_for_the_same_signer(self):
        signer = generate_signing_key()
        assert signer.public_key_bytes == signer.public_key_bytes

    def test_public_key_bytes_differs_across_signers(self):
        signer_a = generate_signing_key()
        signer_b = generate_signing_key()
        assert signer_a.public_key_bytes != signer_b.public_key_bytes


class TestAwsKmsKeySigner:
    """Verified against boto3 1.43.78's actual KMS service model (field
    names, the ED25519_SHA_512/ECC_NIST_EDWARDS25519 algorithm/key-spec
    pair, and the documented SignatureValid-vs-KMSInvalidSignatureException
    contract for Verify) — see key_signer.py's AwsKmsKeySigner docstring."""

    def _client_with_signature_exception_class(self) -> MagicMock:
        """A real boto3 KMS client exposes its service exceptions as
        attributes of client.exceptions (e.g.
        client.exceptions.KMSInvalidSignatureException) — a dynamically
        generated class per client instance. Reproduced here as a real
        Exception subclass so `except self._client.exceptions.
        KMSInvalidSignatureException` in the code under test behaves
        identically against this mock."""
        client = MagicMock()
        client.exceptions.KMSInvalidSignatureException = type(
            "KMSInvalidSignatureException", (Exception,), {}
        )
        return client

    def test_sign_calls_kms_with_the_correct_request_shape(self):
        client = self._client_with_signature_exception_class()
        client.sign.return_value = {"Signature": b"raw-signature-bytes"}

        signer = AwsKmsKeySigner(key_id="arn:aws:kms:us-east-1:123456789012:key/abc", client=client)
        result = signer.sign(b"payload-hash-bytes")

        assert result == b"raw-signature-bytes"
        client.sign.assert_called_once_with(
            KeyId="arn:aws:kms:us-east-1:123456789012:key/abc",
            Message=b"payload-hash-bytes",
            MessageType="RAW",
            SigningAlgorithm="ED25519_SHA_512",
        )

    def test_verify_returns_true_on_a_valid_signature(self):
        client = self._client_with_signature_exception_class()
        client.verify.return_value = {"SignatureValid": True}

        signer = AwsKmsKeySigner(key_id="test-key", client=client)
        assert signer.verify(b"payload-hash-bytes", b"sig-bytes") is True
        client.verify.assert_called_once_with(
            KeyId="test-key",
            Message=b"payload-hash-bytes",
            MessageType="RAW",
            Signature=b"sig-bytes",
            SigningAlgorithm="ED25519_SHA_512",
        )

    def test_verify_returns_false_when_kms_raises_invalid_signature(self):
        """Per AWS's own Verify documentation: an invalid signature is
        reported by *raising* KMSInvalidSignatureException, not by
        returning SignatureValid: False — see the module docstring for
        the exact quoted text this was verified against."""
        client = self._client_with_signature_exception_class()
        client.verify.side_effect = client.exceptions.KMSInvalidSignatureException("bad signature")

        signer = AwsKmsKeySigner(key_id="test-key", client=client)
        assert signer.verify(b"payload-hash-bytes", b"forged-sig") is False

    def test_verify_lets_other_exceptions_propagate(self):
        """A permissions/network/throttling error is a real failure, not
        "this signature is forged" — must not be silently swallowed into
        False the way an actual invalid signature is."""
        client = self._client_with_signature_exception_class()
        client.verify.side_effect = RuntimeError("network timeout")

        signer = AwsKmsKeySigner(key_id="test-key", client=client)
        with pytest.raises(RuntimeError, match="network timeout"):
            signer.verify(b"payload-hash-bytes", b"sig-bytes")

    def test_fails_closed_with_install_hint_when_boto3_unavailable(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked_import)

        with pytest.raises(ImportError, match="pip install -e '.\\[kms\\]'"):
            AwsKmsKeySigner(key_id="test-key")


class TestVaultTransitKeySigner:
    """Verified against hvac 2.4.0's actual
    secrets.transit.sign_data/verify_signed_data method signatures and
    docstrings (hash_input must be pre-base64-encoded by the caller,
    response shape is response["data"][...]) — see key_signer.py's
    VaultTransitKeySigner docstring."""

    def test_sign_base64_encodes_the_input_and_returns_the_versioned_signature(self):
        client = MagicMock()
        client.secrets.transit.sign_data.return_value = {
            "data": {"signature": "vault:v1:abc123==", "key_version": 1}
        }

        signer = VaultTransitKeySigner(key_name="legal-engine-wal", client=client)
        result = signer.sign(b"payload-hash-bytes")

        assert result == b"vault:v1:abc123=="
        client.secrets.transit.sign_data.assert_called_once()
        _, kwargs = client.secrets.transit.sign_data.call_args
        assert kwargs["name"] == "legal-engine-wal"
        import base64

        assert base64.b64decode(kwargs["hash_input"]) == b"payload-hash-bytes"

    def test_verify_passes_the_full_versioned_signature_string_back(self):
        client = MagicMock()
        client.secrets.transit.verify_signed_data.return_value = {"data": {"valid": True}}

        signer = VaultTransitKeySigner(key_name="legal-engine-wal", client=client)
        result = signer.verify(b"payload-hash-bytes", b"vault:v1:abc123==")

        assert result is True
        _, kwargs = client.secrets.transit.verify_signed_data.call_args
        assert kwargs["name"] == "legal-engine-wal"
        assert kwargs["signature"] == "vault:v1:abc123=="

    def test_verify_returns_false_for_an_invalid_signature(self):
        client = MagicMock()
        client.secrets.transit.verify_signed_data.return_value = {"data": {"valid": False}}

        signer = VaultTransitKeySigner(key_name="legal-engine-wal", client=client)
        assert signer.verify(b"payload-hash-bytes", b"vault:v1:forged==") is False

    def test_fails_closed_with_install_hint_when_hvac_unavailable(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "hvac":
                raise ImportError("No module named 'hvac'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked_import)

        with pytest.raises(ImportError, match="pip install -e '.\\[kms\\]'"):
            VaultTransitKeySigner(key_name="legal-engine-wal")
