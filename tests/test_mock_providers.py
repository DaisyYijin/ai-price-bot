"""模拟价格源：确定性、品类价格区间、四平台注册齐全。"""

import pytest

from app.core.models import Quote
from app.providers import base as provider_base
from app.providers.mock import _PRICE_RANGES, MeituanMock, DouyinMock


def test_all_four_platforms_registered():
    assert set(provider_base.available_names()) >= {"meituan", "taobao", "jd", "douyin"}


async def test_quotes_are_deterministic():
    provider = MeituanMock()
    first = await provider.search("流浪地球3", "电影票")
    second = await provider.search("流浪地球3", "电影票")
    assert first == second
    assert all(isinstance(q, Quote) for q in first)


async def test_quotes_differ_by_platform():
    meituan = await MeituanMock().search("流浪地球3", "电影票")
    douyin = await DouyinMock().search("流浪地球3", "电影票")
    assert {q.platform for q in meituan} == {"美团"}
    assert {q.platform for q in douyin} == {"抖音"}


async def test_movie_prices_within_range():
    lo, hi = _PRICE_RANGES["电影票"]
    quotes = await MeituanMock().search("任意影片", "电影票")
    assert quotes
    assert all(lo * 0.8 <= q.price <= hi * 1.1 for q in quotes)


def test_build_enabled_rejects_unknown():
    with pytest.raises(ValueError, match="未知价格源"):
        provider_base.build_enabled(["pdd"])
