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
    postgres_internal_host: str = ""
    postgres_internal_port: int = 0
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
    valkey_admin_host: str = ""
    valkey_admin_password: str = ""
    valkey_public_host: str = "localhost"
    valkey_public_port: int = 6380
    clickhouse_admin_url: str = ""
    clickhouse_admin_password: str = ""
    clickhouse_public_url: str = ""
    qdrant_admin_url: str = ""
    qdrant_api_key: str = ""
    qdrant_public_url: str = ""
    opensearch_admin_url: str = ""
    opensearch_admin_password: str = ""
    opensearch_public_url: str = ""
    hugegraph_admin_url: str = ""
    hugegraph_admin_password: str = ""
    hugegraph_public_url: str = ""
    nats_config_dir: str = ""
    nats_sys_password: str = ""
    nats_admin_host: str = "nats"
    nats_public_url: str = "tls://localhost:4222"
    nats_tls_ca: str = ""
    worker_poll_seconds: float = 2.0
    ui_dist: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
