"""终端体验模式：python -m app.cli

配置了 LLM_API_KEY 走完整 AI 流程；未配置则退化为规则模式
（正则识别比价意图 → 直接调用 compare_prices 工具），保证零配置可跑通。
"""

import asyncio
import re

from app.core.models import InboundMessage
from app.core.dispatcher import Dispatcher
from app.llm.client import LLMClient
from app.tools.price_compare import execute_compare_prices

CATEGORY_HINTS: list[tuple[str, str]] = [
    ("想看", "电影票"), ("电影", "电影票"), ("影片", "电影票"), ("看电影", "电影票"),
    ("外卖", "外卖"), ("点餐", "外卖"), ("吃什么", "外卖"),
    ("手机|耳机|电脑|平板|airpods|switch|相机", "数码"),
    ("书", "图书"),
]

INTENT_RE = re.compile(
    r"(?:我想看|我想买|帮我查|查一下|比价|多少钱|看看|买一个|想看)\s*(?:一部)?(.+?)"
    r"(?:，|,|的)?(?:哪个?.+?|哪家.+?|价格|报价|多少钱|票|在哪买|便宜)?[?？!！。]*$",
    re.IGNORECASE,
)


async def rule_based_reply(text: str) -> str | None:
    """规则模式：识别比价意图并抽取关键词，未命中返回 None。"""
    category = "综合"
    for pattern, cat in CATEGORY_HINTS:
        if re.search(pattern, text, re.IGNORECASE):
            category = cat
            break
    match = INTENT_RE.search(text.strip())
    keyword = match.group(1).strip() if match else ""
    if not keyword:
        return None
    sort_by = "优惠幅度" if re.search(r"优惠|折扣|划算|便宜", text) else "价格"
    return await execute_compare_prices(keyword, category, sort_by)


async def chat_loop() -> None:
    llm = LLMClient()
    dispatcher = Dispatcher(llm=llm)
    use_llm = llm.configured
    if use_llm:
        print(f"已连接 LLM（{llm.model}），直接对话即可，Ctrl+C 退出。")
    else:
        print("未配置 LLM_API_KEY，进入规则模式：说「我想看xxx电影 / 帮我查xxx的价格」。")

    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            return
        if not text:
            continue
        if text in {"exit", "quit", "退出"}:
            return

        if use_llm:
            msg = InboundMessage(
                platform="cli", chat_id="local", user_id="me", user_name="我", text=text
            )
            print(f"\n小价> {await dispatcher.handle(msg)}")
        else:
            reply = await rule_based_reply(text)
            print(f"\n小价> {reply or '（规则模式下我没听懂，试试「我想看流浪地球3」；配置 LLM_API_KEY 后可自由对话）'}")


if __name__ == "__main__":
    asyncio.run(chat_loop())
