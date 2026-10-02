"""内置模拟价格源（美团 / 淘宝 / 京东 / 抖音）。

价格由 hash(平台+关键词+序号) 确定性生成：同一关键词永远得到同一组
报价，便于演示与测试。数据形状（原价、券后价、店铺名）按真实电商
API 返回的模样组织，后续替换为联盟 API 时上层无感知。
"""

import hashlib
import math

from app.core.models import Quote
from app.providers.base import PriceProvider, register

# 品类 → (最低价, 最高价)；未匹配品类走「综合」
_PRICE_RANGES: dict[str, tuple[float, float]] = {
    "电影票": (25.9, 79.9),
    "外卖": (15.0, 88.0),
    "餐饮": (15.0, 88.0),
    "图书": (20.0, 199.0),
    "数码": (99.0, 8999.0),
    "手机": (899.0, 8999.0),
    "服装": (39.0, 899.0),
    "美妆": (29.0, 699.0),
    "综合": (9.9, 999.0),
}

# 各平台报价的商品标题模板：电影票品类与通用品类分开，贴近真实场景
_MOVIE_TEMPLATES: dict[str, list[str]] = {
    "meituan": [
        "{kw}（特惠商户通兑券）",
        "{kw}（周末场次·小食套餐）",
    ],
    "taobao": [
        "{kw} 官方旗舰店代下单",
        "{kw} 全网通用电子券·秒发",
    ],
    "jd": [
        "{kw} 自营·电子券",
        "{kw} PLUS 会员专享价",
    ],
    "douyin": [
        "{kw} 直播间限时团购",
        "{kw} 新人立减券",
    ],
}

_GENERIC_TEMPLATES: dict[str, list[str]] = {
    "meituan": [
        "{kw}（特惠团购）",
        "{kw}（会员折扣）",
    ],
    "taobao": [
        "{kw} 官方旗舰店",
        "{kw} 顺丰包邮·秒发",
    ],
    "jd": [
        "{kw} 京东自营正品",
        "{kw} PLUS 会员专享价",
    ],
    "douyin": [
        "{kw} 直播间限时秒杀",
        "{kw} 新人专享券",
    ],
}

_PLATFORM_LABELS = {
    "meituan": "美团",
    "taobao": "淘宝",
    "jd": "京东",
    "douyin": "抖音",
}

# 平台折扣风格：券后价相对基准价的折让幅度（保持确定性差异）
_PLATFORM_BIAS = {"meituan": 0.97, "taobao": 0.90, "jd": 1.00, "douyin": 0.86}


def _stable_float(seed: str) -> float:
    """由字符串得到 [0,1) 的稳定伪随机数。"""
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0x100000000


def _round_price(value: float) -> float:
    # 价格美化：保留到 .9 / .5 结尾，贴近真实电商定价
    tens = math.floor(value)
    for candidate in (tens - 0.1, tens + 0.9, tens + 0.5, tens - 0.5):
        if candidate > 0:
            return round(candidate, 1)
    return round(value, 1)


class MockProvider(PriceProvider):
    """通用模拟源：子类只声明平台身份。"""

    offers_per_platform: int = 2

    def _make_quotes(self, keyword: str, category: str) -> list[Quote]:
        lo, hi = _PRICE_RANGES.get(category, _PRICE_RANGES["综合"])
        platform_label = self.platform or _PLATFORM_LABELS.get(self.name, self.name)
        bias = _PLATFORM_BIAS.get(self.name, 1.0)
        templates = _MOVIE_TEMPLATES if category == "电影票" else _GENERIC_TEMPLATES
        quotes: list[Quote] = []
        for idx, template in enumerate(
            templates.get(self.name, ["{kw}"])[: self.offers_per_platform]
        ):
            base = lo + (hi - lo) * _stable_float(f"{self.name}|{keyword}|{category}|{idx}")
            price = _round_price(max(lo * 0.8, base * bias))
            original = _round_price(price * (1.05 + 0.4 * _stable_float(f"orig|{self.name}|{keyword}|{idx}")))
            quotes.append(
                Quote(
                    platform=platform_label,
                    title=template.format(kw=keyword),
                    price=price,
                    original_price=original if original > price else None,
                    url=f"https://example.com/{self.name}/search?q={keyword}",
                    remark="模拟数据",
                )
            )
        return quotes

    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        return self._make_quotes(keyword, category)


@register
class MeituanMock(MockProvider):
    name = "meituan"
    platform = "美团"


@register
class TaobaoMock(MockProvider):
    name = "taobao"
    platform = "淘宝"


@register
class JdMock(MockProvider):
    name = "jd"
    platform = "京东"


@register
class DouyinMock(MockProvider):
    name = "douyin"
    platform = "抖音"
