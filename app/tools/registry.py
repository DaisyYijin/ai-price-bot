"""LLM 工具注册表：JSON Schema 定义 + 执行器映射。"""

import json

from app.tools.price_compare import CATEGORIES, execute_compare_prices

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "compare_prices",
            "description": (
                "跨平台比价查询。当用户表达购买、比价、想看某电影等消费意图时调用，"
                "返回美团/淘宝/京东/抖音等平台对同一商品或影片的报价列表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "商品或影片名称关键词，如「流浪地球3」「 AirPods Pro 3」",
                    },
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                        "description": "消费品类，不确定时用「综合」；看电影/购票类用「电影票」",
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
    return await execute_compare_prices(keyword, category)
