"""compare_prices 工具：并行查询所有启用的价格源，按用户意图排序并汇总。"""

import asyncio
import logging

from app.config import get_settings
from app.core.models import Quote
from app.providers import base as provider_base

logger = logging.getLogger(__name__)

CATEGORIES = ["电影票", "外卖", "数码", "图书", "服装", "美妆", "综合"]
SORT_MODES = ["优惠幅度", "价格"]

_QUOTE_LINE = "【{platform}】{title} —— ¥{price}{original}{discount}{url}"


async def execute_compare_prices(
    keyword: str,
    category: str = "综合",
    sort_by: str = "价格",
    city: str = "",
    ctx=None,
) -> str:
    """供 LLM function calling 调用的比价实现，返回给模型阅读的文本。

    sort_by：用户要「优惠最大/折扣」按 优惠幅度；要「最便宜/最低价」按 价格。
    city 未指定时自动使用该用户保存的位置城市（若有）。
    """
    settings = get_settings()
    providers = provider_base.build_effective(settings)
    if not providers:
        return "当前没有启用任何价格数据源（检查 .env 的 PRICE_PROVIDERS）。"

    if not city:
        from app.core import locations

        location = None
        if ctx is not None and ctx.user_id:
            location = locations.get(ctx.platform, ctx.user_id)
        location = location or locations.get_default()
        if location and location.get("city"):
            city = location["city"]

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
            "\n".join(_format_quote(q) for q in result)
        )

    header = f"关键词「{keyword}」（品类：{category}）"
    if city:
        header += f" 目标城市：{city}"

    summary = _rank_summary(all_quotes, sort_by)

    mock_note = (
        "\n\n注：标注「真实」的来自真实抓取/联盟API；其余平台为模拟报价（未接入真实数据源）。"
        if any(getattr(p, "is_mock", False) for p in providers)
        else ""
    )

    return (
        f"{header}，各平台报价如下：\n\n"
        + "\n\n".join(chunks)
        + summary
        + mock_note
    )


def _format_quote(q: Quote) -> str:
    original = f"（原价¥{q.original_price:g}）" if q.original_price else ""
    discount = f" 约{q.discount:g}折" if q.discount else ""
    url = f"\n    链接：{q.url}" if q.url else ""
    return _QUOTE_LINE.format(
        platform=q.platform, title=q.title, price=f"{q.price:g}",
        original=original, discount=discount, url=url,
    )


def _rank_summary(all_quotes: list[Quote], sort_by: str) -> str:
    """生成排序结论：按优惠幅度或价格排出前三并给出推荐。"""
    if not all_quotes:
        return ""
    if sort_by == "优惠幅度":
        with_discount = [q for q in all_quotes if q.discount]
        if not with_discount:
            best = min(all_quotes, key=lambda q: q.price)
            return (
                f"\n\n无折扣信息可比，按最低价：{best.platform} ¥{best.price:g}（{best.title}）"
            )
        ranked = sorted(with_discount, key=lambda q: q.discount)
        lines = [
            f"{i}. {q.platform}｜{q.title}｜¥{q.price:g}（原¥{q.original_price:g}，约{q.discount:g}折）"
            for i, q in enumerate(ranked[:3], 1)
        ]
        best = ranked[0]
        return (
            "\n\n优惠幅度前3：\n" + "\n".join(lines)
            + f"\n推荐：{best.platform}「{best.title}」，¥{best.price:g} 约{best.discount:g}折，优惠最大"
        )
    best = min(all_quotes, key=lambda q: q.price)
    return f"\n\n当前最低价：{best.platform} ¥{best.price:g}（{best.title}）"
