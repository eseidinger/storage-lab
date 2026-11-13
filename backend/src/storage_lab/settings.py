from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_LAB_", extra="ignore")

    database_url: str = "sqlite:///./storage-lab.db"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    credential_key: str = ""
    postgres_admin_dsn: str = ""
    postgres_public_host: str = "localhost"
    postgres_public_port: int = 5432
    s3_endpoint_url: str = ""
    s3_public_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_admin_access_key: str = ""
    s3_admin_secret_key: str = ""
    couchdb_admin_url: str = ""
    couchdb_endpoint_url: str = ""
    couchdb_public_url: str = ""
    couchdb_admin_user: str = ""
    couchdb_admin_password: str = ""
    worker_poll_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
