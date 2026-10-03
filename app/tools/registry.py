"""LLM 工具注册表：JSON Schema 定义 + 执行器映射。"""

import json

from pydantic import BaseModel

from app.tools import nearby
from app.tools.price_compare import CATEGORIES, SORT_MODES, execute_compare_prices


class ToolContext(BaseModel):
    """工具执行的会话上下文：让工具知道是谁在问（位置记忆按用户隔离）。"""

    platform: str = ""
    chat_id: str = ""
    user_id: str = ""


TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "compare_prices",
            "description": (
                "跨平台比价查询。当用户表达购买、比价、想看某电影、找附近团购优惠等消费意图时调用，"
                "返回美团/淘宝/京东/抖音等平台的报价列表与排序结论。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "商品、影片或团购项目关键词，如「流浪地球3」「足疗」「海底捞」",
                    },
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                        "description": "消费品类，不确定时用「综合」；看电影/购票类用「电影票」",
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": SORT_MODES,
                        "description": "用户要「优惠最大/折扣最大/划算」选「优惠幅度」；要「最便宜/最低价」选「价格」",
                    },
                    "city": {
                        "type": "string",
                        "description": "用户提到的城市（如「北京的影院」→北京）；未提及则自动用用户保存的位置",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_my_location",
            "description": (
                "记住用户的位置。用户说「我在XX市XX区/我的地址是XX/定位在XX」时调用。"
                "保存后，之后的「附近」类查询都会用这个位置。用户没给过位置时，先向用户要地址。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "用户提供的地址，尽量含城市，如「北京市朝阳区望京SOHO」",
                    },
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_nearby_places",
            "description": (
                "查找用户附近的场所（基于用户保存的位置）。用户问「附近的电影院/足疗店/火锅店」时调用，"
                "返回按距离排序的场所列表（名称、距离、地址、评分、人均）。"
                "之后可对推荐场所再调 compare_prices 查团购优惠。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "场所类型关键词，如「电影院」「足疗」「火锅」",
                    },
                    "radius_meters": {
                        "type": "integer",
                        "description": "搜索半径（米），默认 5000",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
]


async def execute_tool(name: str, arguments_json: str, ctx: ToolContext | None = None) -> str:
    """执行一次工具调用；未知工具或参数错误返回错误文本供模型自行纠正。"""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        return f"工具参数不是合法 JSON：{exc}"
    if not isinstance(args, dict):
        return "工具参数必须是 JSON 对象"

    if name == "compare_prices":
        keyword = str(args.get("keyword", "")).strip()
        if not keyword:
            return "缺少必填参数 keyword"
        category = str(args.get("category") or "综合").strip()
        sort_by = str(args.get("sort_by") or "价格").strip()
        if sort_by not in SORT_MODES:
            sort_by = "价格"
        city = str(args.get("city") or "").strip()
        return await execute_compare_prices(keyword, category, sort_by, city, ctx=ctx)

    if name == "set_my_location":
        return await _execute_set_location(str(args.get("address") or "").strip(), ctx)

    if name == "find_nearby_places":
        return await _execute_find_nearby(
            str(args.get("keyword") or "").strip(),
            args.get("radius_meters") or 5000,
            ctx,
        )

    return f"未知工具：{name}"


async def _execute_set_location(address: str, ctx: ToolContext | None) -> str:
    if not address:
        return "缺少地址参数"
    if not (ctx and ctx.user_id):
        return "当前会话无法保存位置（缺少用户标识）"
    from app.core import locations

    fields: dict = {"address": address}
    if nearby.amap_configured():
        try:
            formatted, lng, lat = await nearby.geocode(address)
            fields.update(address=formatted, lng=lng, lat=lat)
        except Exception as exc:  # 地址编码失败不阻塞保存
            return f"位置已尝试保存，但地址解析失败：{exc}。可让用户换个更具体的地址再试。"
    entry = locations.set_location(ctx.platform, ctx.user_id, **fields)
    where = entry.get("address") or address
    return f"已记住你的位置：{where}。之后可以直接问「附近的电影院/足疗店」了。"


async def _execute_find_nearby(keyword: str, radius, ctx: ToolContext | None) -> str:
    if not keyword:
        return "缺少场所关键词"
    if not (ctx and ctx.user_id):
        return "当前会话无法确定位置（缺少用户标识）"
    from app.core import locations

    location = locations.get(ctx.platform, ctx.user_id)
    if not location or not (location.get("lng") and location.get("lat")):
        if not nearby.amap_configured():
            return (
                "还不知道你的位置，且未配置高德Key无法解析地址。请先在管理后台配置高德Key，"
                "然后让用户发一句「我在XX市XX区」（企业微信用户可直接发送定位）。"
            )
        if not location:
            return "还不知道你的位置。请先让用户提供地址（说「我在XX市XX区」），我再帮你找附近的。"
        # 有地址没坐标 → 现场地理编码
        try:
            formatted, lng, lat = await nearby.geocode(location.get("address", ""))
            locations.set_location(ctx.platform, ctx.user_id, address=formatted, lng=lng, lat=lat)
            location = locations.get(ctx.platform, ctx.user_id) or {}
        except Exception as exc:
            return f"位置解析失败：{exc}"
    if not nearby.amap_configured():
        return "未配置高德Key（管理后台「高德地图」分区填写），无法搜索附近场所。"

    try:
        radius_meters = max(1000, min(int(radius), 50000))
    except (TypeError, ValueError):
        radius_meters = 5000
    try:
        places = await nearby.nearby_places(keyword, str(location["lng"]), str(location["lat"]), radius_meters)
    except Exception as exc:
        return f"附近搜索失败：{exc}"

    if not places:
        return f"{radius_meters // 1000} 公里内没有找到「{keyword}」，可以试试扩大范围或换个说法。"
    lines = []
    for i, p in enumerate(places, 1):
        distance = f"{p['distance_m'] / 1000:.1f}km" if p["distance_m"] >= 1000 else f"{p['distance_m']}m"
        extras = []
        if p.get("rating"):
            extras.append(f"评分{p['rating']}")
        if p.get("cost"):
            extras.append(f"人均¥{p['cost']}")
        extra = f"（{'，'.join(extras)}）" if extras else ""
        lines.append(f"{i}. {p['name']}｜{distance}｜{p['address'] or '地址见地图'}{extra}")
    return f"你附近（{radius_meters // 1000}公里内）的「{keyword}」按距离排序：\n" + "\n".join(lines)
