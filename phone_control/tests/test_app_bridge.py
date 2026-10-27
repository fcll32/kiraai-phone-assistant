import asyncio
import base64
import io
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from PIL import Image

from phone_control.adb import PhoneError, Screen
from phone_control.remote import AppBridge
from test_phone_control import make_context, make_event, unpack
from phone_control.main import PhoneControlPlugin

TOKEN = "test-only-secret-with-at-least-32-characters"


def setup_app():
    bridge = AppBridge({"device_token": TOKEN})
    app = FastAPI()

    @app.websocket("/device")
    async def device(ws: WebSocket):
        await bridge.accept(ws)

    @app.get("/observe")
    async def observe():
        try:
            screen = await bridge.screenshot(await bridge.select_device())
            return {"width": screen.width, "height": screen.height, "image": bool(screen.png), "nodes": screen.ui_nodes}
        except PhoneError as exc:
            return {"error": str(exc)}

    return app, bridge


def hello(ws, token=TOKEN):
    ws.send_json({"type": "hello", "protocol": 1, "device_id": "phone-1", "name": "Test phone", "token": token})


def test_websocket_authentication_and_heartbeat():
    app, bridge = setup_app()
    with TestClient(app) as client:
        with client.websocket_connect("/device") as ws:
            hello(ws, "incorrect")
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 1008
        assert bridge.socket is None
        with client.websocket_connect("/device") as ws:
            hello(ws)
            assert ws.receive_json()["type"] == "welcome"
            ws.send_json({"type": "heartbeat"})
            assert ws.receive_json()["type"] == "heartbeat_ack"
            with client.websocket_connect("/device") as another:
                hello(another)
                with pytest.raises(WebSocketDisconnect) as error:
                    another.receive_json()
                assert error.value.code == 1013


@pytest.mark.parametrize("ui_only", [False, True])
def test_real_websocket_command_and_observation_round_trip(ui_only):
    app, bridge = setup_app()
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        with client.websocket_connect("/device") as ws:
            hello(ws); ws.receive_json()
            call = pool.submit(client.get, "/observe")
            command = ws.receive_json()
            assert command["method"] == "screenshot"
            assert command["ttl_ms"] == 15000
            data = {"width": 1080, "height": 2400}
            if ui_only:
                data.update(ui_only=True, nodes=[{"text": "设置", "x": 500, "y": 500}])
            else:
                output = io.BytesIO()
                Image.new("RGB", (540, 1200)).save(output, "PNG")
                data["image_base64"] = base64.b64encode(output.getvalue()).decode()
            ws.send_json({"type": "result", "id": command["id"], "ok": True, "data": data})
            response = call.result(timeout=5).json()
            assert response["width"] == 1080 and response["height"] == 2400
            assert response["image"] is not ui_only
            assert not bridge.pending


def test_disconnect_fails_pending_command_without_replay():
    app, bridge = setup_app()
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        with client.websocket_connect("/device") as ws:
            hello(ws); ws.receive_json()
            old = bridge.connection
            call = pool.submit(client.get, "/observe")
            ws.receive_json()
            ws.close()
            assert "断开" in call.result(timeout=5).json()["error"]
        with client.websocket_connect("/device") as ws:
            hello(ws); ws.receive_json()
            assert bridge.connection != old
            assert not bridge.pending


@pytest.mark.asyncio
async def test_android_8_ui_observation_is_not_presented_as_screenshot():
    plugin = PhoneControlPlugin(make_context(), {"allowed_sessions": ["test:dm:owner"]})
    await plugin.initialize()
    plugin.transport.select_device = AsyncMock(return_value="phone-session")
    plugin.transport.screenshot = AsyncMock(return_value=Screen(b"", 720, 1280, 720, 1280, [{"text": "设置", "x": 500, "y": 500}]))
    plugin.transport.action = AsyncMock()
    try:
        observation = await plugin.phone_screenshot(make_event())
        data = unpack(observation)
        assert data["ok"] and not data["screenshot_available"]
        assert data["ui_elements"] and not observation.media_refs
        performed = await plugin.phone_action(make_event(), "tap", {"x": 500, "y": 500}, data["screenshot_id"])
        assert unpack(performed)["action_completed"]
        assert plugin.transport.screenshot.await_count == 2
        shared = await plugin.phone_report(make_event(), screenshot_id=data["screenshot_id"])
        assert not unpack(shared)["ok"]
        plugin.ctx.send_message_chain.assert_not_called()
        shared = unpack(await plugin.phone_report(make_event(), text="已完成点击", screenshot_id=data["screenshot_id"]))
        assert not shared["ok"]
        assert shared["deliveries"]["text"]["ok"]
        assert not shared["deliveries"]["screenshot"]["ok"]
        plugin.ctx.send_message_chain.assert_called_once()
    finally:
        await plugin.terminate()


@pytest.mark.asyncio
async def test_cancellation_preserved_even_if_socket_close_fails():
    bridge = AppBridge({"device_token": TOKEN})
    socket = AsyncMock()
    socket.close.side_effect = RuntimeError("Already closed")
    bridge.socket, bridge.connection = socket, "connection"
    request = asyncio.create_task(bridge.request("connection", "action", {}))
    await asyncio.sleep(0)
    assert bridge.pending
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert not bridge.pending


@pytest.mark.asyncio
@pytest.mark.parametrize("action,params", [
    ("tap", {"x": True, "y": 1}), ("swipe", {"x": 1, "y": 2}),
    ("text", {"text": "x" * 1001}), ("key", {"key": "reboot"}),
    ("wait", {"seconds": -1}), ("open_app", {"package": "app;command"}),
    ("tap", {"x": 1, "y": 1, "extra": "bad"}),
])
async def test_invalid_app_action_never_sent(action, params):
    bridge = AppBridge({"device_token": TOKEN})
    bridge.request = AsyncMock()
    with pytest.raises(PhoneError):
        await bridge.action("phone", action, params, (1080, 2400))
    bridge.request.assert_not_called()


@pytest.mark.asyncio
async def test_stalled_send_is_timed_out_and_failed_close_detaches():
    bridge = AppBridge({"device_token": TOKEN})
    bridge.timeout = 0.02
    socket = AsyncMock()
    async def blocked(*args):
        await asyncio.Event().wait()
    socket.send_json.side_effect = blocked
    socket.close.side_effect = RuntimeError("Socket already gone")
    bridge.socket, bridge.connection = socket, "old"
    with pytest.raises(PhoneError, match="超时"):
        await asyncio.wait_for(bridge.request("old", "screenshot", {}), 2)
    assert bridge.socket is None and bridge.connection is None and not bridge.pending
    with pytest.raises(PhoneError, match="未连接"):
        await bridge.select_device()


@pytest.mark.asyncio
async def test_shutdown_immediately_releases_waiting_request():
    bridge = AppBridge({"device_token": TOKEN})
    socket, sent = AsyncMock(), asyncio.Event()
    async def signal(*args):
        sent.set()
    socket.send_json.side_effect = signal
    bridge.socket, bridge.connection = socket, "old"
    request = asyncio.create_task(bridge.request("old", "screenshot", {}))
    await sent.wait()
    await bridge.close()
    with pytest.raises(PhoneError, match="断开"):
        await asyncio.wait_for(request, 1)
    assert bridge.closed and not bridge.pending and bridge.socket is None


@pytest.mark.asyncio
async def test_inconsistent_screenshot_dimensions_rejected():
    bridge = AppBridge({"device_token": TOKEN})
    output = io.BytesIO()
    Image.new("RGB", (100, 100)).save(output, "PNG")
    bridge.request = AsyncMock(return_value={"width": 1080, "height": 2400, "image_base64": base64.b64encode(output.getvalue()).decode()})
    with pytest.raises(PhoneError, match="比例"):
        await bridge.screenshot("phone")
