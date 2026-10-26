"""Shared test fixtures.

Tests never read the real .env - `_env_file=None` keeps them hermetic, so a
developer's local settings can't make a test pass or fail.
"""

from __future__ import annotations

from typing import Any

import pytest

from insight.config import Settings, get_settings

# The four values that have no default, because a missing secret should stop
# the process rather than quietly fall back to something insecure.
REQUIRED_SECRETS: dict[str, Any] = {
    "postgres_password": "test-pg-password",
    "postgres_audit_password": "test-audit-password",
    "spicedb_preshared_key": "test-spicedb-key",
    "jwt_secret": "test-jwt-secret",
}


def make_settings(**overrides: Any) -> Settings:
    """Build Settings without touching .env or the environment."""
    values: dict[str, Any] = {**REQUIRED_SECRETS, **overrides}
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Any:
    """get_settings() is lru_cached; stop one test leaking into the next."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
