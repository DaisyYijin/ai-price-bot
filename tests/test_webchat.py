"""网页聊天：鉴权、消息走 Dispatcher、GPS 定位按设备记忆。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core import locations
from app.main import create_app


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(locations, "DATA_DIR", tmp_path)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.admin import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path)
    app = create_app()
    return TestClient(app)


def _login(client):
    client.post("/admin/api/setup", json={"username": "admin", "password": "admin-pass-1"})


def test_message_requires_auth(client):
    assert client.post("/chat/api/message", json={"uid": "abc", "text": "hi"}).status_code == 401


def test_chat_flow_with_tools(client, monkeypatch):
    _login(client)

    # 假 LLM：先问位置工具，再作答
    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content="", tool_calls=[SimpleNamespace(
                    id="c1",
                    function=SimpleNamespace(
                        name="set_my_location",
                        arguments='{"address": "北京市朝阳区望京"}',
                    ),
                )])
            return SimpleNamespace(content="已记住位置，附近查询随时问！", tool_calls=None)

    client.app.state.dispatcher.llm = FakeLLM()
    resp = client.post("/chat/api/message", json={"uid": "device-1", "text": "我在望京"})
    assert resp.status_code == 200
    assert "已记住位置" in resp.json()["reply"]
    # 位置已按 web 设备记忆
    entry = locations.get("web", "device-1")
    assert entry and entry["city"] == "北京市"


def test_location_endpoint(client):
    _login(client)
    resp = client.post(
        "/chat/api/location",
        json={"uid": "device-2", "lat": 39.99, "lng": 116.48},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    entry = locations.get("web", "device-2")
    assert entry["lat"] == "39.99" and entry["lng"] == "116.48"
    # 未配置高德Key时 unresolved 但坐标已存
    assert data["resolved"] is False


def test_location_rejects_bad_input(client):
    _login(client)
    assert client.post("/chat/api/location", json={"uid": "d", "lat": 999, "lng": 1}).status_code == 400
    assert client.post("/chat/api/message", json={"uid": "d", "text": ""}).status_code == 400
