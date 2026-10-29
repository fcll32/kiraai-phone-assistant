import asyncio
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import sys
import zipfile
from unittest.mock import AsyncMock

import aiohttp
from cryptography import x509
from cryptography.hazmat.primitives import serialization
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from core.plugin import PluginManager
from core.plugin.plugin_installer import install_from_zip
from webui.utils import _access_token_fingerprint, _create_jwt_token
from phone_control.main import PhoneControlPlugin
from phone_control.protocol import PhoneError, valid_password
from phone_control.remote import AppBridge
from phone_control.server import DEVICE_PATH, PhoneServer, load_identity, prepare_certificate, validate_settings
from test_phone_control import make_context

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from package_plugin import build_plugin


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize("value", ["MyKira88", "good!pass_9", "a" * 32, "a" * 128])
def test_custom_password_policy_accepts_new_and_old_passwords(value):
    assert valid_password(value)


@pytest.mark.parametrize("value", [None, [], "", "1234567", "a" * 129, "hello 12", " pass123", "pass123\n", "中文密码12345678", "pass123\x7f"])
def test_custom_password_policy_rejects_ambiguous_or_invalid_values(value):
    assert not valid_password(value)


@pytest.mark.asyncio
async def test_stopped_builtin_listener_cannot_be_bypassed_on_management_routes(tmp_path):
    ctx = make_context()
    ctx.get_plugin_data_dir = lambda: tmp_path
    plugin = PhoneControlPlugin(ctx, {"public_ip": "127.0.0.1", "phone_port": unused_port()})
    await plugin.initialize()
    try:
        for route in (plugin.device_socket, plugin.voice_socket):
            ws = AsyncMock()
            await route(ws)
            ws.accept.assert_not_called()
            ws.close.assert_awaited_once()
        assert plugin.phone_server is None
    finally:
        await plugin.terminate()


@pytest_asyncio.fixture
async def listener(tmp_path):
    identity = load_identity(tmp_path)
    bridge = AppBridge({"device_token": identity["token"]})
    server = PhoneServer(bridge, tmp_path)
    await server.start("127.0.0.1", unused_port(), identity)
    context = ssl.create_default_context(cafile=str(tmp_path / "cert.pem"))
    try:
        yield server, bridge, identity, context
    finally:
        await bridge.close()
        await server.close()


@pytest.mark.asyncio
async def test_real_tls_authentication_commands_and_private_routes(listener):
    server, bridge, identity, context = listener
    async with aiohttp.ClientSession() as client:
        for path in ("/", "/api/plugin/phone_control/setup", "/identity.json", "/private-key.pem"):
            async with client.get("https://" + server.address + path, ssl=context) as response:
                assert response.status == 404
                assert identity["token"] not in await response.text()
        async with client.ws_connect("wss://" + server.address + DEVICE_PATH, ssl=context) as ws:
            await ws.send_json({"type": "hello", "protocol": 1, "device_id": "test", "token": "wrong"})
            await ws.receive()
            assert ws.close_code == 1008
        async with client.ws_connect("wss://" + server.address + DEVICE_PATH, ssl=context) as ws:
            await ws.send_json({"type": "hello", "protocol": 1, "device_id": "test", "token": identity["token"]})
            assert (await ws.receive_json())["type"] == "welcome"
            pending = asyncio.create_task(bridge.request(await bridge.select_device(), "action", {"action": "key"}))
            command = await ws.receive_json()
            await ws.send_json({"type": "result", "id": command["id"], "ok": True, "data": {"finished": True}})
            assert (await pending)["finished"]
            await ws.send_json({"type": "heartbeat"})
            assert (await ws.receive_json())["type"] == "heartbeat_ack"


@pytest.mark.asyncio
async def test_control_command_keeps_unicode_compact_over_real_tls(listener):
    server, bridge, identity, context = listener
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect("wss://" + server.address + DEVICE_PATH, ssl=context) as ws:
            await ws.send_json({"type": "hello", "protocol": 1, "device_id": "test", "token": identity["token"]})
            await ws.receive_json()
            text = "中文🙂" * 200
            task = asyncio.create_task(bridge.action(await bridge.select_device(), "text", {"text": text}, None))
            try:
                raw = await ws.receive_str(timeout=3)
                command = json.loads(raw)
                await ws.send_json({"type": "result", "id": command["id"], "ok": True, "data": {}})
                await task
                assert command["params"]["args"]["text"] == text
                assert "\\u" not in raw
                assert len(raw.encode("utf-8")) < len(json.dumps(command).encode("utf-8"))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("host", ["203.0.113.10", "2001:db8::3"])
def test_certificate_password_and_pin_survive_reload(tmp_path, host):
    identity = load_identity(tmp_path)
    _, fingerprint, expires = prepare_certificate(tmp_path, host, identity)
    stored = load_identity(tmp_path)
    assert stored["token"] == identity["token"]
    _, repeated, repeated_expiry = prepare_certificate(tmp_path, host, stored)
    assert repeated == fingerprint and repeated_expiry == expires
    certificate = x509.load_pem_x509_certificate((tmp_path / "cert.pem").read_bytes())
    assert certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address(host)]
    assert hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest() == fingerprint
    other_host = "203.0.113.11"
    _, new_pin, _ = prepare_certificate(tmp_path, other_host, stored)
    assert new_pin != fingerprint
    assert load_identity(tmp_path)["token"] == identity["token"]


def test_corrupt_identity_does_not_silently_replace_password(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(PhoneError, match="不会自动替换"):
        load_identity(tmp_path)
    assert path.read_text(encoding="utf-8") == "broken"


@pytest.mark.parametrize("host,port", [("https://1.2.3.4", 8443), ("1.2.3.4:8443", 8443),
    ("0.0.0.0", 8443), ("::", 8443), ("fe80::1%eth0", 8443), ("1.2.3.4", True), ("1.2.3.4", 65536)])
def test_invalid_listener_configuration_rejected(host, port):
    with pytest.raises(PhoneError):
        validate_settings(host, port)


@pytest.mark.asyncio
async def test_busy_port_reports_error_without_stopping_plugin(tmp_path):
    with socket.socket() as occupied:
        occupied.bind(("0.0.0.0", 0))
        occupied.listen()
        ctx = make_context()
        ctx.get_plugin_data_dir = lambda: tmp_path
        plugin = PhoneControlPlugin(ctx, {"listener_enabled": True, "public_ip": "127.0.0.1", "phone_port": occupied.getsockname()[1]})
        await plugin.initialize()
        try:
            info = json.loads((await plugin.connection_info()).body)
            assert not info["ready"] and "端口" in info["error"]
            assert "password" not in info
            assert not plugin._closed
        finally:
            await plugin.terminate()


@pytest.mark.asyncio
async def test_stop_closes_unauthenticated_handshake_and_releases_port(listener):
    server, bridge, identity, context = listener
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect("wss://" + server.address + DEVICE_PATH, ssl=context):
            await asyncio.wait_for(server.close(), 4)
            assert not server.clients and not server.runner
    replacement = PhoneServer(bridge, server.directory)
    try:
        await replacement.start("127.0.0.1", server.port, load_identity(server.directory))
        assert replacement.fingerprint == server.fingerprint
    finally:
        await replacement.close()


@pytest.mark.asyncio
async def test_zip_install_admin_page_setup_and_persistent_reload(tmp_path, monkeypatch):
    # Other installed-plugin tests persist settings too; give this fresh-install
    # scenario its own configuration directory, not their previously started one.
    monkeypatch.setattr("core.plugin.manager.PLUGIN_CONFIG_DIR", tmp_path / "configs")
    archive = build_plugin(tmp_path)
    with zipfile.ZipFile(archive) as package:
        assert not any(name.endswith('.apk') for name in package.namelist())
    installed = await install_from_zip(archive.read_bytes(), tmp_path / "plugins")
    ctx = make_context()
    manager = PluginManager(ctx)
    ctx.plugin_mgr = manager
    app = FastAPI()
    app.state.access_token = "test-admin-password"
    app.state.disable_auth = False
    manager.set_web_app(app)
    plugin_id = await manager.load_plugin_from_dir(installed, auto_install=False)
    assert plugin_id == "phone_control"
    installed_manifest = json.loads((installed / "manifest.json").read_text(encoding="utf-8"))
    plugin_info = manager._build_plugin_info(plugin_id, installed_manifest)
    assert plugin_info.icon == (installed / "icon.png").resolve()
    assert plugin_info.icon.read_bytes() == (installed / "web/assets/plugin-avatar.png").read_bytes()
    token = _create_jwt_token({"sub": "admin", "auth_mode": "enabled", "tv": _access_token_fingerprint(app.state.access_token)})
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            for path in ("/api/plugin/phone_control/setup", "/api/plugin/phone_control/apk", "/page/plugin/phone_control/connect/"):
                assert (await client.get(path)).status_code == 401
            assert (await client.get("/page/plugin/phone_control/connect/assets/scene-settings.png")).status_code == 401
            assert (await client.post("/api/plugin/phone_control/setup", json={})).status_code == 401
            client.cookies.set("kira_token", token)
            assert (await client.get("/page/plugin/phone_control/connect/")).status_code == 200
            # Exercise the installed folder route, not a source-tree preview: all
            # page resources must travel with the ZIP and keep its authentication.
            for name in ("panel.css", "panel.js", "assets/scene-settings.png", "assets/scene-pairing.png",
                         "assets/scene-guide.png", "assets/settings.png", "assets/link.png", "assets/guide.png",
                         "assets/call.png", "assets/shield.png", "assets/connected.png", "assets/rest.png", "assets/error.png", "assets/plugin-avatar.png"):
                resource = await client.get("/page/plugin/phone_control/connect/" + name)
                assert resource.status_code == 200, name
                assert resource.headers["cache-control"] == "no-store"
                assert resource.content == (installed / "web" / name).read_bytes()
            apk_response = await client.get("/api/plugin/phone_control/apk")
            assert apk_response.status_code == 404
            assert "单独下载" in apk_response.json()["detail"]
            assert (await client.post("/api/plugin/phone_control/setup", json={})).status_code == 403
            headers = {"X-Phone-Setup": "1"}
            assert (await client.post("/api/plugin/phone_control/setup", headers=headers, json={"public_ip": "bad"})).status_code == 400
            settings = {"public_ip": "127.0.0.1", "port": unused_port(), "shared_entry": False,
                        "allowed_sessions": ["test:dm:owner"], "voice_enabled": True}
            invalid_voice = await client.post("/api/plugin/phone_control/setup", headers=headers, json=dict(settings, voice_enabled="true"))
            assert invalid_voice.status_code == 400
            saved = await client.post("/api/plugin/phone_control/setup", headers=headers, json=settings)
            assert saved.status_code == 200, saved.text
            assert not (await client.get("/api/plugin/phone_control/setup")).json()["ready"]
            with pytest.raises(OSError):
                await asyncio.open_connection("127.0.0.1", settings["port"])
            await manager.init_plugin(plugin_id)
            assert not (await client.get("/api/plugin/phone_control/setup")).json()["ready"]
            settings.update(action="start", password="MyKira88")
            assert (await client.post("/api/plugin/phone_control/setup", headers=headers, json=settings)).status_code == 200
            response = await client.get("/api/plugin/phone_control/setup")
            assert response.headers["cache-control"] == "no-store"
            paired = response.json()
            assert paired["apk_available"] is False
            assert paired["ready"] and paired["password"] == "MyKira88" and len(paired["fingerprint"]) == 64
            assert paired["allowed_sessions"] == ["test:dm:owner"]
            assert paired["voice_enabled"] is True
            assert json.loads((tmp_path / "configs/phone_control.json").read_text(encoding="utf-8"))["listener_enabled"] is True
            saves = await asyncio.gather(*[
                client.post("/api/plugin/phone_control/setup", headers=headers, json=settings) for _ in range(2)
            ])
            assert sorted(response.status_code for response in saves) == [200, 409]
            await manager.init_plugin(plugin_id)
            reloaded = (await client.get("/api/plugin/phone_control/setup")).json()
            assert reloaded["ready"]
            assert reloaded["voice_enabled"] is True
            assert paired["password"] == reloaded["password"] and paired["fingerprint"] == reloaded["fingerprint"]
            # Real TLS + device authentication with the custom eight-character password.
            server = manager.plugin_instances[plugin_id].phone_server
            tls = ssl.create_default_context(cafile=str(server.directory / "cert.pem"))
            async with aiohttp.ClientSession() as phone:
                async with phone.ws_connect("wss://" + server.address + DEVICE_PATH, ssl=tls) as ws:
                    await ws.send_json({"type": "hello", "protocol": 1, "device_id": "phone", "token": "MyKira88"})
                    assert (await ws.receive_json())["type"] == "welcome"
                    # Stop ignores invalid unsaved form fields and disconnects the device.
                    stopped = await client.post("/api/plugin/phone_control/setup", headers=headers,
                                                json={"action": "stop", "public_ip": "invalid"})
                    assert stopped.status_code == 200
                    assert (await ws.receive(timeout=3)).type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)
            await manager.init_plugin(plugin_id)
            stopped = (await client.get("/api/plugin/phone_control/setup")).json()
            assert not stopped["ready"] and not stopped["listener_enabled"]
            assert json.loads((tmp_path / "configs/phone_control.json").read_text(encoding="utf-8"))["listener_enabled"] is False
            with pytest.raises(OSError):
                await asyncio.open_connection("127.0.0.1", settings["port"])
            settings.pop("password")  # Empty/missing password preserves the custom value.
            assert (await client.post("/api/plugin/phone_control/setup", headers=headers, json=settings)).status_code == 200
            assert (await client.get("/api/plugin/phone_control/setup")).json()["password"] == "MyKira88"
            await manager.terminate(plugin_id)
            assert (await client.get("/api/plugin/phone_control/setup")).status_code in (404, 503)
    finally:
        await manager.terminate(plugin_id)
