from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from the environment (ConfigMap/Secret on Kubernetes, /opt/omd/.env on EC2)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "info"
    api_root_path: str = ""  # "/api" behind Istio/nginx: only affects generated URLs (docs, OpenAPI)
    database_url: str = "postgresql+asyncpg://omd:omd@localhost:5432/omd"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600
    enable_demo: bool = True  # POST /chains/demo creates a synthetic chain
    max_upload_bytes: int = 2_000_000

    # --- IV forecasting (app/forecast) ---
    forecast_symbols: str = "NIFTY,BANKNIFTY"
    risk_free_rate: float = 0.065
    bhav_cache_dir: str = ""  # keep raw bhavcopy zips here (optional)
    model_max_age_days: int = 7  # retrain weekly
    review_enabled: bool = True
    review_required: bool = True  # block publication if Claude review is unavailable
    bedrock_region: str = "ap-south-1"
    bedrock_model_id: str = "in.anthropic.claude-sonnet-5"  # India-only cross-region profile (ap-south-1/2)


@lru_cache
def get_settings() -> Settings:
    return Settings()
