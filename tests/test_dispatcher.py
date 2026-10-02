"""调度器：工具调用循环、历史维护、异常兜底（LLM 用假对象模拟）。"""

from types import SimpleNamespace

from app.core.dispatcher import Dispatcher
from app.core.models import InboundMessage


def tool_call(name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeLLM:
    """按脚本依次返回消息；记录每次收到的 messages 便于断言。"""

    def __init__(self, script: list[SimpleNamespace]):
        self.script = list(script)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, tools=None):
        self.calls.append(messages)
        return self.script.pop(0)


def make_msg(text: str = "我想看流浪地球3") -> InboundMessage:
    return InboundMessage(platform="cli", chat_id="local", user_id="me", text=text)


async def test_plain_reply_without_tools():
    llm = FakeLLM([SimpleNamespace(content="你好呀", tool_calls=None)])
    reply = await Dispatcher(llm=llm).handle(make_msg("你好"))
    assert reply == "你好呀"


async def test_tool_round_and_history():
    llm = FakeLLM(
        [
            SimpleNamespace(content="", tool_calls=[tool_call("compare_prices", '{"keyword":"流浪地球3","category":"电影票"}')]),
            SimpleNamespace(content="抖音最低 35.9，建议入手", tool_calls=None),
        ]
    )
    dispatcher = Dispatcher(llm=llm)
    reply = await dispatcher.handle(make_msg())

    assert "抖音" in reply
    assert len(llm.calls) == 2
    # 第二轮应包含 tool 消息，且内容里有各平台报价
    tool_messages = [m for m in llm.calls[1] if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "美团" in tool_messages[0]["content"]
    assert "京东" in tool_messages[0]["content"]
    # 历史已记录一问一答
    history = dispatcher.history.messages("cli", "local")
    assert history[0] == {"role": "user", "content": "我想看流浪地球3"}
    assert history[-1]["role"] == "assistant"


async def test_llm_error_returns_readable_message():
    class BrokenLLM:
        async def chat(self, messages, tools=None):
            raise RuntimeError("连接超时")

    reply = await Dispatcher(llm=BrokenLLM()).handle(make_msg())
    assert "处理出错" in reply
