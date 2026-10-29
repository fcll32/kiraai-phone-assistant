"""A phone-initiated WebSocket transport; no inbound phone port is needed."""

import asyncio
import base64
import hmac
import json
from uuid import uuid4

from .protocol import PROTOCOL_VERSION, PhoneError, Screen, decode_screen, number, validate_action, valid_password


class AppBridge:
    input_method = "accessibility_unicode"

    def __init__(self, config):
        self.config = config
        self.timeout = number(config.get("command_timeout", 15), "命令超时", 1, 60)
        self.max_edge = int(number(config.get("screenshot_max_edge", 1280), "截图长边", 320, 2560))
        self.image_format = config.get("screenshot_format", "jpeg")
        if self.image_format not in {"png", "jpeg"}:
            raise PhoneError("截图格式必须是 png 或 jpeg")
        self.socket = None
        self.connection = None
        self.device_name = None
        self.pending = {}
        self.closed = False
        self.capabilities = set()

    async def accept(self, ws):
        await ws.accept()
        connection = None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 8)
            if len(raw) > 4096:
                raise PhoneError("Invalid handshake")
            hello = json.loads(raw)
            if not isinstance(hello, dict):
                raise PhoneError("Invalid handshake")
            token = self.config.get("device_token", "")
            provided = hello.get("token", "")
            if (self.closed or self.config.get("transport", "app") != "app"
                    or not valid_password(token)
                    or not isinstance(provided, str)
                    or not hmac.compare_digest(token.encode(), provided.encode())
                    or hello.get("type") != "hello" or type(hello.get("protocol")) is not int
                    or hello.get("protocol") != PROTOCOL_VERSION):
                await ws.close(code=1008, reason="Authentication failed")
                return
            device_id = hello.get("device_id", "")
            wanted = self.config.get("app_device_id", "")
            if not isinstance(device_id, str) or not 1 <= len(device_id) <= 128 or (wanted and wanted != device_id):
                await ws.close(code=1008, reason="Device not allowed")
                return
            if self.socket is not None:
                await ws.close(code=1013, reason="A phone is already connected")
                return
            connection = device_id + ":" + uuid4().hex
            self.socket, self.connection = ws, connection
            self.device_name = str(hello.get("name", "Android"))[:100]
            offered = hello.get("capabilities", [])
            self.capabilities = {v for v in offered if isinstance(v, str) and v in {"ui_tree", "apps", "apps_refresh"}} if isinstance(offered, list) else set()
            await ws.send_json({"type": "welcome", "protocol": PROTOCOL_VERSION})
            while not self.closed:
                raw = await asyncio.wait_for(ws.receive_text(), 75)
                if len(raw) > 12_000_000:
                    raise PhoneError("Frame too large")
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise PhoneError("Invalid message")
                if message.get("type") == "heartbeat":
                    await ws.send_json({"type": "heartbeat_ack"})
                elif message.get("type") == "result":
                    request_id = message.get("id")
                    if not isinstance(request_id, str):
                        raise PhoneError("Invalid result id")
                    future = self.pending.get(request_id)
                    if future is not None and not future.done():
                        future.set_result(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Disconnects fail pending requests; no command is replayed on reconnect.
            if self.closed:
                return
        finally:
            self._detach(connection)
            await self._close_socket(ws)

    def _detach(self, connection):
        if connection and self.connection == connection:
            self.socket = self.connection = self.device_name = None
            self.capabilities = set()
            pending, self.pending = self.pending, {}
            for future in pending.values():
                if not future.done():
                    future.set_exception(PhoneError("手机连接断开；操作可能已执行，请重连后先观察"))

    @staticmethod
    async def _close_socket(ws, code=1000, reason=""):
        try:
            await asyncio.wait_for(ws.close(code=code, reason=reason), 1)
        except Exception:
            pass

    async def select_device(self):
        if not self.socket or self.closed:
            raise PhoneError("手机 App 未连接。请在 App 填写服务器 IP:端口和连接密码，开启无障碍后点击开始连接")
        return self.connection

    async def request(self, connection, method, params):
        if connection != await self.select_device():
            raise PhoneError("手机已重连，请重新截图")
        ws = self.socket
        request_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        async def exchange():
            await ws.send_json({"type": "command", "id": request_id, "method": method,
                                "params": params, "ttl_ms": int(self.timeout * 1000)})
            return await future

        try:
            response = await asyncio.wait_for(exchange(), self.timeout)
            if response.get("ok") is not True:
                raise PhoneError(str(response.get("error", "手机操作失败"))[:700])
            data = response.get("data", {})
            if not isinstance(data, dict):
                raise PhoneError("手机返回了无效结果")
            return data
        except asyncio.CancelledError:
            self._detach(connection)
            await self._close_socket(ws, 1011, "Request cancelled")
            raise
        except asyncio.TimeoutError:
            self._detach(connection)
            await self._close_socket(ws, 1011, "Request timed out")
            raise PhoneError("手机响应超时，操作结果未知；重连后先截图，勿盲目重复")
        except PhoneError:
            raise
        except Exception as exc:
            self._detach(connection)
            await self._close_socket(ws, 1011, "Request failed")
            raise PhoneError("手机通信失败，操作结果未知；重新连接后先观察") from exc
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def screenshot(self, connection, *, ui_only=False):
        if ui_only and "ui_tree" not in self.capabilities:
            raise PhoneError("请升级手机 APK 后再读取 UI 控件；当前仍可使用 phone_screenshot")
        response = await self.request(connection, "ui_tree" if ui_only else "screenshot", {
            "max_edge": self.max_edge, "image_format": self.image_format,
        })
        width = int(number(response.get("width"), "屏幕宽度", 1, 10000))
        height = int(number(response.get("height"), "屏幕高度", 1, 10000))
        nodes = None
        if "nodes" in response or response.get("ui_only") is True:
            nodes = response.get("nodes", [])
            if not isinstance(nodes, list) or len(nodes) > 120:
                raise PhoneError("界面控件数据无效")
            for node in nodes:
                if not isinstance(node, dict) or not isinstance(node.get("text"), str) or len(node["text"]) > 160:
                    raise PhoneError("界面控件数据无效")
                number(node.get("x"), "控件 x", 0, 1000)
                number(node.get("y"), "控件 y", 0, 1000)
            nodes = [{k: node[k] for k in ("text", "x", "y", "clickable", "editable") if k in node} for node in nodes]
        if response.get("ui_only") is True:
            return Screen(b"", width, height, width, height, nodes)
        if ui_only:
            raise PhoneError("手机未返回 UI 控件数据")
        encoded = response.get("image_base64", "")
        if not isinstance(encoded, str) or len(encoded) > 11_000_000:
            raise PhoneError("手机截图过大或格式错误")
        # Keep base64 decoding and image validation off the shared server loop.
        def decode():
            return decode_screen(base64.b64decode(encoded, validate=True), self.max_edge, allow_jpeg=True)
        screen = await asyncio.to_thread(decode)
        if abs(screen.width * height - screen.height * width) > max(width, height) * 2:
            raise PhoneError("截图比例与设备尺寸不一致，请重新观察")
        return Screen(screen.png, width, height, screen.preview_width, screen.preview_height, nodes, mime=screen.mime)

    async def apps(self, connection, query, offset, limit, refresh=False):
        if "apps" not in self.capabilities:
            raise PhoneError("请升级手机 APK 后再读取应用列表")
        if refresh and "apps_refresh" not in self.capabilities:
            raise PhoneError("强制刷新应用列表需要升级手机 APK；旧版每次查询仍直接读取")
        data = await self.request(connection, "apps", {"query": query, "offset": offset, "limit": limit, "refresh": refresh})
        apps = data.get("apps")
        if not isinstance(apps, list) or len(apps) > limit:
            raise PhoneError("应用列表格式无效")
        import re
        for app in apps:
            if (not isinstance(app, dict) or not isinstance(app.get("name"), str) or len(app["name"]) > 80
                    or not isinstance(app.get("package"), str) or len(app["package"]) > 200
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", app["package"])):
                raise PhoneError("应用列表格式无效")
        total, next_offset = data.get("total"), data.get("next_offset")
        if (type(total) is not int or not 0 <= total <= 100000 or data.get("offset") != offset
                or type(next_offset) is not int or next_offset != (offset + len(apps) if offset + len(apps) < total else -1)
                or (next_offset != -1 and not apps)):
            raise PhoneError("应用列表分页无效")
        return {"apps": [{"name": a["name"], "package": a["package"]} for a in apps],
                "total": total, "offset": offset, "next_offset": next_offset}

    async def action(self, connection, action, params, size):
        validate_action(action, params)
        if action == "wait":
            # Waiting has no phone-side effect. Keep the device lock at the tool
            # layer, but avoid a round trip and sleeping on Android's worker.
            if connection != await self.select_device():
                raise PhoneError("手机已重连，请重新观察")
            await asyncio.sleep(params.get("seconds", 1))
            if connection != await self.select_device():
                raise PhoneError("等待期间手机已重连，请重新观察")
            return
        if action == "key" and params["key"] == "wake":
            raise PhoneError("App 模式不支持唤醒按键，请在手机上解锁")
        await self.request(connection, "action", {"action": action, "args": params, "size": list(size) if size else None})

    async def close(self):
        self.closed = True
        ws = self.socket
        self._detach(self.connection)
        if ws:
            await self._close_socket(ws, 1001, "Plugin stopped")
