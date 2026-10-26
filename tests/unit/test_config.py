"""Settings: defaults, derived values, and the guards from ADR-001."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from insight.config import Settings
from tests.conftest import make_settings


class TestDefaults:
    def test_development_by_default(self, settings: Settings) -> None:
        assert settings.app_env == "development"
        assert settings.is_production is False

    def test_embedding_defaults_match_env_example(self, settings: Settings) -> None:
        assert settings.embedding_model == "nomic-embed-text"
        assert settings.embedding_dimension == 768

    def test_missing_secret_is_fatal(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None)


class TestSecretHandling:
    def test_secrets_are_secretstr(self, settings: Settings) -> None:
        assert isinstance(settings.postgres_password, SecretStr)
        assert isinstance(settings.jwt_secret, SecretStr)

    def test_repr_does_not_leak(self, settings: Settings) -> None:
        dumped = repr(settings)
        assert "test-pg-password" not in dumped
        assert settings.jwt_secret.get_secret_value() not in dumped
        assert "**********" in dumped

    def test_value_still_reachable_deliberately(self, settings: Settings) -> None:
        assert settings.postgres_password.get_secret_value() == "test-pg-password"


class TestJwtSecretGuard:
    """A forged token is indistinguishable from a real one."""

    def test_short_secret_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least 32"):
            make_settings(jwt_secret="too-short")

    @pytest.mark.parametrize(
        "placeholder",
        [
            "replace-with-openssl-rand-hex-32",
            "change-me-change-me-change-me-change-me",
            "generate-your-own-secret-value-here-please",
            "your-secret-key-goes-right-here-ok",
        ],
    )
    def test_placeholder_is_rejected_even_when_long_enough(self, placeholder: str) -> None:
        assert len(placeholder) >= 32
        with pytest.raises(ValidationError, match="placeholder"):
            make_settings(jwt_secret=placeholder)

    def test_a_real_secret_is_accepted(self) -> None:
        s = make_settings(jwt_secret="b" * 64)
        assert s.jwt_secret.get_secret_value() == "b" * 64


class TestDerivedValues:
    def test_database_url(self) -> None:
        s = make_settings(postgres_host="db", postgres_port=5433, postgres_db="x")
        assert s.database_url == ("postgresql+asyncpg://insight:test-pg-password@db:5433/x")

    def test_audit_url_uses_the_audit_role(self, settings: Settings) -> None:
        assert "insight_audit:test-audit-password" in settings.audit_database_url

    def test_json_logs_off_in_development(self, settings: Settings) -> None:
        assert settings.emit_json_logs is False

    def test_json_logs_on_in_staging(self) -> None:
        assert make_settings(app_env="staging").emit_json_logs is True

    def test_json_logs_can_be_forced(self) -> None:
        assert make_settings(log_json=True).emit_json_logs is True


class TestLangfuseGuard:
    """Board prompts must not reach the hosted Langfuse (locked decision 2)."""

    def test_self_hosted_is_fine(self) -> None:
        s = make_settings(langfuse_host="http://localhost:3000")
        assert s.langfuse_host == "http://localhost:3000"

    @pytest.mark.parametrize(
        "host",
        [
            "https://cloud.langfuse.com",
            "https://us.cloud.langfuse.com",
            "https://EU.CLOUD.LANGFUSE.COM",
        ],
    )
    def test_saas_host_is_rejected(self, host: str) -> None:
        with pytest.raises(ValidationError, match="self-hosted"):
            make_settings(langfuse_host=host)


class TestProductionModelGuard:
    """Production inference stays inside the client tenancy."""

    def test_local_model_allowed_in_development(self) -> None:
        s = make_settings(litellm_generation_model="ollama/llama3.1:8b")
        assert s.litellm_generation_model.startswith("ollama/")

    def test_local_generation_model_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="client tenancy"):
            make_settings(
                app_env="production",
                litellm_generation_model="ollama/llama3.1:8b",
                litellm_fallback_model="bedrock/anthropic.claude-3-5-sonnet",
            )

    def test_local_fallback_model_also_rejected(self) -> None:
        with pytest.raises(ValidationError, match="client tenancy"):
            make_settings(
                app_env="production",
                litellm_generation_model="bedrock/anthropic.claude-3-5-sonnet",
                litellm_fallback_model="ollama/mistral:7b",
            )

    def test_in_tenancy_models_accepted_in_production(self) -> None:
        s = make_settings(
            app_env="production",
            litellm_generation_model="bedrock/anthropic.claude-3-5-sonnet",
            litellm_fallback_model="azure/gpt-4o",
        )
        assert s.is_production is True


class TestRetrievalGuard:
    def test_rerank_must_narrow(self) -> None:
        with pytest.raises(ValidationError, match="can only narrow"):
            make_settings(retrieve_top_k=10, rerank_top_k=50)

    def test_narrowing_is_fine(self) -> None:
        s = make_settings(retrieve_top_k=50, rerank_top_k=5)
        assert s.rerank_top_k < s.retrieve_top_k

    def test_dimension_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            make_settings(embedding_dimension=0)
