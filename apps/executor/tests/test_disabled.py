import pytest

from autoaxe_executor.__main__ import smoke


def test_sdk_import_only(monkeypatch):
    monkeypatch.setenv("AUTOAXE_ENVIRONMENT", "fixture")
    monkeypatch.setenv("AUTOAXE_LIVE_ENABLED", "false")
    assert smoke()


def test_nonfixture_refused(monkeypatch):
    monkeypatch.setenv("AUTOAXE_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError):
        smoke()


def test_live_refused(monkeypatch):
    monkeypatch.setenv("AUTOAXE_LIVE_ENABLED", "true")
    with pytest.raises(RuntimeError):
        smoke()
