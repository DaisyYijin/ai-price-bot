"""真实数据源：签名算法、响应映射（mock HTTP）、密钥解析选择。"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.providers import base as provider_base
from app.providers.dataoke import DataokeProvider, dataoke_sign
from app.providers.jd_union import JdUnionProvider, jd_union_sign
from app.providers.mock import JdMock, MeituanMock


def test_dataoke_sign_vector():
    # 升序 k+v 拼接、secret 包首尾、MD5 小写
    expected = hashlib.md5("secreta1b2secret".encode()).hexdigest()
    assert dataoke_sign({"b": "2", "a": "1"}, "secret") == expected
    assert dataoke_sign({"b": "2", "a": "1"}, "secret").islower()


def test_jd_union_sign_vector():
    # 同样规则但大写
    expected = hashlib.md5("secreta1b2secret".encode()).hexdigest().upper()
    assert jd_union_sign({"b": "2", "a": "1"}, "secret") == expected


def _fake_settings(**kwargs):
    defaults = dict(
        enabled_provider_names=lambda: ["meituan", "taobao", "jd", "douyin"],
        dataoke_app_key="dk-key",
        dataoke_app_secret="dk-secret",
        jd_union_app_key="jd-key",
        jd_union_secret_key="jd-secret",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


async def test_dataoke_mapping(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "list": [
                {
                    "goodsName": "小米手机 12",
                    "actualPrice": "1999.0",
                    "originalPrice": "2299.0",
                    "couponPrice": "100",
                    "shopName": "小米官方旗舰店",
                    "marketingMainLink": "https://uland.taobao.com/x",
                },
                {"title": "旧字段商品", "actualPrice": "59.9"},
            ]
        },
    }

    async def fake_get_json(url, params):
        assert url.endswith("get-goods-list") and "sign" in params
        return payload

    monkeypatch.setattr("app.providers.dataoke.get_settings", lambda: _fake_settings())
    monkeypatch.setattr("app.providers.dataoke._get_json", fake_get_json)
    quotes = await DataokeProvider().search("小米手机")
    assert len(quotes) == 2
    assert quotes[0].platform == "淘宝"
    assert quotes[0].price == 1999.0
    assert quotes[0].original_price == 2299.0
    assert "小米官方旗舰店" in quotes[0].remark and "券" in quotes[0].remark
    assert quotes[0].url == "https://uland.taobao.com/x"
    assert quotes[1].title == "旧字段商品"  # 新旧字段名兼容


async def test_dataoke_api_error(monkeypatch):
    async def fake_get_json(url, params):
        return {"code": 1001, "msg": "签名错误"}

    monkeypatch.setattr("app.providers.dataoke.get_settings", lambda: _fake_settings())
    monkeypatch.setattr("app.providers.dataoke._get_json", fake_get_json)
    with pytest.raises(RuntimeError, match="大淘客接口错误"):
        await DataokeProvider().search("x")


async def test_jd_union_mapping(monkeypatch):
    inner = {
        "code": 0,
        "data": {
            "list": [
                {
                    "skuName": "京东自营商品A",
                    "priceInfo": {"price": "99.00", "lowestPrice": "89.00"},
                    "materialUrl": "https://u.jd.com/xyz",
                    "couponInfo": {"couponList": [{"quota": "100.0", "discount": "10.0"}]},
                }
            ]
        },
    }
    payload = {"jd_union_open_goods_query_responce": {"code": "0", "queryResult": json.dumps(inner)}}

    async def fake_post_json(url, data):
        assert url == "https://api.jd.com/routerjson" and "sign" in data
        return payload

    monkeypatch.setattr("app.providers.jd_union.get_settings", lambda: _fake_settings())
    monkeypatch.setattr("app.providers.jd_union._post_json", fake_post_json)
    quotes = await JdUnionProvider().search("商品A")
    assert quotes[0].platform == "京东"
    assert quotes[0].price == 89.0
    assert quotes[0].original_price == 99.0
    assert "满100减10" in quotes[0].remark


async def test_jd_union_api_error(monkeypatch):
    inner = {"code": 1, "message": "app_key 不存在"}
    payload = {"jd_union_open_goods_query_responce": {"queryResult": json.dumps(inner)}}

    async def fake_post_json(url, data):
        return payload

    monkeypatch.setattr("app.providers.jd_union.get_settings", lambda: _fake_settings())
    monkeypatch.setattr("app.providers.jd_union._post_json", fake_post_json)
    with pytest.raises(RuntimeError, match="京东联盟接口错误"):
        await JdUnionProvider().search("x")


def test_build_effective_prefers_real_when_configured():
    settings = _fake_settings(
        enabled_provider_names=lambda: ["meituan", "taobao", "jd"],
        jd_union_app_key="",
        jd_union_secret_key="",
    )
    providers = provider_base.build_effective(settings)
    assert isinstance(providers[0], MeituanMock)
    assert isinstance(providers[1], DataokeProvider)  # 配了大淘客密钥 → 真实源
    assert isinstance(providers[2], JdMock)  # 京东密钥为空 → 回落模拟
    assert providers[0].is_mock is True and providers[1].is_mock is False


def test_build_effective_browser_meituan(monkeypatch, tmp_path):
    """浏览器开关+已登录 → 美团用浏览器真实 Provider；未登录回落模拟。"""
    from app.browser import manager as bm
    from app.providers.browser_meituan import BrowserMeituanProvider

    monkeypatch.setattr(bm, "DATA_DIR", tmp_path)
    settings = _fake_settings(browser_enabled=True)
    # 未登录 → 模拟
    assert isinstance(provider_base.build_effective(settings)[0], MeituanMock)
    # 已登录 → 浏览器真实源
    bm.mark_logged_in("meituan")
    providers = provider_base.build_effective(_fake_settings(browser_enabled=True))
    assert isinstance(providers[0], BrowserMeituanProvider)
    # 开关关闭时即使已登录也回落模拟
    assert isinstance(provider_base.build_effective(_fake_settings(browser_enabled=False))[0], MeituanMock)


async def test_browser_meituan_requires_login(monkeypatch, tmp_path):
    from app.browser import manager as bm
    from app.providers.browser_meituan import BrowserMeituanProvider

    monkeypatch.setattr(bm, "DATA_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="未登录"):
        await BrowserMeituanProvider().search("足疗")
