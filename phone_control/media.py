"""Session media storage with a compact layout for Windows path limits."""

import asyncio
from contextlib import nullcontext
import hashlib
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from core.utils import media_refs
from core.utils.media_refs import store_session_media
from core.utils.path_utils import get_data_path


def session_media_scope():
    """3.1 owns in-flight media pins; older Kira has no scope lifecycle."""
    scope = getattr(media_refs, "session_media_scope", None)
    return scope() if scope else nullcontext()


async def store_screenshot(image, png: bytes, sid: str, screenshot_id: str) -> dict:
    root = get_data_path()
    if os.name != "nt" or len(str(root)) + 224 < 250:
        return await store_session_media(image, sid, "phone_" + screenshot_id)

    # Keep the framework's session hash directory so its normal GC still applies.
    # Avoid the extra 64-character message directory on Windows MAX_PATH systems.
    directory = root / "session_media" / hashlib.sha256(sid.encode("utf-8")).hexdigest()
    mime = image.mime or "image/png"
    target = directory / ("phone_" + uuid4().hex + (".jpg" if mime == "image/jpeg" else ".png"))

    # Kira 3.1 has no public API for pinning a custom compact path. Keep this
    # Windows-only adapter bound to its actual GC lock/scope, never a second
    # lock which would race cleanup. Unknown future contracts fail explicitly.
    scoped = hasattr(media_refs, "session_media_scope")
    lock = media_refs._media_lock if scoped else nullcontext()
    scope = media_refs._current_media_scope.get() if scoped else None

    def write():
        with lock:
            resolved = target.resolve()
            if scope is not None and not scope.closed and resolved not in scope.paths:
                scope.paths.add(resolved)
                pins = media_refs._protected_media_paths
                pins[resolved] = pins.get(resolved, 0) + 1
            directory.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="phone_", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(png)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)

    task = asyncio.create_task(asyncio.to_thread(write))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # The worker must finish before the enclosing scope releases its pins.
        await task
        raise
    return {"type": "kira_image_ref", "path": target.relative_to(root).as_posix(),
            "mime_type": mime, "detail": "high"}
