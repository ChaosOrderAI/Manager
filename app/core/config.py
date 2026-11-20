from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # TCP gateway
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 7808

    # Database
    database_url: str = "postgresql+asyncpg://m68:m68@postgres:5432/m68"
    sync_database_url: str = "postgresql+psycopg2://m68:m68@postgres:5432/m68"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_token: str = "change-me"          # simple bearer auth for admin API

    # Business
    offline_timeout_sec: int = 300        # no msg -> offline
    low_battery_pct: int = 20

    # Auth code issued after registration (in real deployment generate unique)
    default_auth_code: str = "M68AUTH"

    class Config:
        env_file = ".env"


settings = Settings()
