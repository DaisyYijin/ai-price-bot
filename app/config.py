"""全局配置：全部由 .env / 环境变量驱动，未启用的平台不加载。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- AI 大模型（OpenAI 兼容）----
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 90.0

    # ---- 企业微信（自建应用）----
    wecom_enabled: bool = False
    wecom_corp_id: str = ""
    wecom_agent_id: int = 0
    wecom_secret: str = ""
    wecom_token: str = ""
    wecom_encoding_aes_key: str = ""

    # ---- 钉钉（Stream 模式）----
    dingtalk_enabled: bool = False
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""

    # ---- QQ 官方机器人 ----
    qq_enabled: bool = False
    qq_app_id: str = ""
    qq_client_secret: str = ""

    # ---- 比价 / 会话 ----
    price_providers: str = "meituan,taobao,jd,douyin"
    history_rounds: int = 10

    def enabled_provider_names(self) -> list[str]:
        return [name.strip() for name in self.price_providers.split(",") if name.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
