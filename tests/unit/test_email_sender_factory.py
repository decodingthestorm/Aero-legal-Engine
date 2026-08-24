"""Tests core.email_sender_factory's dispatch logic.

Unlike test_key_signer_factory.py, there's no "fails closed with an
install hint" case here — smtplib/email are stdlib, so selecting "smtp"
never fails to *construct*, only to actually *send* without a real
server (see test_email_sender.py).
"""

from legal_engine.core.config import settings
from legal_engine.core.email_sender import LoggingEmailSender, SmtpEmailSender
from legal_engine.core.email_sender_factory import build_email_sender


class TestBuildEmailSender:
    def test_default_backend_is_logging(self):
        assert isinstance(build_email_sender(), LoggingEmailSender)

    def test_smtp_backend_builds_smtp_sender_with_configured_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "email_backend", "smtp")
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(settings, "smtp_port", 2525)
        monkeypatch.setattr(settings, "smtp_username", "user@example.com")
        monkeypatch.setattr(settings, "smtp_from_address", "noreply@example.com")

        sender = build_email_sender()

        assert isinstance(sender, SmtpEmailSender)
        assert sender._host == "smtp.example.com"
        assert sender._port == 2525
        assert sender._username == "user@example.com"
        assert sender._from_address == "noreply@example.com"
