"""Voice auth/lifecycle on real TLS, and real Kira agent + SQLite memory.

Audio capture and provider responses are scripted; this does not measure a
real phone's acoustic echo, provider latency or microphone compatibility.
"""
import asyncio
import base64
import contextlib
import io
import json
from pathlib import Path
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock
import wave

import aiohttp
import httpx
from openai import AsyncOpenAI
import pytest
import pytest_asyncio

from core.chat.message_elements import Record, Text
from core.chat.session import Session
from core.chat.session_manager import SessionManager
from core.db.db_mgr import DatabaseManager
from core.db.service import DatabaseService
from core.provider import ModelInfo, ModelType
from core.provider.openai_compatible import OpenAICompatibleLLMClient
from phone_control.main import PhoneControlPlugin, TOOL_NAMES
from phone_control.protocol import PhoneError
from phone_control.server import DEVICE_PATH
from phone_control.voice import MAX_AUDIO_BYTES, MAX_CHUNK_BYTES, MAX_PCM_BYTES, VOICE_PATH, VoiceCall, record_bytes, spoken_text
from test_builtin_server import unused_port
from test_phone_control import make_context, make_event, png


def wav_bytes():
    result = io.BytesIO()
    with wave.open(result, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 1600)
    return result.getvalue()


@pytest_asyncio.fixture
async def voice_server(tmp_path):
    ctx = make_context()
    ctx.get_plugin_data_dir = lambda: tmp_path
    plugin = PhoneControlPlugin(ctx, {"transport": "app", "public_ip": "127.0.0.1",
        "phone_port": unused_port(), "listener_enabled": True, "device_token": "MyKira88", "voice_enabled": True, "action_delay": 0})
    await plugin.initialize()
    assert plugin.phone_server.runner, plugin.setup_error
    plugin.voice.backend.models = lambda: (object(), object(), object())
    plugin.voice.backend.run = AsyncMock()
    tls = ssl.create_default_context(cafile=str(tmp_path / "cert.pem"))
    async with aiohttp.ClientSession() as client:
        try:
            yield plugin, client, tls
        finally:
            await plugin.terminate()


async def connect(server, **hello):
    plugin, client, tls = server
    ws = await client.ws_connect("wss://" + plugin.phone_server.address + VOICE_PATH, ssl=tls)
    await ws.send_json(dict({"type": "hello", "protocol": 1, "device_id": "test-phone", "name": "Test",
        "token": plugin.transport.config["device_token"]}, **hello))
    first = await ws.receive_json(timeout=3)
    return ws, first


async def utterance(ws, turn="turn-1", pcm=b"\0\0" * 1600):
    await ws.send_json({"type": "audio_start", "id": turn})
    await ws.send_bytes(pcm)
    await ws.send_json({"type": "audio_end", "id": turn})


@pytest.mark.asyncio
async def test_long_chinese_transcript_fits_android_text_limit(voice_server):
    text = "中" * 3000
    async def reply(call, pcm, turn):
        await call.send({"type": "transcript", "role": "assistant", "text": text}, turn=turn)
    voice_server[0].voice.backend.run.side_effect = reply
    ws, welcome = await connect(voice_server)
    try:
        assert welcome["type"] == "welcome"
        await ws.receive_json(timeout=3)
        await utterance(ws)
        raw = await ws.receive_str(timeout=3)
        assert json.loads(raw)["text"] == text
        assert len(raw) <= 16384
    finally:
        await ws.close()


@pytest.mark.asyncio
async def test_turn_error_returns_to_listening_without_hanging_up(voice_server):
    plugin = voice_server[0]
    plugin.voice.backend.run.side_effect = PhoneError("没有听清，请再说一次")
    ws, welcome = await connect(voice_server)
    assert welcome["type"] == "welcome"
    await ws.receive_json(timeout=3)
    await utterance(ws, "failed-turn")
    error = await ws.receive_json(timeout=3)
    assert error["type"] == "error" and error["id"] == "failed-turn"
    assert await ws.receive_json(timeout=3) == {"type": "state", "state": "listening", "id": "failed-turn"}
    plugin.voice.backend.run.side_effect = None
    await utterance(ws, "next-turn")
    assert await ws.receive_json(timeout=3) == {"type": "state", "state": "listening", "id": "next-turn"}
    await ws.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [{"token": "bad"}, {"protocol": True}, {"protocol": 2},
    {"device_id": "other:dm:owner"}, {"device_id": "../owner"}, {"device_id": ""}])
async def test_voice_auth_rejects_invalid_hello(voice_server, patch):
    ws, reply = await connect(voice_server, **patch)
    assert reply["type"] == "error"
    assert voice_server[0].voice.call is None
    await ws.close()


@pytest.mark.asyncio
async def test_voice_disabled_and_pinned_device(voice_server):
    plugin = voice_server[0]
    plugin.plugin_cfg["voice_enabled"] = False
    ws, reply = await connect(voice_server)
    assert reply["type"] == "error" and "开启" in reply["message"]
    await ws.close()
    plugin.plugin_cfg["voice_enabled"] = True
    plugin.plugin_cfg["app_device_id"] = "another-phone"
    ws, reply = await connect(voice_server)
    assert reply["type"] == "error" and "权限" in reply["message"]
    await ws.close()


@pytest.mark.asyncio
async def test_voice_requires_models_and_has_single_call(voice_server):
    plugin = voice_server[0]
    models = plugin.voice.backend.models
    del plugin.voice.backend.models
    ws, reply = await connect(voice_server)
    assert reply["type"] == "error" and "默认语音识别" in reply["message"]
    await ws.close()
    plugin.voice.backend.models = models
    ws, reply = await connect(voice_server)
    assert reply["type"] == "welcome"
    await ws.receive_json(timeout=3)
    second, reply = await connect(voice_server)
    assert reply["type"] == "error" and "已经有" in reply["message"]
    await second.close()
    await ws.send_json({"type": "heartbeat"})
    assert (await ws.receive_json(timeout=3))["type"] == "pong"
    await ws.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["overflow", "odd", "no_start", "wrong_end", "duplicate"])
async def test_voice_bounds_and_no_duplicate_replay(voice_server, bad):
    plugin = voice_server[0]
    ws, welcome = await connect(voice_server)
    assert welcome["max_seconds"] == 30
    await ws.receive_json(timeout=3)
    if bad == "duplicate":
        await utterance(ws)
        assert (await ws.receive_json(timeout=3))["state"] == "listening"
        await ws.send_json({"type": "audio_start", "id": "turn-1"})
    else:
        if bad != "no_start":
            await ws.send_json({"type": "audio_start", "id": "turn-1"})
        if bad == "overflow":
            for _ in range(MAX_PCM_BYTES // MAX_CHUNK_BYTES + 1):
                await ws.send_bytes(b"\0" * MAX_CHUNK_BYTES)
        else:
            await ws.send_bytes(b"\0" if bad == "odd" else b"\0\0")
        if bad == "wrong_end":
            await ws.send_json({"type": "audio_end", "id": "wrong"})
    error = await ws.receive_json(timeout=3)
    assert error["type"] == "error"
    assert plugin.voice.backend.run.await_count == (1 if bad == "duplicate" else 0)
    await ws.close()


@pytest.mark.asyncio
async def test_interrupt_revokes_old_output_before_new_turn(voice_server):
    plugin = voice_server[0]
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def backend(call, pcm, turn):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            # Even a provider that swallows cancellation cannot send stale audio.
            assert not await call.send({"type": "audio", "mime": "audio/wav", "length": 1}, turn=turn, binary=b"x")
    plugin.voice.backend.run = backend
    ws, _ = await connect(voice_server)
    await ws.receive_json(timeout=3)
    await utterance(ws)
    await asyncio.wait_for(entered.wait(), 3)
    await ws.send_json({"type": "interrupt", "request_id": "stop-1"})
    assert await ws.receive_json(timeout=3) == {"type": "state", "state": "listening", "interrupt_id": "stop-1"}
    assert cancelled.is_set()
    plugin.voice.backend.run = AsyncMock()
    await utterance(ws, "turn-2")
    assert await ws.receive_json(timeout=3) == {"type": "state", "state": "listening", "id": "turn-2"}
    await ws.close()


@pytest.mark.asyncio
async def test_voice_event_authorization_is_live_and_device_bound(voice_server):
    plugin = voice_server[0]
    ws, _ = await connect(voice_server)
    await ws.receive_json(timeout=3)
    call = plugin.voice.call
    event = make_event()
    event.session = Session("phone", "dm", "test-phone")
    with pytest.raises(PhoneError, match="未获"):
        plugin._authorize(event)
    event._phone_voice_owner = plugin.voice
    call.event, call.active_id = event, "turn"
    plugin._authorize(event)
    plugin.transport.connection = "another-phone:nonce"
    with pytest.raises(PhoneError, match="另一台"):
        plugin._authorize(event)
    plugin.transport.connection = "test-phone:nonce"
    assert (await plugin._send(event, Text("正在看屏幕")))["ok"]
    assert (await ws.receive_json(timeout=3))["progress"] is True
    await call.cancel()
    with pytest.raises(PhoneError, match="已结束"):
        plugin._authorize(event)
    await ws.close()


@pytest.mark.asyncio
async def test_voice_rechecks_device_after_waiting_for_lock(voice_server):
    plugin = voice_server[0]
    ws, _ = await connect(voice_server)
    await ws.receive_json(timeout=3)
    call = plugin.voice.call
    event = make_event()
    event._phone_voice_owner = plugin.voice
    call.event, call.active_id = event, "turn"
    plugin.transport.connection = "test-phone:nonce"
    select = plugin.transport.select_device = AsyncMock(return_value="another-phone:nonce")
    await plugin._lock.acquire()
    status = asyncio.create_task(plugin.phone_status(event))
    await asyncio.sleep(0)
    plugin.transport.connection = "another-phone:nonce"
    plugin._lock.release()
    result = json.loads((await status).text)
    assert not result["ok"] and "另一台" in result["error"]
    select.assert_not_called()
    await ws.close()


@pytest.mark.asyncio
async def test_cancelled_stt_cannot_start_agent_or_write_context(voice_server):
    plugin = voice_server[0]
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def stt(record):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            return "迟到的识别文本不应该触发手机动作"
    llm, tts = SimpleNamespace(chat=AsyncMock()), SimpleNamespace(text_to_speech=AsyncMock())
    plugin.ctx.provider_mgr = SimpleNamespace(get_default_stt=lambda: SimpleNamespace(speech_to_text=stt),
        get_default_llm=lambda: llm, get_default_tts=lambda: tts)
    plugin.ctx.session_mgr = SimpleNamespace(get_session=AsyncMock(), update_memory=AsyncMock())
    del plugin.voice.backend.models
    del plugin.voice.backend.run
    ws, _ = await connect(voice_server)
    await ws.receive_json(timeout=3)
    await utterance(ws)
    assert (await ws.receive_json(timeout=3))["state"] == "thinking"
    await asyncio.wait_for(entered.wait(), 3)
    await ws.send_json({"type": "interrupt", "request_id": "stop-stt"})
    assert (await ws.receive_json(timeout=3))["interrupt_id"] == "stop-stt"
    assert cancelled.is_set()
    llm.chat.assert_not_called()
    tts.text_to_speech.assert_not_called()
    plugin.ctx.session_mgr.get_session.assert_not_called()
    plugin.ctx.session_mgr.update_memory.assert_not_called()
    await ws.close()


@pytest.mark.asyncio
async def test_disconnect_cancels_turn_and_reconnect_does_not_replay(voice_server):
    plugin = voice_server[0]
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def backend(call, pcm, turn):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    plugin.voice.backend.run = backend
    ws, _ = await connect(voice_server)
    await ws.receive_json(timeout=3)
    await utterance(ws)
    await asyncio.wait_for(entered.wait(), 3)
    await ws.close()
    await asyncio.wait_for(cancelled.wait(), 3)
    # Wait until the close handler finishes releasing its single-call slot.
    for _ in range(20):
        if plugin.voice.call is None:
            break
        await asyncio.sleep(0.01)
    plugin.voice.backend.run = AsyncMock()
    again, welcome = await connect(voice_server)
    assert welcome["type"] == "welcome"
    await again.receive_json(timeout=3)
    await again.send_json({"type": "ping"})
    assert (await again.receive_json(timeout=3))["type"] == "pong"
    plugin.voice.backend.run.assert_not_called()
    await again.close()


@pytest.mark.asyncio
async def test_bounded_audio_record_and_mime(tmp_path):
    raw = wav_bytes()
    record = Record("base64://" + base64.b64encode(raw).decode())
    assert await record_bytes(record) == (raw, "audio/wav")
    path = tmp_path / "too-large.wav"
    path.write_bytes(b"x" * (MAX_AUDIO_BYTES + 1))
    with pytest.raises(PhoneError, match="过长"):
        await record_bytes(Record(str(path)))
    with pytest.raises(PhoneError, match="裸 PCM"):
        await record_bytes(Record("base64://" + base64.b64encode(b"\0" * 100).decode()))
    assert spoken_text("<think>secret</think><msg>好了</msg><file>private/path</file>") == "好了"


@pytest.mark.asyncio
async def test_real_kira_voice_tools_media_sqlite_and_second_turn(voice_server, tmp_path, monkeypatch):
    plugin, client, tls = voice_server
    ctx = plugin.ctx
    database = DatabaseManager(f"sqlite+aiosqlite:///{(tmp_path / 'voice.db').as_posix()}")
    await database.init()
    service = DatabaseService(database)
    await service.init_tables()
    memory_config = {"bot_config": {"bot": {"max_memory_length": 20}}}
    ctx.session_mgr = SessionManager(service, memory_config)
    requests, audio_inputs, tts_inputs, commands = [], [], [], []
    image = png(320, 640)
    audio = wav_bytes()
    from core.utils import media_refs
    if hasattr(media_refs, "session_media_scope"):
        observe = plugin._observe
        async def observe_during_cleanup(*args, **kwargs):
            result = await observe(*args, **kwargs)
            # A concurrent context trim can run before this turn is persisted.
            await asyncio.to_thread(media_refs.cleanup_session_media, "phone:dm:test-phone", [])
            for ref in result.media_refs:
                assert (await media_refs.resolve_media_reference(ref))["type"] == "image_url"
            return result
        monkeypatch.setattr(plugin, "_observe", observe_during_cleanup)

    async def stt(record):
        path = Path(record.file)
        audio_inputs.append(path)
        with wave.open(str(path), "rb") as recorded:
            assert recorded.getframerate() == 16000 and recorded.getnchannels() == 1
            assert recorded.getsampwidth() == 2 and recorded.getnframes() == 1600
        return "看看当前手机屏幕" if len(audio_inputs) == 1 else "刚才看到了什么"

    async def tts(text):
        tts_inputs.append(text)
        return Record("base64://" + base64.b64encode(audio).decode())

    def completion(request):
        body = json.loads(request.content)
        requests.append(body)
        assert {t["function"]["name"] for t in body["tools"]} == set(TOOL_NAMES)
        messages = body["messages"]
        step = len(requests)
        if step > 1:
            tools = [m for m in messages if m["role"] == "tool"]
            assert json.loads(tools[0]["content"])["ok"]
            images = [p["image_url"]["url"] for m in messages if isinstance(m.get("content"), list)
                for p in m["content"] if p["type"] == "image_url"]
            assert len(images) == 1 and base64.b64decode(images[0].split(",", 1)[1]) == image
        if step == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "screen-1", "type": "function",
                "function": {"name": "phone_screenshot", "arguments": "{}"}}]}
        else:
            message = {"role": "assistant", "content": "屏幕上是测试页面。"}
        return httpx.Response(200, json={"id": f"reply-{step}", "object": "chat.completion", "created": 1,
            "model": "scripted", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if step == 1 else "stop"}]})

    api = AsyncOpenAI(api_key="test", base_url="https://scripted.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(completion)))
    model = OpenAICompatibleLLMClient(ModelInfo(ModelType.LLM, "scripted", "test", "test"))
    monkeypatch.setattr(model, "_build_client", lambda: api)
    ctx.provider_mgr = SimpleNamespace(get_default_stt=lambda: SimpleNamespace(speech_to_text=stt),
        get_default_llm=lambda: model, get_default_tts=lambda: SimpleNamespace(text_to_speech=tts))
    # Use the production bound tools and real FuncToolManager/AgentExecutor.
    for name in TOOL_NAMES:
        ctx.tool_mgr.register_tool(name, name, {"type": "object", "properties": {}}, getattr(plugin, name))
    ctx.tool_mgr.register_tool("unrelated_admin_tool", "must be excluded", {}, AsyncMock())
    del plugin.voice.backend.models
    del plugin.voice.backend.run
    ready = asyncio.Event()

    async def phone():
        async with client.ws_connect("wss://" + plugin.phone_server.address + DEVICE_PATH, ssl=tls) as ws:
            await ws.send_json({"type": "hello", "protocol": 1, "device_id": "test-phone", "token": plugin.transport.config["device_token"]})
            assert (await ws.receive_json())["type"] == "welcome"
            ready.set()
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    return
                command = json.loads(msg.data)
                commands.append(command)
                await ws.send_json({"type": "result", "id": command["id"], "ok": True,
                    "data": {"image_base64": base64.b64encode(image).decode(), "width": 320, "height": 640}})

    phone_task = asyncio.create_task(phone())
    try:
        await asyncio.wait_for(ready.wait(), 3)
        ws, welcome = await connect(voice_server)
        assert welcome["type"] == "welcome"
        await ws.receive_json(timeout=3)
        for turn in ("first", "second"):
            await utterance(ws, turn)
            transcripts, got_audio = [], False
            while True:
                item = await ws.receive_json(timeout=5)
                assert item["type"] != "error", item
                assert item.get("id") == turn
                if item["type"] == "audio":
                    assert item["mime"] == "audio/wav" and item["length"] == len(audio)
                    assert (await ws.receive(timeout=5)).data == audio
                    got_audio = True
                elif item["type"] == "transcript":
                    transcripts.append(item)
                elif item.get("state") == "listening":
                    break
            assert got_audio and {t["role"] for t in transcripts} == {"user", "assistant"}
            # A fresh SessionManager must restore prior tool/media context from SQLite.
            ctx.session_mgr = SessionManager(service, memory_config)
        stored = await ctx.session_mgr.get_session("phone:dm:test-phone")
        if hasattr(media_refs, "session_media_scope"):
            media_refs.cleanup_session_media("phone:dm:test-phone", stored.flatten_content())
            for ref in media_refs.collect_media_reference_paths(stored.flatten_content()):
                assert (media_refs.get_data_path() / ref).is_file()
        assert len(stored.content) == 2
        assert any(m["role"] == "tool" and m["name"] == "phone_screenshot" for m in stored.flatten_content())
        assert any(isinstance(m["content"], list) and any(p.get("type") == "kira_image_ref" for p in m["content"])
            for m in stored.flatten_content())
        assert len(requests) == 3 and len(commands) == 1 and len(tts_inputs) == 2
        assert all(not path.exists() for path in audio_inputs)
        assert not ctx.send_message_chain.called
        await ws.send_json({"type": "hangup"})
        await ws.close()
    finally:
        phone_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await phone_task
        await api.close()
        await database.dispose()
