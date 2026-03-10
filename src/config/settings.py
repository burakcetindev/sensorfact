from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or an ``.env`` file.

    All settings can be overridden at runtime by prefixing the env-var name with
    ``APP_`` (e.g. ``APP_MAX_PARALLEL_REQUESTS=10``).

    Attributes:
        blockchain_api_base_url:    Base URL of the upstream blockchain REST API
                                    (currently mempool.space; kept for documentation).
        energy_cost_per_byte_kwh:   Energy model constant: KWh consumed per byte
                                    of transaction data (assignment spec: 4.56).
        co2_per_kwh_kg:             CO₂ intensity in kg per KWh used to compute
                                    carbon-equivalent fields.  Default is the IEA
                                    2023 European average grid mix (0.233 kg/KWh).
        request_timeout_seconds:    Per-request HTTP timeout.
        max_retries:                Maximum number of retry attempts on transient
                                    failures before raising an error.
        retry_backoff_seconds:      Initial backoff delay for non-rate-limit errors;
                                    doubles on each subsequent retry.
        rate_limit_backoff_seconds: Initial backoff delay after an HTTP 429 response;
                                    doubles on each subsequent retry.
        block_cache_ttl_seconds:    TTL for cached raw block payloads (default 15 min).
        tx_cache_ttl_seconds:       TTL for cached transaction payloads (default 15 min).
        daily_cache_ttl_seconds:    TTL for cached daily energy summaries (default 5 min).
        max_parallel_requests:      Semaphore cap on concurrent outbound HTTP calls
                                    when fetching block transaction pages.
    """

    blockchain_api_base_url: str = "https://blockchain.info"
    energy_cost_per_byte_kwh: float = 4.56
    request_timeout_seconds: float = 10.0
    max_retries: int = 4
    retry_backoff_seconds: float = 0.5
    rate_limit_backoff_seconds: float = 5.0
    block_cache_ttl_seconds: int = 900
    tx_cache_ttl_seconds: int = 900
    daily_cache_ttl_seconds: int = 300
    max_parallel_requests: int = 5
    # CO2 intensity used for equivalence calculations.
    # Default: 0.233 kg CO2 per kWh (European average grid mix, IEA 2023).
    co2_per_kwh_kg: float = 0.233

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        extra="ignore",
    )


settings = Settings()
