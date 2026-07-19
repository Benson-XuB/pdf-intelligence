from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    dashscope_api_key: str = ""
    deepseek_api_key: str = ""
    sendgrid_api_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = "http://localhost:8000"
    guest_max_uploads: int = 1
    confidence_threshold: float = 0.85
    qwen_model: str = "qwen-vl-max"
    upload_dir: str = "./data/uploads"
    output_dir: str = "./data/outputs"
    redis_url: str = "redis://localhost:6379/0"
    enable_docling: bool = True
    docling_fast_mode: bool = False
    docling_use_vlm: bool = False
    docling_timeout_seconds: int = 120
    sec_user_agent: str = "pdf-intelligence demo@example.com"
    sec_request_interval_seconds: float = 0.12
    sec_request_timeout_seconds: int = 30
    filing_cache_dir: str = "./data/filings"
    reconciliation_abs_tolerance_millions: float = 1.0
    reconciliation_rel_tolerance: float = 0.001
    verification_rate_threshold: float = 0.90
    require_api_key: bool = False
    api_keys: str = ""
    api_rate_limit_per_minute: int = 120
    api_log_max_entries: int = 2000
    hk_cross_list_rel_tolerance: float = 0.05

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
