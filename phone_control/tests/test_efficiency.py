import asyncio
import base64
from time import monotonic
from unittest.mock import AsyncMock
import pytest
import phone_control.main as main
from phone_control.main import Snapshot, FRAME_BYTE_BUDGET
from phone_control.protocol import Screen, PhoneError
from phone_control.remote import AppBridge
from test_phone_control import plugin, make_event, unpack, png


def app_bridge():
    bridge = AppBridge({})
    bridge.capabilities = {'ui_tree', 'apps', 'apps_refresh'}
    bridge.select_device = AsyncMock(return_value='phone')
    bridge.action = AsyncMock()
    ui = {'ui_only':True,'width':1080,'height':2400,'nodes':[{'text':'按钮','x':500,'y':300}]}
    image = {'width':1080,'height':2400,'image_base64':base64.b64encode(png()).decode()}
    async def request(serial,method,params): return ui if method=='ui_tree' else image
    bridge.request = AsyncMock(side_effect=request)
    return bridge, ui


@pytest.mark.asyncio
async def test_ui_action_chain_never_transfers_image_until_requested(plugin):
    bridge,_=app_bridge();plugin.transport=bridge
    frame=unpack(await plugin.phone_ui(make_event()))['screenshot_id']
    for _ in range(5):
        response=await plugin.phone_tap(make_event(),500,300,frame)
        data=unpack(response)
        assert data['ok'] and data['action_completed'] and not data['image_bytes'] and not response.media_refs
        frame=data['screenshot_id']
    assert [c.args[1] for c in bridge.request.await_args_list]==['ui_tree']*6
    response=await plugin.phone_navigate(make_event(),'recent',observe_mode='screenshot')
    assert unpack(response)['screenshot_available'] and response.media_refs


@pytest.mark.asyncio
async def test_empty_auto_ui_falls_back_to_screenshot(plugin):
    bridge,ui=app_bridge();plugin.transport=bridge
    frame=unpack(await plugin.phone_ui(make_event()))['screenshot_id']
    ui['nodes']=[]
    result=unpack(await plugin.phone_tap(make_event(),500,300,frame))
    assert result['ok'] and result['screenshot_available'] and result['observation_fallback']
    assert [c.args[1] for c in bridge.request.await_args_list]==['ui_tree','ui_tree','screenshot']


@pytest.mark.asyncio
async def test_observation_mode_cannot_leak_from_another_session(plugin):
    bridge,_=app_bridge();plugin.transport=bridge
    await plugin.phone_ui(make_event(session='other'))
    response=await plugin.phone_navigate(make_event(),'home')
    assert unpack(response)['screenshot_available']
    assert bridge.request.await_args_list[-1].args[1]=='screenshot'


@pytest.mark.asyncio
async def test_unsupported_mode_rejected_before_action(plugin):
    for mode in ('bad','ui',True):
        assert not unpack(await plugin.phone_action(make_event(),'key',{'key':'home'},observe_mode=mode))['ok']
    plugin.transport.action.assert_not_called()


@pytest.mark.asyncio
async def test_image_encoding_shared_and_skipped_when_unused(plugin,monkeypatch):
    original=Snapshot.image
    calls=[]
    def image(self): calls.append(self);return original(self)
    monkeypatch.setattr(Snapshot,'image',image)
    assert unpack(await plugin.phone_screenshot(make_event(),True))['ok']
    assert len(calls)==1
    calls.clear()
    plugin.ctx.get_session_capabilities.return_value={'image_recognition':{'enabled':False}}
    await plugin.phone_screenshot(make_event())
    assert not calls


@pytest.mark.asyncio
async def test_frame_cache_bounds_memory_and_keeps_freshest_target(plugin):
    event=make_event()
    data=b'x'*(8*1024*1024)
    for index in range(16):
        plugin._remember_frame(str(index),Snapshot(event.sid,'serial',0,monotonic(),Screen(data,100,100,100,100)))
    assert len(plugin._frames)==4
    assert sum(len(v.screen.png) for v in plugin._frames.values())==FRAME_BYTE_BUDGET
    assert plugin._frame(event,'15',for_action=True)
    with pytest.raises(PhoneError):plugin._frame(event,'14',for_action=True)
    plugin._frames['15'].created-=601
    plugin._remember_frame('ui',Snapshot(event.sid,'serial',0,monotonic(),Screen(b'',100,100,100,100,[])))
    assert '15' not in plugin._frames


@pytest.mark.asyncio
async def test_apps_refresh_flag_is_forwarded_and_capability_checked():
    bridge,_=app_bridge()
    bridge.request=AsyncMock(return_value={'apps':[],'total':0,'offset':0,'next_offset':-1})
    await bridge.apps('phone','',0,50,True)
    assert bridge.request.call_args.args[2]['refresh'] is True
    bridge.capabilities.remove('apps_refresh')
    with pytest.raises(PhoneError):await bridge.apps('phone','',0,50,True)


@pytest.mark.asyncio
async def test_ui_capability_rechecked_after_waiting_for_device_lock(plugin):
    bridge, _ = app_bridge()
    plugin.transport = bridge
    await plugin._lock.acquire()
    action = asyncio.create_task(plugin.phone_navigate(make_event(), 'home', observe_mode='ui'))
    try:
        await asyncio.sleep(0)
        # A peer reconnects without UI support while this tool is queued.
        bridge.capabilities.clear()
    finally:
        plugin._lock.release()
    data = unpack(await action)
    assert not data['ok'] and not data['action_may_have_run']
    bridge.action.assert_not_awaited()


@pytest.mark.asyncio
async def test_local_wait_still_observes_and_invalidates_previous_target(plugin):
    bridge, _ = app_bridge()
    bridge.action = AppBridge.action.__get__(bridge)
    plugin.transport = bridge
    event = make_event()
    previous = unpack(await plugin.phone_ui(event))['screenshot_id']
    waited = unpack(await plugin.phone_action(event, 'wait', {'seconds': 0}))
    assert waited['ok'] and waited['action_completed'] and not waited['screenshot_available']
    assert [c.args[1] for c in bridge.request.await_args_list] == ['ui_tree', 'ui_tree']
    stale = unpack(await plugin.phone_tap(event, 500, 300, previous, False))
    assert not stale['ok'] and not stale['action_may_have_run']
    assert len(bridge.request.await_args_list) == 2
