"""ASPIS application settings -- loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    environment: str = "dev"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "aspis"
    postgres_user: str = "aspis"
    postgres_password: str = "changeme_in_production"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # MQTT
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_broker_port_tls: int = 8883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_use_tls: bool = False
    mqtt_client_id: str = "aspis-consumer-01"

    # Azure IoT Hub
    azure_iot_hub_connection_string: str = ""
    azure_iot_hub_name: str = ""

    # Azure Blob Storage
    azure_storage_account_name: str = ""
    azure_storage_account_key: str = ""
    azure_storage_connection_string: str = ""
    azure_storage_container_media: str = "flight-media"
    azure_storage_container_thermal: str = "thermal-images"
    azure_storage_container_models: str = "model-artifacts"
    azure_storage_container_logs: str = "flight-logs"

    # Azure Key Vault
    azure_keyvault_url: str = ""

    # JWT Auth
    jwt_secret_key: str = "changeme_generate_a_real_secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # DJI FlightHub 2
    flighthub_api_url: str = ""
    flighthub_api_key: str = ""
    flighthub_workspace_id: str = ""

    # Alerts
    sendgrid_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    alert_email_from: str = "alerts@aspis.ids.gr"
    alert_webhook_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
