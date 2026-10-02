"""全局配置：由 .env / config/config.env / 环境变量驱动，未启用的平台不加载。

优先级（低→高）：.env → config/config.env → 环境变量。
config/config.env 由网页管理后台维护。

持久化目录分工（均可用环境变量覆盖，Docker 各自挂载独立卷）：
  CONFIG_DIR  配置文件（默认 config/）→ config.env
  DATA_DIR    凭据（默认 data/）      → admin_password、session.key
  LOG_DIR     日志（默认 logs/）      → app.log
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "config"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
LOG_DIR = Path(os.environ.get("LOG_DIR", "logs"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", CONFIG_DIR / "config.env"),
        env_file_encoding="utf-8",
        extra="ignore",
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


def reload_settings() -> None:
    """管理后台保存配置后调用：清缓存，后续 get_settings() 读到新值。"""
    get_settings.cache_clear()
