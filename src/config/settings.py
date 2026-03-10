from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    blockchain_api_base_url: str = "https://blockchain.info"
    energy_cost_per_byte_kwh: float = 4.56
    request_timeout_seconds: float = 10.0
    max_retries: int = 4
    retry_backoff_seconds: float = 0.5
    block_cache_ttl_seconds: int = 900
    tx_cache_ttl_seconds: int = 900
    daily_cache_ttl_seconds: int = 300
    max_parallel_requests: int = 8

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        extra="ignore",
    )


settings = Settings()
