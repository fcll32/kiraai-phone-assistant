"""Real Kira loader/agent/provider and TLS socket; phone/model responses are scripted."""
import asyncio
import base64
import contextlib
import json
import ssl

import aiohttp
import httpx
import pytest
from openai import AsyncOpenAI

from core.agent.agent_executor import AgentExecutionContext, AgentExecutor
from core.adapter.src.qq.im import QQIMCapability
from core.plugin import PluginManager
from core.plugin.plugin_installer import install_from_zip
from core.provider import LLMRequest, ModelInfo, ModelType
from core.provider.openai_compatible import OpenAICompatibleLLMClient
from phone_control.main import TOOL_NAMES
from phone_control.server import DEVICE_PATH
from test_builtin_server import unused_port, build_plugin
from test_phone_control import make_context, make_event
from test_vision_tools import encoded_image


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
async def test_installed_zip_phone_tls_agent_and_provider_context(tmp_path, monkeypatch, fmt):
    archive = build_plugin(tmp_path)
    installed = await install_from_zip(archive.read_bytes(), tmp_path / "plugins")
    ctx = make_context()
    manager = PluginManager(ctx)
    ctx.plugin_mgr = manager
    plugin_id = await manager.load_plugin_from_dir(installed, auto_install=False)
    phone_task = None
    api_client = None
    requests, commands, sent_images = [], [], []
    try:
        await manager.update_plugin_config(plugin_id, {"transport": "app", "builtin_server": True, "shared_entry": False,
            "public_ip": "127.0.0.1", "phone_port": unused_port(), "listener_enabled": True,
            "allowed_sessions": ["test:dm:owner"], "action_delay": 0})
        plugin = manager.plugin_instances[plugin_id]
        server = plugin.phone_server
        tls = ssl.create_default_context(cafile=str(server.directory / "cert.pem"))
        ready = asyncio.Event()

        async def phone():
            async with aiohttp.ClientSession() as session:
                # The phone initiates this connection, just like Android behind NAT.
                async with session.ws_connect("wss://" + server.address + DEVICE_PATH, ssl=tls) as ws:
                    await ws.send_json({"type": "hello", "protocol": 1, "device_id": "test-phone",
                        "token": plugin.transport.config["device_token"]})
                    assert (await ws.receive_json())["type"] == "welcome"
                    ready.set()
                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            break
                        command = json.loads(message.data)
                        commands.append(command)
                        assert command["ttl_ms"] > 0
                        data = {}
                        if command["method"] == "screenshot":
                            assert command["params"]["image_format"] == "jpeg"
                            raw = encoded_image(fmt, color=(len(sent_images) * 25, 80, 120))
                            sent_images.append(raw)
                            data = {"width": 640, "height": 1280,
                                "image_base64": base64.b64encode(raw).decode()}
                        await ws.send_json({"type": "result", "id": command["id"], "ok": True, "data": data})

        phone_task = asyncio.create_task(phone())
        await asyncio.wait_for(ready.wait(), 3)

        def completion(request):
            body = json.loads(request.content)
            requests.append(body)
            assert {tool["function"]["name"] for tool in body["tools"]} == set(TOOL_NAMES)
            tool_messages = [m for m in body["messages"] if m["role"] == "tool"]
            results = [json.loads(m["content"]) for m in tool_messages]
            assert all(result["ok"] for result in results)
            images = [part["image_url"]["url"] for m in body["messages"]
                if isinstance(m.get("content"), list) for part in m["content"] if part["type"] == "image_url"]
            assert all(m["role"] != "tool" or isinstance(m["content"], str) for m in body["messages"])
            assert [base64.b64decode(url.split(",", 1)[1]) for url in images] == sent_images
            assert all(url.startswith("data:image/" + ("jpeg" if fmt == "JPEG" else "png") + ";") for url in images)
            step = len(requests)
            operations = [("phone_status", {}), ("phone_screenshot", {"send_to_chat": True}),
                ("phone_watch", {"frames": 2}),
                ("phone_tap", {"x": 500, "y": 500, "screenshot_id": results[-1].get("screenshot_id") if results else ""}),
                ("phone_navigate", {"key": "recent"})]
            message = {"role": "assistant", "content": "已完成"}
            if step <= len(operations):
                name, args = operations[step - 1]
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": f"call-{step}",
                    "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
            return httpx.Response(200, json={"id": f"reply-{step}", "object": "chat.completion", "created": 1,
                "model": "scripted-vision", "choices": [{"index": 0, "message": message,
                    "finish_reason": "tool_calls" if step <= len(operations) else "stop"}]})

        api_client = AsyncOpenAI(api_key="test-only", base_url="https://scripted.invalid/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(completion)))
        model = OpenAICompatibleLLMClient(ModelInfo(ModelType.LLM, "scripted", "test", "test"))
        monkeypatch.setattr(model, "_build_client", lambda: api_client)
        tool_set = ctx.tool_mgr.build_tool_set()
        request = LLMRequest(tool_set=tool_set)
        event = make_event(supported=list(QQIMCapability._SUPPORTED_ELEMENTS))
        await plugin.inject_phone_prompt(event, request)
        request.assemble_prompt()
        execution = AgentExecutionContext(event, request, [], [model])
        steps = [step async for step in AgentExecutor(ctx.tool_mgr, tool_set).run(execution, max_steps=8)]
        assert len(steps) == len(requests) == 6 and steps[-1].is_final
        assert all(step.state == "success" for step in steps)
        assert [m.name for m in execution.new_messages if m.role == "tool"] == [
            "phone_status", "phone_screenshot", "phone_watch", "phone_tap", "phone_navigate"]
        assert any(isinstance(m.content, list) and any(p.get("type") == "kira_image_ref" for p in m.content)
                   for m in execution.new_messages)
        assert all(m in request.messages for m in execution.new_messages)
        assert [c["params"]["action"] for c in commands if c["method"] == "action"] == ["tap", "key"]
        assert commands[-2]["params"]["args"]["key"] == "recent"
        assert len(sent_images) == 5
        ctx.send_message_chain.assert_awaited_once()
        assert ctx.send_message_chain.call_args.args[0] == event.sid
    finally:
        await manager.terminate(plugin_id)
        if phone_task:
            if not phone_task.done():
                phone_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await phone_task
        if api_client:
            await api_client.close()
