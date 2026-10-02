"""京东联盟（JD Union）真实数据源 → 京东报价。

注册: union.jd.com → 推广管理 → API 申请 AppKey / AppSecretKey（个人实名即可，
jd.union.open.goods.query 商品查询无需 OAuth 授权）。
接口: POST https://api.jd.com/routerjson（method=jd.union.open.goods.query）
签名: 全部系统参数按 key 升序拼 k+v，secret 包首尾，MD5 大写。
"""

import hashlib
import json
from datetime import datetime

import httpx

from app.config import get_settings
from app.core.models import Quote
from app.providers.base import PriceProvider

_ROUTER_URL = "https://api.jd.com/routerjson"
_METHOD = "jd.union.open.goods.query"


def jd_union_sign(params: dict[str, str], secret: str) -> str:
    concat = "".join(f"{k}{params[k]}" for k in sorted(params))
    return hashlib.md5(f"{secret}{concat}{secret}".encode("utf-8")).hexdigest().upper()


def _to_float(value) -> float | None:
    try:
        result = float(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


async def _post_json(url: str, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, data=data)
        resp.raise_for_status()
        return resp.json()


class JdUnionProvider(PriceProvider):
    name = "jd_union"
    platform = "京东"
    is_mock = False

    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        settings = get_settings()
        business = {"goodsReqDTO": {"keyword": keyword, "pageIndex": 1, "pageSize": 4}}
        payload = {
            "method": _METHOD,
            "app_key": settings.jd_union_app_key,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "1.0",
            "sign_method": "md5",
            "360buy_param_json": json.dumps(business, ensure_ascii=False, separators=(",", ":")),
        }
        payload["sign"] = jd_union_sign(payload, settings.jd_union_secret_key)
        data = await _post_json(_ROUTER_URL, payload)

        envelope = data.get(f"{_METHOD.replace('.', '_')}_responce") or {}
        result = envelope.get("queryResult")
        inner = json.loads(result) if isinstance(result, str) else (result or {})
        if inner.get("code") != 0:
            raise RuntimeError(f"京东联盟接口错误: {inner.get('message') or inner}")
        items = (inner.get("data") or {}).get("list") or []

        quotes: list[Quote] = []
        for item in items:
            price_info = item.get("priceInfo") or {}
            price = _to_float(price_info.get("lowestPrice")) or _to_float(price_info.get("price"))
            if price is None:
                continue
            original = _to_float(price_info.get("price"))
            coupons = ((item.get("couponInfo") or {}).get("couponList")) or []
            remark = "真实报价"
            if coupons:
                coupon = coupons[0]
                quota, discount = _to_float(coupon.get("quota")), _to_float(coupon.get("discount"))
                if quota and discount:
                    remark += f" · 满{quota:g}减{discount:g}"
            quotes.append(
                Quote(
                    platform=self.platform,
                    title=item.get("skuName") or keyword,
                    price=price,
                    original_price=original if original and original > price else None,
                    url=item.get("materialUrl") or item.get("goodsUrl"),
                    remark=remark,
                )
            )
        return quotes
