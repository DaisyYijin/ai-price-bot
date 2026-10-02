"""工具层：compare_prices 汇总与参数校验。"""

from app.tools.registry import TOOL_SPECS, execute_tool


async def test_compare_prices_covers_all_platforms():
    result = await execute_tool(
        "compare_prices", '{"keyword": "流浪地球3", "category": "电影票"}'
    )
    for platform in ("美团", "淘宝", "京东", "抖音"):
        assert platform in result
    assert "最低价" in result


async def test_execute_tool_rejects_missing_keyword():
    result = await execute_tool("compare_prices", "{}")
    assert "keyword" in result


async def test_execute_tool_rejects_bad_json():
    result = await execute_tool("compare_prices", "{oops")
    assert "JSON" in result


async def test_execute_tool_unknown_tool():
    assert "未知工具" in await execute_tool("nope", "{}")


def test_tool_spec_shape():
    spec = TOOL_SPECS[0]["function"]
    assert spec["name"] == "compare_prices"
    assert "keyword" in spec["parameters"]["required"]
