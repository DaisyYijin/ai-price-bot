"""OpenAI 兼容 LLM 客户端（DeepSeek / GLM / Kimi / Ollama 等通用）。"""

import logging

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是「小价」，一个跨平台比价 AI 助手，部署在企业微信、钉钉、QQ 里。

职责与风格：
- 用户表达任何消费意图（想看电影、买手机、点外卖、找附近足疗/美食团购、比价）时，调用 \
compare_prices 工具查询各平台报价，再用简明中文总结。
- 用户问「哪个优惠最大 / 最划算 / 折扣最大」时，sort_by 用「优惠幅度」；问「最便宜 / 最低价」时用「价格」。\
回答时按工具返回的排序结论组织：先给出推荐（哪家、多少钱、几折、为什么），再列其余选项。
- 用户提到城市（如「北京的电影院」）时把城市传给工具的 city 参数；没提城市而问「附近」时，\
正常查询并在结尾注明「位置按服务器/登录账号所在城市，如需其他城市请说城市名」。
- 报价来自工具返回，不要编造数字；没有数据或某平台查询失败就如实说明，可建议用户稍后再试。
- 回复保持简短（聊天软件场景）：推荐结论放最前面，列表最多列 3-5 条，用分行，少用长段落。
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

    async def aclose(self) -> None:
        """管理后台热重载配置后，旧客户端连接池由此释放。"""
        await self._client.close()

    async def chat(self, messages: list[dict], tools: list[dict] | None = None):
        """一次补全调用，返回原始 choice.message（可能含 tool_calls）。"""
        kwargs: dict = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = await self._client.chat.completions.create(**kwargs)
        return response.choices[0].message
