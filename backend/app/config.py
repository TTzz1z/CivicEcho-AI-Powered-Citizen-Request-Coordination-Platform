from functools import lru_cache
import os

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://tingting:change-me@postgres:5432/tingting"
    app_name: str = "Tingting Ticket Service"
    jwt_secret: str = "development-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 30
    service_api_token: str = "development-service-token-change-me"
    default_timezone: str = "Asia/Shanghai"
    cors_origins: str = "http://localhost:8080,http://localhost:5173"
    max_request_body_bytes: int = 1_048_576
    attachment_max_bytes: int = 20 * 1024 * 1024
    attachment_image_max_bytes: int = 10 * 1024 * 1024
    attachment_request_overhead_bytes: int = 1_048_576
    attachment_allowed_extensions: str = "jpg,jpeg,png,webp,pdf,doc,docx,xls,xlsx,txt"
    attachment_allowed_content_types: str = (
        "image/jpeg,image/png,image/webp,application/pdf,application/msword,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "text/plain"
    )
    object_storage_endpoint: str = "minio:9000"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: str = "minioadmin"
    object_storage_bucket: str = "tingting-attachments"
    object_storage_secure: bool = False
    object_storage_region: str | None = None
    object_storage_timeout_seconds: int = Field(default=5, ge=1, le=60)
    object_storage_readiness_required: bool = False
    malware_scan_mode: str = "disabled"
    malware_scan_url: str | None = None
    malware_scan_token: str | None = None
    malware_scan_timeout_seconds: int = 30
    malware_scan_require_clean: bool = False
    database_connect_timeout_seconds: int = 5
    allow_citizen_self_register: bool = True
    login_rate_limit_attempts: int = Field(default=5, ge=1)
    login_rate_limit_window_seconds: int = Field(default=60, ge=1)
    register_rate_limit_attempts: int = Field(default=10, ge=1)
    register_rate_limit_window_seconds: int = Field(default=300, ge=1)
    anon_ticket_rate_limit_attempts: int = Field(default=15, ge=1)
    anon_ticket_rate_limit_window_seconds: int = Field(default=300, ge=1)
    upload_rate_limit_attempts: int = Field(default=30, ge=1)
    upload_rate_limit_window_seconds: int = Field(default=60, ge=1)
    ai_rate_limit_attempts: int = Field(default=30, ge=1)
    ai_rate_limit_window_seconds: int = Field(default=60, ge=1)
    export_rate_limit_attempts: int = Field(default=10, ge=1)
    export_rate_limit_window_seconds: int = Field(default=60, ge=1)
    log_level: str = "INFO"
    ai_provider: str = "rules"
    ai_model_name: str = "phase6-rules-v1"
    ai_api_key: str | None = None
    ai_base_url: str = "https://api.deepseek.com"
    ai_model: str = "deepseek-chat"
    ai_timeout_seconds: int = 30
    ai_max_tokens: int = 1024
    anonymous_retention_days: int = Field(default=30, ge=1, le=365)
    # --- Knowledge Base / RAG ---
    embedding_api_key: str | None = None
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dimensions: int = 1024
    embedding_timeout_seconds: int = 30
    kb_chunk_size: int = 500
    kb_chunk_overlap: int = 100
    kb_rag_top_k: int = 5
    kb_rag_min_lexical_coverage: float = Field(default=0.22, ge=0, le=1)
    kb_rag_min_vector_similarity: float = Field(default=0.62, ge=0, le=1)
    kb_upload_bucket: str = "tingting-kb"
    kb_allow_direct_publish: bool = True
    oidc_enabled: bool = False
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_scopes: str = "openid profile email"
    directory_api_url: str | None = None
    directory_api_token: str | None = None
    work_order_platform: str = "disabled"
    work_order_api_url: str | None = None
    work_order_api_token: str | None = None
    sms_api_url: str | None = None
    sms_api_token: str | None = None
    map_api_url: str | None = None
    map_api_token: str | None = None
    division_api_url: str | None = None
    division_api_token: str | None = None
    central_log_endpoint: str | None = None
    central_log_token: str | None = None
    monitoring_endpoint: str | None = None
    monitoring_token: str | None = None
    integration_timeout_seconds: int = 10
    worker_enabled: bool = True
    worker_scan_interval_seconds: int = 60
    worker_due_soon_hours: int = 4
    worker_outbox_retention_days: int = Field(default=90, ge=1)
    worker_ai_retention_days: int = Field(default=180, ge=1)
    worker_orphan_grace_days: int = Field(default=7, ge=1)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_attachment_extensions(self) -> set[str]:
        return {item.strip().lower().lstrip(".") for item in self.attachment_allowed_extensions.split(",") if item.strip()}

    @property
    def allowed_attachment_content_types(self) -> set[str]:
        return {item.strip().lower() for item in self.attachment_allowed_content_types.split(",") if item.strip()}

    @model_validator(mode="after")
    def reject_weak_production_secrets(self):
        if self.malware_scan_mode not in {"disabled", "http", "clamd"}:
            raise ValueError("MALWARE_SCAN_MODE must be disabled, http, or clamd")
        if self.malware_scan_mode in {"http", "clamd"} and not self.malware_scan_url:
            raise ValueError("MALWARE_SCAN_URL is required when malware scanning is enabled")
        if self.attachment_max_bytes <= 0 or self.attachment_image_max_bytes <= 0:
            raise ValueError("attachment size limits must be positive")
        if self.ai_provider not in {"rules", "deepseek"}:
            raise ValueError("AI_PROVIDER currently supports rules or deepseek")
        if self.work_order_platform not in {"disabled", "servicenow", "government"}:
            raise ValueError("WORK_ORDER_PLATFORM must be disabled, servicenow or government")
        if self.oidc_enabled and not all((self.oidc_issuer, self.oidc_client_id, self.oidc_client_secret, self.oidc_redirect_uri)):
            raise ValueError("OIDC issuer, client credentials and redirect URI are required when OIDC is enabled")
        if self.app_env.strip().lower() not in {"production", "prod"}:
            return self
        weak_markers = {"change-me", "development", "example", "default", "password", "minioadmin", "<生成"}
        for name, value, minimum in (
            ("JWT_SECRET", self.jwt_secret, 32),
            ("SERVICE_API_TOKEN", self.service_api_token, 32),
        ):
            lowered = value.lower()
            if len(value) < minimum or any(marker in lowered for marker in weak_markers):
                raise ValueError(f"{name} is weak or still uses a placeholder")
        try:
            database_password = make_url(self.database_url).password or ""
        except (ArgumentError, ValueError):
            raise ValueError("DATABASE_URL is invalid") from None
        if len(database_password) < 16 or any(marker in database_password.lower() for marker in weak_markers):
            raise ValueError("DATABASE_URL contains a weak/default password")
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("CORS_ORIGINS must be an explicit production allowlist")
        if (
            self.malware_scan_mode not in {"http", "clamd"}
            or not self.malware_scan_url
            or not self.malware_scan_require_clean
        ):
            raise ValueError(
                "production requires MALWARE_SCAN_MODE=http|clamd, MALWARE_SCAN_URL, "
                "and MALWARE_SCAN_REQUIRE_CLEAN=true"
            )
        # Production requires reachable object storage credentials. In-cluster MinIO
        # may use HTTP (OBJECT_STORAGE_SECURE=false); external HTTPS is terminated at Caddy.
        if not (self.object_storage_endpoint or "").strip():
            raise ValueError("OBJECT_STORAGE_ENDPOINT is required in production")
        if len(self.object_storage_access_key.strip()) < 8 or len(self.object_storage_secret_key.strip()) < 16:
            raise ValueError("production requires object storage access keys of at least 8 characters and secrets of at least 16")
        if not (self.object_storage_bucket or "").strip() or not (self.kb_upload_bucket or "").strip():
            raise ValueError("OBJECT_STORAGE_BUCKET and KB_UPLOAD_BUCKET are required in production")
        storage_values = f"{self.object_storage_access_key} {self.object_storage_secret_key}".lower()
        if any(marker in storage_values for marker in weak_markers):
            raise ValueError("object storage credentials are weak or still use a placeholder")
        if (self.monitoring_token or "").strip():
            monitoring = self.monitoring_token.strip()
            if len(monitoring) < 32 or any(marker in monitoring.lower() for marker in weak_markers):
                raise ValueError("MONITORING_TOKEN is weak or still uses a placeholder")
        seed_password = (os.environ.get("SEED_PASSWORD") or os.environ.get("LOCAL_SEED_PASSWORD") or "").strip()
        if seed_password:
            forbidden_seed = {
                "password", "123456789012", "change-me", "admin123456",
            }
            if (len(seed_password) < 12 or seed_password.lower() in forbidden_seed
                    or seed_password.lower().startswith("tingting-seed-demo-")):
                raise ValueError("SEED_PASSWORD must not use a default/demo password in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
