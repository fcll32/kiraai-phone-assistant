import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { test } from 'node:test'

// Execute the actual component scripts against a deterministic clock and native
// boundary. This checks state/gesture races, not Android rendering or hit testing.
function component(file, overrides = {}) {
  let now = 1000, sequence = 0
  const jobs = new Map(), hooks = {}, watchers = [], events = []
  const schedule = (fn, delay, interval = false) => {
    const id = ++sequence
    jobs.set(id, { fn, at: now + delay, delay, interval })
    return id
  }
  const nativeState = { running: false, connected: false, configured: true, accessibility: true,
    screenProtected: true, secureConfigured: true, address: '203.0.113.10:8443', status: '已停止' }
  const config = { address: nativeState.address, password: 'a'.repeat(32), fingerprint: '' }
  const phone = { readState: () => JSON.stringify(nativeState), readConfig: () => JSON.stringify(config),
    saveConfig(address, password, fingerprint) { Object.assign(config, { address, password, fingerprint }); nativeState.address = address; nativeState.configured = true },
    setSecure(value) { nativeState.screenProtected = value; return value }, secure() {},
    startConnection() { nativeState.running = true }, stopConnection() { nativeState.running = false; nativeState.connected = false },
    prepare() {}, savePreferences() {}, ...overrides.phone }
  const dialogs = [], toasts = []
  const context = vm.createContext({
    console, Math, JSON, Set, Promise,
    Date: class extends Date { static now() { return now } },
    setTimeout: (fn, ms) => schedule(fn, ms), clearTimeout: id => jobs.delete(id),
    setInterval: (fn, ms) => schedule(fn, ms, true), clearInterval: id => jobs.delete(id),
    ref: value => ({ value }), reactive: value => value,
    computed: read => ({ get value() { return read() } }),
    nextTick: fn => { if (fn) fn(); return Promise.resolve() },
    watch(read, fn, options = {}) { const w = { read, fn, old: JSON.stringify(read()) }; watchers.push(w); if (options.immediate) fn(read()) },
    defineProps: definitions => Object.fromEntries(Object.entries(definitions).map(([key, spec]) =>
      [key, overrides.props?.[key] ?? (typeof spec.default === 'function' ? spec.default() : spec.default)])),
    defineEmits: () => (name, ...args) => events.push([name, ...args]),
    onUnmounted: fn => { hooks.unmount = fn }, onReady: fn => { hooks.ready = fn },
    onShow: fn => { hooks.show = fn }, onHide: fn => { hooks.hide = fn }, onBackPress: fn => { hooks.back = fn },
    phone, errorText: error => error.message,
    uni: { showModal: options => dialogs.push(options), showToast: options => toasts.push(options.title),
      getWindowInfo: () => ({ windowWidth: 390, windowHeight: 844 }),
      getStorageSync: () => '', setStorageSync() {}, ...overrides.uni }
  })
  const run = source => vm.runInContext(source, context)
  for (const lib of ['timers', 'interactions']) run(readFileSync(new URL(`../uni-app/lib/${lib}.js`, import.meta.url), 'utf8').replaceAll('export ', ''))
  const script = readFileSync(new URL('../uni-app/' + file, import.meta.url), 'utf8').split('<script setup>')[1].split('</script>')[0]
  run(script.replace(/^import .*$/gm, ''))
  function flush() {
    for (const w of watchers) { const v = JSON.stringify(w.read()); if (v !== w.old) { w.old = v; w.fn(w.read()) } }
  }
  function tick(ms) {
    const end = now + ms
    while (true) {
      const due = [...jobs.entries()].filter(([, j]) => j.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
      if (!due) break
      const [id, job] = due
      now = job.at
      if (job.interval) job.at += job.delay
      else jobs.delete(id)
      job.fn(); flush()
    }
    now = end; flush()
  }
  return { run, tick, flush, hooks, events, nativeState, phone, dialogs, toasts, jobs }
}
const page = options => {
  const p = component('pages/index/index.uvue', options)
  p.run('Object.assign(form, JSON.parse(phone.readConfig()))')
  return p
}
const touch = (x, y = 100) => `({touches:[{clientX:${x},clientY:${y}}]})`

test('idle polling skips closed diagnostics but keeps call and connection state current', () => {
  let diagnostics = 0, calls = 0
  const p = page({phone: {
    readCallState() { calls++; return JSON.stringify({active:false}) },
    readVirtualMicState() { diagnostics++; return JSON.stringify({active:false,status:'idle'}) }
  }})
  p.hooks.show()
  const initial = diagnostics
  p.tick(9000)
  assert.equal(diagnostics, initial)
  assert.equal(calls, 11)
  p.nativeState.connected = true; p.nativeState.running = true
  p.tick(900); assert.equal(p.run('state.connected'), true)
  p.run('page.value = 4; labOpen.value = true'); p.flush()
  assert.equal(diagnostics, initial + 1)
  p.tick(900); assert.equal(diagnostics, initial + 2)
  p.run('labOpen.value = false'); p.flush()
  p.tick(900); assert.equal(diagnostics, initial + 2)
  p.hooks.hide(); const before = calls; p.tick(9000)
  assert.equal(calls, before)
  p.hooks.show(); assert.equal(diagnostics, initial + 3)
  p.hooks.unmount()
})

test('active or pending diagnostics keep polling even after leaving their panel', () => {
  let reads = 0
  const snapshot = {active:true,status:'playing'}
  const p = page({phone:{readVirtualMicState() { reads++; return JSON.stringify(snapshot) }}})
  p.hooks.show(); p.tick(900); assert.equal(reads,2)
  snapshot.active = false; snapshot.status = 'binding'
  p.tick(900); p.tick(900); assert.equal(reads,4)
  snapshot.status = 'ready'
  p.tick(900); p.tick(900); assert.equal(reads,5)
  p.hooks.unmount()
})

test('quick start follows actual setup state and never starts a connection by itself', () => {
  const c = component('components/QuickStart.uvue')
  c.run('act(); act()'); c.tick(400)
  assert.equal(c.run('index.value'), 1)
  c.run('act()'); assert.deepEqual(c.events.at(-1), ['action', 1])
  c.run('props.configured = true; act()'); c.tick(400)
  assert.equal(c.run('index.value'), 2)
  c.run('act()'); assert.deepEqual(c.events.at(-1), ['action', 2])
  c.run('props.accessibility = true; act()'); c.tick(400)
  c.run('act()'); assert.deepEqual(c.events.at(-1), ['action', 3])
  c.run('next()'); assert.deepEqual(c.events.at(-1), ['close'])
  c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('quick start settles immediately when animations disable or app hides', () => {
  const c = component('components/QuickStart.uvue')
  c.run('next(); props.duration = 0'); c.flush()
  assert.equal(c.run('index.value'), 1); assert.equal(c.jobs.size, 0)
  c.run('next()'); assert.equal(c.run('index.value'), 2)
  c.run('props.duration = 400'); c.flush(); c.run('back(); props.active = false'); c.flush()
  assert.equal(c.run('index.value'), 1); assert.equal(c.jobs.size, 0)
  c.run('act()'); assert.equal(c.events.length, 0)
  c.hooks.unmount()
})

test('first launch guide can be skipped and replayed without discarding drafts', () => {
  const saved = new Map()
  const p = page({uni: {getStorageSync: key => saved.get(key), setStorageSync: (key,value) => saved.set(key,value)}})
  p.nativeState.configured = false; p.hooks.ready()
  assert.equal(p.run('guideOpen.value'), true)
  p.run("form.address = 'draft:8443'; closeGuide(); openGuide()")
  assert.equal(p.run('form.address'), 'draft:8443')
  assert.equal(p.hooks.back(), true)
  assert.equal(saved.get('kira-quick-start-v1'), true)
  p.hooks.ready(); assert.equal(p.run('guideOpen.value'), false)
  p.hooks.unmount(); assert.equal(p.jobs.size, 0)
})

test('saving rechecks native control, call and microphone experiment states', async () => {
  for (const busy of ['control', 'call', 'experiment']) {
    let saves = 0
    const p = page({ phone: {
      saveConfig() { saves++ },
      readCallState: () => JSON.stringify({ active: busy === 'call' }),
      readVirtualMicState: () => JSON.stringify({ active: busy === 'experiment' })
    } })
    p.nativeState.running = busy === 'control'
    await p.run('saveConnection()')
    assert.equal(saves, 0, busy)
    assert.equal(p.run('saveButton.value'), 'idle')
    assert.match(p.toasts.at(-1), /请先停止/)
    p.hooks.unmount()
  }
})

test('liquid navigation retargets from its current position and cleans up', () => {
  const c = component('components/LiquidNav.uvue')
  c.run('props.page = 4'); c.flush(); c.tick(120)
  assert.ok(c.run('head.value > tail.value'))
  c.run('props.page = 1'); c.flush(); c.tick(420)
  assert.equal(c.run('head.value'), 1); assert.equal(c.run('tail.value'), 1)
  c.run('props.page = 2; props.duration = 0'); c.flush()
  assert.equal(c.run('head.value'), 3)
  c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('jelly protection waits for confirmation and disabled requests do nothing', () => {
  const c = component('components/JellySwitch.uvue')
  c.run('request()'); c.tick(500)
  assert.equal(c.run('position.value'), 0)
  assert.equal(c.events[0][1].detail.value, true)
  c.run('props.checked = true'); c.flush(); c.tick(400)
  assert.equal(c.run('position.value'), 1)
  c.run('props.disabled = true; request()')
  assert.equal(c.events.length, 1); c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('sheet cancels stale close animation on reopen, uses distance and ignores stale fling', () => {
  const c = component('components/SpringSheet.uvue')
  c.run('props.open = true'); c.flush(); c.tick(420)
  c.run('props.open = false'); c.flush(); c.tick(100)
  c.run('props.open = true'); c.flush(); c.tick(420)
  assert.equal(c.run('mounted.value'), true); assert.equal(c.run('progress.value'), 1)
  c.run(`start(${touch(100, 100)})`); c.tick(16); c.run(`move(${touch(100, 145)})`)
  c.tick(120); c.run('end()'); c.tick(420)
  assert.equal(c.events.some(e => e[0] === 'close'), false)
  c.run(`start(${touch(100, 100)}); move(${touch(100, 270)}); end()`)
  assert.equal(c.events.at(-1)[0], 'close')
  c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('flip actions cannot fire before the back settles and rapid taps do not double flip', () => {
  const c = component('components/CapabilityFlip.uvue')
  c.run("flip(); flip(); act('connect')"); assert.equal(c.events.length, 0)
  c.tick(320); assert.equal(c.run('back.value'), true); assert.equal(c.run('ready.value'), false)
  c.tick(300); c.run("act('connect')"); assert.equal(c.events.at(-1)[0], 'connect')
  c.run('flip()'); c.tick(620); assert.equal(c.run('back.value'), false)
  c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('a new card gesture cancels its delayed detail entry; interrupted drag retains position', () => {
  const c = component('components/SwipeDeck.uvue', { props: { cards: [{}, {}, {}] } })
  c.run('onSelect(0, null)'); c.tick(50); c.run(`onStart(${touch(100)})`); c.tick(500)
  assert.equal(c.events.some(e => e[0] === 'select'), false)
  c.run('settle(1)'); c.tick(120)
  const ratio = c.run('ratio.value')
  c.run(`onStart(${touch(100)})`)
  assert.equal(c.run('ratio.value'), ratio)
  c.run('onCancel()'); c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('floating labels stay raised for values after blur and lower only when empty', () => {
  const c = component('components/FloatingField.uvue')
  assert.match(c.run('labelStyle.value.transform'), /translateY\(0px\)/)
  c.run('focused.value = true'); assert.match(c.run('labelStyle.value.transform'), /-28px/)
  c.run("props.modelValue = '1.2.3.4:8443'; focused.value = false")
  assert.match(c.run('labelStyle.value.transform'), /-28px/)
  c.run("props.modelValue = ''"); assert.match(c.run('labelStyle.value.transform'), /translateY\(0px\)/)
})

test('detail header snaps intermediate scroll and clears pending work on unmount', () => {
  const c = component('components/StickyDetail.uvue')
  c.run('offset.value = 120; velocity = 0; snap()'); c.tick(420)
  assert.equal(c.run('scrollTarget.value'), 180)
  c.run('offset.value = 60; velocity = -0.4; snap()'); c.tick(420)
  assert.equal(c.run('scrollTarget.value'), 0)
  c.run('end()'); c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('granting microphone never starts a call without another tap', () => {
  let requests = 0, starts = 0
  const call = { active: false, microphoneGranted: false }
  const p = page({ phone: { readCallState: () => JSON.stringify(call),
    requestMicrophone() { requests++ }, startCall() { starts++; call.active = true } } })
  p.run('refresh(); startCall()')
  assert.equal(requests, 1); assert.equal(starts, 0)
  call.microphoneGranted = true
  p.run('refresh()'); assert.equal(starts, 0)
  // Voice does not require the separate remote-control connection to be running.
  p.run('startCall()'); assert.equal(starts, 1); assert.equal(p.nativeState.running, false)
  p.run('startCall()'); assert.equal(starts, 1)
})
test('voice failures remain visible and tests cannot contend with an active call', () => {
  let tests = 0, starts = 0
  const call = { active: false, microphoneGranted: true }
  const mic = { active: false, verified: false }
  const p = page({ phone: { readCallState: () => JSON.stringify(call),
    readVirtualMicState: () => JSON.stringify(mic),
    startCall() { starts++; throw Error('server unavailable') },
    testVirtualMic() { tests++ } } })
  p.run('refresh(); startCall()')
  assert.equal(p.run('voice.active'), false); assert.equal(p.toasts.at(-1), 'server unavailable')
  mic.active = true; p.run('startCall()'); assert.equal(starts, 1)
  mic.active = false; call.active = true
  p.run("testMic('top.kira.phone')"); assert.equal(tests, 0)
  assert.equal(p.run('mic.verified'), false)
})
test('hanging up reads native state and hiding the UI does not silently end a call', () => {
  let stops = 0
  const call = { active: true, microphoneGranted: true, muted: false }
  const p = page({ phone: { readCallState: () => JSON.stringify(call),
    stopCall() { stops++; call.active = false }, setCallMuted(value) { call.muted = value } } })
  p.run('refresh(); toggleMute()'); assert.equal(p.run('voice.muted'), true)
  p.hooks.hide(); assert.equal(stops, 0)
  p.run('stopCall()'); assert.equal(stops, 1); assert.equal(p.run('voice.active'), false)
})
test('expanded home cards open the intended call pane and obey animation preference', () => {
  const p = page()
  p.run('effects.transition = false; effects.cards = false; openStack(1)')
  assert.equal(p.run('expanded.value'), true); assert.equal(p.run('page.value'), 0)
  p.run('openStack(2)'); assert.equal(p.run('page.value'), 4); assert.equal(p.run('labOpen.value'), true)
  assert.equal(p.run('stackStyle(2).transitionDuration'), '0ms')
})

test('privacy switch commits only native-confirmed state and recovers from failure', () => {
  const p = page()
  p.run('setShield(false)')
  assert.equal(p.run('shield.value'), false)
  assert.equal(p.nativeState.screenProtected, false)
  p.phone.setSecure = () => { throw Error('native failure') }
  p.run('setShield(true)')
  assert.equal(p.run('shield.value'), false)
  assert.equal(p.toasts.at(-1), 'native failure')
  assert.equal(p.run('shieldBusy.value'), false)
})
test('privacy switch does not report success if native state disagrees', () => {
  const p = page({ phone: { setSecure: () => true } })
  p.run('onShieldChange({detail:{value:false}})')
  assert.equal(p.run('shield.value'), true)
  assert.equal(p.toasts.some(t => t.startsWith('已关闭')), false)
})
test('connection confirmation is single-flight and failed startup cancels every delayed transition', () => {
  const p = page({ phone: { startConnection() { throw Error('start failed') } } })
  p.run('toggleConnection(); toggleConnection()')
  assert.equal(p.dialogs.length, 1)
  p.dialogs[0].success({ confirm: true })
  assert.equal(p.run('heroOpacity.value'), 0)
  assert.equal(p.run('heroTitle.value'), '准备连接')
  p.tick(2000)
  assert.equal(p.run('heroTitle.value'), '准备连接')
  assert.equal(p.run('heroOpacity.value'), 1)
  assert.equal(p.run('connectButton.value'), 'idle')
  assert.equal(p.run('starting'), false)
})

test('connection draft survives navigation and accessibility settings, then saves before confirmation', () => {
  const p = page()
  p.nativeState.configured = false; p.nativeState.accessibility = false
  p.run("applyPage(1); form.address = '203.0.113.20:9443'; applyPage(0); applyPage(1)")
  assert.equal(p.run('form.address'), '203.0.113.20:9443')
  p.hooks.hide(); p.nativeState.accessibility = true; p.hooks.show()
  assert.equal(p.nativeState.running, false)
  p.run('toggleConnection()')
  assert.equal(p.nativeState.address, '203.0.113.20:9443')
  assert.equal(p.dialogs.length, 1)
  assert.match(p.dialogs[0].content, /203\.0\.113\.20:9443/)
  p.dialogs[0].success({ confirm: true }); p.tick(1500)
  assert.equal(p.nativeState.running, true)
  p.hooks.unmount()
})

test('invalid connection input stays visible and never starts or opens confirmation', () => {
  const p = page({ phone: { saveConfig() { throw Error('请复制完整的连接密码，至少 32 位') } } })
  p.run("form.password = 'short'; toggleConnection()")
  assert.equal(p.dialogs.length, 0)
  assert.equal(p.nativeState.running, false)
  assert.match(p.run('connectionFeedback.value'), /连接密码/)
  assert.equal(p.run('form.password'), 'short')
  p.hooks.unmount()
})

test('blank connection fields show readable guidance before native validation', () => {
  let saves = 0
  const p = page({ phone: { saveConfig() { saves++; throw Error('native validation must not run') } } })
  p.run("form.address = '  '; form.password = '  '; toggleConnection()")
  assert.equal(saves, 0)
  assert.equal(p.dialogs.length, 0)
  assert.equal(p.nativeState.running, false)
  assert.equal(p.toasts.at(-1), '请填写服务器地址，例如 203.0.113.10:8443')
  assert.equal(p.run('form.address'), '  ')
  p.run("form.address = '203.0.113.20:9443'; toggleConnection()")
  assert.equal(saves, 0)
  assert.equal(p.dialogs.length, 0)
  assert.equal(p.toasts.at(-1), '请填写连接密码')
  assert.equal(p.nativeState.running, false)
  p.hooks.unmount()
})

test('synchronous dialog failure releases confirmation gate and allows retry', () => {
  let attempts = 0
  const p = page({ uni: { showModal() { attempts++; throw Error('dialog unavailable') } } })
  p.run('toggleConnection(); toggleConnection()')
  assert.equal(attempts, 2)
  assert.equal(p.run('confirming'), false)
  assert.match(p.run('connectionFeedback.value'), /dialog unavailable/)
  p.hooks.unmount()
})

test('returning from a hidden confirmation allows retry and ignores its late callback', () => {
  const p = page()
  p.run('toggleConnection()'); p.hooks.hide(); p.hooks.show()
  p.run('toggleConnection()')
  assert.equal(p.dialogs.length, 2)
  p.dialogs[0].success({ confirm: true }); p.tick(1000)
  assert.equal(p.nativeState.running, false)
  assert.equal(p.run('confirming'), true)
  p.dialogs[1].success({ confirm: true }); p.tick(1000)
  assert.equal(p.nativeState.running, true)
  p.hooks.unmount()
})

test('accessibility still binding gives visible feedback and the next tap rechecks native state', () => {
  const p = page()
  p.nativeState.accessibility = false
  p.run('toggleConnection()')
  assert.equal(p.dialogs.length, 0)
  assert.match(p.run('connectionFeedback.value'), /无障碍/)
  p.nativeState.accessibility = true
  p.run('toggleConnection()')
  assert.equal(p.dialogs.length, 1)
  p.hooks.unmount()
})
test('fast authentication cannot be overwritten by connecting animation callbacks', () => {
  const p = page()
  p.run('toggleConnection()'); p.dialogs[0].success({ confirm: true }); p.tick(200)
  p.nativeState.connected = true
  p.run('refresh()'); p.tick(800)
  assert.equal(p.run('heroTitle.value'), '手机已就绪')
  assert.equal(p.run('connectButton.value'), 'success')
  p.run('toggleConnection()'); p.tick(1500)
  assert.equal(p.run('heroTitle.value'), '准备连接')
})
test('hiding during preparation cancels the pending start without trapping the button', () => {
  const p = page()
  p.run('toggleConnection()'); p.dialogs[0].success({ confirm: true })
  p.hooks.hide(); p.tick(2000)
  assert.equal(p.nativeState.running, false)
  assert.equal(p.run('starting'), false)
  assert.equal(p.run('connectButton.value'), 'idle')
})
test('startup still works with all effects disabled', () => {
  const p = page()
  p.run('effects.transition = false; effects.feedback = false; effects.cards = false; toggleConnection()')
  p.dialogs[0].success({ confirm: true }); p.tick(400)
  assert.equal(p.nativeState.running, true)
  assert.equal(p.run('heroOpacity.value'), 1)
  assert.equal(p.run('connectButton.value'), 'idle')
})
test('left swipe settles towards the next card, not the opposite direction', () => {
  const c = component('components/SwipeDeck.uvue', { props: { cards: [{}, {}, {}], width: 346 } })
  c.run(`onStart(${touch(250)})`); c.tick(100); c.run(`onMove(${touch(130)}); onEnd()`)
  c.tick(200)
  assert.ok(c.run('ratio.value') < -0.3)
  c.tick(300)
  assert.deepEqual(c.events.at(-1), ['change', 1])
  c.run('onSelect(0)')
  assert.equal(c.events.some(e => e[0] === 'select'), false)
})
test('first-card outward swipe and cancelled gestures do not change cards', () => {
  const c = component('components/SwipeDeck.uvue', { props: { cards: [{}, {}, {}], width: 346 } })
  c.run(`onStart(${touch(100)})`); c.tick(100); c.run(`onMove(${touch(200)}); onEnd()`); c.tick(500)
  assert.equal(c.events.some(e => e[0] === 'change'), false)
  c.run(`onStart(${touch(250)})`); c.tick(100); c.run(`onMove(${touch(100)}); onCancel()`); c.tick(500)
  assert.equal(c.events.some(e => e[0] === 'change'), false)
})
test('wheel clears stale velocity and ignores native click generated after dragging', () => {
  const c = component('components/SpeedWheel.uvue')
  c.run(`onStart(${touch(100, 200)})`); c.tick(100); c.run(`onMove(${touch(100, 150)})`)
  c.tick(200); c.run('onEnd(); pick(0)'); c.tick(600)
  assert.deepEqual(c.events.filter(e => e[0] === 'change'), [['change', 2]])
  assert.deepEqual(c.events.at(-1), ['settling', false])
})
test('success animation and shine leave no timers after unmount', () => {
  const c = component('components/FeedbackButton.uvue', { props: { state: 'success', shine: true } })
  c.tick(50); c.hooks.unmount(); c.tick(5000)
  assert.equal(c.jobs.size, 0)
  assert.equal(c.run('armLong.value'), false)
})
test('returning to idle cancels old success strokes; background stops decorative loops', () => {
  const c = component('components/FeedbackButton.uvue', { props: { state: 'success', shine: true } })
  c.tick(50); c.run("props.state = 'idle'"); c.flush(); c.tick(500)
  assert.equal(c.run('armLong.value'), false)
  c.run('props.active = false'); c.flush(); c.tick(5000)
  assert.equal(c.jobs.size, 0)
})
test('closing detail completes before its navigation action runs', () => {
  const p = page()
  p.run('detailOpen.value = true; detailIndex.value = 0; detailAction()')
  p.tick(240); assert.equal(p.run('page.value'), 0)
  p.tick(100); assert.equal(p.run('detailOpen.value'), false)
  assert.equal(p.run('page.value'), 1)
})

test('detail first frame uses the tapped card bounds; closing early cannot reopen it', () => {
  const c = component('components/SwipeDeck.uvue')
  c.run('onSelect(0, {currentTarget:{getBoundingClientRect:()=>({left:33,top:400,width:324,height:180})}})')
  c.tick(400)
  const selection = c.events.at(-1)[1]
  const p = page()
  p.run(`openDetail(${JSON.stringify(selection)})`)
  assert.equal(p.run('detailOpen.value'), true)
  assert.equal(p.run('detailMs.value'), 0)
  assert.equal(p.run('detailX.value'), 23)
  assert.equal(p.run('detailY.value'), 364)
  assert.ok(p.run('detailSY.value') < 0.3)
  p.run('closeDetail()'); p.tick(2000)
  assert.equal(p.run('detailOpen.value'), false)
  assert.equal(p.run('detailBusy.value'), false)
})

test('detail expansion, connection transition and deck settling use selected speed', () => {
  for (const [speed, duration] of [[0, 180], [1, 320], [2, 500]]) {
    const p = page()
    p.run(`speed.value = ${speed}; openDetail({index:0,rect:null})`)
    p.tick(26)
    assert.equal(p.run('detailMs.value'), Math.round(360 * duration / 320))
    p.run("runHeroTransition('connecting', () => {})")
    assert.equal(p.run('heroMs.value'), Math.round(190 * duration / 320))
    const c = component('components/SwipeDeck.uvue', { props: { duration } })
    c.run('settle(1)')
    c.tick(duration * 400 / 320 - 20)
    assert.equal(c.events.some(e => e[0] === 'change'), false)
    c.tick(40)
    assert.deepEqual(c.events.at(-1), ['change', 1])
  }
})

test('wheel tap selects a different speed and unlocks saving after settling', () => {
  const c = component('components/SpeedWheel.uvue', { props: { duration: 200 } })
  c.run(`onStart(${touch(100, 80)}); onEnd(); pick(0)`)
  c.tick(100)
  assert.deepEqual(c.events.at(-1), ['settling', true])
  c.tick(120)
  assert.deepEqual(c.events.slice(-2), [['change', 0], ['settling', false]])
})

test('speed saves the selected value, restores on page startup, and rolls back failed saves', () => {
  const p = page()
  p.phone.savePreferences = (reduced, speed) => { p.nativeState.animationSpeed = speed }
  p.run('openWheel(); onWheelChange(2); confirmSpeed()')
  assert.equal(p.nativeState.animationSpeed, 2)
  assert.equal(p.run('motionDuration.value'), 500)
  p.tick(1500)
  p.run('speed.value = 1'); p.hooks.ready()
  assert.equal(p.run('speed.value'), 2)
  p.run('openWheel(); onWheelChange(0)')
  p.phone.savePreferences = () => { throw Error('save failed') }
  p.run('confirmSpeed()')
  assert.equal(p.run('speed.value'), 2)
  assert.equal(p.run('wheel.value'), true)
  assert.equal(p.toasts.at(-1), 'save failed')
  p.hooks.unmount()
})

test('cancelling a speed draft preserves the saved selection and reopening clears settling', () => {
  const p = page()
  p.run('openWheel(); onWheelChange(0); wheelSettling.value = true')
  p.hooks.back()
  p.run('openWheel()')
  assert.equal(p.run('wheelDraft.value'), 1)
  assert.equal(p.run('wheelSettling.value'), false)
})

test('connection hero swaps pre-mounted faces edge-on, ignores repeat taps and stops when hidden', () => {
  const c = component('components/ConnectionHero.uvue')
  c.run('flip(); flip()')
  assert.equal(c.run('back.value'), false)
  assert.equal(c.run('angle.value'), 90)
  assert.equal(c.jobs.size, 1)
  c.tick(240)
  assert.equal(c.run('back.value'), true)
  assert.equal(c.run('angle.value'), -90)
  c.tick(260)
  assert.equal(c.run('angle.value'), 0)
  assert.equal(c.run('busy.value'), false)
  c.run('flip(); props.active = false'); c.flush(); c.tick(1000)
  assert.equal(c.run('back.value'), false)
  assert.equal(c.run('busy.value'), false)
  assert.equal(c.jobs.size, 0)
  c.run('props.active = true; props.duration = 0'); c.flush(); c.run('flip()')
  assert.equal(c.run('back.value'), true)
  assert.equal(c.jobs.size, 0)
  c.hooks.unmount()
})

test('hero flip duration follows all three speeds without recurring frame jobs', () => {
  for (const duration of [270, 480, 750]) {
    const c = component('components/ConnectionHero.uvue', { props: { duration } })
    c.run('flip()'); c.tick(duration / 2 - 1)
    assert.equal(c.run('back.value'), false)
    c.tick(duration / 2 + 25)
    assert.equal(c.run('back.value'), true)
    assert.equal(c.run('busy.value'), false)
    assert.equal(c.jobs.size, 0)
    c.run('flip()'); c.hooks.unmount(); c.tick(1000)
    assert.equal(c.jobs.size, 0)
  }
})

test('sheet animation does not refresh its parent on every frame, but drag remains linked', () => {
  const c = component('components/SpringSheet.uvue')
  assert.equal(c.jobs.size, 0)
  c.run('props.open = true'); c.flush(); c.tick(420)
  assert.equal(c.events.filter(e => e[0] === 'progress').length, 1)
  c.run(`start(${touch(100, 100)}); move(${touch(100, 180)})`)
  assert.ok(c.events.at(-1)[1] < 1)
  c.run('cancel()'); c.tick(420)
  assert.equal(c.run('progress.value'), 1)
  c.hooks.unmount()
})

test('unchanged native transcripts keep their identity and changed results still propagate', () => {
  let transcript = '你好'
  const p = page({ phone: { readCallState: () => JSON.stringify({ active: true, transcripts: [{ text: transcript }] }) } })
  p.run('refreshVoice(); const oldTranscript = voice.transcripts; refreshVoice()')
  assert.equal(p.run('voice.transcripts === oldTranscript'), true)
  transcript = '新回复'; p.run('refreshVoice()')
  assert.equal(p.run('voice.transcripts === oldTranscript'), false)
  assert.equal(p.run('voice.transcripts[0].text'), '新回复')
  p.run('startStars(); startCta()')
  assert.equal(p.jobs.size, 0)
})

test('detail entry no longer adds a full 400ms pause after a click', () => {
  const c = component('components/SwipeDeck.uvue')
  c.run('onSelect(0, null)'); c.tick(99)
  assert.equal(c.events.length, 0)
  c.tick(1); assert.equal(c.events.at(-1)[0], 'select')
  const p = component('components/StickyDetail.uvue')
  p.run('offset.value = 120; scrollTarget.value = 120; props.active = false'); p.flush()
  assert.equal(p.run('scrollTarget.value'), 0)
  assert.equal(p.jobs.size, 0)
})
