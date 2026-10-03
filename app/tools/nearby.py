"""高德地图工具：地址地理编码 + 周边场所搜索（官方 API，需管理后台配置 Key）。

注册: lbs.amap.com → 个人实名 → 创建应用 → 添加 Key（Web服务）。
"""

import httpx

from app.config import get_settings

_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
_AROUND_URL = "https://restapi.amap.com/v3/place/around"


def _key() -> str:
    return get_settings().amap_key.strip()


def amap_configured() -> bool:
    return bool(_key())


async def _get_json(url: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def geocode(address: str) -> tuple[str, str, str] | None:
    """地址 → (格式化地址, lng, lat)；失败返回 None。"""
    data = await _get_json(_GEOCODE_URL, {"address": address, "key": _key()})
    if data.get("status") != "1":
        raise RuntimeError(f"高德地理编码失败: {data.get('info') or data}")
    geocodes = data.get("geocodes") or []
    if not geocodes:
        return None
    g = geocodes[0]
    return g.get("formatted_address") or address, str(g.get("location", "")).split(",")[0], str(g.get("location", "")).split(",")[1]


async def regeo(lng: str, lat: str) -> str:
    """坐标 → 格式化地址（逆地理编码）。"""
    data = await _get_json(_REGEO_URL, {"location": f"{lng},{lat}", "key": _key()})
    if data.get("status") != "1":
        raise RuntimeError(f"高德逆地理编码失败: {data.get('info') or data}")
    return (data.get("regeocode") or {}).get("formatted_address") or ""


async def nearby_places(keyword: str, lng: str, lat: str, radius: int = 5000) -> list[dict]:
    """周边搜索：返回 [{name, address, distance_m, rating, cost}]，按距离排序。"""
    data = await _get_json(
        _AROUND_URL,
        {
            "location": f"{lng},{lat}",
            "keywords": keyword,
            "radius": radius,
            "offset": 8,
            "page": 1,
            "key": _key(),
            "extensions": "base",
        },
    )
    if data.get("status") != "1":
        raise RuntimeError(f"高德周边搜索失败: {data.get('info') or data}")
    pois = data.get("pois") or []
    results = []
    for poi in pois:
        biz = poi.get("biz_ext") or {}
        try:
            distance = int(float(poi.get("distance") or 0))
        except (TypeError, ValueError):
            distance = 0
        results.append(
            {
                "name": poi.get("name") or "",
                "address": poi.get("address") or "",
                "distance_m": distance,
                "rating": biz.get("rating") or "",
                "cost": biz.get("cost") or "",
            }
        )
    results.sort(key=lambda p: p["distance_m"])
    return results[:5]
