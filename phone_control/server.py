"""Persistent pairing credentials and an in-process TLS listener for the phone."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
from uuid import uuid4

from aiohttp import web, WSMsgType

from .protocol import PhoneError, valid_password
from .gateway import WebUIProxy
from .voice import VOICE_PATH, MAX_CHUNK_BYTES

DEVICE_PATH = "/ws/plugin/phone_control/device"


def validate_settings(ip, port):
    if not isinstance(ip, str) or "%" in ip:
        raise PhoneError("请填写服务器的公网 IP，不含端口或 http://")
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        raise PhoneError("请填写服务器的公网 IP，不含端口或 http://") from None
    if address.is_unspecified or address.is_multicast:
        raise PhoneError("请填写实际的服务器 IP，不能使用 0.0.0.0 或广播地址")
    if type(port) is not int or not 1 <= port <= 65535:
        raise PhoneError("手机连接端口需要是 1–65535 之间的整数")
    return str(address), port


def private_write(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_identity(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "identity.json"
    if path.exists():
        try:
            identity = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(identity, dict) or not valid_password(identity.get("token")):
                raise ValueError("Invalid identity")
            return identity
        except (ValueError, OSError):
            raise PhoneError("已保存的连接信息无法读取，请恢复插件数据备份；不会自动替换旧密码") from None
    identity = {"token": "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789") for _ in range(12))}
    private_write(path, json.dumps(identity))
    return identity


def prepare_certificate(directory, host, identity):
    # Import lazily so a failed dependency installation can be explained in the UI.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    directory = Path(directory)
    now = datetime.now(timezone.utc)
    certificate = None
    if identity.get("host") == host and identity.get("cert") and identity.get("key"):
        certificate = x509.load_pem_x509_certificate(identity["cert"].encode("ascii"))
        if certificate.not_valid_after_utc <= now:
            certificate = None
    if certificate is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
                       .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host))]), critical=False)
                       .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                       .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                       .sign(key, hashes.SHA256()))
        identity = dict(identity, host=host,
                        cert=certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
                        key=key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()).decode("ascii"))
        # A single atomic identity file keeps the certificate and key together.
        private_write(directory / "identity.json", json.dumps(identity))
    cert_path, key_path = directory / "cert.pem", directory / "private-key.pem"
    private_write(cert_path, identity["cert"])
    private_write(key_path, identity["key"])
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_path, key_path)
    fingerprint = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
    return context, fingerprint, certificate.not_valid_after_utc.date().isoformat()


class PhoneSocket:
    """Adapt aiohttp WebSockets to the bridge's small Starlette-like interface."""

    def __init__(self, request):
        self.request = request
        self.ws = web.WebSocketResponse(max_msg_size=12_000_000, compress=False, timeout=1)

    async def accept(self):
        await self.ws.prepare(self.request)

    async def receive_text(self):
        message = await self.ws.receive()
        if message.type != WSMsgType.TEXT:
            raise PhoneError("手机连接已关闭或消息格式不正确")
        return message.data

    async def send_json(self, value):
        # Android accepts UTF-8 JSON. Avoid expanding Chinese/emoji into ASCII
        # escapes, which wastes bandwidth and can exceed its text-frame limit.
        await self.ws.send_str(json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    async def receive(self):
        message = await self.ws.receive()
        if message.type == WSMsgType.TEXT:
            return {"type": "websocket.receive", "text": message.data}
        if message.type == WSMsgType.BINARY:
            return {"type": "websocket.receive", "bytes": message.data}
        return {"type": "websocket.disconnect"}

    async def send_bytes(self, value):
        await self.ws.send_bytes(value)

    async def close(self, code=1000, reason=""):
        await self.ws.close(code=code, message=reason.encode("utf-8"))


class PhoneServer:
    def __init__(self, bridge, directory, voice=None):
        self.bridge = bridge
        self.voice = voice
        self.directory = Path(directory)
        self.runner = None
        self.site = None
        self.clients = set()
        self.fingerprint = ""
        self.expires = ""
        self.host = ""
        self.port = 0
        self.webui_proxy = None
        self.accept_connections = True

    async def start(self, host, port, identity, *, webui_port=None):
        self.host, self.port = validate_settings(host, port)
        if webui_port == port:
            raise PhoneError("加密入口内部端口不能与 Kira 管理网页端口相同；Docker 请使用公网 5267 → 容器 8443")
        context, self.fingerprint, self.expires = await asyncio.to_thread(
            prepare_certificate, self.directory, self.host, identity)
        app = web.Application(client_max_size=4096)
        app.router.add_get(DEVICE_PATH, self._accept)
        if self.voice is not None:
            app.router.add_get(VOICE_PATH, self._accept_voice)
        if webui_port is not None:
            self.webui_proxy = WebUIProxy(webui_port)
            app.router.add_route("*", "/{path:.*}", self.webui_proxy.handle)
        # Forward the original encoded upload together with its Content-Encoding
        # and Content-Length. Decoding here would corrupt the upstream request.
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=2, auto_decompress=False)
        await runner.setup()
        try:
            bind_host = "::" if ipaddress.ip_address(self.host).version == 6 else "0.0.0.0"
            self.site = web.TCPSite(runner, bind_host, self.port, ssl_context=context)
            await self.site.start()
        except BaseException:
            await runner.cleanup()
            if self.webui_proxy:
                await self.webui_proxy.close()
                self.webui_proxy = None
            self.site = None
            raise
        self.runner = runner

    async def _accept(self, request):
        if len(self.clients) >= 8 or self.bridge.closed or not self.accept_connections:
            raise web.HTTPServiceUnavailable(text="Phone connection unavailable")
        task = asyncio.current_task()
        self.clients.add(task)
        socket = PhoneSocket(request)
        try:
            await self.bridge.accept(socket)
            return socket.ws
        finally:
            self.clients.discard(task)

    async def close(self):
        if self.webui_proxy:
            await self.webui_proxy.close()
            self.webui_proxy = None
        if self.site:
            await self.site.stop()
            self.site = None
        tasks = list(self.clients)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    async def _accept_voice(self, request):
        if len(self.clients) >= 8 or self.bridge.closed or not self.accept_connections:
            raise web.HTTPServiceUnavailable(text="Phone connection unavailable")
        task = asyncio.current_task()
        self.clients.add(task)
        socket = PhoneSocket(request)
        # Audio upload is small PCM chunks, separate from the large image pipe.
        socket.ws = web.WebSocketResponse(max_msg_size=MAX_CHUNK_BYTES + 1, compress=False, timeout=1)
        try:
            await self.voice.accept(socket)
            return socket.ws
        finally:
            self.clients.discard(task)

    @property
    def address(self):
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"
