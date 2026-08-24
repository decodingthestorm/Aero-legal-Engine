"""Tests core.timestamper_factory's dispatch logic.

The case worth pinning beyond plain backend selection: selecting the real
backend without a TSA URL must fail at construction rather than at the
first anchor attempt. A timestamper pointed at "" would otherwise look
configured and only reveal itself when someone tried to attest something
— the same shape of problem as a threshold that can never fire.
"""

import pytest

from legal_engine.core.config import settings
from legal_engine.core.timestamper import LocalTimestamper, Rfc3161Timestamper
from legal_engine.core.timestamper_factory import build_timestamper


class TestBuildTimestamper:
    def test_default_backend_is_local(self):
        assert isinstance(build_timestamper(), LocalTimestamper)

    def test_default_is_not_trusted_timestamping(self):
        """The default must never look like attestation — a deployment
        that hasn't configured a TSA has exactly the trust the WAL's own
        clock already gave it, and the token says so."""
        assert build_timestamper().timestamp(b"x").source == "local"

    def test_rfc3161_backend_builds_the_real_client(self, monkeypatch):
        monkeypatch.setattr(settings, "timestamp_backend", "rfc3161")
        monkeypatch.setattr(settings, "tsa_url", "https://tsa.example/tsr")

        timestamper = build_timestamper()

        assert isinstance(timestamper, Rfc3161Timestamper)
        assert timestamper._url == "https://tsa.example/tsr"

    def test_rfc3161_without_a_url_fails_at_construction(self, monkeypatch):
        monkeypatch.setattr(settings, "timestamp_backend", "rfc3161")
        monkeypatch.setattr(settings, "tsa_url", "")

        with pytest.raises(ValueError, match="requires settings.tsa_url"):
            build_timestamper()

    def test_hash_algorithm_flows_through_to_both_backends(self, monkeypatch):
        monkeypatch.setattr(settings, "timestamp_hash_algorithm", "sha512")
        assert build_timestamper()._hash_algorithm == "sha512"

        monkeypatch.setattr(settings, "timestamp_backend", "rfc3161")
        monkeypatch.setattr(settings, "tsa_url", "https://tsa.example/tsr")
        assert build_timestamper()._hash_algorithm == "sha512"

    def test_timeout_flows_through(self, monkeypatch):
        monkeypatch.setattr(settings, "timestamp_backend", "rfc3161")
        monkeypatch.setattr(settings, "tsa_url", "https://tsa.example/tsr")
        monkeypatch.setattr(settings, "tsa_timeout_seconds", 3.5)
        assert build_timestamper()._timeout_seconds == 3.5
