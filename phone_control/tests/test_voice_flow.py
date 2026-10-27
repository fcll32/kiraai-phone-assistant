"""Transport backpressure/cancellation checks using controlled socket boundaries."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import phone_control.voice as voice
from phone_control.protocol import PhoneError


def call_for(socket):
    bridge = voice.VoiceBridge(SimpleNamespace())
    call = voice.VoiceCall(bridge, socket, 'phone', 'Phone', active_id='turn')
    bridge.call = call
    return call


@pytest.mark.asyncio
async def test_interrupt_finishes_audio_pair_before_next_control_message():
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []
    async def header(payload):
        sent.append(payload['type'])
        if payload['type'] == 'audio':
            entered.set()
            await release.wait()
    async def binary(data): sent.append(data)
    call = call_for(SimpleNamespace(send_json=header, send_bytes=binary, close=AsyncMock()))
    sending = asyncio.create_task(call.send({'type':'audio'}, turn='turn', binary=b'voice'))
    call.task = sending
    await entered.wait()
    interrupt = asyncio.create_task(call.cancel())
    await asyncio.sleep(0)
    release.set()
    await interrupt
    assert await call.send({'type':'state'})
    assert sent == ['audio', b'voice', 'state']
    assert sending.cancelled() and call.alive


@pytest.mark.asyncio
async def test_send_deadline_includes_lock_queue(monkeypatch):
    monkeypatch.setattr(voice, 'SEND_TIMEOUT', .03, raising=False)
    socket = SimpleNamespace(send_json=AsyncMock(), close=AsyncMock())
    call = call_for(socket)
    await call.send_lock.acquire()
    task = asyncio.create_task(call.send({'type':'pong'}))
    try:
        done, _ = await asyncio.wait([task], timeout=.2)
        assert done, 'send must not wait forever for another outgoing packet'
        with pytest.raises(PhoneError): await task
        assert not call.alive
        socket.send_json.assert_not_called()
        socket.close.assert_awaited()
    finally:
        call.send_lock.release()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_broken_audio_pair_closes_call_and_revokes_output():
    socket = SimpleNamespace(send_json=AsyncMock(), send_bytes=AsyncMock(side_effect=OSError('closed')), close=AsyncMock())
    call = call_for(socket)
    with pytest.raises(PhoneError): await call.send({'type':'audio'}, turn='turn', binary=b'voice')
    assert not call.alive
    assert not await call.send({'type':'state'})
    assert socket.send_json.await_count == 1
    socket.close.assert_awaited()


@pytest.mark.asyncio
async def test_bridge_close_is_bounded_when_peer_never_acknowledges(monkeypatch):
    monkeypatch.setattr(voice, 'CLOSE_TIMEOUT', .03, raising=False)
    async def stuck(**kwargs): await asyncio.Event().wait()
    call = call_for(SimpleNamespace(close=stuck))
    task = asyncio.create_task(call.bridge.close())
    try:
        done, _ = await asyncio.wait([task], timeout=.2)
        assert done, 'plugin shutdown must not wait forever on a peer'
        await task
        assert not call.alive and call.bridge.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_interrupted_stalled_audio_drains_or_closes_without_orphan_task(monkeypatch):
    monkeypatch.setattr(voice, 'SEND_TIMEOUT', .03)
    entered = asyncio.Event()
    async def binary(data):
        entered.set()
        await asyncio.Event().wait()
    socket = SimpleNamespace(send_json=AsyncMock(), send_bytes=binary, close=AsyncMock())
    call = call_for(socket)
    before = asyncio.all_tasks()
    call.task = asyncio.create_task(call.send({'type':'audio'}, turn='turn', binary=b'voice'))
    await entered.wait()
    await call.cancel()
    assert not call.alive
    assert not await call.send({'type':'state'})
    assert not (asyncio.all_tasks() - before)
    socket.close.assert_awaited()


@pytest.mark.asyncio
async def test_audio_deadline_closes_once_and_stopped_outputs_never_queue(monkeypatch):
    monkeypatch.setattr(voice, 'SEND_TIMEOUT', .03)
    async def stuck(data): await asyncio.Event().wait()
    socket = SimpleNamespace(send_json=AsyncMock(), send_bytes=stuck, close=AsyncMock())
    call = call_for(socket)
    with pytest.raises(PhoneError): await call.send({'type':'audio'}, turn='turn', binary=b'voice')
    assert socket.close.await_count == 1
    await call.send_lock.acquire()
    try:
        assert not await asyncio.wait_for(call.send({'type':'state'}), .01)
    finally:
        call.send_lock.release()
