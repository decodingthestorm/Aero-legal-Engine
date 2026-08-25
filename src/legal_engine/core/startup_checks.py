"""Refuses to start a deployment that is running on placeholder secrets.

``jwt_secret`` and ``api_client_secret`` both ship as
``"change-me-in-production"``. That is the right default for a repo you
can clone and run — but it means a deployment that never set them signs
every token with a value published in this repository's source. Anyone
who can read GitHub can mint a valid token for any subject and tenant.

Nothing checked. The README listed plaintext secret defaults under Known
limitations, which made it an acknowledged risk rather than a prevented
one — and an acknowledged risk still ships.

## Why a hard failure rather than a warning

Every other guard in this codebase fails closed: ``KeySigner`` and
``EmailSender`` raise instead of silently degrading, and
``SemanticEntropyGate`` refuses to construct a threshold it could never
fire on. A warning here would be the same shape of mistake this session
has now found three times — something that reads as a control and isn't
one, because nothing enforces it. A log line at startup gets scrolled
past exactly once.

## Why keyed on ``environment`` rather than ``api_auth_enabled``

Coupling this to whether auth is switched on would mean "auth disabled in
production" silently exempts you from the check — but that combination is
itself a misconfiguration, not a reason to relax. Any ``environment``
value that isn't a recognised development name is treated as a
deployment. That errs toward refusing to boot, which is recoverable in
seconds by setting the variable, whereas the failure it prevents is not
recoverable at all.
"""

from __future__ import annotations

from legal_engine.core.config import Settings
from legal_engine.core.exceptions import LegalEngineError

# Anything not in this set is treated as a deployment.
_DEVELOPMENT_ENVIRONMENTS = frozenset({"development", "dev", "local", "test", "testing"})

# The shipped defaults, plus the values people reach for when replacing a
# default without really replacing it.
_PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "change-me-in-production",
        "changeme",
        "change-me",
        "secret",
        "password",
        "test",
    }
)

# RFC 7518 §3.2: for HMAC-SHA256 "a key of the same size as the hash
# output (for instance, 256 bits for HS256) or larger MUST be used". 32
# characters is that floor, so this is a standards requirement rather than
# a number picked to feel strict.
_MINIMUM_JWT_SECRET_LENGTH = 32


class InsecureConfigurationError(LegalEngineError):
    """A deployment is configured with secrets that cannot be trusted."""


def _placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDER_SECRETS


def verify_production_configuration(settings: Settings) -> None:
    """Raises if a non-development deployment is using placeholder or
    too-short secrets. A no-op in development, so the zero-config clone
    -and-run path and the whole test suite are unaffected.

    Called from api/main.py's lifespan rather than at import time: a
    module-level check would fire while merely importing the app, which
    would make the failure impossible to test and would break tooling that
    imports without running.
    """
    if settings.environment.strip().lower() in _DEVELOPMENT_ENVIRONMENTS:
        return

    problems: list[str] = []

    if _placeholder(settings.jwt_secret):
        problems.append(
            "LEGAL_ENGINE_JWT_SECRET is still a placeholder — every token this "
            "deployment issues would be forgeable by anyone with the source"
        )
    elif len(settings.jwt_secret) < _MINIMUM_JWT_SECRET_LENGTH:
        problems.append(
            f"LEGAL_ENGINE_JWT_SECRET is {len(settings.jwt_secret)} characters; "
            f"HS256 requires at least {_MINIMUM_JWT_SECRET_LENGTH} (RFC 7518 §3.2)"
        )

    if _placeholder(settings.api_client_secret):
        problems.append(
            "LEGAL_ENGINE_API_CLIENT_SECRET is still a placeholder — the demo "
            "credential would grant tokens to anyone who tried it"
        )

    if problems:
        raise InsecureConfigurationError(
            f"refusing to start in environment {settings.environment!r} with insecure "
            "configuration:\n  - " + "\n  - ".join(problems) + "\n"
            "Set these via environment variables, or set LEGAL_ENGINE_ENVIRONMENT to a "
            f"development value ({', '.join(sorted(_DEVELOPMENT_ENVIRONMENTS))}) if this "
            "is not a deployment."
        )
