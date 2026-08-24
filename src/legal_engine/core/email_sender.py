"""EmailSender abstracts email dispatch behind ``send()``, matching
core/key_signer.py's Protocol-plus-default-plus-lazy-real-backend shape:
a stateless dispatch service, not a WAL-backed trust ledger the way
compliance/consent.py's ConsentLedger is — that's why this lives in
``core/`` alongside ``KeySigner``, not in ``compliance/``.

``LoggingEmailSender`` is the default, always-available implementation:
logs instead of actually sending. This is what lets `POST /auth/invite`,
`POST /auth/request-password-reset`, and registration's email-
verification step all be genuinely exercised in this test suite without
a real mail server — the same role ``Ed25519FileKeySigner`` plays for
``KeySigner``.

``SmtpEmailSender`` is real, dispatching code — ``smtplib`` +
``email.message``, both stdlib, so unlike ``AwsKmsKeySigner``/
``VaultTransitKeySigner`` there's no install extra needed at all; it's
always constructible. What makes it "unverified here" (the same honesty
category as the KMS/Vault adapters) is that ``.send()`` needs a real SMTP
server to actually succeed against, which this environment doesn't have
— a genuine connection failure there is left to propagate as a real
error, not silently swallowed.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from legal_engine.core.logging import get_logger

logger = get_logger(__name__)


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class LoggingEmailSender:
    """Default, always-available EmailSender: logs instead of sending.
    Real production use wants ``settings.email_backend = "smtp"`` instead
    — see core/email_sender_factory.py."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("email_logged_not_sent", to=to, subject=subject, body=body)


class SmtpEmailSender:
    """Real SMTP dispatch. Accepts an injected client (``smtp_client=``)
    the same way ``AwsKmsKeySigner`` accepts ``client=`` — specifically so
    ``send()``'s actual message-composition/dispatch logic is unit-tested
    against a mock (tests/unit/test_email_sender.py) rather than only
    asserted to exist. An injected client is assumed already connected
    (and authenticated, if needed) — ``send()`` just calls
    ``send_message`` on it directly, no ``starttls``/``login``/context-
    manager handling, since that's the caller's responsibility once
    they're supplying the client themselves. Without one, ``send()``
    opens, optionally STARTTLS's and logs into, and closes a fresh
    connection for every call — simple over efficient, since nothing here
    is expected to send at any real volume."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
        from_address: str = "",
        use_tls: bool = True,
        smtp_client: smtplib.SMTP | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_address = from_address or username
        self._use_tls = use_tls
        self._smtp_client = smtp_client

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        if self._smtp_client is not None:
            self._smtp_client.send_message(message)
            return

        with smtplib.SMTP(self._host, self._port) as client:
            if self._use_tls:
                client.starttls()
            if self._username:
                client.login(self._username, self._password)
            client.send_message(message)
