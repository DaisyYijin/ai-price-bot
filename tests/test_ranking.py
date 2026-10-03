"""优惠排序链路：折扣计算、Top3 输出、sort_by/city 参数。"""

from app.core.models import Quote
from app.tools import price_compare as pc
from app.tools.registry import execute_tool


def test_quote_discount():
    assert Quote(platform="x", title="t", price=75, original_price=100).discount == 7.5
    assert Quote(platform="x", title="t", price=100, original_price=100).discount is None
    assert Quote(platform="x", title="t", price=99).discount is None


class FakeProvider:
    def __init__(self, quotes, name="fake", platform="测试"):
        self.name, self.platform, self._quotes = name, platform, quotes
        self.is_mock = False

    async def search(self, keyword, category="综合"):
        return self._quotes


async def _patch_providers(monkeypatch, quotes):
    def fake_effective(settings):
        return [FakeProvider(quotes)]

    monkeypatch.setattr(pc.provider_base, "build_effective", fake_effective)


QUOTES = [
    Quote(platform="美团", title="影院A双人券", price=59, original_price=100),   # 5.9折
    Quote(platform="抖音", title="影院B通兑", price=39, original_price=80),      # 4.9折 最大
    Quote(platform="淘宝", title="影院C代兑", price=29, original_price=60),      # 4.8折? 29/60=4.8
    Quote(platform="京东", title="影院D无折扣", price=35),
]


async def test_sort_by_discount(monkeypatch):
    await _patch_providers(monkeypatch, QUOTES)
    result = await execute_tool(
        "compare_prices",
        '{"keyword":"电影票","category":"电影票","sort_by":"优惠幅度"}',
    )
    assert "优惠幅度前3" in result and "推荐" in result
    # 折扣标注存在
    assert "折" in result
    # 每条报价带约X折（无原价的那条除外）
    assert "约4.8折" in result or "约4.9折" in result


async def test_sort_by_price_default(monkeypatch):
    await _patch_providers(monkeypatch, QUOTES)
    result = await execute_tool("compare_prices", '{"keyword":"电影票"}')
    assert "当前最低价" in result
    assert "淘宝" in result  # ¥29 最低


async def test_city_passed_through(monkeypatch):
    await _patch_providers(monkeypatch, QUOTES)
    result = await execute_tool(
        "compare_prices", '{"keyword":"电影票","city":"北京"}'
    )
    assert "北京" in result


async def test_invalid_sort_falls_back(monkeypatch):
    await _patch_providers(monkeypatch, QUOTES)
    result = await execute_tool(
        "compare_prices", '{"keyword":"x","sort_by":"whatever"}'
    )
    assert "当前最低价" in result  # 回落价格排序
