"""Isolamento global da suíte contra integrações externas reais."""

import os

# Antes da importação do app: nunca herdar integrações do .env da estação.
os.environ["BOOTSTRAP_USERS_JSON"] = ""
os.environ["APP_ENV"] = "test"
os.environ["LOCAL_BACKUP_ENABLED"] = "false"

import pytest


@pytest.fixture(autouse=True)
def disable_real_delivery_by_default(monkeypatch):
    """Um teste só acessa storage quando habilita explicitamente o modo desejado."""
    monkeypatch.setenv("DELIVERY_MODE", "disabled")
    monkeypatch.setenv("DATABRICKS_UPLOAD_ENABLED", "false")

    monkeypatch.setenv("DELIVERY_UNIT", "AUREA")
    monkeypatch.setenv("DELIVERY_POLO", "SP")
    monkeypatch.setenv("DELIVERY_TEST", "false")
    monkeypatch.setenv("BOOTSTRAP_USERS_JSON", "")
    monkeypatch.setenv("TRUST_CLOUDFLARE", "false")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    from app.rate_limit import reset_rate_limits
    reset_rate_limits()
