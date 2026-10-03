"""位置记忆与附近搜索：存储、工具执行、compare_prices 城市回填。"""

import pytest

from app.core import locations
from app.tools import price_compare as pc
from app.tools.registry import ToolContext, execute_tool

CTX = ToolContext(platform="cli", chat_id="local", user_id="me")


@pytest.fixture(autouse=True)
def _tmp_locations(tmp_path, monkeypatch):
    monkeypatch.setattr(locations, "DATA_DIR", tmp_path)


def test_parse_city():
    assert locations.parse_city("北京市朝阳区望京SOHO") == "北京市"
    assert locations.parse_city("上海市浦东新区") == "上海市"
    assert locations.parse_city("没有城市的样子") == ""


def test_location_store_roundtrip():
    locations.set_location("cli", "me", address="北京市朝阳区望京")
    entry = locations.get("cli", "me")
    assert entry["address"] == "北京市朝阳区望京"
    assert entry["city"] == "北京市"
    # 合并更新
    locations.set_location("cli", "me", lng="116.48", lat="39.99")
    entry = locations.get("cli", "me")
    assert entry["lng"] == "116.48" and entry["address"] == "北京市朝阳区望京"
    assert locations.get("cli", "other") is None


async def test_set_my_location_tool():
    result = await execute_tool(
        "set_my_location", '{"address": "上海市浦东新区世纪大道100号"}', CTX
    )
    assert "已记住" in result and "上海市浦东新区" in result
    entry = locations.get("cli", "me")
    assert entry["city"] == "上海市"

    # 缺少会话上下文 → 明确提示
    result = await execute_tool("set_my_location", '{"address": "x"}')
    assert "无法保存" in result


async def test_find_nearby_requires_location_then_config(monkeypatch):
    # 未设置位置且未配置 Key → 引导提示
    result = await execute_tool("find_nearby_places", '{"keyword": "电影院"}', CTX)
    assert "位置" in result

    locations.set_location("cli", "me", address="北京市朝阳区望京")
    # 有位置但无 Key → 提示配置高德
    result = await execute_tool("find_nearby_places", '{"keyword": "电影院"}', CTX)
    assert "高德" in result


async def test_find_nearby_formats_places(monkeypatch):
    from app.tools import nearby

    monkeypatch.setattr(nearby, "amap_configured", lambda: True)

    async def fake_geocode(address):
        return address, "116.48", "39.99"

    async def fake_nearby(keyword, lng, lat, radius=5000):
        assert (lng, lat) == ("116.48", "39.99")
        return [
            {"name": "望京影院", "address": "望京街9号", "distance_m": 600, "rating": "4.5", "cost": "45"},
            {"name": "CGV影城", "address": "阜通东大街", "distance_m": 1500, "rating": "", "cost": ""},
        ]

    monkeypatch.setattr(nearby, "geocode", fake_geocode)
    monkeypatch.setattr(nearby, "nearby_places", fake_nearby)

    # 先设位置（带坐标），再搜附近
    locations.set_location("cli", "me", address="北京市朝阳区望京", lng="116.48", lat="39.99")
    result = await execute_tool("find_nearby_places", '{"keyword": "电影院"}', CTX)
    assert "望京影院" in result and "600m" in result
    assert "1.5km" in result and "评分4.5" in result


async def test_compare_prices_uses_saved_city(monkeypatch):
    from tests.test_ranking import FakeProvider

    def fake_effective(settings):
        return [FakeProvider([])]

    monkeypatch.setattr(pc.provider_base, "build_effective", fake_effective)
    locations.set_location("cli", "me", address="深圳市南山区科技园")
    result = await execute_tool("compare_prices", '{"keyword":"电影票"}', CTX)
    assert "深圳市" in result  # 未传 city 时自动使用保存的城市
