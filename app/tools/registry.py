"""LLM 工具注册表：JSON Schema 定义 + 执行器映射。"""

import json

from app.tools.price_compare import CATEGORIES, SORT_MODES, execute_compare_prices

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
                        "description": "用户提到的城市（如「北京的影院」→北京）；未提及则留空",
                    },
                },
                "required": ["keyword"],
            },
        },
    }
]


async def execute_tool(name: str, arguments_json: str) -> str:
    """执行一次工具调用；未知工具或参数错误返回错误文本供模型自行纠正。"""
    if name != "compare_prices":
        return f"未知工具：{name}"
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        return f"工具参数不是合法 JSON：{exc}"
    keyword = str(args.get("keyword", "")).strip()
    if not keyword:
        return "缺少必填参数 keyword"
    category = str(args.get("category") or "综合").strip()
    sort_by = str(args.get("sort_by") or "价格").strip()
    if sort_by not in SORT_MODES:
        sort_by = "价格"
    city = str(args.get("city") or "").strip()
    return await execute_compare_prices(keyword, category, sort_by, city)
