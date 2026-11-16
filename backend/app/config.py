from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: str
    jwt_secret_key: SecretStr
    access_token_expire_minutes: int = 30
    cors_origins: list[str] = Field(default_factory=list)
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None
    public_api_base_url: str | None = None
    @field_validator("database_url")
    @classmethod
    def require_async_postgres(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def require_strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return value

    @field_validator("access_token_expire_minutes")
    @classmethod
    def require_positive_expiry(cls, value: int) -> int:
        if not 1 <= value <= 10080:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and 10080")
        return value

    @field_validator("public_api_base_url")
    @classmethod
    def normalize_public_api_url(cls, value: str | None) -> str | None:
        return value.strip().rstrip("/") if value else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
