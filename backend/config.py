from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Values that change per machine or are secret. Read from .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "cafe"
    postgres_password: str = "cafe_pass"
    postgres_db: str = "cafe"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_url: str = "redis://localhost:6379/0"

    groq_api_key: str = ""
    nvidia_api_key: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
