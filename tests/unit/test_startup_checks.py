"""Covers the refusal to start a deployment on placeholder secrets.

The case that matters most is the one that used to be the shipped
behaviour: environment set to something production-like while both
secrets are still the defaults committed to this repository. That
combination started the app happily for the project's entire history.
"""

from __future__ import annotations

import pytest

from legal_engine.core.config import Settings
from legal_engine.core.startup_checks import (
    InsecureConfigurationError,
    verify_production_configuration,
)

_REAL_SECRET = "u7Qm2kR9xL4vB6nT1yH8sC3wZ5jF0dP2"  # 32 chars, not a placeholder


def _settings(**overrides) -> Settings:
    defaults = {
        "environment": "production",
        "jwt_secret": _REAL_SECRET,
        "api_client_secret": "a-real-client-secret",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestDevelopmentIsExempt:
    @pytest.mark.parametrize(
        "environment", ["development", "dev", "local", "test", "testing", "Development", "  DEV  "]
    )
    def test_development_environments_skip_every_check(self, environment):
        """The zero-config clone-and-run path has to keep working, and the
        whole test suite runs on these defaults."""
        verify_production_configuration(
            _settings(
                environment=environment,
                jwt_secret="change-me-in-production",
                api_client_secret="change-me-in-production",
            )
        )

    def test_the_shipped_defaults_are_accepted_in_development(self):
        verify_production_configuration(Settings())


class TestPlaceholderSecretsAreRejected:
    def test_the_actual_shipped_configuration_in_production_is_refused(self):
        """The regression this module exists for: the defaults committed
        to this repo, with a production environment name."""
        with pytest.raises(InsecureConfigurationError) as exc:
            verify_production_configuration(
                Settings(
                    environment="production",
                    jwt_secret="change-me-in-production",
                    api_client_secret="change-me-in-production",
                )
            )
        message = str(exc.value)
        assert "JWT_SECRET" in message
        assert "API_CLIENT_SECRET" in message

    def test_reports_every_problem_at_once(self):
        """One restart per problem would be a miserable way to find out
        there were two."""
        with pytest.raises(InsecureConfigurationError) as exc:
            verify_production_configuration(
                _settings(jwt_secret="changeme", api_client_secret="secret")
            )
        assert str(exc.value).count("\n  - ") == 2

    @pytest.mark.parametrize(
        "placeholder", ["", "change-me-in-production", "changeme", "secret", "password", "test"]
    )
    def test_common_non_replacements_are_caught(self, placeholder):
        with pytest.raises(InsecureConfigurationError):
            verify_production_configuration(_settings(jwt_secret=placeholder))

    def test_placeholder_detection_ignores_case_and_padding(self):
        with pytest.raises(InsecureConfigurationError):
            verify_production_configuration(_settings(jwt_secret="  Change-Me-In-Production  "))

    def test_a_placeholder_client_secret_alone_is_enough(self):
        with pytest.raises(InsecureConfigurationError, match="API_CLIENT_SECRET"):
            verify_production_configuration(_settings(api_client_secret="change-me-in-production"))


class TestJwtSecretLength:
    def test_a_short_but_genuine_secret_is_rejected(self):
        """RFC 7518 §3.2 requires an HS256 key at least as long as the
        hash output. A real-looking 12-character secret is still too
        short to be one."""
        with pytest.raises(InsecureConfigurationError, match="RFC 7518"):
            verify_production_configuration(_settings(jwt_secret="hunter2hunter"))

    def test_exactly_thirty_two_characters_is_accepted(self):
        verify_production_configuration(_settings(jwt_secret="x" * 32))

    def test_thirty_one_characters_is_rejected(self):
        with pytest.raises(InsecureConfigurationError):
            verify_production_configuration(_settings(jwt_secret="x" * 31))

    def test_length_is_only_reported_when_the_value_is_not_a_placeholder(self):
        """A placeholder that happens to be short should be reported as a
        placeholder — the more actionable message — not as a length
        problem."""
        with pytest.raises(InsecureConfigurationError) as exc:
            verify_production_configuration(_settings(jwt_secret="secret"))
        assert "placeholder" in str(exc.value)
        assert "RFC 7518" not in str(exc.value)


class TestValidProductionConfiguration:
    def test_real_secrets_in_production_start_cleanly(self):
        verify_production_configuration(_settings())

    def test_an_unrecognised_environment_name_is_treated_as_a_deployment(self):
        """"staging", "prod-eu", anything unfamiliar — the check errs
        toward refusing to boot, which costs seconds to fix, rather than
        toward starting insecurely, which costs everything."""
        with pytest.raises(InsecureConfigurationError):
            verify_production_configuration(
                _settings(environment="staging", jwt_secret="change-me-in-production")
            )
        verify_production_configuration(_settings(environment="staging"))
