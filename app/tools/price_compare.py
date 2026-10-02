"""compare_prices 工具：并行查询所有启用的价格源并汇总。"""

import asyncio
import logging

from app.config import get_settings
from app.core.models import Quote
from app.providers import base as provider_base

logger = logging.getLogger(__name__)

CATEGORIES = ["电影票", "外卖", "数码", "图书", "服装", "美妆", "综合"]

_QUOTE_LINE = "【{platform}】{title} —— ¥{price}{original}{url}"


async def execute_compare_prices(keyword: str, category: str = "综合") -> str:
    """供 LLM function calling 调用的比价实现，返回给模型阅读的文本。"""
    settings = get_settings()
    providers = provider_base.build_enabled(settings.enabled_provider_names())
    if not providers:
        return "当前没有启用任何价格数据源（检查 .env 的 PRICE_PROVIDERS）。"

    results = await asyncio.gather(
        *(p.search(keyword, category) for p in providers),
        return_exceptions=True,
    )

    chunks: list[str] = []
    all_quotes: list[Quote] = []
    for provider, result in zip(providers, results):
        if isinstance(result, BaseException):
            logger.warning("价格源 %s 查询失败: %s", provider.name, result)
            chunks.append(f"【{provider.platform}】查询失败：{result}")
            continue
        if not result:
            chunks.append(f"【{provider.platform}】无相关报价")
            continue
        all_quotes.extend(result)
        chunks.append(
            "\n".join(
                _QUOTE_LINE.format(
                    platform=q.platform,
                    title=q.title,
                    price=f"{q.price:g}",
                    original=f"（原价 ¥{q.original_price:g}）" if q.original_price else "",
                    url=f"\n    链接：{q.url}" if q.url else "",
                )
                for q in result
            )
        )

    summary = ""
    if all_quotes:
        best = min(all_quotes, key=lambda q: q.price)
        summary = f"\n\n当前最低价：{best.platform} ¥{best.price:g}（{best.title}）"

    return (
        f"关键词「{keyword}」（品类：{category}）各平台报价如下：\n\n"
        + "\n\n".join(chunks)
        + summary
        + "\n\n注：当前为模拟数据，仅用于演示流程。"
    )
