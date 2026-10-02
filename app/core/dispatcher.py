"""消息调度器：统一消息 → 会话历史 → LLM 工具循环 → 回复文本。"""

import logging

from app.core.history import ConversationHistory
from app.core.models import InboundMessage
from app.llm.client import SYSTEM_PROMPT, LLMClient
from app.tools.registry import TOOL_SPECS, execute_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3


class Dispatcher:
    def __init__(self, llm: LLMClient | None = None, history: ConversationHistory | None = None):
        self.llm = llm or LLMClient()
        self.history = history or ConversationHistory()

    async def handle(self, msg: InboundMessage) -> str:
        """处理一条入站消息，返回回复文本。异常统一兜底为用户可读的话。"""
        self.history.append(msg.platform, msg.chat_id, "user", msg.text)
        try:
            reply = await self._run_llm_loop(msg)
        except Exception as exc:  # noqa: BLE001 — 平台侧只应看到可读错误
            logger.exception("处理消息失败")
            reply = f"处理出错了：{exc}"
        self.history.append(msg.platform, msg.chat_id, "assistant", reply)
        return reply

    async def _run_llm_loop(self, msg: InboundMessage) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.history.messages(msg.platform, msg.chat_id),
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            answer = await self.llm.chat(messages, tools=TOOL_SPECS)
            if not answer.tool_calls:
                return answer.content or "（我暂时没有想好怎么回复）"
            messages.append(
                {
                    "role": "assistant",
                    "content": answer.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in answer.tool_calls
                    ],
                }
            )
            for call in answer.tool_calls:
                result = await execute_tool(call.function.name, call.function.arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )
        # 工具轮次用尽，强制不带工具收尾
        final = await self.llm.chat(messages, tools=None)
        return final.content or "（比价结果处理超时，请稍后再试）"
