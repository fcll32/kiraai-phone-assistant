"""Regressions for frame identity, image formats and model-facing controls."""
import base64
import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from core.utils.media_refs import resolve_media_reference
from phone_control.protocol import PhoneError, Screen, decode_screen
from phone_control.remote import AppBridge
from test_phone_control import make_event, plugin, unpack


def encoded_image(fmt="JPEG", color="#305080", size=(320, 640)):
    output = io.BytesIO()
    with Image.new("RGB", size, color) as image:
        image.save(output, fmt)
    return output.getvalue()


@pytest.mark.parametrize("fmt,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png")])
@pytest.mark.asyncio
async def test_app_image_format_preserved_through_media_storage(plugin, fmt, mime):
    raw = encoded_image(fmt)
    bridge = AppBridge({})
    bridge.request = AsyncMock(return_value={"width": 640, "height": 1280,
        "image_base64": base64.b64encode(raw).decode()})
    screen = await bridge.screenshot("connection")
    assert bridge.request.call_args.args[2]["image_format"] == "jpeg"
    assert screen.png == raw and screen.mime == mime
    assert (screen.width, screen.height) == (640, 1280)
    plugin.transport.screenshot.return_value = screen
    observed = await plugin.phone_screenshot(make_event(), send_to_chat=True)
    data = unpack(observed)
    resolved = await resolve_media_reference(observed.media_refs[0])
    url = resolved["image_url"]["url"]
    assert url.startswith(f"data:{mime};base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == raw
    assert data["image_bytes"] == len(raw) and data["image_mime"] == mime
    assert data["timing_ms"]["total"] >= data["timing_ms"]["capture_and_transfer"] >= 0
    assert plugin.ctx.send_message_chain.call_args.args[1].message_list[0].mime == mime


def test_jpeg_is_opt_in_and_resizing_preserves_format():
    raw = encoded_image()
    with pytest.raises(PhoneError):
        decode_screen(raw, 1280)
    assert decode_screen(raw, 1280, allow_jpeg=True).png is raw
    smaller = decode_screen(raw, 160, allow_jpeg=True)
    assert (smaller.preview_width, smaller.preview_height) == (80, 160)
    assert smaller.mime == "image/jpeg"
    with pytest.raises((PhoneError, OSError)):
        decode_screen(b"\xff\xd8\xffbroken", 1280, allow_jpeg=True)


@pytest.mark.asyncio
async def test_new_observation_invalidates_old_position_without_action(plugin):
    event = make_event()
    old = unpack(await plugin.phone_screenshot(event))["screenshot_id"]
    latest = unpack(await plugin.phone_screenshot(event))["screenshot_id"]
    denied = unpack(await plugin.phone_tap(event, 500, 500, old))
    assert not denied["ok"] and not denied["action_may_have_run"]
    plugin.transport.action.assert_not_called()
    assert unpack(await plugin.phone_tap(event, 500, 500, latest))["action_completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("direction,points", [
    ("up", (500, 800, 500, 200)), ("down", (500, 200, 500, 800)),
    ("left", (800, 500, 200, 500)), ("right", (200, 500, 800, 500)),
])
async def test_swipe_finger_direction(plugin, direction, points):
    event = make_event()
    frame = unpack(await plugin.phone_screenshot(event))["screenshot_id"]
    assert unpack(await plugin.phone_swipe(event, direction, frame, observe_after=False))["ok"]
    args = plugin.transport.action.call_args.args
    assert args[1] == "swipe"
    assert tuple(args[2][key] for key in ("x", "y", "x2", "y2")) == points
    assert args[2]["duration_ms"] == 300


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["back", "home", "recent"])
async def test_navigation(plugin, key):
    assert unpack(await plugin.phone_navigate(make_event(), key, False))["ok"]
    assert plugin.transport.action.call_args.args[1:] == ("key", {"key": key}, None)


@pytest.mark.asyncio
async def test_new_tools_deny_unauthorized_sessions(plugin):
    event = make_event(session="stranger")
    results = [await plugin.phone_tap(event, 500, 500, "no"),
               await plugin.phone_swipe(event, "up", "no"),
               await plugin.phone_navigate(event, "recent"), await plugin.phone_watch(event)]
    assert all(not unpack(result)["ok"] for result in results)
    plugin.transport.select_device.assert_not_called()


@pytest.mark.asyncio
async def test_watch_orders_real_images_and_only_last_frame_can_position(plugin):
    event = make_event()
    raw = [encoded_image(color=color) for color in ("red", "blue", "green")]
    screens = [decode_screen(image, 1280, allow_jpeg=True) for image in raw]
    plugin.transport.screenshot.side_effect = screens
    result = await plugin.phone_watch(event)
    data = unpack(result)
    assert data["ok"] and not data["audio_included"] and not data["continuous_stream"]
    assert [frame["index"] for frame in data["frames"]] == [1, 2, 3]
    assert data["screenshot_id"] == data["frames"][-1]["screenshot_id"]
    for expected, ref in zip(raw, result.media_refs, strict=True):
        resolved = await resolve_media_reference(ref)
        assert base64.b64decode(resolved["image_url"]["url"].split(",", 1)[1]) == expected
    assert not unpack(await plugin.phone_tap(event, 500, 500, data["frames"][0]["screenshot_id"], False))["ok"]
    # The ADB fixture rechecks device size before touching.
    plugin.transport.screenshot.side_effect = None
    plugin.transport.screenshot.return_value = screens[-1]
    assert unpack(await plugin.phone_tap(event, 500, 500, data["screenshot_id"], False))["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("frames,interval", [(True, .5), (5, .5), (2, .1), (2, float("nan"))])
async def test_watch_rejects_invalid_bounds(plugin, frames, interval):
    assert not unpack(await plugin.phone_watch(make_event(), frames, interval))["ok"]
    plugin.transport.select_device.assert_not_called()


@pytest.mark.asyncio
async def test_watch_requires_native_vision_and_real_screen(plugin):
    plugin.ctx.get_session_capabilities.return_value = {"image_recognition": {"mode": "vlm_description"}}
    assert not unpack(await plugin.phone_watch(make_event()))["ok"]
    plugin.transport.select_device.assert_not_called()
    plugin.ctx.get_session_capabilities.return_value = {"image_recognition": {"mode": "native"}}
    plugin.transport.screenshot.return_value = Screen(b"", 1080, 2400, 1080, 2400, [])
    result = await plugin.phone_watch(make_event())
    assert not unpack(result)["ok"] and not result.media_refs


@pytest.mark.asyncio
async def test_watch_disconnect_returns_only_captured_frames(plugin):
    plugin.transport.screenshot.side_effect = [decode_screen(encoded_image(), 1280, allow_jpeg=True), PhoneError("disconnected")]
    result = await plugin.phone_watch(make_event())
    assert not unpack(result)["ok"] and len(unpack(result)["frames"]) == len(result.media_refs) == 1
    assert not plugin._lock.locked()
