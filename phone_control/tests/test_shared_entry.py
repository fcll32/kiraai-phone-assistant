import asyncio
import gzip
import hashlib
import json
import ssl
from types import SimpleNamespace

import aiohttp
from aiohttp import web
import pytest
import pytest_asyncio
from fastapi import FastAPI

from phone_control.main import PhoneControlPlugin
from phone_control.remote import AppBridge
from phone_control.server import DEVICE_PATH, PhoneServer, load_identity
from test_builtin_server import unused_port
from test_phone_control import make_context


@pytest_asyncio.fixture
async def shared_entry(tmp_path):
    app = web.Application()
    redirected = []
    foreign = web.Application()
    async def trap(request):
        redirected.append(request.headers.get('Cookie'))
        return web.Response(status=403)
    foreign.router.add_get('/never-send-credentials', trap)
    trap_runner = web.AppRunner(foreign, access_log=None)
    await trap_runner.setup()
    trap_port = unused_port()
    await web.TCPSite(trap_runner, '127.0.0.1', trap_port).start()

    @web.middleware
    async def login(request, handler):
        if request.path != '/login' and request.cookies.get('session') != 'admin':
            raise web.HTTPUnauthorized()
        return await handler(request)
    app.middlewares.append(login)

    async def signin(request):
        response = web.Response(text='login')
        response.set_cookie('session', 'admin', secure=True, httponly=True)
        response.set_cookie('other', 'keep', secure=True)
        return response
    async def info(request):
        return web.json_response({'query': request.query_string, 'proto': request.headers.get('X-Forwarded-Proto'),
                                  'forwarded': request.headers.get('Forwarded'), 'host': request.host,
                                  'forwarded_for': request.headers.get('X-Forwarded-For')})
    async def upload(request):
        digest = hashlib.sha256()
        async for chunk in request.content.iter_chunked(65536):
            digest.update(chunk)
        return web.Response(text=digest.hexdigest())
    async def redirect(request):
        return web.Response(status=302, headers={'Location': f'http://127.0.0.1:{upstream_port}/info?a=1'})
    async def escape(request):
        return web.Response(status=302, headers={'Location': f'http://127.0.0.1:{trap_port}/never-send-credentials'})
    async def events(request):
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        await response.write(b'data: first\n\n')
        await asyncio.sleep(1)
        await response.write(b'data: last\n\n')
        return response
    async def socket(request):
        ws = web.WebSocketResponse(protocols=['kira-test'])
        await ws.prepare(request)
        async for message in ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                await ws.send_str(message.data)
            elif message.type == aiohttp.WSMsgType.BINARY:
                await ws.send_bytes(message.data)
        return ws
    app.router.add_get('/login', signin)
    app.router.add_get('/info', info)
    app.router.add_post('/upload', upload)
    app.router.add_get('/redirect', redirect)
    app.router.add_get('/escape-ws', escape)
    app.router.add_get('/events', events)
    app.router.add_get('/manage-ws', socket)
    upstream = web.AppRunner(app, access_log=None)
    await upstream.setup()
    upstream_port = unused_port()
    await web.TCPSite(upstream, '127.0.0.1', upstream_port).start()
    identity = load_identity(tmp_path)
    bridge = AppBridge({'device_token': identity['token']})
    server = PhoneServer(bridge, tmp_path)
    await server.start('127.0.0.1', unused_port(), identity, webui_port=upstream_port)
    tls = ssl.create_default_context(cafile=str(tmp_path / 'cert.pem'))
    try:
        yield server, bridge, identity, tls
    finally:
        await bridge.close()
        await server.close()
        await upstream.cleanup()
        await trap_runner.cleanup()
        assert not redirected, 'Browser credentials must never reach a redirected upstream'


@pytest.mark.asyncio
async def test_shared_tls_entry_auth_cookies_stream_upload_and_phone(shared_entry):
    server, bridge, identity, tls = shared_entry
    base = 'https://' + server.address
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as browser:
        async with browser.get(base + '/info', ssl=tls) as response:
            assert response.status == 401
        async with browser.get(base + '/login', ssl=tls) as response:
            assert len(response.headers.getall('Set-Cookie')) == 2
        headers = {'Cookie': 'session=admin', 'X-Forwarded-For': 'spoofed', 'Forwarded': 'spoofed'}
        async with browser.get(base + '/info?a=1&a=2', headers=headers, ssl=tls) as response:
            value = await response.json()
            assert value == {'query': 'a=1&a=2', 'proto': 'https', 'forwarded': None,
                             'host': server.address, 'forwarded_for': '127.0.0.1'}
        # Larger than the original phone-only listener's 4 KiB HTTP body budget.
        body = b'plugin-upload' * 65536
        async with browser.post(base + '/upload', data=body, headers=headers, ssl=tls) as response:
            assert response.status == 200 and await response.text() == hashlib.sha256(body).hexdigest()
        async with browser.get(base + '/redirect', headers=headers, ssl=tls, allow_redirects=False) as response:
            assert response.headers['Location'] == base + '/info?a=1'
        async with browser.get(base + '/events', headers=headers, ssl=tls) as response:
            assert await asyncio.wait_for(response.content.readline(), .5) == b'data: first\n'
            await response.read()
        # Management login never grants phone access; it still needs its own password.
        async with browser.ws_connect(base + DEVICE_PATH, ssl=tls) as ws:
            await ws.send_json({'type': 'hello', 'protocol': 1, 'device_id': 'phone', 'token': identity['token']})
            assert (await ws.receive_json())['type'] == 'welcome'
        assert server.runner


@pytest.mark.asyncio
async def test_management_websocket_auth_text_binary_and_protocol(shared_entry):
    server, _, _, tls = shared_entry
    async with aiohttp.ClientSession() as browser:
        with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
            await browser.ws_connect('https://' + server.address + '/manage-ws', ssl=tls)
        assert exc.value.status == 401
        with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
            await browser.ws_connect('https://' + server.address + '/escape-ws', ssl=tls,
                                     headers={'Cookie': 'session=admin'})
        assert exc.value.status == 502
        async with browser.ws_connect('https://' + server.address + '/manage-ws', ssl=tls,
                                      headers={'Cookie': 'session=admin'}, protocols=['kira-test']) as ws:
            assert ws.protocol == 'kira-test'
            await ws.send_str('中文控制台')
            assert (await ws.receive()).data == '中文控制台'
            await ws.send_bytes(b'\x00\x01test')
            assert (await ws.receive()).data == b'\x00\x01test'


@pytest.mark.asyncio
async def test_shared_entry_preserves_compressed_upload(shared_entry):
    server, _, _, tls = shared_entry
    body = b'compressed-plugin-upload' * 4096
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as browser:
        async with browser.post('https://' + server.address + '/upload', ssl=tls,
                                headers={'Cookie': 'session=admin', 'Content-Encoding': 'gzip'},
                                data=gzip.compress(body)) as response:
            assert response.status == 200, await response.text()
            assert await response.text() == hashlib.sha256(body).hexdigest()


@pytest.mark.asyncio
async def test_stopping_phone_keeps_management_entry_alive(shared_entry):
    server, bridge, _, tls = shared_entry
    await bridge.close()
    async with aiohttp.ClientSession() as browser:
        async with browser.get('https://' + server.address + '/login', ssl=tls) as response:
            assert response.status == 200
        with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
            await browser.ws_connect('https://' + server.address + DEVICE_PATH, ssl=tls)
        assert exc.value.status == 503


@pytest.mark.asyncio
async def test_shared_plugin_reuses_entry_across_stop_and_restart(tmp_path, monkeypatch):
    ctx = make_context()
    ctx.get_plugin_data_dir = lambda: tmp_path
    app = FastAPI()
    app.state.disable_auth = False
    ctx.plugin_mgr = SimpleNamespace(_web_app=app)
    cfg = {'shared_entry': True, 'shared_entry_started': True, 'listener_enabled': True, 'public_ip': '127.0.0.1',
           'phone_port': unused_port(), 'public_port': 5267}
    first = PhoneControlPlugin(ctx, cfg)
    await first.initialize()
    entry = first.phone_server
    assert entry and entry.runner and not first.setup_error
    try:
        info = json.loads((await first.connection_info()).body)
        assert info['address'] == '127.0.0.1:5267' and info['listen_port'] == cfg['phone_port']
        await first.terminate()
        assert entry.runner and entry.bridge.closed
        stopped = PhoneControlPlugin(ctx, dict(cfg, listener_enabled=False))
        await stopped.initialize()
        assert not json.loads((await stopped.connection_info()).body)['ready']
        assert entry.runner
        await stopped.terminate()
        resumed = PhoneControlPlugin(ctx, cfg)
        await resumed.initialize()
        assert resumed.phone_server is entry and entry.bridge is resumed.transport
        assert not entry.bridge.closed
        await resumed.terminate()
        async with app.router.lifespan_context(app):
            pass
        assert entry.runner is None and entry.webui_proxy is None
        # A fresh manager after a Kira restart must retain WebUI without reopening control.
        ctx.plugin_mgr = SimpleNamespace(_web_app=app)
        restarted = PhoneControlPlugin(ctx, dict(cfg, listener_enabled=False))
        await restarted.initialize()
        try:
            assert restarted.phone_server.runner and not restarted.phone_server.accept_connections
            assert not restarted._accepting_connections()
            assert not json.loads((await restarted.connection_info()).body)['ready']
        finally:
            await restarted.terminate()
            await ctx.plugin_mgr._phone_control_entry.close()
    finally:
        await entry.close()


@pytest.mark.asyncio
async def test_shared_entry_rejects_same_internal_port_and_unprotected_webui(tmp_path):
    bridge = AppBridge({})
    server = PhoneServer(bridge, tmp_path)
    with pytest.raises(ValueError, match='内部端口'):
        await server.start('127.0.0.1', 5267, {}, webui_port=5267)
    ctx = make_context()
    ctx.get_plugin_data_dir = lambda: tmp_path
    app = FastAPI()
    app.state.disable_auth = True
    ctx.plugin_mgr = SimpleNamespace(_web_app=app)
    plugin = PhoneControlPlugin(ctx, {'shared_entry': True, 'listener_enabled': True, 'public_ip': '127.0.0.1'})
    await plugin.initialize()
    try:
        assert not json.loads((await plugin.connection_info()).body)['ready']
        assert '登录验证' in plugin.setup_error
    finally:
        await plugin.terminate()


@pytest.mark.asyncio
async def test_real_kira_admin_can_stop_and_resume_through_shared_https(tmp_path, monkeypatch):
    import uvicorn
    from core.plugin import PluginManager
    from core.plugin.plugin_installer import install_from_zip
    from webui.utils import _access_token_fingerprint, _create_jwt_token
    from package_plugin import build_plugin

    monkeypatch.setattr('core.plugin.manager.PLUGIN_CONFIG_DIR', tmp_path / 'configs')
    monkeypatch.setattr('core.utils.path_utils.get_data_path', lambda: tmp_path)
    backend_port = unused_port()
    (tmp_path / 'webui.json').write_text(json.dumps({'port': backend_port}), encoding='utf-8')
    installed = await install_from_zip(build_plugin(tmp_path).read_bytes(), tmp_path / 'plugins')
    ctx = make_context()
    ctx.get_plugin_data_dir = lambda: tmp_path / 'identity'
    manager = PluginManager(ctx)
    ctx.plugin_mgr = manager
    app = FastAPI()
    app.state.disable_auth = False
    app.state.access_token = 'admin-test-password'
    manager.set_web_app(app)
    backend = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=backend_port, log_level='error'))
    serving = asyncio.create_task(backend.serve())
    try:
        async with asyncio.timeout(5):
            while not backend.started:
                if serving.done():
                    await serving
                await asyncio.sleep(.01)
        plugin_id = await manager.load_plugin_from_dir(installed, auto_install=False)
        assert plugin_id == 'phone_control'
        listen = unused_port()
        await manager.update_plugin_config(plugin_id, {'shared_entry': True, 'shared_entry_started': True,
            'listener_enabled': True, 'public_ip': '127.0.0.1', 'phone_port': listen, 'public_port': 5267})
        plugin = manager.plugin_instances[plugin_id]
        entry = plugin.phone_server
        assert entry and not plugin.setup_error
        tls = ssl.create_default_context(cafile=str(entry.directory / 'cert.pem'))
        base = 'https://' + entry.address
        token = _create_jwt_token({'sub': 'admin', 'auth_mode': 'enabled', 'tv': _access_token_fingerprint(app.state.access_token)})
        async with aiohttp.ClientSession() as client:
            async with client.get(base + '/api/plugin/phone_control/setup', ssl=tls) as response:
                assert response.status == 401
            headers = {'Cookie': 'kira_token=' + token, 'X-Phone-Setup': '1'}
            async with client.get(base + '/page/plugin/phone_control/connect/', ssl=tls, headers=headers) as response:
                assert response.status == 200 and 'setup-form' in await response.text()
            async with client.post(base + '/api/plugin/phone_control/setup', ssl=tls, headers=headers,
                                   json={'action': 'stop'}) as response:
                assert response.status == 200
            async with client.get(base + '/api/plugin/phone_control/setup', ssl=tls, headers=headers) as response:
                assert not (await response.json())['ready']
            assert manager.plugin_instances[plugin_id].phone_server is entry and entry.runner
            async with client.post(base + '/api/plugin/phone_control/setup', ssl=tls, headers=headers,
                json={'action': 'start', 'shared_entry': True, 'listen_port': listen,
                      'public_ip': '127.0.0.1', 'port': 5267, 'password': 'KiraTest88'}) as response:
                assert response.status == 200, await response.text()
            async with client.ws_connect(base + DEVICE_PATH, ssl=tls) as ws:
                await ws.send_json({'type': 'hello', 'protocol': 1, 'device_id': 'phone', 'token': 'KiraTest88'})
                assert (await ws.receive_json())['type'] == 'welcome'
    finally:
        await manager.terminate('phone_control')
        backend.should_exit = True
        await asyncio.wait_for(serving, 5)
    assert entry.runner is None
