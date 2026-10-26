"""Application settings.

Every value comes from the environment, loaded from .env in development.
Nothing is hardcoded - above all not model names, which must stay
configuration so production can route inside the client tenancy without a
code change (locked decision 2).

Secrets use SecretStr, so printing or logging the settings object shows
'**********' rather than the value. That matters on an engagement handling
board material: an accidental `log.info("config", settings=settings)` must
not leak a database password into Langfuse.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Langfuse's hosted offering. Sending prompts here would put board material
# outside the client tenancy, which their data-residency decision forbids.
LANGFUSE_SAAS_HOSTS = ("cloud.langfuse.com",)

# A signing secret left at its .env.example value is public knowledge, and
# anyone holding it can forge a token for any user. Length alone does not
# catch it: "replace-with-openssl-rand-hex-32" is exactly 32 characters.
PLACEHOLDER_PREFIXES = ("replace-with", "change-me", "generate-", "your-", "example")

# HS256 below 32 bytes is brute-forceable offline from a single captured
# token (RFC 7518 section 3.2).
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Runtime configuration, validated once at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- application --------------------------------------------------------
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool | None = Field(
        default=None,
        description="Force JSON logs. Defaults to on outside development.",
    )

    # -- postgres -----------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "insight"
    postgres_user: str = "insight"
    postgres_password: SecretStr

    # Separate INSERT-only role for the audit chain (INS-11). Application
    # code holds these credentials but cannot UPDATE or DELETE with them.
    postgres_audit_user: str = "insight_audit"
    postgres_audit_password: SecretStr

    # Connection pool. pre_ping costs one round trip per checkout and saves
    # you from every stale-connection bug after a Postgres restart or a
    # network blip - worth it.
    db_pool_size: int = Field(default=10, gt=0)
    db_max_overflow: int = Field(default=5, ge=0)
    db_pool_pre_ping: bool = True
    db_echo: bool = False

    # -- redis --------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # -- spicedb ------------------------------------------------------------
    spicedb_endpoint: str = "localhost:50051"
    spicedb_preshared_key: SecretStr
    spicedb_insecure: bool = True

    # -- auth ---------------------------------------------------------------
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1_209_600

    # -- llm gateway --------------------------------------------------------
    litellm_generation_model: str = "ollama/llama3.1:8b"
    litellm_fallback_model: str = "ollama/mistral:7b"
    ollama_base_url: str = "http://localhost:11434"

    # -- embeddings ---------------------------------------------------------
    # Stored alongside every vector so a mismatch is detectable rather than
    # silently returning meaningless nearest neighbours.
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = Field(default=768, gt=0)

    # -- retrieval ----------------------------------------------------------
    rerank_model: str = "BAAI/bge-reranker-base"
    retrieve_top_k: int = Field(default=50, gt=0)
    rerank_top_k: int = Field(default=5, gt=0)

    # -- observability ------------------------------------------------------
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")

    # -- deferred -----------------------------------------------------------
    # Populated only for the one gate-3 certification run. Blank in normal
    # development. See docs/KNOWN_LIMITATIONS.md.
    anthropic_api_key: SecretStr = SecretStr("")

    # ----------------------------------------------------------------------
    # derived values
    # ----------------------------------------------------------------------
    @property
    def database_url(self) -> str:
        """Async DSN for the application role."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def audit_database_url(self) -> str:
        """Async DSN for the INSERT-only audit role."""
        return (
            f"postgresql+asyncpg://{self.postgres_audit_user}:"
            f"{self.postgres_audit_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def emit_json_logs(self) -> bool:
        if self.log_json is not None:
            return self.log_json
        return self.app_env != "development"

    # ----------------------------------------------------------------------
    # guards - these turn ADR-001 from a document into something enforced
    # ----------------------------------------------------------------------
    @model_validator(mode="after")
    def _langfuse_must_be_self_hosted(self) -> Settings:
        host = self.langfuse_host.lower()
        if any(saas in host for saas in LANGFUSE_SAAS_HOSTS):
            raise ValueError(
                f"LANGFUSE_HOST points at the hosted service ({self.langfuse_host}). "
                "Board prompts must not leave the client tenancy - run Langfuse "
                "self-hosted. See docs/ADR-001-stack.md."
            )
        return self

    @model_validator(mode="after")
    def _production_must_not_use_local_models(self) -> Settings:
        if not self.is_production:
            return self
        local_prefixes = ("ollama/", "local/")
        for field in ("litellm_generation_model", "litellm_fallback_model"):
            value: str = getattr(self, field)
            if value.lower().startswith(local_prefixes):
                raise ValueError(
                    f"{field.upper()}={value} is a local model, but APP_ENV=production. "
                    "Production inference must route inside the client tenancy "
                    "(Bedrock / Azure OpenAI). See docs/ADR-001-stack.md."
                )
        return self

    @model_validator(mode="after")
    def _jwt_secret_must_be_real(self) -> Settings:
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET is {len(secret)} characters; at least "
                f"{MIN_JWT_SECRET_LENGTH} are required. HS256 with a short secret "
                "is brute-forceable offline from one captured token. "
                "Generate one with: openssl rand -hex 32"
            )
        if secret.lower().startswith(PLACEHOLDER_PREFIXES):
            raise ValueError(
                "JWT_SECRET is still the .env.example placeholder. That value is "
                "public, so anyone can forge a token for any user. "
                "Generate one with: openssl rand -hex 32"
            )
        return self

    @model_validator(mode="after")
    def _rerank_must_narrow(self) -> Settings:
        if self.rerank_top_k > self.retrieve_top_k:
            raise ValueError(
                f"RERANK_TOP_K ({self.rerank_top_k}) exceeds RETRIEVE_TOP_K "
                f"({self.retrieve_top_k}); reranking can only narrow a candidate set."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings singleton. Cached so .env is read once per process."""
    return Settings()
