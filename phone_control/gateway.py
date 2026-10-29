"""Stream the shared HTTPS entry to Kira's local HTTP/WebSocket server."""
import asyncio
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout, DummyCookieJar, TraceConfig, WSMsgType, WSServerHandshakeError, web
from multidict import CIMultiDict
from yarl import URL


HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade"}


def forwarded_headers(headers):
    blocked = HOP_HEADERS | {part.strip().lower() for value in headers.getall("Connection", [])
                             for part in value.split(",")}
    return CIMultiDict((key, value) for key, value in headers.items() if key.lower() not in blocked)


class WebUIProxy:
    def __init__(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Kira 管理网页端口无效")
        self.origin = f"http://127.0.0.1:{port}"
        trace = TraceConfig()
        trace.on_request_redirect.append(self._check_redirect)
        self.session = ClientSession(cookie_jar=DummyCookieJar(), trust_env=False, auto_decompress=False,
                                     trace_configs=[trace], timeout=ClientTimeout(total=None, sock_connect=5))
        self.tasks = set()

    async def _check_redirect(self, session, context, params):
        location = params.response.headers.get("Location")
        if location and params.url.join(URL(location)).origin() != URL(self.origin).origin():
            # WebSocket handshakes can follow redirects internally. Never carry
            # the browser's Cookie/Authorization to another server or port.
            raise ClientError("Kira upstream redirected outside the local origin")

    async def handle(self, request):
        task = asyncio.current_task()
        self.tasks.add(task)
        response = None
        try:
            # A fixed loopback origin prevents Host/path headers from selecting a target.
            target = URL(self.origin + request.raw_path, encoded=True)
            headers = forwarded_headers(request.headers)
            headers.popall("Forwarded", None)
            headers["X-Forwarded-Proto"] = "https"
            headers["X-Forwarded-For"] = request.remote or "127.0.0.1"
            headers["X-Forwarded-Host"] = request.host
            if request.headers.get("Upgrade", "").lower() == "websocket":
                return await self._websocket(request, target, headers)
            body = request.content.iter_chunked(65536) if request.can_read_body else None
            async with self.session.request(request.method, target, headers=headers, data=body,
                                             allow_redirects=False) as upstream:
                output = forwarded_headers(upstream.headers)
                location = output.get("Location")
                if location and urlsplit(location).netloc == urlsplit(self.origin).netloc:
                    parsed = urlsplit(location)
                    output["Location"] = str(request.url.with_path(parsed.path).with_query(parsed.query).with_fragment(parsed.fragment))
                response = web.StreamResponse(status=upstream.status, headers=output)
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await response.write(chunk)
                await response.write_eof()
                return response
        except WSServerHandshakeError as exc:
            # The upstream retains its login checks; never upgrade an unauthenticated socket.
            return web.Response(status=exc.status if 400 <= exc.status <= 599 else 502)
        except (ClientError, asyncio.TimeoutError):
            if response is not None and response.prepared:
                # The status/headers have gone out already; abort a truncated
                # stream instead of appending an unrelated 502 response to it.
                raise ConnectionResetError("Kira upstream stream interrupted") from None
            raise web.HTTPBadGateway(text="Kira 管理网页暂时不可用，请稍后重试") from None
        finally:
            self.tasks.discard(task)

    async def _websocket(self, request, target, headers):
        offered = [item.strip() for item in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if item.strip()]
        for key in list(headers):
            if key.lower().startswith("sec-websocket-"):
                headers.popall(key, None)
        async with self.session.ws_connect(target, headers=headers, protocols=offered,
                                            max_msg_size=16 * 1024 * 1024, compress=0) as upstream:
            downstream = web.WebSocketResponse(protocols=[upstream.protocol] if upstream.protocol else [],
                                                max_msg_size=16 * 1024 * 1024, compress=False, timeout=1)
            await downstream.prepare(request)

            async def relay(source, destination):
                async for message in source:
                    if message.type == WSMsgType.TEXT:
                        await destination.send_str(message.data)
                    elif message.type == WSMsgType.BINARY:
                        await destination.send_bytes(message.data)
                code = source.close_code or 1000
                await destination.close(code=code if code not in {1005, 1006, 1015} else 1011)

            tasks = [asyncio.create_task(relay(downstream, upstream)),
                     asyncio.create_task(relay(upstream, downstream))]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await downstream.close()
            return downstream

    async def close(self):
        tasks = [task for task in self.tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.session.close()
