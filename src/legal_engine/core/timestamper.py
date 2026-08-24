"""RFC 3161 trusted timestamping, behind the same Protocol-plus-default-
plus-lazy-real-backend shape as core/key_signer.py and
core/email_sender.py.

## What this is for

Every timestamp in this system is currently **self-asserted**:
``WriteAheadLog.append`` stamps ``datetime.now(UTC)`` from the machine's
own clock, signs it, and chains it. That makes the log tamper-*evident* —
you cannot alter an entry without breaking the chain — but it proves
nothing about *when* anything happened to anyone who doesn't already
trust the machine that wrote it. Someone who controls the host can
backdate the clock and produce a perfectly valid chain.

A Time-Stamp Authority closes that gap: it signs "I saw this digest at
this time," and its signature is what a third party actually checks. That
is a different property from the WAL's own signature, which only says
"this host wrote this."

## Anchoring, not per-entry stamping

``anchor`` below timestamps the WAL's *head hash*, not each entry. That
follows from the chain: entry N's ``payload_hash`` transitively commits
to every entry before it, so one token over the head attests the entire
log up to that point. Stamping every append would put a network round
trip on the hot path of every write, make the WAL unavailable whenever
the TSA is, and buy nothing the chain doesn't already give.

## What this verifies, and what it does not

``Rfc3161Timestamper.timestamp`` checks the response status, that the
returned nonce equals the one sent (anti-replay), that the returned
message imprint equals the digest sent (the TSA stamped *our* data), and
that the hash algorithm matches. Any mismatch raises — it fails closed.

It does **not** verify the TSA's signature over the token, or validate
its certificate chain. That is not an oversight to be fixed by trying
harder: ``cryptography`` 50.x exposes no CMS/PKCS#7 *verification* API at
all (only decrypt and certificate loading — checked, not assumed), and
hand-rolling CMS signature validation would be exactly the kind of
security code that should never be hand-rolled. So the full DER token is
retained on the returned ``TimestampToken`` and verification is an
explicit, separate step against a real trust store:

    openssl ts -verify -in token.tsr -data anchored.bin -CAfile tsa-ca.pem

Treat a ``source="tsa"`` token as "a TSA granted this and the nonce and
imprint round-tripped," not as "cryptographically verified." That
distinction is carried on the object itself rather than left to this
docstring — see ``TimestampToken.source``.

## Backends

``LocalTimestamper`` is the always-available default and is deliberately
**not** trusted timestamping: it reads the local clock and returns
``source="local"``. It exists so the anchoring path is exercisable in
tests and offline, the same role ``LoggingEmailSender`` plays for email.

``Rfc3161Timestamper`` is real dispatch, needing the ``tsp`` install
extra (pyasn1/pyasn1-modules — pure Python, no native extensions). Like
the KMS/Vault ``KeySigner`` backends, it has never been exercised against
a live TSA in this environment; the request encoding and response parsing
are exercised for real against synthetic DER (tests/unit/test_timestamper.py).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from legal_engine.core.exceptions import LegalEngineError

# id-sha384 / id-sha256 (NIST), and the two OIDs a TSP response is built from.
_HASH_OIDS = {
    "sha256": "2.16.840.1.101.3.4.2.1",
    "sha384": "2.16.840.1.101.3.4.2.2",
    "sha512": "2.16.840.1.101.3.4.2.3",
}
_ID_CT_TSTINFO = "1.2.840.113549.1.9.16.1.4"
_ID_SIGNEDDATA = "1.2.840.113549.1.7.2"

# PKIStatus: only these two mean the TSA actually issued a token.
_PKI_STATUS_GRANTED = 0
_PKI_STATUS_GRANTED_WITH_MODS = 1


class TimestampError(LegalEngineError):
    """A TSA rejected the request, or returned a token that doesn't match
    what was asked for."""


@dataclass(frozen=True)
class TimestampToken:
    """``source`` is the field that matters and is why this isn't just a
    datetime: ``"local"`` means the host's own clock, carrying exactly the
    trust the WAL already had and no more; ``"tsa"`` means a Time-Stamp
    Authority granted a token whose nonce and imprint matched what was
    sent. Making that structural rather than documentary is deliberate —
    a caller that persists or displays a timestamp can branch on it, and
    cannot accidentally treat a local stamp as third-party attestation.

    ``der`` is the raw token, retained for exactly one reason: signature
    verification is not performed here (see the module docstring), so the
    bytes a real verifier would need must survive."""

    digest: bytes
    gen_time: datetime
    source: Literal["local", "tsa"]
    der: bytes | None = None
    serial_number: int | None = None
    policy: str | None = None


class Timestamper(Protocol):
    def timestamp(self, data: bytes) -> TimestampToken: ...


class LocalTimestamper:
    """Default backend. **Not** trusted timestamping — see the module
    docstring. Returns ``source="local"`` so nothing downstream can
    mistake it for attestation."""

    def __init__(self, hash_algorithm: str = "sha384") -> None:
        if hash_algorithm not in _HASH_OIDS:
            raise ValueError(f"unsupported hash algorithm {hash_algorithm!r}")
        self._hash_algorithm = hash_algorithm

    def timestamp(self, data: bytes) -> TimestampToken:
        digest = hashlib.new(self._hash_algorithm, data).digest()
        return TimestampToken(digest=digest, gen_time=datetime.now(UTC), source="local")


class Rfc3161Timestamper:
    """Real TSP dispatch over HTTP. ``http_post`` is an injected seam,
    the same way ``AwsKmsKeySigner`` takes ``client=`` and
    ``SmtpEmailSender`` takes ``smtp_client=``: it makes the request
    encoding and response parsing unit-testable against synthetic DER
    without a live TSA. It takes ``(url, body, timeout)`` and returns the
    raw response bytes."""

    def __init__(
        self,
        url: str,
        hash_algorithm: str = "sha384",
        timeout_seconds: float = 10.0,
        http_post: Any = None,
    ) -> None:
        if hash_algorithm not in _HASH_OIDS:
            raise ValueError(f"unsupported hash algorithm {hash_algorithm!r}")
        self._url = url
        self._hash_algorithm = hash_algorithm
        self._timeout_seconds = timeout_seconds
        self._http_post = http_post

    def _asn1(self) -> Any:
        try:
            from pyasn1.codec.der import decoder, encoder
            from pyasn1.type import tag, univ, useful
            from pyasn1_modules import rfc3161, rfc5652
        except Exception as exc:
            # Broad, matching every other lazy backend here: a missing
            # extra and a broken install should produce the same
            # actionable message.
            raise ImportError(
                "Rfc3161Timestamper requires pyasn1: pip install 'legal-engine[tsp]' "
                f"(underlying error: {exc.__class__.__name__}: {exc})"
            ) from exc
        return decoder, encoder, tag, univ, useful, rfc3161, rfc5652

    def build_request(self, data: bytes, nonce: int) -> tuple[bytes, bytes]:
        """Returns ``(der_request, digest)``. Split out from ``timestamp``
        so the encoding is testable on its own, and so a caller that wants
        to archive exactly what was sent can."""
        _, encoder, _, univ, _, rfc3161, _ = self._asn1()

        digest = hashlib.new(self._hash_algorithm, data).digest()

        imprint = rfc3161.MessageImprint()
        imprint["hashAlgorithm"]["algorithm"] = univ.ObjectIdentifier(
            _HASH_OIDS[self._hash_algorithm]
        )
        imprint["hashAlgorithm"]["parameters"] = encoder.encode(univ.Null(""))
        imprint["hashedMessage"] = univ.OctetString(digest)

        request = rfc3161.TimeStampReq()
        request["version"] = 1
        request["messageImprint"] = imprint
        request["nonce"] = univ.Integer(nonce)
        # certReq=True asks the TSA to embed its certificate in the token.
        # Since verification happens later and elsewhere (see the module
        # docstring), the token has to be self-contained enough for that
        # verifier to work with.
        request["certReq"] = univ.Boolean(True)
        return encoder.encode(request), digest

    def parse_response(self, response_der: bytes, expected_nonce: int, expected_digest: bytes) -> TimestampToken:
        """Fails closed on anything that isn't a granted token matching
        the nonce and digest that were sent."""
        decoder, _, _, _, _, rfc3161, rfc5652 = self._asn1()

        try:
            response, _ = decoder.decode(response_der, asn1Spec=rfc3161.TimeStampResp())
        except Exception as exc:
            raise TimestampError(f"TSA response is not a valid TimeStampResp: {exc}") from exc

        status = int(response["status"]["status"])
        if status not in (_PKI_STATUS_GRANTED, _PKI_STATUS_GRANTED_WITH_MODS):
            raise TimestampError(f"TSA rejected the request (PKIStatus {status})")

        token = response["timeStampToken"]
        if not token.isValue:
            raise TimestampError("TSA returned a granted status with no timeStampToken")

        content_type = str(token["contentType"])
        if content_type != _ID_SIGNEDDATA:
            raise TimestampError(f"timeStampToken is not CMS SignedData (contentType {content_type})")

        try:
            signed_data, _ = decoder.decode(bytes(token["content"]), asn1Spec=rfc5652.SignedData())
            encap = signed_data["encapContentInfo"]
            tst_info, _ = decoder.decode(bytes(encap["eContent"]), asn1Spec=rfc3161.TSTInfo())
        except Exception as exc:
            raise TimestampError(f"could not extract TSTInfo from the token: {exc}") from exc

        if str(encap["eContentType"]) != _ID_CT_TSTINFO:
            raise TimestampError("token's encapsulated content is not id-ct-TSTInfo")

        # Anti-replay. Without this check a recorded response could be
        # replayed for any later request and look valid.
        if not tst_info["nonce"].isValue or int(tst_info["nonce"]) != expected_nonce:
            raise TimestampError("TSA response nonce does not match the request (possible replay)")

        returned_digest = bytes(tst_info["messageImprint"]["hashedMessage"])
        if returned_digest != expected_digest:
            raise TimestampError("TSA timestamped a different digest than the one submitted")

        returned_oid = str(tst_info["messageImprint"]["hashAlgorithm"]["algorithm"])
        if returned_oid != _HASH_OIDS[self._hash_algorithm]:
            raise TimestampError(f"TSA used hash algorithm {returned_oid}, expected {self._hash_algorithm}")

        return TimestampToken(
            digest=returned_digest,
            gen_time=_parse_generalized_time(str(tst_info["genTime"])),
            source="tsa",
            der=response_der,
            serial_number=int(tst_info["serialNumber"]),
            policy=str(tst_info["policy"]),
        )

    def timestamp(self, data: bytes) -> TimestampToken:
        # 64 bits of nonce, per RFC 3161's guidance that it be large
        # enough that a TSA can't feasibly have seen it before.
        nonce = int.from_bytes(secrets.token_bytes(8), "big")
        request_der, digest = self.build_request(data, nonce)
        response_der = self._post(request_der)
        return self.parse_response(response_der, expected_nonce=nonce, expected_digest=digest)

    def _post(self, request_der: bytes) -> bytes:
        if self._http_post is not None:
            result: bytes = self._http_post(self._url, request_der, self._timeout_seconds)
            return result

        import httpx

        response = httpx.post(
            self._url,
            content=request_der,
            headers={"Content-Type": "application/timestamp-query"},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.content


def _parse_generalized_time(value: str) -> datetime:
    """ASN.1 GeneralizedTime as a TSA emits it: ``YYYYMMDDHHMMSS[.fff]Z``,
    always UTC in this profile. Parsed here rather than via
    ``datetime.fromisoformat`` because that rejects the compact form."""
    text = value.strip()
    if not text.endswith("Z"):
        raise TimestampError(f"TSA genTime {value!r} is not UTC-qualified")
    text = text[:-1]
    fmt = "%Y%m%d%H%M%S.%f" if "." in text else "%Y%m%d%H%M%S"
    try:
        return datetime.strptime(text, fmt).replace(tzinfo=UTC)
    except ValueError as exc:
        raise TimestampError(f"TSA genTime {value!r} is not a valid GeneralizedTime") from exc


def anchor(wal: Any, timestamper: Timestamper) -> TimestampToken | None:
    """Timestamps the WAL's head hash, attesting every entry in the log at
    once — see the module docstring on why this is the right granularity.
    Returns None for an empty WAL, since there is nothing to attest.

    Deliberately a free function rather than a ``WriteAheadLog`` method:
    the WAL's job is to be an append-only signed chain, and it holds
    together with no notion of trusted time at all. Anchoring is something
    done *to* a WAL by whoever has a TSA configured.
    """
    entries = wal.entries()
    if not entries:
        return None
    head = entries[-1]
    return timestamper.timestamp(head.payload_hash.encode("ascii"))
