"""Compatibility checks against Kira 3.1's actual media/tool contracts."""
import asyncio
import base64
from types import SimpleNamespace

import pytest

from core.agent.agent_executor import AgentExecutor
from core.agent.tool import ToolResult
from core.chat.message_elements import Image
from core.provider import LLMResponse
from core.utils import media_refs
from phone_control.media import store_screenshot
from test_phone_control import make_context, make_event, png


pytestmark = pytest.mark.skipif(not hasattr(media_refs, "session_media_scope"), reason="Kira 3.1 media lifecycle")


@pytest.mark.asyncio
async def test_screenshot_survives_cleanup_until_scope_closes(tmp_path, monkeypatch):
    import phone_control.media as storage
    # Exercise the old compact Windows layout as well as the normal root.
    root = tmp_path
    monkeypatch.setattr(media_refs, "get_data_path", lambda: root)
    monkeypatch.setattr(storage, "get_data_path", lambda: root)
    raw = png(20, 40)
    image = Image("base64://" + base64.b64encode(raw).decode(), mime="image/png")
    async with media_refs.session_media_scope():
        ref = await store_screenshot(image, raw, "phone:dm:cleanup", "frame")
        await asyncio.to_thread(media_refs.cleanup_session_media, "phone:dm:cleanup", [])
        assert (root / ref["path"]).is_file(), "in-flight screenshot was collected"
        assert (await media_refs.resolve_media_reference(ref))["type"] == "image_url"
    media_refs.cleanup_session_media("phone:dm:cleanup", [])
    assert not (root / ref["path"]).exists(), "scope must release its protection"


@pytest.mark.asyncio
async def test_truncated_tool_text_keeps_images_in_provider_context():
    ctx = make_context()
    ctx.config.get_config = lambda key, default=None: 64 if key.endswith("max_tool_output_tokens") else default
    raw = png(20, 40)
    async with media_refs.session_media_scope():
        ref = await store_screenshot(Image("base64://" + base64.b64encode(raw).decode(), mime="image/png"), raw, "test:dm:truncate", "frame")
        async def observe(event):
            return ToolResult(text='{"ok": true, "ui_elements": "' + "界面内容" * 2000 + '"}', media_refs=[ref])
        ctx.tool_mgr.register_tool("phone_screenshot", "observe", {}, observe)
        response = LLMResponse(text_response="", tool_calls=[{"id": "frame", "type": "function", "function": {"name": "phone_screenshot", "arguments": "{}"}}])
        await ctx.tool_mgr.execute_tool(make_event(), response, ctx.tool_mgr.build_tool_set())
        messages = AgentExecutor._build_tool_messages(response.tool_results)
        assert "truncated" in messages[0].content
        assert len(messages[0].content.encode()) <= 256
        assert messages[1].role == "user" and ref in messages[1].content
        resolved = await media_refs.resolve_media_references(messages)
        assert any(p.get("image_url", {}).get("url", "").endswith(base64.b64encode(raw).decode()) for p in resolved[1]["content"])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_voice_failure_releases_inflight_media(failure):
    from phone_control.voice import KiraVoiceBackend
    backend = KiraVoiceBackend(None)
    refs = []
    async def interrupted(*args):
        raw = png(20, 40)
        refs.append(await store_screenshot(Image("base64://" + base64.b64encode(raw).decode(), mime="image/png"), raw, "phone:dm:interrupted", "frame"))
        media_refs.cleanup_session_media("phone:dm:interrupted", [])
        assert (media_refs.get_data_path() / refs[0]["path"]).exists()
        raise failure()
    backend._run = interrupted
    with pytest.raises(failure):
        await backend.run(None, b"", "turn")
    media_refs.cleanup_session_media("phone:dm:interrupted", [])
    assert not (media_refs.get_data_path() / refs[0]["path"]).exists()


@pytest.mark.asyncio
async def test_installed_plugin_components_in_new_details_api(tmp_path):
    import httpx
    from fastapi import FastAPI
    from core.plugin import PluginManager
    from core.plugin.plugin_installer import install_from_zip
    from webui.routes.auth import require_auth
    from webui.routes.plugins import PluginsRoutes
    from test_builtin_server import build_plugin
    from phone_control.main import TOOL_NAMES
    archive = build_plugin(tmp_path)
    installed = await install_from_zip(archive.read_bytes(), tmp_path / "plugins")
    ctx = make_context()
    manager = PluginManager(ctx)
    ctx.plugin_mgr = manager
    plugin_id = await manager.load_plugin_from_dir(installed, auto_install=False)
    try:
        app = FastAPI()
        PluginsRoutes(app, SimpleNamespace(plugin_manager=manager)).register()
        app.dependency_overrides[require_auth] = lambda: "admin"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/plugins/{plugin_id}/components")
            assert response.status_code == 200
            items = response.json()
            assert {i["name"] for i in items if i["type"] == "tool"} == set(TOOL_NAMES)
            assert any(i["type"] == "page" and i["name"] == "/connect" for i in items)
            assert any(i["type"] == "api" and i["name"] == "GET /apk" for i in items)
            assert all(set(i) == {"type", "name", "description"} for i in items)
    finally:
        await manager.terminate(plugin_id)
