"""Central, validated configuration. Everything comes from environment variables (12-factor)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    env: Literal["local", "staging", "prod"] = "local"
    log_level: str = "INFO"
    # AWS_REGION is used for AWS resources such as S3 and DynamoDB.
    aws_region: str = "eu-west-1"

    # Mesh API is OpenAI-compatible and handles both embeddings and generation.
    mesh_api_key: str = ""
    mesh_base_url: str = "https://api.meshapi.ai/v1"

    # --- PostgreSQL / pgvector vector store ---
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "primark_sop"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"  # noqa: S105
    postgres_sslmode: str = "disable"
    postgres_table: str = "sop_chunks"
    postgres_url: str = ""  # If set, overrides individual postgres_* settings
    embedding_model_name: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    retrieval_top_k: int = 6
    retrieval_candidates: int = 30
    max_chunks_per_sop: int = 3

    # --- Mesh API generation ---
    generation_model_id: str = "openai/gpt-oss-20b"
    rewrite_model_id: str = "openai/gpt-oss-20b"
    max_output_tokens: int = 900
    temperature: float = 0.1

    # --- Bedrock Guardrails (the "Guardrails" box in the architecture) ---
    guardrail_id: str = ""
    guardrail_version: str = "DRAFT"
    guardrail_fail_open: bool = False  # never fail open outside local

    # --- AuthN (JWT from the client's IdP, e.g. Entra ID / Okta / Cognito) ---
    auth_disabled: bool = False
    jwt_issuer: str = ""
    jwt_audience: str = ""
    jwks_url: str = ""
    jwt_country_claim: str = "country"  # ISO-3166 alpha-2 claim used to scope country-specific SOPs

    # --- State ---
    sessions_table: str = ""  # DynamoDB table; empty => in-memory (local only)
    session_ttl_seconds: int = 60 * 60 * 24
    history_turns: int = 4

    # --- Ingestion ---
    sop_bucket: str = ""

    cors_origins: str = ""  # comma-separated; empty => same-origin only

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def postgres_connection_string(self) -> str:
        if self.postgres_url:
            return self.postgres_url
        user_part = f"{self.postgres_user}:{self.postgres_password}@" if self.postgres_user else ""
        return (
            f"postgresql://{user_part}{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            f"?sslmode={self.postgres_sslmode}"
        )

    def validate_for_serving(self) -> None:
        """Called by the API at startup. Refuses to boot a non-local environment with unsafe settings."""
        if self.env != "local":
            problems = []
            if self.auth_disabled:
                problems.append("AUTH_DISABLED must be false")
            if not (self.jwt_issuer and self.jwt_audience and self.jwks_url):
                problems.append("JWT_ISSUER, JWT_AUDIENCE and JWKS_URL are required")
            if not self.mesh_api_key:
                problems.append("MESH_API_KEY is required")
            if not self.guardrail_id:
                problems.append("GUARDRAIL_ID is required")
            if self.guardrail_fail_open:
                problems.append("GUARDRAIL_FAIL_OPEN must be false")
            if not self.sessions_table:
                problems.append("SESSIONS_TABLE is required")
            if problems:
                raise ValueError(f"Unsafe configuration for ENV={self.env}: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
