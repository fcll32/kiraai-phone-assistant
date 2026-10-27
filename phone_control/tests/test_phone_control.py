import asyncio
import base64
import io
import json
import shlex
import shutil
import sys
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from PIL import Image as PILImage

from core.agent.func_tool_manager import FuncToolManager
from core.agent.tool import ToolSet
from core.chat.message_elements import Image, Text
from core.chat.message_utils import KiraIMMessage, KiraIMSentResult, KiraMessageBatchEvent, MessageChain
from core.chat.session import Session, User
from core.config.config_field import build_fields
from core.plugin import PluginContext, PluginManager
from core.plugin import registry
from core.provider import LLMRequest
from core.utils.media_refs import resolve_media_reference

from phone_control.adb import ADB_IME, AdbClient, PhoneError, decode_screen
from phone_control.main import PhoneControlPlugin, TOOL_NAMES


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def png(width=1080, height=2400):
    output = io.BytesIO()
    with PILImage.new("RGB", (width, height), "#163151") as im:
        im.save(output, "PNG")
    return output.getvalue()


def make_event(user="owner", session="owner", supported=None):
    return KiraMessageBatchEvent(
        supported_elements=supported if supported is not None else ["text", "image"],
        timestamp=1,
        session=Session(adapter_name="test", session_type="dm", session_id=session),
        messages=[KiraIMMessage(
            message_id="incoming-1", self_id="bot", chain=MessageChain([Text("操作手机")]),
            timestamp=1, sender=User(user),
        )],
    )


def unpack(value):
    return json.loads(value.text)


def make_context():
    ctx = PluginContext(**{field.name: None for field in fields(PluginContext)})
    ctx.config = SimpleNamespace(get_config=lambda key, default=None: default, get=lambda key, default=None: default)
    ctx.tool_mgr = FuncToolManager(ctx.config)
    ctx.provider_mgr = SimpleNamespace(get_default_vlm=lambda: None)
    ctx.get_session_capabilities = AsyncMock(return_value={"image_recognition": {"enabled": True, "mode": "native"}})
    ctx.send_message_chain = AsyncMock(return_value=KiraIMSentResult(ok=True, message_id="sent-1"))
    return ctx


@pytest_asyncio.fixture
async def plugin():
    inst = PhoneControlPlugin(make_context(), {
        "allowed_sessions": ["test:dm:owner", "test:dm:other"], "action_delay": 0, "transport": "adb",
    })
    await inst.initialize()
    inst.transport.select_device = AsyncMock(return_value="serial-1")
    inst.transport.screenshot = AsyncMock(return_value=decode_screen(png(), 1280))
    inst.transport.action = AsyncMock()
    yield inst
    await inst.terminate()


@pytest.mark.asyncio
async def test_native_screenshot_uses_real_framework_media_references(plugin):
    observed = await plugin.phone_screenshot(make_event(), send_to_chat=True)
    data = unpack(observed)
    assert data["ok"] and data["delivery"]["ok"], data
    assert data["device_size"] == [1080, 2400]
    assert data["preview_size"] == [576, 1280]
    resolved = await resolve_media_reference(observed.media_refs[0])
    url = resolved["image_url"]["url"]
    with PILImage.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as preview:
        assert preview.size == (576, 1280)
    sent_chain = plugin.ctx.send_message_chain.call_args.args[1]
    assert isinstance(sent_chain.message_list[0], Image)


@pytest.mark.asyncio
async def test_qq_img_capability_allows_screenshot_and_saved_frame_delivery(plugin):
    from core.adapter.src.qq.im import QQIMCapability
    from core.adapter.src.qq_official.im import QQOfficialIMCapability

    # Use the real adapters' format vocabulary, not the Image enum's value.
    for adapter in (QQIMCapability, QQOfficialIMCapability):
        event = make_event(supported=list(adapter._SUPPORTED_ELEMENTS))
        plugin.ctx.send_message_chain.reset_mock()
        observed = await plugin.phone_screenshot(event, send_to_chat=True)
        data = unpack(observed)
        assert data["delivery"]["ok"], data
        assert observed.media_refs  # Sending to QQ must not consume the model image.
        plugin.ctx.send_message_chain.assert_awaited_once()
        chain = plugin.ctx.send_message_chain.call_args.args[1]
        assert isinstance(chain.message_list[0], Image)
        encoded = await chain.message_list[0].to_base64()
        assert encoded
        if adapter is QQIMCapability:
            from core.adapter.src.qq.napcat_client import QQMessageChain
            capability = object.__new__(QQIMCapability)
            segments = await capability._process_outgoing_message(chain)
            outgoing = QQMessageChain(segments).to_list()
            assert len(outgoing) == 1 and outgoing[0]["type"] == "image"
            assert outgoing[0]["data"]["file"] == "base64://" + encoded

        reported = unpack(await plugin.phone_report(event, screenshot_id=data["screenshot_id"]))
        assert reported["deliveries"]["screenshot"]["ok"], reported
        assert plugin.ctx.send_message_chain.await_count == 2


@pytest.mark.asyncio
async def test_default_access_denied_and_tools_hidden(plugin):
    plugin.plugin_cfg["allowed_sessions"] = []
    event = make_event()
    assert not unpack(await plugin.phone_status(event))["ok"]
    assert not unpack(await plugin.phone_screenshot(event))["ok"]
    assert not unpack(await plugin.phone_action(event, "key", {"key": "home"}))["ok"]
    assert not unpack(await plugin.phone_report(event, "progress"))["ok"]
    plugin.transport.select_device.assert_not_called()
    plugin.ctx.send_message_chain.assert_not_called()
    req = LLMRequest(tool_set=ToolSet())
    removed = []
    req.tool_set.remove = lambda *names: removed.extend(names)
    await plugin.inject_phone_prompt(event, req)
    assert set(removed) == set(TOOL_NAMES)
    assert not req.system_prompt


@pytest.mark.asyncio
async def test_prompt_is_added_once(plugin):
    req = LLMRequest()
    await plugin.inject_phone_prompt(make_event(), req)
    await plugin.inject_phone_prompt(make_event(), req)
    assert len(req.system_prompt) == 1
    assert "phone_report" in req.system_prompt[0].content


@pytest.mark.asyncio
async def test_invalid_action_does_not_invalidate_observation(plugin):
    event = make_event()
    observation = unpack(await plugin.phone_screenshot(event))["screenshot_id"]
    invalid = unpack(await plugin.phone_action(event, "tap", {"x": True, "y": 1}, observation))
    assert not invalid["action_may_have_run"]
    plugin.transport.action.assert_not_called()
    valid = unpack(await plugin.phone_action(event, "tap", {"x": 1, "y": 1}, observation))
    assert valid["action_completed"]


@pytest.mark.asyncio
async def test_command_waiting_on_lock_cannot_run_after_termination(plugin):
    await plugin._lock.acquire()
    command = asyncio.create_task(plugin.phone_action(make_event(), "key", {"key": "home"}))
    await asyncio.sleep(0)
    await plugin.terminate()
    plugin._lock.release()
    data = unpack(await command)
    assert not data["ok"] and not data["action_may_have_run"]
    plugin.transport.action.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_sender_batch_cannot_borrow_last_senders_permission(plugin):
    plugin.plugin_cfg["allowed_users"] = ["owner"]
    event = make_event()
    event.messages.insert(0, make_event(user="stranger").messages[0])
    assert not unpack(await plugin.phone_status(event))["ok"]
    plugin.transport.select_device.assert_not_called()


@pytest.mark.asyncio
async def test_screenshot_cannot_cross_sessions(plugin):
    frame = unpack(await plugin.phone_screenshot(make_event()))["screenshot_id"]
    other = make_event(session="other")
    assert not unpack(await plugin.phone_report(other, screenshot_id=frame))["ok"]
    assert not unpack(await plugin.phone_action(other, "tap", {"x": 500, "y": 500}, frame))["ok"]
    plugin.ctx.send_message_chain.assert_not_called()
    plugin.transport.action.assert_not_called()


@pytest.mark.asyncio
async def test_action_returns_new_screenshot_and_invalidates_old_frame(plugin):
    event = make_event()
    frame = unpack(await plugin.phone_screenshot(event))["screenshot_id"]
    performed = await plugin.phone_action(event, "tap", {"x": 500, "y": 500}, frame)
    assert unpack(performed)["action_completed"]
    assert performed.media_refs
    plugin.transport.action.assert_awaited_once_with("serial-1", "tap", {"x": 500, "y": 500}, (1080, 2400))
    assert not unpack(await plugin.phone_action(event, "tap", {"x": 500, "y": 500}, frame))["ok"]
    assert plugin.transport.action.await_count == 1


@pytest.mark.asyncio
async def test_expired_frame_and_rotated_screen_rejected(plugin):
    event = make_event()
    frame = unpack(await plugin.phone_screenshot(event))["screenshot_id"]
    plugin._frames[frame].created -= 121
    assert not unpack(await plugin.phone_action(event, "tap", {"x": 1, "y": 1}, frame))["ok"]
    frame = unpack(await plugin.phone_screenshot(event))["screenshot_id"]
    plugin.transport.screenshot.return_value = decode_screen(png(2400, 1080), 1280)
    assert not unpack(await plugin.phone_action(event, "tap", {"x": 1, "y": 1}, frame))["ok"]
    plugin.transport.action.assert_not_called()


@pytest.mark.asyncio
async def test_action_success_is_preserved_when_after_screenshot_fails(plugin):
    plugin.transport.screenshot.side_effect = PhoneError("capture failed")
    data = unpack(await plugin.phone_action(make_event(), "key", {"key": "home"}))
    assert not data["ok"] and data["action_completed"]
    assert plugin.transport.action.await_count == 1


@pytest.mark.asyncio
async def test_report_is_immediate_while_phone_is_busy(plugin):
    started, release = asyncio.Event(), asyncio.Event()

    async def action(*args):
        started.set()
        await release.wait()

    plugin.transport.action.side_effect = action
    task = asyncio.create_task(plugin.phone_action(make_event(), "wait", {"seconds": 1}, observe_after=False))
    await started.wait()
    report = await asyncio.wait_for(plugin.phone_report(make_event(), "正在处理"), timeout=1)
    assert unpack(report)["ok"]
    assert not task.done()
    release.set()
    assert unpack(await task)["ok"]


@pytest.mark.asyncio
async def test_partial_delivery_does_not_claim_success(plugin):
    event = make_event()
    frame = unpack(await plugin.phone_screenshot(event))["screenshot_id"]
    plugin.ctx.send_message_chain.side_effect = [
        KiraIMSentResult(ok=True, message_id="text-1"), KiraIMSentResult(ok=False, err="image refused"),
    ]
    data = unpack(await plugin.phone_report(event, "已打开页面", frame))
    assert not data["ok"]
    assert data["deliveries"]["text"]["ok"]
    assert not data["deliveries"]["screenshot"]["ok"]
    assert plugin.ctx.send_message_chain.await_count == 2


@pytest.mark.asyncio
async def test_unsupported_images_are_not_sent(plugin):
    event = make_event(supported=["text"])
    data = unpack(await plugin.phone_screenshot(event, send_to_chat=True))
    assert not data["delivery"]["ok"]
    plugin.ctx.send_message_chain.assert_not_called()


@pytest.mark.asyncio
async def test_vlm_missing_and_disabled_vision_are_explicit(plugin):
    plugin.ctx.get_session_capabilities.return_value = {"image_recognition": {"mode": "vlm_description"}}
    data = unpack(await plugin.phone_screenshot(make_event()))
    assert not data["ok"] and data["captured"] and data["vision_error"]
    plugin.ctx.get_session_capabilities.return_value = {"image_recognition": {"enabled": False}}
    data = unpack(await plugin.phone_screenshot(make_event()))
    assert "关闭" in data["vision_error"]


@pytest.mark.asyncio
async def test_vlm_description_mode(plugin, monkeypatch):
    import phone_control.main as main
    plugin.ctx.get_session_capabilities.return_value = {"image_recognition": {"mode": "vlm_description"}}
    plugin.ctx.provider_mgr.get_default_vlm = lambda: object()
    monkeypatch.setattr(main, "desc_img", AsyncMock(return_value="设置按钮位于 (500,500)"))
    value = await plugin.phone_screenshot(make_event())
    assert unpack(value)["vision_mode"] == "vlm_description"
    assert not value.media_refs


@pytest.mark.asyncio
async def test_real_plugin_loader_registers_schema_and_tools(tmp_path):
    destination = tmp_path / "plugins" / "phone_control"
    destination.mkdir(parents=True)
    for name in ("main.py", "adb.py", "protocol.py", "media.py", "remote.py", "server.py", "voice.py", "__init__.py", "manifest.json", "schema.json"):
        shutil.copyfile(PLUGIN_ROOT / name, destination / name)
    shutil.copytree(PLUGIN_ROOT / "web", destination / "web")
    ctx = make_context()
    manager = PluginManager(ctx)
    ctx.plugin_mgr = manager
    plugin_id = await manager.load_plugin_from_dir(destination, auto_install=False)
    try:
        assert plugin_id == "phone_control"
        assert plugin_id in manager.plugin_instances
        assert not registry._plugin_load_errors.get(plugin_id)
        assert {tool.name for tool in ctx.tool_mgr.tool_set.tools} == set(TOOL_NAMES)
        assert len(registry._plugin_components[plugin_id].hooks) == 1
        schema = json.loads((PLUGIN_ROOT / "schema.json").read_text(encoding="utf-8"))
        parsed = build_fields(schema)
        assert len(parsed) == len(schema)
        assert next(field for field in parsed if field.key == "allowed_sessions").default == []
        tool = ctx.tool_mgr.tool_set.get("phone_status")
        assert not unpack(await tool.execute(make_event()))["ok"]
    finally:
        await manager.terminate(plugin_id)


@pytest.mark.asyncio
async def test_multi_device_selection_requires_exact_serial():
    adb = AdbClient({})
    adb.devices = AsyncMock(return_value=[{"serial": "a", "state": "device"}, {"serial": "b", "state": "device"}])
    with pytest.raises(PhoneError, match="多台"):
        await adb.select_device()
    adb.serial = "b"
    assert await adb.select_device() == "b"
    adb.devices.return_value = [{"serial": "b", "state": "unauthorized"}]
    with pytest.raises(PhoneError, match="unauthorized"):
        await adb.select_device()


@pytest.mark.asyncio
async def test_wireless_connect_failure_is_not_ignored():
    adb = AdbClient({"connect_address": "192.0.2.1:5555"})
    adb.run = AsyncMock(return_value=b"failed to connect")
    with pytest.raises(PhoneError, match="连接失败"):
        await adb.select_device()


@pytest.mark.asyncio
async def test_touch_mapping_and_ascii_remote_shell_quoting():
    adb = AdbClient({})
    adb.run = AsyncMock(return_value=b"")
    await adb.action("phone", "tap", {"x": 1000, "y": 500}, (1080, 2400))
    assert shlex.split(adb.run.call_args.args[-1]) == ["input", "tap", "1079", "1200"]
    text = "it's a; $(echo nope) & test"
    await adb.action("phone", "text", {"text": text}, None)
    assert shlex.split(adb.run.call_args.args[-1]) == ["input", "text", text.replace(" ", "%s")]


@pytest.mark.asyncio
@pytest.mark.parametrize("action,params", [
    ("tap", {"x": float("nan"), "y": 1}), ("tap", {"x": True, "y": 1}),
    ("tap", {"x": -1, "y": 1}), ("swipe", {"x": 1, "y": 1}),
    ("key", {"key": "reboot"}), ("text", {"text": "中文"}),
    ("text", {"text": "%s"}), ("open_app", {"package": "app;reboot"}),
    ("tap", {"x": 1, "y": 1, "extra": "no"}), ("shell", {"text": "id"}),
])
async def test_invalid_arguments_never_reach_adb(action, params):
    adb = AdbClient({})
    adb.run = AsyncMock()
    with pytest.raises(PhoneError):
        await adb.action("phone", action, params, (1080, 2400))
    adb.run.assert_not_called()


@pytest.mark.asyncio
async def test_unicode_ime_is_checked_and_broadcast_encoded():
    adb = AdbClient({"text_input_mode": "adb_keyboard"})
    adb.shell = AsyncMock(side_effect=[ADB_IME, "Broadcast completed: result=0"])
    await adb.action("phone", "text", {"text": "你好🙂"}, None)
    args = adb.shell.call_args.args
    assert base64.b64decode(args[-1]).decode("utf-8") == "你好🙂"
    adb.shell = AsyncMock(return_value="another/.IME")
    with pytest.raises(PhoneError, match="手动切换"):
        await adb.action("phone", "text", {"text": "你好"}, None)
    assert adb.shell.await_count == 1


def test_invalid_screenshot_is_not_accepted():
    with pytest.raises(PhoneError, match="PNG"):
        decode_screen(b"device offline", 1280)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancellation_reaps_real_subprocess(monkeypatch, cancel):
    original = asyncio.create_subprocess_exec
    spawned = []
    ready = asyncio.Event()

    async def start(*args, **kwargs):
        process = await original(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
        spawned.append(process)
        ready.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    adb = AdbClient({})
    adb.timeout = 0.15
    task = asyncio.create_task(adb.run("devices"))
    await ready.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(PhoneError, match="超时"):
            await task
    assert not adb.processes
    assert spawned[0].returncode is not None
