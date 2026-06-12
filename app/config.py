# app/config.py
# This file reads all values from .env and makes them available
# as a single `settings` object throughout the entire application.
# Instead of os.getenv() scattered everywhere, we use settings.DATABASE_URL

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Application
    APP_NAME: str = "PayFlow Payment Orchestration Layer"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    SECRET_KEY: str

    # Gateway webhook secrets (for signature verification)
    RAZORPAY_WEBHOOK_SECRET: str = "razorpay_test_secret"
    STRIPE_WEBHOOK_SECRET: str = "stripe_test_secret"
    PAYU_WEBHOOK_SECRET: str = "payu_test_secret"
    UPI_WEBHOOK_SECRET: str = "upi_test_secret"

    # Routing
    DEFAULT_ROUTING_STRATEGY: str = "weighted_score"
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_TIMEOUT: int = 30

    # Reconciliation
    RECONCILIATION_INTERVAL_MINUTES: int = 15
    STALE_TRANSACTION_MINUTES: int = 5

    class Config:
        env_file = ".env"
        case_sensitive = True


# lru_cache means this function runs only ONCE no matter how many
# times it's called. Settings are read once and cached forever.
@lru_cache()
def get_settings() -> Settings:
    return Settings()


# Single shared instance used across the entire app
settings = get_settings()