"""Round-1 guards for destructive demo_reset."""
from __future__ import annotations

import pytest

from scripts.demo_reset import assert_safe_to_reset


def test_demo_reset_requires_confirm(monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD", "tingting-seed-demo-2026")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://tingting_ci:ci-only-postgres-password@localhost:5432/tingting_ci",
    )
    monkeypatch.delenv("CONFIRM_DEMO_RESET", raising=False)
    with pytest.raises(SystemExit) as exc:
        assert_safe_to_reset(confirm_reset=False)
    assert exc.value.code == 2


def test_demo_reset_rejects_production(monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD", "tingting-seed-demo-2026")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://tingting_ci:ci-only-postgres-password@localhost:5432/tingting_ci",
    )
    with pytest.raises(SystemExit) as exc:
        assert_safe_to_reset(confirm_reset=True)
    assert exc.value.code == 2


def test_demo_reset_rejects_unknown_database(monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD", "tingting-seed-demo-2026")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://tingting:ci-only-postgres-password@localhost:5432/prod_civic",
    )
    with pytest.raises(SystemExit) as exc:
        assert_safe_to_reset(confirm_reset=True)
    assert exc.value.code == 2


def test_demo_reset_requires_database_url(monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD", "tingting-seed-demo-2026")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        assert_safe_to_reset(confirm_reset=True)
    assert exc.value.code == 2


def test_demo_reset_allows_whitelist_with_confirm(monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD", "tingting-seed-demo-2026")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://tingting_ci:ci-only-postgres-password@localhost:5432/tingting_ci",
    )
    assert_safe_to_reset(confirm_reset=True)
