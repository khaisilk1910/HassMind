import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Home Assistant
    ha_url: str = "http://127.0.0.1:8123"
    ha_token_file: str = "/run/secrets/ha_token"
    ha_token: str = ""
    ha_notify_service: str = ""

    # OpenAI-compatible LLM
    openai_api_key_file: str = "/run/secrets/openai_api_key"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.6"
    max_tool_rounds: int = 10

    # HassMind API/UI
    agent_name: str = "HassMind"
    db_path: str = "/data/hassmind.db"
    host: str = "0.0.0.0"
    port: int = 8090
    api_token_file: str = "/run/secrets/hassmind_api_token"
    api_token: str = ""
    runtime_secret_dir: str = "/data/secrets"
    runtime_api_token_name: str = "hassmind_api_token"
    runtime_recovery_key_name: str = "admin_recovery_key"
    timezone: str = "Asia/Ho_Chi_Minh"

    # Web admin authentication/security
    admin_username: str = "admin"
    admin_bootstrap_password_file: str = "/run/secrets/admin_password"
    admin_bootstrap_password: str = ""
    admin_recovery_key_file: str = "/run/secrets/admin_recovery_key"
    admin_recovery_key: str = ""
    admin_session_cookie: str = "hassmind_admin_session"
    admin_csrf_cookie: str = "hassmind_csrf"
    admin_session_ttl_minutes: int = 720
    admin_session_idle_minutes: int = 30
    admin_cookie_secure: bool = False
    admin_allowed_networks: str = "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    password_min_length: int = 14

    # Observability / diagnostics
    log_level: str = "INFO"
    log_format: str = "json"
    log_file_enabled: bool = True
    log_file: str = "/data/logs/hassmind.log"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    log_ring_size: int = 2000
    log_include_content: bool = False
    log_scrub_existing_on_start: bool = True
    audit_scrub_existing_on_start: bool = True

    # Core safety policy
    allow_service_domains: str = "light,switch,fan,climate,media_player,scene,input_boolean,input_number,input_select,number,select"
    deny_service_domains: str = "shell_command,hassio,homeassistant,lock,alarm_control_panel,cover,update,button"
    approval_ttl_minutes: int = 120
    auto_apply_after_approval: bool = True

    scheduler_enabled: bool = True
    event_agent_enabled: bool = True
    event_retention: int = 5000

    searxng_url: str = ""
    telegram_bot_token_file: str = "/run/secrets/telegram_bot_token"
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""

    knowledge_dir: str = "/knowledge"
    skills_dir: str = "/app/config/skills"
    mcp_config: str = "/app/config/mcp_servers.yaml"

    # Integration adapter defaults
    integration_http_timeout: float = 15.0
    integration_health_timeout: float = 3.0

    camera_tts_enabled: bool = False
    camera_tts_url: str = "http://127.0.0.1:8124"
    camera_tts_api_key_file: str = "/run/secrets/camera_tts_api_key"
    camera_tts_api_key: str = ""
    camera_tts_allow_actions: bool = True

    facedetect_enabled: bool = False
    facedetect_url: str = "http://127.0.0.1:8181"

    zalo_enabled: bool = False
    zalo_url: str = "http://127.0.0.1:3100"
    zalo_username: str = "admin"
    zalo_password_file: str = "/run/secrets/zalo_password"
    zalo_password: str = ""
    zalo_default_account: str = ""
    zalo_allow_send: bool = False
    zalo_webhook_enabled: bool = False
    zalo_webhook_secret_file: str = "/run/secrets/zalo_webhook_secret"
    zalo_webhook_secret: str = ""
    zalo_auto_register_webhook: bool = False
    zalo_webhook_callback_base: str = "http://127.0.0.1:8090"
    zalo_agent_reply_enabled: bool = False
    zalo_agent_allowed_thread_ids: str = ""

    wyoming_enabled: bool = False
    wyoming_host: str = "127.0.0.1"
    wyoming_port: int = 10300
    wyoming_allow_tts: bool = True

    # Home Assistant custom-component adapters
    ha_custom_integrations_enabled: bool = True
    shopping_allow_mutations: bool = False
    shopping_allow_delete: bool = False
    ytdlp_allow_playback: bool = True
    ytdlp_allow_downloads: bool = False

    @staticmethod
    def _read_optional(path: str) -> str:
        if not path:
            return ""
        p = Path(path)
        try:
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return ""

    def _runtime_secret_path(self, name: str) -> Path:
        return Path(self.runtime_secret_dir) / name

    def read_runtime_secret(self, name: str) -> str:
        return self._read_optional(str(self._runtime_secret_path(name)))

    def write_runtime_secret(self, name: str, value: str) -> Path:
        value = value.strip()
        if not value:
            raise ValueError("Secret value must not be empty")
        root = Path(self.runtime_secret_dir)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        target = self._runtime_secret_path(name)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(value, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target

    def read_ha_token(self) -> str:
        token = self._read_optional(self.ha_token_file) or self.ha_token
        if not token:
            raise RuntimeError(f"Home Assistant token not found: {self.ha_token_file}")
        return token

    def read_openai_key(self) -> str:
        return self._read_optional(self.openai_api_key_file) or self.openai_api_key

    def read_api_token(self) -> str:
        token = (
            self.read_runtime_secret(self.runtime_api_token_name)
            or self._read_optional(self.api_token_file)
            or self.api_token
        )
        if not token:
            raise RuntimeError("HassMind API token is not configured")
        return token

    def api_token_source(self) -> str:
        if self.read_runtime_secret(self.runtime_api_token_name):
            return "runtime_file"
        if self._read_optional(self.api_token_file):
            return "docker_secret"
        if self.api_token:
            return "environment"
        return "missing"

    def read_admin_bootstrap_password(self) -> str:
        return self._read_optional(self.admin_bootstrap_password_file) or self.admin_bootstrap_password

    def read_admin_recovery_key(self) -> str:
        return (
            self.read_runtime_secret(self.runtime_recovery_key_name)
            or self._read_optional(self.admin_recovery_key_file)
            or self.admin_recovery_key
        )

    def admin_recovery_key_source(self) -> str:
        if self.read_runtime_secret(self.runtime_recovery_key_name):
            return "runtime_file"
        if self._read_optional(self.admin_recovery_key_file):
            return "docker_secret"
        if self.admin_recovery_key:
            return "environment"
        return "missing"

    def read_telegram_token(self) -> str:
        return self._read_optional(self.telegram_bot_token_file) or self.telegram_bot_token

    def read_camera_tts_key(self) -> str:
        return (
            self.read_runtime_secret("integration_camera_tts_api_key")
            or self._read_optional(self.camera_tts_api_key_file)
            or self.camera_tts_api_key
        )

    def read_zalo_password(self) -> str:
        return (
            self.read_runtime_secret("integration_zalo_password")
            or self._read_optional(self.zalo_password_file)
            or self.zalo_password
        )

    def read_zalo_webhook_secret(self) -> str:
        return (
            self.read_runtime_secret("integration_zalo_webhook_secret")
            or self._read_optional(self.zalo_webhook_secret_file)
            or self.zalo_webhook_secret
        )

    def configured_secret_values(self) -> list[str]:
        values = [
            self._read_optional(self.ha_token_file), self.ha_token,
            self._read_optional(self.openai_api_key_file), self.openai_api_key,
            self.read_runtime_secret(self.runtime_api_token_name), self._read_optional(self.api_token_file), self.api_token,
            self._read_optional(self.telegram_bot_token_file), self.telegram_bot_token,
            self.read_runtime_secret("integration_camera_tts_api_key"), self._read_optional(self.camera_tts_api_key_file), self.camera_tts_api_key,
            self.read_runtime_secret("integration_zalo_password"), self._read_optional(self.zalo_password_file), self.zalo_password,
            self.read_runtime_secret("integration_zalo_webhook_secret"), self._read_optional(self.zalo_webhook_secret_file), self.zalo_webhook_secret,
            self._read_optional(self.admin_bootstrap_password_file), self.admin_bootstrap_password,
            self.read_runtime_secret(self.runtime_recovery_key_name), self._read_optional(self.admin_recovery_key_file), self.admin_recovery_key,
        ]
        return [v for v in values if isinstance(v, str) and len(v) >= 8]

    @property
    def allowed_domains(self) -> set[str]:
        return {x.strip() for x in self.allow_service_domains.split(",") if x.strip()}

    @property
    def denied_domains(self) -> set[str]:
        return {x.strip() for x in self.deny_service_domains.split(",") if x.strip()}

    @property
    def telegram_allowed_ids(self) -> set[str]:
        return {x.strip() for x in self.telegram_allowed_chat_ids.split(",") if x.strip()}

    @property
    def zalo_allowed_thread_ids(self) -> set[str]:
        return {x.strip().removeprefix("zalo:") for x in self.zalo_agent_allowed_thread_ids.split(",") if x.strip()}

    @property
    def admin_allowed_network_list(self) -> list[str]:
        return [x.strip() for x in self.admin_allowed_networks.split(",") if x.strip()]


settings = Settings()
