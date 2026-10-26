"""Application factory."""

from __future__ import annotations

from fastapi.testclient import TestClient

from insight import __version__
from insight.main import create_app
from tests.conftest import make_settings


def test_health_reports_version_and_env() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "env": "development",
    }


def test_docs_available_in_development() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200


def test_docs_disabled_in_production() -> None:
    """The OpenAPI schema names every endpoint holding board material."""
    app = create_app(
        make_settings(
            app_env="production",
            litellm_generation_model="bedrock/anthropic.claude-3-5-sonnet",
            litellm_fallback_model="azure/gpt-4o",
        )
    )
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_settings_are_attached_to_app_state() -> None:
    settings = make_settings()
    app = create_app(settings)
    assert app.state.settings is settings
