"""大淘客（Dataoke）真实数据源 → 淘宝报价。

注册: www.dataoke.com → 开放平台创建应用，获取 AppKey / AppSecret。
接口: GET https://openapi.dataoke.com/api/goods/get-goods-list
签名: 参数按 key 升序拼 k+v，secret 包首尾，MD5 小写。

字段做了多候选兼容（goodsName/title、actualPrice 等），官方字段命名
随版本有过调整；解析失败会抛错并在比价结果里显示为该平台查询失败。
"""

import hashlib

import httpx

from app.config import get_settings
from app.core.models import Quote
from app.providers.base import PriceProvider

_GOODS_LIST_URL = "https://openapi.dataoke.com/api/goods/get-goods-list"
_API_VERSION = "v1.2.4"


def dataoke_sign(params: dict[str, str], secret: str) -> str:
    concat = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hashlib.md5(f"{secret}{concat}{secret}".encode("utf-8")).hexdigest()


def _to_float(value) -> float | None:
    try:
        result = float(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


async def _get_json(url: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


class DataokeProvider(PriceProvider):
    name = "dataoke"
    platform = "淘宝"
    is_mock = False

    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        settings = get_settings()
        params = {
            "appKey": settings.dataoke_app_key,
            "version": _API_VERSION,
            "keyWords": keyword,
            "pageId": "1",
            "pageSize": "4",
        }
        params["sign"] = dataoke_sign(params, settings.dataoke_app_secret)
        data = await _get_json(_GOODS_LIST_URL, params)
        if data.get("code") != 0:
            raise RuntimeError(f"大淘客接口错误: {data.get('msg') or data}")
        items = (data.get("data") or {}).get("list") or []

        quotes: list[Quote] = []
        for item in items:
            price = _to_float(item.get("actualPrice")) or _to_float(item.get("originPrice"))
            if price is None:
                continue
            original = _to_float(item.get("originalPrice")) or _to_float(item.get("shopPrice"))
            shop = item.get("shopName")
            coupon = _to_float(item.get("couponPrice"))
            remark = "真实报价"
            if shop:
                remark += f" · {shop}"
            if coupon:
                remark += f" · 可用券¥{coupon:g}"
            quotes.append(
                Quote(
                    platform=self.platform,
                    title=item.get("goodsName") or item.get("title") or keyword,
                    price=price,
                    original_price=original if original and original > price else None,
                    url=item.get("marketingMainLink") or item.get("dtkLink") or item.get("itemLink"),
                    remark=remark,
                )
            )
        return quotes
