"""OpenAI 兼容 LLM 客户端（DeepSeek / GLM / Kimi / Ollama 等通用）。"""

import logging

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是「小价」，一个跨平台比价 AI 助手，部署在企业微信、钉钉、QQ 里。

职责与风格：
- 用户表达任何消费意图（想看电影、买手机、点外卖、比价）时，调用 compare_prices \
工具查询各平台报价，再用简明中文总结：分平台列出价格，指出最低价和你的建议。
- 报价来自工具返回，不要编造数字；没有数据就如实说明。
- 回复保持简短（聊天软件场景），多用分行列表，少用长段落。
- 与消费无关的闲聊可以正常回应，但别过度推销比价。
"""


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "EMPTY",
            timeout=settings.llm_timeout,
        )
        self.model = settings.llm_model

    @property
    def configured(self) -> bool:
        return bool(get_settings().llm_api_key)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None):
        """一次补全调用，返回原始 choice.message（可能含 tool_calls）。"""
        kwargs: dict = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = await self._client.chat.completions.create(**kwargs)
        return response.choices[0].message
