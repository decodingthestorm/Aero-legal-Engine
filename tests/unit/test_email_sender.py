"""Exercises core/email_sender.py.

LoggingEmailSender is exercised for real (no mocking needed — it's the
default, always-available backend). SmtpEmailSender is exercised against
an injected mock client (unittest.mock), the same technique
test_key_signer.py uses for AwsKmsKeySigner — proving this module's own
message-composition/dispatch logic is correct, not that a real SMTP
server behaves as assumed, which nothing in this environment can
provide.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from legal_engine.core.email_sender import LoggingEmailSender, SmtpEmailSender


class TestLoggingEmailSender:
    def test_send_logs_the_message_instead_of_sending(self, capsys):
        # structlog's logger_factory (core/logging.py's configure_logging)
        # writes straight to stdout rather than through stdlib logging, so
        # pytest's caplog fixture (which only sees stdlib logging records)
        # can't see this — capsys, which captures the actual stdout
        # stream, is the correct tool here regardless of whether
        # configure_logging() has run yet in this test session.
        sender = LoggingEmailSender()
        sender.send(to="alice@example.com", subject="Hello", body="World")

        captured = capsys.readouterr()
        assert "email_logged_not_sent" in captured.out
        assert "alice@example.com" in captured.out

    def test_send_never_raises(self):
        sender = LoggingEmailSender()
        sender.send(to="alice@example.com", subject="Hello", body="World")  # should not raise


class TestSmtpEmailSenderWithInjectedClient:
    def test_send_composes_the_message_correctly(self):
        client = MagicMock()
        sender = SmtpEmailSender(
            host="smtp.example.com", port=587, from_address="noreply@example.com", smtp_client=client
        )
        sender.send(to="alice@example.com", subject="Hello", body="World")

        client.send_message.assert_called_once()
        [sent_message] = client.send_message.call_args.args
        assert sent_message["To"] == "alice@example.com"
        assert sent_message["From"] == "noreply@example.com"
        assert sent_message["Subject"] == "Hello"
        assert sent_message.get_content().strip() == "World"

    def test_from_address_defaults_to_username_when_not_given(self):
        client = MagicMock()
        sender = SmtpEmailSender(
            host="smtp.example.com", port=587, username="user@example.com", smtp_client=client
        )
        sender.send(to="alice@example.com", subject="Hello", body="World")

        [sent_message] = client.send_message.call_args.args
        assert sent_message["From"] == "user@example.com"

    def test_injected_client_bypasses_starttls_and_login(self):
        """An injected client is assumed already connected/authenticated
        — send() should call send_message directly on it, not attempt to
        starttls/login/close a connection it doesn't own."""
        client = MagicMock()
        sender = SmtpEmailSender(host="smtp.example.com", port=587, smtp_client=client)
        sender.send(to="alice@example.com", subject="Hello", body="World")

        client.starttls.assert_not_called()
        client.login.assert_not_called()
        client.__exit__.assert_not_called()

    def test_send_propagates_a_dispatch_failure_rather_than_swallowing_it(self):
        client = MagicMock()
        client.send_message.side_effect = ConnectionRefusedError("no SMTP server here")
        sender = SmtpEmailSender(host="smtp.example.com", port=587, smtp_client=client)

        with pytest.raises(ConnectionRefusedError):
            sender.send(to="alice@example.com", subject="Hello", body="World")


class TestSmtpEmailSenderWithoutInjectedClient:
    """No mail server exists in this environment to actually connect to —
    proves the real-connection code path is at least reached and fails
    the way a real network error would, not proof it succeeds against a
    genuine SMTP server."""

    def test_connecting_to_a_nonexistent_server_raises_a_real_error(self):
        sender = SmtpEmailSender(host="127.0.0.1", port=1, use_tls=False)
        with pytest.raises(OSError):
            sender.send(to="alice@example.com", subject="Hello", body="World")
