"""Settings-driven factory for EmailSender, mirroring
core/key_signer_factory.py's pattern exactly: callers (api/main.py's
lifespan) don't need to know which backend they're getting, just call
the factory.

Unlike the KMS/Vault KeySigner backends, "smtp" doesn't fail closed with
an install-hint ImportError when misconfigured — smtplib/email are
stdlib, always importable, so there's no "did you pip install the right
extra" failure mode here. A misconfigured SmtpEmailSender instead fails
at send() time with a real connection/auth error, which is the honest
failure mode to let propagate rather than paper over.
"""

from __future__ import annotations

from legal_engine.core.config import settings
from legal_engine.core.email_sender import EmailSender, LoggingEmailSender, SmtpEmailSender


def build_email_sender() -> EmailSender:
    if settings.email_backend == "smtp":
        return SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_address=settings.smtp_from_address,
            use_tls=settings.smtp_use_tls,
        )
    return LoggingEmailSender()
