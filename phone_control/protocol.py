"""Shared validation and image types for both supported phone transports."""
import io
import math
import re
from dataclasses import dataclass

from PIL import Image

PROTOCOL_VERSION = 1
ACTION_FIELDS = {
    "tap": {"x", "y"}, "long_press": {"x", "y", "duration_ms"},
    "swipe": {"x", "y", "x2", "y2", "duration_ms"},
    "key": {"key"}, "text": {"text"}, "open_app": {"package"}, "wait": {"seconds"},
}
KEY_NAMES = {"back", "home", "recent", "enter", "backspace", "wake", "volume_up", "volume_down"}


class PhoneError(ValueError):
    """An actionable phone connection or input error."""


def valid_password(value):
    # Keep the exact same printable-ASCII policy as the Android client.
    return isinstance(value, str) and 8 <= len(value) <= 128 and all(33 <= ord(c) <= 126 for c in value)


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise PhoneError(f"{name} 必须是数字")
    if not math.isfinite(value) or not low <= value <= high:
        raise PhoneError(f"{name} 必须在 {low} 到 {high} 之间")
    return float(value)


def validate_action(action, params):
    if not isinstance(action, str) or action not in ACTION_FIELDS or not isinstance(params, dict) or set(params) - ACTION_FIELDS[action]:
        raise PhoneError("未知动作或多余参数，请按工具参数说明调用")
    if action in {"tap", "long_press", "swipe"}:
        for key in (["x", "y", "x2", "y2"] if action == "swipe" else ["x", "y"]):
            number(params.get(key), key, 0, 1000)
        if "duration_ms" in params:
            value = params["duration_ms"]
            number(value, "duration_ms", 100, 3000)
            if not isinstance(value, int):
                raise PhoneError("duration_ms 必须是整数")
    elif action == "key":
        if not isinstance(params.get("key"), str) or params["key"] not in KEY_NAMES:
            raise PhoneError("不支持的系统按键")
    elif action == "text":
        value = params.get("text")
        if not isinstance(value, str) or not 1 <= len(value) <= 1000 or "\x00" in value:
            raise PhoneError("输入文本长度须为 1–1000 字且不能包含空字符")
    elif action == "open_app":
        value = params.get("package")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", value):
            raise PhoneError("package 必须是 Android 包名，例如 com.android.settings")
    else:
        number(params.get("seconds", 1), "seconds", 0, 5)


@dataclass(frozen=True)
class Screen:
    png: bytes
    width: int
    height: int
    preview_width: int
    preview_height: int
    ui_nodes: list | None = None
    mime: str = "image/png"


def decode_screen(raw: bytes, max_edge: int, *, allow_jpeg: bool = False) -> Screen:
    is_png = raw.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = allow_jpeg and raw.startswith(b"\xff\xd8\xff")
    if not (is_png or is_jpeg):
        raise PhoneError("手机未返回有效 PNG/JPEG 截图；检查连接以及当前应用是否允许截图")
    with Image.open(io.BytesIO(raw)) as original:
        if original.format not in ({"PNG", "JPEG"} if allow_jpeg else {"PNG"}):
            raise PhoneError("手机返回了不支持的图片格式")
        if original.width * original.height > 24_000_000:
            raise PhoneError("截图尺寸过大")
        width, height = original.size
        original.load()
        mime = "image/jpeg" if original.format == "JPEG" else "image/png"
        # The phone already scales captures. Validate decoding, but avoid another
        # full compression pass (and JPEG generation loss) at the server.
        if max(width, height) <= max_edge:
            return Screen(raw, width, height, width, height, mime=mime)
        preview = original.convert("RGB")
    try:
        preview.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        preview.save(output, format="JPEG" if is_jpeg else "PNG", **({"quality": 85} if is_jpeg else {}))
        return Screen(output.getvalue(), width, height, *preview.size, mime=mime)
    finally:
        preview.close()
