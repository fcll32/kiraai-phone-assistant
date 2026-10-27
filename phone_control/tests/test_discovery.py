import base64
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from phone_control.remote import AppBridge
from phone_control.protocol import PhoneError
from test_phone_control import plugin, make_event, unpack, png
from test_app_bridge import setup_app, TOKEN


@pytest.mark.asyncio
async def test_combined_image_and_nodes_preserve_media_context(plugin):
    bridge = AppBridge({})
    bridge.select_device = AsyncMock(return_value='phone')
    bridge.request = AsyncMock(return_value={'width':1080,'height':2400,
        'nodes':[{'text':'设置','x':500,'y':300}], 'image_base64':base64.b64encode(png()).decode()})
    plugin.transport = bridge
    observed = await plugin.phone_screenshot(make_event())
    data = unpack(observed)
    assert data['ok'] and data['ui_elements'][0]['text'] == '设置'
    assert data['screenshot_available'] and len(observed.media_refs) == 1


@pytest.mark.asyncio
async def test_ui_observation_can_target_action_but_not_cross_sessions(plugin):
    bridge = AppBridge({})
    bridge.capabilities = {'ui_tree'}
    bridge.select_device = AsyncMock(return_value='phone')
    bridge.request = AsyncMock(return_value={'width':1080,'height':2400,'ui_only':True,
        'nodes':[{'text':'设置','x':500,'y':300}]})
    bridge.action = AsyncMock()
    plugin.transport = bridge
    observed = await plugin.phone_ui(make_event())
    data = unpack(observed)
    assert data['ok'] and not data['screenshot_available'] and not observed.media_refs
    assert bridge.request.call_args.args[1] == 'ui_tree'
    rejected = await plugin.phone_tap(make_event(session='other'),500,300,data['screenshot_id'],False)
    assert not unpack(rejected)['ok']
    bridge.action.assert_not_called()
    assert unpack(await plugin.phone_tap(make_event(),500,300,data['screenshot_id'],False))['ok']
    bridge.action.assert_awaited_once()


@pytest.mark.asyncio
async def test_discovery_authorization_and_old_apk(plugin):
    bridge = AppBridge({})
    bridge.select_device = AsyncMock(return_value='phone')
    bridge.request = AsyncMock()
    plugin.transport = bridge
    for call in (plugin.phone_ui, plugin.phone_apps):
        assert not unpack(await call(make_event(session='forbidden')))['ok']
        result = unpack(await call(make_event()))
        assert not result['ok'] and '升级' in result['error']
    bridge.request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('kwargs',[{'limit':True},{'limit':101},{'offset':-1},{'query':'x'*81}])
async def test_apps_bad_parameters_never_dispatch(plugin,kwargs):
    bridge = AppBridge({})
    bridge.request = AsyncMock()
    plugin.transport = bridge
    assert not unpack(await plugin.phone_apps(make_event(),**kwargs))['ok']
    bridge.request.assert_not_called()


@pytest.mark.asyncio
async def test_apps_invalid_reply_and_next_page():
    bridge = AppBridge({})
    bridge.capabilities = {'apps'}
    bridge.request = AsyncMock(return_value={'apps':[{'name':'设置','package':'com.android.settings'}],
        'offset':0,'total':2,'next_offset':1})
    assert (await bridge.apps('phone','',0,1))['next_offset'] == 1
    bridge.request.return_value['apps'][0]['package'] = '../invalid'
    with pytest.raises(PhoneError):
        await bridge.apps('phone','',0,1)


def test_apps_real_websocket_discovery_and_launch():
    app,bridge=setup_app()
    @app.get('/apps')
    async def apps():
        return await bridge.apps(await bridge.select_device(),'设置',0,50)
    @app.get('/launch')
    async def launch():
        await bridge.action(await bridge.select_device(),'open_app',{'package':'com.android.settings'},None)
        return {'ok':True}
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        with client.websocket_connect('/device') as ws:
            ws.send_json({'type':'hello','protocol':1,'device_id':'phone','token':TOKEN,'capabilities':['ui_tree','apps']})
            assert ws.receive_json()['type']=='welcome'
            future=pool.submit(client.get,'/apps')
            command=ws.receive_json()
            assert command['method']=='apps' and command['params']['query']=='设置'
            ws.send_json({'type':'result','id':command['id'],'ok':True,'data':{
                'apps':[{'name':'设置','package':'com.android.settings'}],'total':1,'offset':0,'next_offset':-1}})
            assert future.result(5).json()['apps'][0]['package']=='com.android.settings'
            future=pool.submit(client.get,'/launch')
            command=ws.receive_json()
            assert command['method']=='action' and command['params']['args']=={'package':'com.android.settings'}
            ws.send_json({'type':'result','id':command['id'],'ok':True,'data':{}})
            assert future.result(5).json()['ok']
