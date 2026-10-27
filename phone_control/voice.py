"""Authenticated, bounded App calls using Kira's STT, agent, memory and TTS.

The voice socket is independent of the device command socket. This is a
half-duplex, utterance-based protocol, not an audio injection or streaming API.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import hmac
import json
from pathlib import Path
import re
import tempfile
from time import monotonic, time
from uuid import uuid4
import wave

import aiohttp

from core.adapter.adapter_info import AdapterInfo
from core.agent.agent_executor import AgentExecutionContext, AgentExecutor
from core.agent.message import OpenAIMessage
from core.chat.message_elements import Record, Text
from core.chat.message_utils import KiraIMMessage, KiraMessageBatchEvent, MessageChain
from core.chat.session import Session, User
from core.plugin import logger
from core.prompt_manager import Prompt
from core.provider import LLMRequest

from .protocol import PhoneError, valid_password
from .media import session_media_scope

VOICE_PATH = "/ws/plugin/phone_control/voice"
SAMPLE_RATE = 16000
MAX_PCM_BYTES = SAMPLE_RATE * 2 * 30
MAX_CHUNK_BYTES = 65536
MAX_AUDIO_BYTES = 10 * 1024 * 1024
SEND_TIMEOUT = 10
CLOSE_TIMEOUT = 3


async def close_socket(socket, code=1000, reason="Voice call ended"):
    try:
        async with asyncio.timeout(CLOSE_TIMEOUT):
            await socket.close(code=code, reason=reason)
    except Exception:
        pass


def spoken_text(value):
    """Only speak visible reply text, never reasoning or attachment paths."""
    value = re.sub(r"<(think|thinking|reasoning|file|record|image)\b[^>]*>.*?</\1>", "", value or "", flags=re.S | re.I)
    value = re.sub(r"</?[a-zA-Z][^>]*>", "", value)
    return value.strip()[:4000]


async def record_bytes(record):
    if not isinstance(record, Record) or not record.file:
        raise PhoneError("语音合成没有返回可播放的声音")
    if record.file_type in {"base64", "data_url"}:
        encoded = record.file.split(",", 1)[1] if record.file_type == "data_url" else record.file
        if len(encoded) > (MAX_AUDIO_BYTES + 2) // 3 * 4:
            raise PhoneError("回复语音过长，请让 AI 简短回答")
        raw = base64.b64decode(encoded, validate=True)
    elif record.file_type == "path":
        def read():
            with open(record.file, "rb") as stream:
                return stream.read(MAX_AUDIO_BYTES + 1)
        raw = await asyncio.to_thread(read)
    elif record.file_type == "url":
        data = bytearray()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as client:
            async with client.get(record.file) as response:
                response.raise_for_status()
                async for chunk in response.content.iter_chunked(MAX_CHUNK_BYTES):
                    data.extend(chunk)
                    if len(data) > MAX_AUDIO_BYTES:
                        raise PhoneError("回复语音过长，请让 AI 简短回答")
        raw = bytes(data)
    else:
        raise PhoneError("语音合成返回了不支持的音频格式")
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        raise PhoneError("回复语音为空或过长")
    # Many Kira providers omit MIME. Use actual container bytes for Android.
    if raw.startswith(b"RIFF") and raw[8:12] == b"WAVE":
        mime = "audio/wav"
    elif raw.startswith(b"OggS"):
        mime = "audio/ogg"
    elif raw.startswith(b"fLaC"):
        mime = "audio/flac"
    elif raw[4:8] == b"ftyp":
        mime = "audio/mp4"
    elif raw.startswith(b"ID3") or (len(raw) > 1 and raw[0] == 255 and raw[1] & 0xE0 == 0xE0):
        mime = "audio/aac" if raw[:2] in {b"\xff\xf1", b"\xff\xf9"} else "audio/mpeg"
    else:
        raise PhoneError("语音合成请使用 WAV、MP3、AAC、OGG 或 FLAC 格式，不能使用裸 PCM")
    return raw, mime


@dataclass(eq=False)
class VoiceCall:
    bridge: "VoiceBridge"
    socket: object
    device_id: str
    name: str
    call_id: str = field(default_factory=lambda: uuid4().hex)
    alive: bool = True
    active_id: str = ""
    event: object = None
    task: asyncio.Task | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def sid(self):
        return "phone:dm:" + self.device_id

    def ensure_current(self, turn):
        if not self.alive or self.bridge.closed or self.bridge.call is not self or self.active_id != turn:
            raise asyncio.CancelledError

    async def send(self, payload, *, turn="", binary=None):
        if not self.alive or (turn and turn != self.active_id):
            return False
        deadline = asyncio.get_running_loop().time() + SEND_TIMEOUT
        try:
            async with asyncio.timeout_at(deadline):
                async with self.send_lock:
                    if not self.alive or (turn and turn != self.active_id):
                        return False
                    if turn:
                        payload = dict(payload, id=turn)
                    if binary is None:
                        await self.socket.send_json(payload)
                    else:
                        # Preserve the header/binary pair across a turn interrupt.
                        # The lock remains held until delivery or failure, so an
                        # interrupt acknowledgement can never split this pair.
                        packet = asyncio.create_task(self._audio_packet(payload, binary, deadline))
                        try:
                            await asyncio.shield(packet)
                        except asyncio.CancelledError:
                            try:
                                await packet
                            except BaseException:
                                self.alive = False
                                self.active_id = ""
                                if self.event is not None:
                                    self.event.stop()
                                await close_socket(self.socket, 1011, "Audio delivery interrupted")
                            raise
            return True
        except Exception as exc:
            was_alive = self.alive
            self.alive = False
            self.active_id = ""
            if self.event is not None:
                self.event.stop()
            if was_alive:
                await close_socket(self.socket, 1011, "Voice delivery failed")
            raise PhoneError("语音发送超时或连接中断，请重新发起通话") from exc

    async def _audio_packet(self, payload, binary, deadline):
        async with asyncio.timeout_at(deadline):
            await self.socket.send_json(payload)
            await self.socket.send_bytes(binary)

    async def cancel(self):
        # Revoke tool and output access BEFORE cancelling provider/tool awaits.
        self.active_id = ""
        if self.event is not None:
            self.event.stop()
        self.event = None
        task, self.task = self.task, None
        if task and not task.done():
            task.cancel()
            done, _ = await asyncio.wait([task], timeout=3)
            if not done:
                self.alive = False
                self.bridge.draining.add(task)
                task.add_done_callback(self.bridge.finished_draining)
                raise PhoneError("上一次操作仍在停止，请重新发起通话")
        if task and task.done():
            # Consume its exception even after a disconnected peer.
            try:
                task.result()
            except (asyncio.CancelledError, Exception):
                pass


class KiraVoiceBackend:
    def __init__(self, plugin):
        self.plugin = plugin

    def models(self):
        try:
            providers = self.plugin.ctx.provider_mgr
            models = providers.get_default_stt(), providers.get_default_llm(), providers.get_default_tts()
            if not all(models):
                raise ValueError("Missing model")
            if self.plugin.ctx.session_mgr is None:
                raise ValueError("Missing session manager")
            return models
        except Exception:
            raise PhoneError("请先在 KiraAI 中设置默认语音识别、聊天和语音合成模型，再发起通话") from None

    async def run(self, call, pcm, turn):
        # This custom workflow bypasses Kira's IM workflow; own the same media
        # scope through agent execution AND memory commit, including failures.
        async with session_media_scope():
            await self._run(call, pcm, turn)

    async def _run(self, call, pcm, turn):
        stt, llm, tts = self.models()
        ctx = self.plugin.ctx
        started = monotonic()
        await call.send({"type": "state", "state": "thinking", "detail": "正在听懂你说的话"}, turn=turn)
        # STT providers may require a file. Own and remove that file after use.
        with tempfile.TemporaryDirectory(prefix="kira-phone-voice-") as directory:
            path = Path(directory) / "utterance.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(SAMPLE_RATE)
                audio.writeframes(pcm)
            async with asyncio.timeout(60):
                text = await stt.speech_to_text(Record(record=str(path), mime="audio/wav"))
        call.ensure_current(turn)
        if not isinstance(text, str) or not text.strip():
            raise PhoneError("没有听清，请再说一次")
        text = text.strip()[:8000]
        await call.send({"type": "transcript", "role": "user", "text": text}, turn=turn)
        stt_done = monotonic()
        session = await ctx.session_mgr.get_session(call.sid, ensure_session=True)
        call.ensure_current(turn)
        event = KiraMessageBatchEvent(
            supported_elements=["text"], timestamp=int(time()),
            adapter=AdapterInfo(True, "phone", "手机通话", "phone"),
            session=Session("phone", "dm", call.device_id, session_title="手机通话"),
            messages=[KiraIMMessage(message_id=turn, self_id="kira-phone",
                chain=MessageChain([Text(text)]), timestamp=int(time()), sender=User(call.device_id, call.name))],
        )
        event.message_str = text
        event.message_repr = text
        event._phone_voice_owner = call.bridge
        call.event = event
        from .main import TOOL_NAMES
        tool_set = ctx.tool_mgr.build_tool_set()
        tool_set.remove(*(tool.name for tool in tool_set.tools if tool.name not in TOOL_NAMES))
        user_message = OpenAIMessage(role="user", content=text)
        messages = [user_message]
        request = LLMRequest(messages=session.flatten_content() + [user_message], tool_set=tool_set)
        if ctx.prompt_mgr is not None:
            request.system_prompt.extend(await ctx.prompt_mgr.get_agent_prompt({
                "platform": "phone", "adapter": "phone", "chat_type": "DirectMessage",
                "self_id": "kira-phone", "session_title": "手机通话", "session_description": "App 内语音通话"}))
        call.ensure_current(turn)
        await self.plugin.inject_phone_prompt(event, request)
        request.system_prompt.append(Prompt(
            "你正在和手机主人进行 App 内语音通话。用简短自然的纯文字回答，系统会读出你的回复。"
            "不要输出 XML、Markdown、思考过程或语音标签。只有明确请求时才操作手机。"
            "可以用 phone_report 发文字进度；这个通话界面不接收图片附件，但截图仍可用于你的观察。"
            "每次中断后先重新观察，不能重放之前未确认的操作。",
            name="phone_voice", source="phone_control"))
        request.tools = tool_set.to_list()
        request.assemble_prompt(dynamic_position="system")
        execution = AgentExecutionContext(event, request, messages, [llm])
        reply = ""
        try:
            maximum = ctx.config.get_config("bot_config.agent.max_tool_loop", 8)
            try:
                maximum = max(1, min(16, int(maximum)))
            except (TypeError, ValueError):
                maximum = 8
            async with asyncio.timeout(180):
                async for step in AgentExecutor(ctx.tool_mgr, tool_set).run(execution, maximum):
                    call.ensure_current(turn)
                    if step.state == "error":
                        raise PhoneError("聊天模型暂时无法回答，请稍后重试")
                    if step.state == "stopped":
                        raise PhoneError("本轮回答已停止")
                    content = spoken_text(step.llm_response.text_response)
                    if content:
                        reply = content
                        await call.send({"type": "transcript", "role": "assistant", "text": content}, turn=turn)
            if not reply:
                reply = "这一步处理结束了。"
                await call.send({"type": "transcript", "role": "assistant", "text": reply}, turn=turn)
        except BaseException:
            # Completed tool results/media stay in memory; no unfinished tool-call
            # envelope is appended by AgentExecutor. Never automatically retry.
            messages.append(OpenAIMessage(role="user", content="[本轮通话已中断或失败；未确认的手机操作不要重放，请先观察当前状态。]"))
            raise
        finally:
            try:
                await ctx.session_mgr.update_memory(call.sid, messages)
            finally:
                if call.event is event:
                    call.event = None
        agent_done = monotonic()
        call.ensure_current(turn)
        await call.send({"type": "state", "state": "synthesizing", "detail": "正在生成回复声音"}, turn=turn)
        async with asyncio.timeout(60):
            record = await tts.text_to_speech(reply)
            raw, mime = await record_bytes(record)
        await call.send({"type": "audio", "mime": mime, "length": len(raw),
            "timing_ms": {"recognition": round((stt_done - started) * 1000),
                "agent": round((agent_done - stt_done) * 1000),
                "synthesis": round((monotonic() - agent_done) * 1000)}}, turn=turn, binary=raw)


class VoiceBridge:
    def __init__(self, plugin):
        self.plugin = plugin
        self.backend = KiraVoiceBackend(plugin)
        self.call = None
        self.closed = False
        self.draining = set()

    def finished_draining(self, task):
        self.draining.discard(task)
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass

    def available(self):
        if self.closed or self.plugin.plugin_cfg.get("voice_enabled", False) is not True:
            raise PhoneError("请先在 KiraAI 的手机连接页面开启 App 内通话")
        if self.plugin.plugin_cfg.get("transport", "app") != "app":
            raise PhoneError("App 通话需要使用 App 连接方式")

    def authorize(self, event):
        self.available()
        call = self.call
        if not call or not call.alive or call.event is not event or not call.active_id or event.is_stopped:
            raise PhoneError("这次通话已结束或中断，请重新发起")
        # The command bridge is a separate authenticated socket. A second
        # paired phone must never inherit control of the first phone.
        transport = self.plugin.transport
        connection = getattr(transport, "connection", "")
        if connection and connection.rsplit(":", 1)[0] != call.device_id:
            raise PhoneError("控制连接属于另一台手机，请先连接当前通话手机")

    async def send_text(self, event, element):
        self.authorize(event)
        if not isinstance(element, Text):
            return {"ok": False, "error": "通话界面仅接收文字进度，截图可直接提供给 AI 观察"}
        call = self.call
        ok = await call.send({"type": "transcript", "role": "assistant", "text": element.text[:4000], "progress": True}, turn=call.active_id)
        return {"ok": ok, "message_id": uuid4().hex if ok else ""}

    async def _turn(self, call, pcm, turn):
        try:
            await self.backend.run(call, pcm, turn)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[phone_control] Voice turn failed (%s)", type(exc).__name__)
            detail = str(exc) if isinstance(exc, PhoneError) else "通话处理失败，请检查 KiraAI 的模型配置后重试"
            await call.send({"type": "error", "message": detail[:200]}, turn=turn)
        finally:
            if call.alive and call.active_id == turn:
                call.event = None
                await call.send({"type": "state", "state": "listening"}, turn=turn)

    async def accept(self, socket):
        call = None
        await socket.accept()
        try:
            raw = await asyncio.wait_for(socket.receive_text(), timeout=8)
            if len(raw) > 4096:
                raise PhoneError("连接请求过长")
            hello = json.loads(raw)
            self.available()
            token = getattr(self.plugin.transport, "config", {}).get("device_token", "")
            supplied = hello.get("token") if isinstance(hello, dict) else None
            device = hello.get("device_id") if isinstance(hello, dict) else None
            if (not valid_password(token) or not isinstance(supplied, str)
                    or not hmac.compare_digest(token.encode(), supplied.encode())):
                raise PhoneError("手机连接密码不正确")
            if (hello.get("type") != "hello" or type(hello.get("protocol")) is not int or hello["protocol"] != 1
                    or not isinstance(device, str) or not 1 <= len(device) <= 128 or any(ord(c) < 32 for c in device)):
                raise PhoneError("手机通话协议或设备信息不正确")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", device):
                raise PhoneError("手机设备 ID 只能包含字母、数字、点、横线和下划线")
            allowed = self.plugin.plugin_cfg.get("app_device_id", "")
            if allowed and device != allowed:
                raise PhoneError("这台手机没有连接权限")
            self.backend.models()
            if self.call is not None or self.draining:
                raise PhoneError("已经有一个通话，请先结束再重试")
            name = hello.get("name", "手机")
            call = VoiceCall(self, socket, device, str(name)[:80])
            self.call = call
            await call.send({"type": "welcome", "protocol": 1, "call_id": call.call_id,
                "sample_rate": SAMPLE_RATE, "channels": 1, "format": "pcm_s16le", "max_seconds": 30})
            await call.send({"type": "state", "state": "listening"})
            buffer, recording, started, seen = bytearray(), "", 0.0, set()
            while call.alive and not self.closed:
                timeout = min(75, max(0.1, 35 - (monotonic() - started))) if recording else 75
                message = await asyncio.wait_for(socket.receive(), timeout=timeout)
                if message.get("type") == "websocket.disconnect":
                    break
                chunk = message.get("bytes")
                if chunk is not None:
                    if (not recording or not isinstance(chunk, bytes) or not chunk or len(chunk) > MAX_CHUNK_BYTES
                            or len(chunk) % 2 or len(buffer) + len(chunk) > MAX_PCM_BYTES or monotonic() - started > 35):
                        raise PhoneError("语音数据超出限制，请每次说话不超过 30 秒")
                    buffer.extend(chunk)
                    continue
                text = message.get("text", "")
                if not isinstance(text, str) or len(text) > 4096:
                    raise PhoneError("通话消息格式不正确")
                command = json.loads(text)
                if not isinstance(command, dict):
                    raise PhoneError("通话消息格式不正确")
                kind = command.get("type")
                if kind in {"ping", "heartbeat"}:
                    await call.send({"type": "pong"})
                elif kind == "pong":
                    continue
                elif kind == "hangup":
                    break
                elif kind == "interrupt":
                    interrupt_id = command.get("request_id", "")
                    if not isinstance(interrupt_id, str) or len(interrupt_id) > 128:
                        raise PhoneError("打断请求格式不正确")
                    buffer.clear()
                    recording = ""
                    await call.cancel()
                    await call.send({"type": "state", "state": "listening", "interrupt_id": interrupt_id})
                elif kind == "audio_start":
                    turn = command.get("id")
                    if not isinstance(turn, str) or not 1 <= len(turn) <= 128 or turn in seen:
                        raise PhoneError("语音编号无效或重复，请重新发起通话")
                    if recording or (call.task is not None and not call.task.done()):
                        raise PhoneError("请等待 AI 回答，或先点打断")
                    if len(seen) >= 512:
                        raise PhoneError("本次通话已达上限，请重新发起")
                    seen.add(turn)
                    buffer.clear()
                    recording, call.active_id, started = turn, turn, monotonic()
                elif kind == "audio_end":
                    if not recording or command.get("id") != recording or not buffer:
                        raise PhoneError("没有收到完整语音，请再说一次")
                    pcm, turn = bytes(buffer), recording
                    buffer.clear()
                    recording = ""
                    call.task = asyncio.create_task(self._turn(call, pcm, turn))
                else:
                    raise PhoneError("不支持的通话消息")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = str(exc) if isinstance(exc, PhoneError) else "通话连接中断，请重新发起"
            try:
                if call:
                    await call.cancel()
                async with asyncio.timeout(3):
                    if call:
                        await call.send({"type": "error", "message": detail[:200]})
                    else:
                        await socket.send_json({"type": "error", "message": detail[:200]})
            except Exception:
                pass
        finally:
            if call:
                call.alive = False
                try:
                    await call.cancel()
                except PhoneError:
                    pass
                if self.call is call:
                    self.call = None
            await close_socket(socket)

    async def close(self):
        self.closed = True
        if self.call:
            call = self.call
            call.alive = False
            try:
                await call.cancel()
            finally:
                await close_socket(call.socket, 1001, "Plugin stopped")
