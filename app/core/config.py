import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv(override=True)


class Settings(BaseSettings):
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    REDDIT_USER_AGENT: str = "foxhound/0.1"
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    APP_BASE_URL: str = "http://127.0.0.1:8000"

    model_config = {"env_prefix": "FOXHOUND_", "extra": "ignore"}

    @property
    def tinyfish_api_key(self) -> str:
        return os.environ.get("TINYFISH_API_KEY", "")

    @property
    def anthropic_api_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def llm_model_default(self) -> str:
        return os.environ.get("FOXHOUND_LLM_MODEL", "claude-sonnet-4-20250514")

    @property
    def llm_model_premium(self) -> str:
        return os.environ.get("FOXHOUND_LLM_MODEL_PREMIUM", "claude-sonnet-4-20250514")

    @property
    def agent_model(self) -> str:
        return os.environ.get("FOXHOUND_AGENT_MODEL", "claude-sonnet-4-20250514")

    @property
    def translator_timeout_seconds(self) -> float:
        raw = os.environ.get("FOXHOUND_TRANSLATOR_TIMEOUT_SECONDS", "8")
        try:
            return max(float(raw), 1.0)
        except Exception:
            return 8.0

    @property
    def tinyfish_timeout_seconds(self) -> float:
        """TinyFish SDK timeout. Default 600s (SDK default). Don't reduce below 300s
        — ATS forms are complex and TinyFish's internal timeout is ~5 minutes."""
        raw = os.environ.get("FOXHOUND_TINYFISH_TIMEOUT_SECONDS", "600")
        try:
            return max(float(raw), 60.0)
        except Exception:
            return 600.0

    @property
    def tinyfish_proxy_url(self) -> str:
        return os.environ.get("TINYFISH_PROXY_URL", "")

    @property
    def discord_webhook_url(self) -> str:
        return os.environ.get("FOXHOUND_DISCORD_WEBHOOK_URL", "")

    @property
    def slack_webhook_url(self) -> str:
        return os.environ.get("FOXHOUND_SLACK_WEBHOOK_URL", "")

    @property
    def sms_webhook_url(self) -> str:
        return os.environ.get("FOXHOUND_SMS_WEBHOOK_URL", "")

    @property
    def internal_token(self) -> str:
        return os.environ.get("FOXHOUND_INTERNAL_TOKEN", "")

    # --- Channel webhook verification ---

    @property
    def slack_signing_secret(self) -> str:
        return os.environ.get("SLACK_SIGNING_SECRET", "")

    @property
    def discord_public_key(self) -> str:
        return os.environ.get("DISCORD_PUBLIC_KEY", "")

    @property
    def twilio_auth_token(self) -> str:
        return os.environ.get("TWILIO_AUTH_TOKEN", "")

    @property
    def skip_webhook_verify(self) -> bool:
        return os.environ.get("FOXHOUND_SKIP_WEBHOOK_VERIFY", "") == "1"

    # --- Fly.io (sandbox preview deployment) ---

    @property
    def fly_api_token(self) -> str:
        return os.environ.get("FLY_API_TOKEN", "")

    @property
    def fly_org(self) -> str:
        return os.environ.get("FLY_ORG", "personal")

    @property
    def fly_region(self) -> str:
        return os.environ.get("FLY_REGION", "iad")

    @property
    def fly_sandbox_image(self) -> str:
        return os.environ.get("FLY_SANDBOX_IMAGE", "registry.fly.io/foxhound-sandbox:latest")

    @property
    def fly_machine_size(self) -> str:
        """Machine size preset: shared-cpu-1x with 512MB RAM."""
        return os.environ.get("FLY_MACHINE_SIZE", "shared-cpu-1x")

    @property
    def fly_machine_memory_mb(self) -> int:
        return int(os.environ.get("FLY_MACHINE_MEMORY_MB", "512"))

    @property
    def preview_ttl_hours(self) -> int:
        return int(os.environ.get("FOXHOUND_PREVIEW_TTL_HOURS", "24"))

    # --- Supabase (auth for Foxhound itself) ---

    @property
    def supabase_url(self) -> str:
        return os.environ.get("SUPABASE_URL", "")

    @property
    def supabase_anon_key(self) -> str:
        return os.environ.get("SUPABASE_ANON_KEY", "")

    @property
    def supabase_service_key(self) -> str:
        return os.environ.get("SUPABASE_SERVICE_KEY", "")

    @property
    def supabase_storage_url(self) -> str:
        base = self.supabase_url.rstrip("/")
        return f"{base}/storage/v1" if base else ""

    # --- Codegen model routing ---

    @property
    def codegen_model_heavy(self) -> str:
        """Model for heavy codegen passes (core logic, frontend)."""
        return os.environ.get("FOXHOUND_CODEGEN_MODEL_HEAVY", "claude-opus-4-20250514")

    @property
    def codegen_model_light(self) -> str:
        """Model for light codegen passes (planning, infra boilerplate)."""
        return os.environ.get("FOXHOUND_CODEGEN_MODEL_LIGHT", "claude-haiku-4-5-20251001")


settings = Settings()
