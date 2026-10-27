"""Async ADB transport with fixed commands and bounded subprocesses."""

from __future__ import annotations

import asyncio
import base64
import re
import shlex
import subprocess
import sys

from .protocol import PhoneError, Screen, decode_screen, number, validate_action


KEYS = {
    "back": "4", "home": "3", "recent": "187", "enter": "66",
    "backspace": "67", "wake": "224", "volume_up": "24",
    "volume_down": "25",
}
ADB_IME = "com.android.adbkeyboard/.AdbIME"


class AdbClient:
    def __init__(self, config: dict):
        self.executable = str(config.get("adb_path", "adb")).strip() or "adb"
        self.host = str(config.get("adb_server_host", "")).strip()
        self.port = int(number(config.get("adb_server_port", 5037), "ADB 服务端口", 1, 65535))
        self.serial = str(config.get("device_serial", "")).strip()
        self.target = str(config.get("connect_address", "")).strip()
        self.timeout = number(config.get("command_timeout", 15), "命令超时", 1, 60)
        self.max_edge = int(number(config.get("screenshot_max_edge", 1280), "截图长边", 320, 2560))
        self.input_method = config.get("text_input_mode", "adb")
        if self.input_method not in {"adb", "adb_keyboard"}:
            raise PhoneError("输入模式必须为 adb 或 adb_keyboard")
        self.processes: set[asyncio.subprocess.Process] = set()
        self.closed = False

    async def run(self, *args: str) -> bytes:
        if self.closed:
            raise PhoneError("插件已停止，请重新启用")
        command = [self.executable]
        if self.host:
            command.extend(["-H", self.host])
        command.extend(["-P", str(self.port), *args])
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except FileNotFoundError as exc:
            raise PhoneError("找不到 adb；请安装 Android Platform Tools 并配置 adb_path") from exc
        self.processes.add(process)
        try:
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), self.timeout)
            except asyncio.TimeoutError as exc:
                raise PhoneError("ADB 命令超时，操作结果未知；先重新截图，勿盲目重复操作") from exc
            if process.returncode:
                detail = stderr.decode("utf-8", errors="replace").strip()[:700]
                raise PhoneError(f"ADB 执行失败：{detail or '请检查设备连接'}")
            return stdout
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.communicate()
            self.processes.discard(process)

    async def close(self):
        self.closed = True
        processes = list(self.processes)
        for process in processes:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        await asyncio.gather(*(p.wait() for p in processes))

    async def devices(self) -> list[dict]:
        output = (await self.run("devices", "-l")).decode("utf-8", errors="replace")
        devices = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 2 and not line.startswith(("List of devices", "*")):
                devices.append({"serial": parts[0], "state": parts[1], "detail": " ".join(parts[2:])})
        return devices

    async def select_device(self) -> str:
        if self.target:
            if not re.fullmatch(r"(?:[a-zA-Z0-9_.-]+|\[[a-fA-F0-9:]+\]):[0-9]{1,5}", self.target):
                raise PhoneError("connect_address 格式必须为主机:端口")
            response = (await self.run("connect", self.target)).decode("utf-8", errors="replace")
            if "connected to" not in response.lower():
                raise PhoneError(f"无线 ADB 连接失败：{response.strip()[:500]}")
        devices = await self.devices()
        wanted = self.serial or self.target
        if wanted:
            matches = [d for d in devices if d["serial"] == wanted]
            if not matches:
                raise PhoneError("指定手机未连接，请核对 device_serial 和 adb devices -l")
            selected = matches[0]
        else:
            online = [d for d in devices if d["state"] == "device"]
            if len(online) != 1:
                raise PhoneError("请连接并授权一台手机；连接多台时必须配置 device_serial。状态：" + str(devices))
            selected = online[0]
        if selected["state"] != "device":
            raise PhoneError(f"手机状态为 {selected['state']}；请解锁手机确认 USB 调试授权或重新连接")
        return selected["serial"]

    async def shell(self, serial: str, *args: str) -> str:
        # ADB forwards a shell string; quoting each argument also protects the remote shell.
        raw = await self.run("-s", serial, "shell", shlex.join(args))
        result = raw.decode("utf-8", errors="replace").strip()
        if re.search(r"(?im)^(?:error:|exception|java\.lang\.|securityexception)", result):
            raise PhoneError(f"Android 拒绝执行：{result[:500]}")
        return result

    async def screenshot(self, serial: str) -> Screen:
        raw = await self.run("-s", serial, "exec-out", "screencap", "-p")
        return await asyncio.to_thread(decode_screen, raw, self.max_edge)

    async def action(self, serial: str, action: str, params: dict, size: tuple[int, int] | None):
        validate_action(action, params)

        def point(xname, yname):
            if size is None:
                raise PhoneError("点击和滑动前需要先截图")
            x = number(params.get(xname), xname, 0, 1000)
            y = number(params.get(yname), yname, 0, 1000)
            return str(round(x * (size[0] - 1) / 1000)), str(round(y * (size[1] - 1) / 1000))

        if action in {"tap", "long_press", "swipe"}:
            x, y = point("x", "y")
            if action == "tap":
                await self.shell(serial, "input", "tap", x, y)
            else:
                x2, y2 = point("x2", "y2") if action == "swipe" else (x, y)
                default = 600 if action == "long_press" else 400
                duration = int(number(params.get("duration_ms", default), "duration_ms", 100, 3000))
                await self.shell(serial, "input", "swipe", x, y, x2, y2, str(duration))
        elif action == "key":
            key = params.get("key")
            if not isinstance(key, str) or key not in KEYS:
                raise PhoneError("支持的按键：" + ", ".join(KEYS))
            await self.shell(serial, "input", "keyevent", KEYS[key])
        elif action == "text":
            text = params.get("text")
            if not isinstance(text, str) or not 1 <= len(text) <= 1000 or "\x00" in text:
                raise PhoneError("输入文本长度须为 1–1000 字且不能包含空字符")
            if self.input_method == "adb_keyboard":
                current = await self.shell(serial, "settings", "get", "secure", "default_input_method")
                if current != ADB_IME:
                    raise PhoneError("中文输入需要在手机上安装并手动切换到 ADB Keyboard；插件不会修改默认输入法")
                encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
                response = await self.shell(serial, "am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", encoded)
                if "Broadcast completed" not in response:
                    raise PhoneError("ADB Keyboard 未确认广播完成，请检查输入法")
            else:
                if any(ord(c) < 32 or ord(c) > 126 for c in text) or "%s" in text:
                    raise PhoneError("普通 ADB 输入仅支持可打印 ASCII（不含字面量 %s）；中文/换行请配置 adb_keyboard")
                await self.shell(serial, "input", "text", text.replace(" ", "%s"))
        elif action == "open_app":
            package = params.get("package")
            if not isinstance(package, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", package):
                raise PhoneError("package 必须是 Android 包名，例如 com.android.settings")
            result = await self.shell(serial, "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
            if "Events injected: 1" not in result:
                raise PhoneError("应用未成功启动，可能未安装或没有启动入口：" + result[:500])
        else:
            await asyncio.sleep(number(params.get("seconds", 1), "seconds", 0, 5))
