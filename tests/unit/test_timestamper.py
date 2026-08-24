"""Exercises the RFC 3161 client against synthetic DER.

There's no Time-Stamp Authority to reach in this environment, but unlike
the KMS/Vault signers — where the wire format belongs to AWS and Vault —
TSP's request and response structures are the standard itself, so they
can be built and torn down here for real. ``_FakeTsa`` below assembles a
genuine ``TimeStampResp``: a CMS ``SignedData`` whose encapsulated
content is a DER-encoded ``TSTInfo``, context-tagged the way the ASN.1
requires. The client parses actual bytes, not a mock object standing in
for them.

What that does *not* cover is a live TSA's behaviour or its signature —
see core/timestamper.py on why signature verification is deliberately out
of scope here rather than hand-rolled.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from legal_engine.core.timestamper import (
    LocalTimestamper,
    Rfc3161Timestamper,
    TimestampError,
    TimestampToken,
    _parse_generalized_time,
    anchor,
)

pyasn1 = pytest.importorskip("pyasn1", reason="the `tsp` extra is not installed")

from pyasn1.codec.der import decoder, encoder
from pyasn1.type import tag, univ, useful
from pyasn1_modules import rfc3161, rfc5652

_SHA384_OID = "2.16.840.1.101.3.4.2.2"
_SHA256_OID = "2.16.840.1.101.3.4.2.1"
_ID_CT_TSTINFO = "1.2.840.113549.1.9.16.1.4"
_ID_SIGNEDDATA = "1.2.840.113549.1.7.2"


class _FakeTsa:
    """Builds real DER TimeStampResp payloads. Each knob exists to drive
    one specific rejection path in parse_response."""

    def __init__(
        self,
        status: int = 0,
        gen_time: str = "20260824120000Z",
        serial: int = 42,
        policy: str = "1.2.3.4.1",
        hash_oid: str = _SHA384_OID,
        override_nonce: int | None = None,
        override_digest: bytes | None = None,
        omit_token: bool = False,
        content_type: str = _ID_SIGNEDDATA,
        encap_type: str = _ID_CT_TSTINFO,
    ) -> None:
        self.__dict__.update(locals())
        self.requests: list[bytes] = []

    def __call__(self, url: str, body: bytes, timeout: float) -> bytes:
        self.requests.append(body)
        request, _ = decoder.decode(body, asn1Spec=rfc3161.TimeStampReq())
        nonce = self.override_nonce if self.override_nonce is not None else int(request["nonce"])
        digest = self.override_digest or bytes(request["messageImprint"]["hashedMessage"])
        return self.build(nonce, digest)

    def build(self, nonce: int, digest: bytes) -> bytes:
        imprint = rfc3161.MessageImprint()
        imprint["hashAlgorithm"]["algorithm"] = univ.ObjectIdentifier(self.hash_oid)
        imprint["hashAlgorithm"]["parameters"] = encoder.encode(univ.Null(""))
        imprint["hashedMessage"] = univ.OctetString(digest)

        tst = rfc3161.TSTInfo()
        tst["version"] = 1
        tst["policy"] = univ.ObjectIdentifier(self.policy)
        tst["messageImprint"] = imprint
        tst["serialNumber"] = univ.Integer(self.serial)
        tst["genTime"] = useful.GeneralizedTime(self.gen_time)
        tst["nonce"] = univ.Integer(nonce)

        encap = rfc5652.EncapsulatedContentInfo()
        encap["eContentType"] = univ.ObjectIdentifier(self.encap_type)
        encap["eContent"] = univ.OctetString(encoder.encode(tst)).subtype(
            explicitTag=tag.Tag(tag.tagClassContext, tag.tagFormatSimple, 0)
        )
        signed = rfc5652.SignedData()
        signed["version"] = 3
        signed["digestAlgorithms"] = rfc5652.DigestAlgorithmIdentifiers()
        signed["encapContentInfo"] = encap
        signed["signerInfos"] = rfc5652.SignerInfos()

        response = rfc3161.TimeStampResp()
        response["status"]["status"] = rfc3161.PKIStatus(self.status)
        if not self.omit_token:
            token = rfc3161.TimeStampToken()
            token["contentType"] = univ.ObjectIdentifier(self.content_type)
            token["content"] = univ.Any(encoder.encode(signed)).subtype(
                explicitTag=tag.Tag(tag.tagClassContext, tag.tagFormatSimple, 0)
            )
            response["timeStampToken"] = token
        return encoder.encode(response)


def _client(tsa: _FakeTsa | None = None, **kwargs) -> Rfc3161Timestamper:
    return Rfc3161Timestamper(url="https://tsa.example/tsr", http_post=tsa, **kwargs)


class TestLocalTimestamper:
    def test_reports_itself_as_local_not_attested(self):
        """The whole point of the source field: a local stamp must be
        impossible to mistake for third-party attestation downstream."""
        token = LocalTimestamper().timestamp(b"payload")
        assert token.source == "local"
        assert token.der is None

    def test_digest_is_the_configured_algorithm(self):
        token = LocalTimestamper(hash_algorithm="sha384").timestamp(b"payload")
        assert token.digest == hashlib.sha384(b"payload").digest()

    def test_gen_time_is_utc_aware(self):
        assert LocalTimestamper().timestamp(b"x").gen_time.tzinfo is not None

    def test_rejects_an_unsupported_hash_algorithm(self):
        with pytest.raises(ValueError, match="unsupported hash algorithm"):
            LocalTimestamper(hash_algorithm="md5")


class TestRequestEncoding:
    def test_request_is_a_decodable_timestampreq(self):
        request_der, _ = _client().build_request(b"payload", nonce=12345)
        decoded, _ = decoder.decode(request_der, asn1Spec=rfc3161.TimeStampReq())
        assert int(decoded["version"]) == 1
        assert int(decoded["nonce"]) == 12345

    def test_imprint_is_the_sha384_of_the_data(self):
        request_der, digest = _client().build_request(b"payload", nonce=1)
        decoded, _ = decoder.decode(request_der, asn1Spec=rfc3161.TimeStampReq())
        assert digest == hashlib.sha384(b"payload").digest()
        assert bytes(decoded["messageImprint"]["hashedMessage"]) == digest
        assert str(decoded["messageImprint"]["hashAlgorithm"]["algorithm"]) == _SHA384_OID

    def test_hash_algorithm_is_configurable(self):
        request_der, digest = _client(hash_algorithm="sha256").build_request(b"payload", nonce=1)
        decoded, _ = decoder.decode(request_der, asn1Spec=rfc3161.TimeStampReq())
        assert digest == hashlib.sha256(b"payload").digest()
        assert str(decoded["messageImprint"]["hashAlgorithm"]["algorithm"]) == _SHA256_OID

    def test_requests_the_tsa_certificate(self):
        """certReq=True is what makes the retained token self-contained
        enough for the offline `openssl ts -verify` step."""
        request_der, _ = _client().build_request(b"payload", nonce=1)
        decoded, _ = decoder.decode(request_der, asn1Spec=rfc3161.TimeStampReq())
        assert bool(decoded["certReq"]) is True

    def test_each_call_uses_a_fresh_nonce(self):
        tsa = _FakeTsa()
        client = _client(tsa)
        client.timestamp(b"payload")
        client.timestamp(b"payload")
        nonces = [
            int(decoder.decode(r, asn1Spec=rfc3161.TimeStampReq())[0]["nonce"]) for r in tsa.requests
        ]
        assert nonces[0] != nonces[1]

    def test_rejects_an_unsupported_hash_algorithm(self):
        with pytest.raises(ValueError, match="unsupported hash algorithm"):
            _client(hash_algorithm="md5")


class TestSuccessfulTimestamp:
    def test_returns_an_attested_token(self):
        token = _client(_FakeTsa()).timestamp(b"payload")
        assert isinstance(token, TimestampToken)
        assert token.source == "tsa"
        assert token.digest == hashlib.sha384(b"payload").digest()

    def test_parses_gen_time_as_utc(self):
        token = _client(_FakeTsa(gen_time="20260824120000Z")).timestamp(b"payload")
        assert token.gen_time == datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)

    def test_parses_fractional_gen_time(self):
        token = _client(_FakeTsa(gen_time="20260824120000.500Z")).timestamp(b"payload")
        assert token.gen_time.microsecond == 500000

    def test_carries_serial_and_policy(self):
        token = _client(_FakeTsa(serial=99, policy="1.3.6.1.4.1.1")).timestamp(b"payload")
        assert token.serial_number == 99
        assert token.policy == "1.3.6.1.4.1.1"

    def test_retains_the_raw_der_for_offline_verification(self):
        """Signature verification happens elsewhere, so the bytes a real
        verifier needs have to survive the call."""
        token = _client(_FakeTsa()).timestamp(b"payload")
        assert token.der is not None
        decoded, _ = decoder.decode(token.der, asn1Spec=rfc3161.TimeStampResp())
        assert int(decoded["status"]["status"]) == 0

    def test_granted_with_mods_is_accepted(self):
        assert _client(_FakeTsa(status=1)).timestamp(b"payload").source == "tsa"


class TestRejectionPaths:
    """Every one of these must fail closed rather than return a token."""

    def test_rejected_status_raises(self):
        with pytest.raises(TimestampError, match="rejected"):
            _client(_FakeTsa(status=2)).timestamp(b"payload")

    def test_replayed_nonce_raises(self):
        """The anti-replay property: a recorded response must not validate
        against a later request."""
        with pytest.raises(TimestampError, match="nonce"):
            _client(_FakeTsa(override_nonce=999999)).timestamp(b"payload")

    def test_digest_mismatch_raises(self):
        """A TSA that stamped something other than what was submitted."""
        with pytest.raises(TimestampError, match="different digest"):
            _client(_FakeTsa(override_digest=b"\x00" * 48)).timestamp(b"payload")

    def test_wrong_hash_algorithm_raises(self):
        with pytest.raises(TimestampError, match="hash algorithm"):
            _client(_FakeTsa(hash_oid=_SHA256_OID)).timestamp(b"payload")

    def test_granted_but_missing_token_raises(self):
        with pytest.raises(TimestampError, match="no timeStampToken"):
            _client(_FakeTsa(omit_token=True)).timestamp(b"payload")

    def test_non_signeddata_content_type_raises(self):
        with pytest.raises(TimestampError, match="not CMS SignedData"):
            _client(_FakeTsa(content_type="1.2.840.113549.1.7.1")).timestamp(b"payload")

    def test_wrong_encapsulated_content_type_raises(self):
        with pytest.raises(TimestampError, match="id-ct-TSTInfo"):
            _client(_FakeTsa(encap_type="1.2.840.113549.1.7.1")).timestamp(b"payload")

    def test_garbage_response_raises(self):
        with pytest.raises(TimestampError, match="not a valid TimeStampResp"):
            _client(lambda url, body, timeout: b"not der at all").timestamp(b"payload")

class TestGeneralizedTimeParsing:
    """Exercised directly rather than through _FakeTsa: pyasn1's encoder
    refuses to *build* a GeneralizedTime without a "Z", so a malformed
    genTime can't be delivered by a synthetic TSA at all — only by a real
    one that ignores the profile."""

    def test_parses_the_compact_form(self):
        assert _parse_generalized_time("20260824120000Z") == datetime(
            2026, 8, 24, 12, 0, 0, tzinfo=UTC
        )

    def test_parses_fractional_seconds(self):
        parsed = _parse_generalized_time("20260824120000.250Z")
        assert parsed.microsecond == 250000
        assert parsed.tzinfo is UTC

    def test_rejects_a_non_utc_qualified_time(self):
        with pytest.raises(TimestampError, match="not UTC-qualified"):
            _parse_generalized_time("20260824120000")

    def test_rejects_an_offset_qualified_time(self):
        with pytest.raises(TimestampError, match="not UTC-qualified"):
            _parse_generalized_time("20260824120000+0200")

    def test_rejects_garbage(self):
        with pytest.raises(TimestampError, match="not a valid GeneralizedTime"):
            _parse_generalized_time("not-a-timeZ")


class _StubWal:
    def __init__(self, entries):
        self._entries = entries

    def entries(self):
        return self._entries


class _StubEntry:
    def __init__(self, payload_hash: str):
        self.payload_hash = payload_hash


class TestAnchor:
    def test_anchors_the_head_hash(self):
        """One token over the head attests the whole chain — entry N's
        hash transitively commits to everything before it."""
        head = "a" * 96
        wal = _StubWal([_StubEntry("b" * 96), _StubEntry(head)])
        token = anchor(wal, LocalTimestamper())
        assert token.digest == hashlib.sha384(head.encode("ascii")).digest()

    def test_empty_wal_anchors_nothing(self):
        assert anchor(_StubWal([]), LocalTimestamper()) is None

    def test_anchoring_works_through_a_real_tsa_client(self):
        wal = _StubWal([_StubEntry("c" * 96)])
        token = anchor(wal, _client(_FakeTsa()))
        assert token.source == "tsa"
        assert token.digest == hashlib.sha384(("c" * 96).encode("ascii")).digest()

    def test_anchoring_a_real_wal(self):
        """End-to-end against the actual WriteAheadLog rather than a stub,
        so a change to WALEntry's shape breaks this."""
        from legal_engine.core.key_signer import generate_signing_key
        from legal_engine.core.wal import WriteAheadLog

        wal = WriteAheadLog(generate_signing_key())
        wal.append("statute_ingested", {"citation": "Sec. 1"})
        wal.append("statute_ingested", {"citation": "Sec. 2"})

        token = anchor(wal, LocalTimestamper())
        expected = hashlib.sha384(wal.entries()[-1].payload_hash.encode("ascii")).digest()
        assert token.digest == expected
