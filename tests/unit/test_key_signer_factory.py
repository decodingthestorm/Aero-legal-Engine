"""Tests core.key_signer_factory's dispatch logic.

Selecting a "real" backend (aws_kms/vault_transit) without its underlying
package actually importable isn't mocked around here — it's asserted to
raise ImportError with a helpful message, same contract as
test_knowledge_graph_factory.py: the factory dispatches correctly, and
the concrete class's lazy import is what enforces "you need to pip
install X to use this." The import itself is blocked via
builtins.__import__ (not just relying on boto3/hvac being absent from
this environment) so this passes deterministically regardless of whether
the `kms` extra happens to be installed in whatever venv runs it — see
test_key_signer.py's identical technique for AwsKmsKeySigner/
VaultTransitKeySigner directly.
"""

import builtins

import pytest

from legal_engine.core.config import settings
from legal_engine.core.key_signer import Ed25519FileKeySigner
from legal_engine.core.key_signer_factory import build_key_signer


class TestDefaultBackend:
    def test_default_is_the_file_backed_signer(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "wal_path", str(tmp_path / "wal"))
        assert isinstance(build_key_signer(), Ed25519FileKeySigner)


def _block_import(monkeypatch, blocked_name: str) -> None:
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == blocked_name:
            raise ImportError(f"No module named '{blocked_name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)


class TestBackendSwitchWithoutOptionalDependency:
    def test_aws_kms_backend_fails_closed_with_install_hint(self, monkeypatch):
        monkeypatch.setattr(settings, "wal_signer_backend", "aws_kms")
        _block_import(monkeypatch, "boto3")
        with pytest.raises(ImportError, match="pip install -e '.\\[kms\\]'"):
            build_key_signer()

    def test_vault_transit_backend_fails_closed_with_install_hint(self, monkeypatch):
        monkeypatch.setattr(settings, "wal_signer_backend", "vault_transit")
        _block_import(monkeypatch, "hvac")
        with pytest.raises(ImportError, match="pip install -e '.\\[kms\\]'"):
            build_key_signer()
