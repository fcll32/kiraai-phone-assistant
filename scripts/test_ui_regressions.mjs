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
    __vue: { ref: value => ({ value }), reactive: value => value,
    computed: read => ({ get value() { return read() } }),
    nextTick: fn => { if (fn) fn(); return Promise.resolve() },
    watch(read, fn, options = {}) { const w = { read, fn, old: JSON.stringify(read()) }; watchers.push(w); if (options.immediate) fn(read()) },
    onUnmounted: fn => { hooks.unmount = fn } },
    defineProps: definitions => Object.fromEntries(Object.entries(definitions).map(([key, spec]) =>
      [key, overrides.props?.[key] ?? (typeof spec.default === 'function' ? spec.default() : spec.default)])),
    defineEmits: () => (name, ...args) => events.push([name, ...args]),
    onReady: fn => { hooks.ready = fn },
    onShow: fn => { hooks.show = fn }, onHide: fn => { hooks.hide = fn }, onBackPress: fn => { hooks.back = fn },
    phone, errorText: error => error.message,
    uni: { showModal: options => dialogs.push(options), showToast: options => toasts.push(options.title),
      getWindowInfo: () => ({ windowWidth: 390, windowHeight: 844 }),
      getStorageSync: () => '', setStorageSync() {}, ...overrides.uni }
  })
  const run = source => vm.runInContext(source, context)
  for (const lib of ['timers', 'interactions', 'motion', 'typography']) run(readFileSync(new URL(`../uni-app/lib/${lib}.js`, import.meta.url), 'utf8').replaceAll('export ', ''))
  const script = readFileSync(new URL('../uni-app/' + file, import.meta.url), 'utf8').split('<script setup>')[1].split('</script>')[0]
  // Resolve Vue bindings through the actual imports so missing imports fail here,
  // just as they do when the component runs in the app.
  run(script.replace(/import\s*\{([^}]+)\}\s*from\s*['"]vue['"]/g, 'const {$1} = __vue')
    .replace(/^import .*$/gm, ''))
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

test('guide is consumed on first display and is not replayed after a restart mid-introduction', () => {
  const saved = new Map()
  const uni = {getStorageSync: key => saved.get(key), setStorageSync: (key,value) => saved.set(key,value)}
  const p = page({uni})
  p.nativeState.configured = false; p.hooks.ready()
  assert.equal(p.run('welcomeOpen.value'), true)
  assert.equal(saved.get('kira-onboarding-shown-v1'), true)
  p.run("form.address = 'draft:8443'; finishWelcome(false)")
  assert.equal(p.run('form.address'), 'draft:8443')
  assert.equal(p.run('welcomeOpen.value'), false)
  p.hooks.unmount(); assert.equal(p.jobs.size, 0)
  // Only retain the marker written before presentation, as on a force-close.
  saved.delete('kira-welcome-v1'); saved.delete('kira-quick-start-v1')
  const restarted=page({uni});restarted.nativeState.configured=false;restarted.hooks.ready()
  assert.equal(restarted.run('welcomeOpen.value'),false)
  assert.equal(restarted.run('guideOpen.value'),false);restarted.hooks.unmount()
})

test('existing installations and completed legacy guides do not show onboarding again', () => {
  for (const legacy of ['kira-welcome-v1','kira-quick-start-v1']) {
    const p=page({uni:{getStorageSync:key=>key===legacy,setStorageSync(){}}})
    p.nativeState.configured=false;p.hooks.ready()
    assert.equal(p.run('welcomeOpen.value'),false);p.hooks.unmount()
  }
  const configured=page();configured.hooks.ready()
  assert.equal(configured.run('welcomeOpen.value'),false);configured.hooks.unmount()
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
  assert.equal(c.run('selected.value'), -1, 'about is only in the drawer')
  assert.equal(c.run('head.value'), 1); assert.equal(c.jobs.size, 0)
  c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('liquid capsule stays inside the dock while springing across both edges', () => {
  for (const width of [280, 370, 440]) {
    const c = component('components/LiquidNav.uvue', { props: { width } })
    for (const target of [4, 0, 1, 4, 0]) {
      c.run(`props.page = ${target}`); c.flush()
      for (let frame = 0; frame < 26; frame++) {
        c.tick(16)
        const style = c.run('pillStyle.value')
        const left = Number(style.transform.match(/translateX\(([-\d.]+)px\)/)[1])
        const scale = Number(style.transform.match(/scaleX\(([-\d.]+)\)/)[1])
        const right = left + parseFloat(style.width) * scale
        assert.ok(left >= 5.99 && right <= width - 5.99, `capsule escaped ${width}px dock: ${left}..${right}`)
      }
    }
    c.hooks.unmount()
  }
})

test('drawer-only pages settle a stretched capsule before returning to bottom navigation', () => {
  const c = component('components/LiquidNav.uvue')
  c.run('props.page = 4'); c.flush(); c.tick(80)
  c.run('props.page = 2'); c.flush()
  assert.equal(c.jobs.size, 0)
  assert.equal(c.run('head.value'), 2)
  assert.equal(c.run('tail.value'), 2)
  c.run('props.page = 1'); c.flush(); c.tick(420)
  assert.equal(c.run('head.value'), 1); assert.equal(c.run('tail.value'), 1)
  c.hooks.unmount()
})

test('overlay input blocking does not cancel navigation animation or activate a hidden tab', () => {
  const c = component('components/LiquidNav.uvue')
  c.run('props.page = 4'); c.flush(); c.tick(80)
  const before = c.run('head.value')
  c.run('props.interactive = false'); c.flush(); c.run('select(1)'); c.tick(80)
  assert.equal(c.events.length, 0)
  assert.notEqual(c.run('head.value'), before)
  c.tick(300)
  assert.equal(c.run('head.value'), 2)
  c.run('props.interactive = true; select(1)')
  assert.equal(c.events.at(-1)[1], 1)
  c.run('props.active = false'); c.flush(); assert.equal(c.jobs.size, 0)
  c.hooks.unmount()
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

test('privacy UI starts off and restores the actual saved native choice', () => {
  for (const remembered of [false, true]) {
    const p = page()
    assert.equal(p.run('shield.value'), false)
    p.nativeState.screenProtected = remembered
    p.hooks.ready()
    assert.equal(p.run('shield.value'), remembered)
    p.hooks.unmount()
  }
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
  assert.equal(p.toasts.at(-1), '请填写服务器地址，例如 203.0.113.10:5267')
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

test('welcome controls accept real taps, block repeated advances and only finish on the last page', () => {
  const c = component('components/WelcomeGuide.uvue')
  c.run(`start(${touch(180)}); end(); next(); next()`)
  assert.equal(c.events.length, 0)
  c.tick(420); assert.equal(c.run('index.value'), 1)
  c.run('next(); next()'); c.tick(420)
  assert.equal(c.run('index.value'), 2)
  c.run('next()'); assert.deepEqual(c.events.at(-1), ['finish'])
  c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('welcome swipe follows the finger, uses the one-third threshold and ignores old flick velocity', () => {
  const c = component('components/WelcomeGuide.uvue')
  c.run(`start(${touch(300)})`); c.tick(1000); c.run(`move(${touch(155)})`)
  assert.ok(c.run('position.value') > .33)
  const dotWidth = parseFloat(c.run('dotStyle(0).width'))
  assert.ok(dotWidth > 8 && dotWidth < 28)
  c.tick(200); c.run('end()'); c.tick(420)
  assert.equal(c.run('index.value'), 1)
  c.run(`start(${touch(200)})`); c.tick(10); c.run(`move(${touch(170)})`); c.tick(200); c.run('end()'); c.tick(420)
  assert.equal(c.run('index.value'), 1)
  c.run('go(2); props.active = false'); c.flush()
  assert.equal(c.run('index.value'), 2); assert.equal(c.jobs.size, 0)
  c.hooks.unmount()
})

test('welcome cancel and reduced motion settle without leaving frame loops', () => {
  const c = component('components/WelcomeGuide.uvue')
  c.run(`start(${touch(300)}); move(${touch(100)}); cancel()`); c.tick(420)
  assert.equal(c.run('index.value'), 0)
  c.run('go(1); props.duration = 0'); c.flush()
  assert.equal(c.run('index.value'), 1); assert.equal(c.jobs.size, 0)
  c.hooks.unmount()
})

test('spotlight clips measured targets to the window and suspends its breathing loop', () => {
  const c = component('components/SpotlightGuide.uvue', { props: { rect: {left:370,top:810,width:80,height:60} } })
  assert.ok(c.run('box.value.left + box.value.width') <= 382)
  assert.ok(c.run('box.value.top + box.value.height') <= 836)
  assert.ok(c.run('bubbleY.value') <= 634)
  assert.equal(c.run('entered.value'), false)
  c.tick(16); assert.equal(c.run('entered.value'), true)
  assert.equal(c.jobs.size, 1)
  c.run('props.busy = true; next()'); assert.equal(c.events.length, 0)
  c.run('props.duration = 0'); c.flush(); assert.equal(c.jobs.size, 0)
  c.hooks.unmount()
})

test('spotlight advances only after real measurements and drops callbacks arriving after hide', () => {
  const measurements = []; let starts = 0
  const p = page({phone: {startConnection() { starts++ }}, uni: {createSelectorQuery() {
    return {selector:'', select(value) { this.selector=value; return this }, boundingClientRect(callback) { measurements.push({selector:this.selector,callback}); return this }, exec() {} }
  }}})
  p.run('finishWelcome(true)')
  assert.equal(measurements[0].selector, '#guide-menu')
  assert.equal(p.run('spotlightOpen.value'), false)
  measurements[0].callback({left:20,top:40,width:42,height:42}); p.tick(410)
  assert.equal(p.run('spotlightOpen.value'), true)
  p.run('nextSpotlight(0); nextSpotlight(0)'); assert.equal(measurements.length, 2)
  assert.equal(measurements[1].selector, '#guide-connect')
  measurements[1].callback({left:30,top:340,width:320,height:52}); p.tick(410)
  assert.equal(p.run('spotlightIndex.value'), 1)
  p.run('nextSpotlight(1)'); assert.equal(measurements[2].selector, '#guide-status')
  p.hooks.hide(); measurements[2].callback({left:260,top:40,width:100,height:42}); p.tick(1000)
  assert.equal(p.run('spotlightOpen.value'), false)
  assert.equal(p.jobs.size, 0); assert.equal(starts, 0)
  p.hooks.unmount()
})

test('unavailable spotlight targets fall back to the existing four-step guide', () => {
  const p = page({uni: {createSelectorQuery: () => ({ select() { return this }, boundingClientRect() { return this }, exec() {} })}})
  p.run('finishWelcome(true)'); p.tick(810)
  assert.equal(p.run('spotlightOpen.value'), false); assert.equal(p.run('guideOpen.value'), true)
  p.hooks.unmount(); assert.equal(p.jobs.size, 0)
  const failed = page({uni: {createSelectorQuery() { throw new Error('native view unavailable') }}})
  failed.run('finishWelcome(true)')
  assert.equal(failed.run('guideOpen.value'), true)
  failed.hooks.unmount(); assert.equal(failed.jobs.size, 0)
})

test('field errors shake with decreasing amplitude, select the password and clear cleanly', () => {
  const c = component('components/FloatingField.uvue', {props: {modelValue:'KiraTest88',selectOnError:true}})
  c.run("props.error = '密码不匹配'; props.errorRevision++"); c.flush(); c.tick(1)
  assert.equal(c.run('shakeX.value'), -10)
  c.tick(180); assert.ok(Math.abs(c.run('shakeX.value')) <= 6)
  c.tick(230)
  assert.equal(c.run('shakeX.value'), 0); assert.equal(c.run('requestFocus.value'), true)
  assert.equal(c.run('selectionStart.value'), 0); assert.equal(c.run('selectionEnd.value'), 10)
  c.run("input({detail:{value:'newpass88'}}); props.error = ''"); c.flush()
  assert.equal(c.run('requestFocus.value'), true, 'typing after an error must keep the keyboard focused')
  assert.equal(c.run('selectionStart.value'), -1); assert.equal(c.jobs.size, 0)
  assert.deepEqual(c.events.at(-2), ['update:modelValue','newpass88'])
  c.hooks.unmount()
})

test('hiding an error field cancels focus and disabling motion settles immediately', () => {
  const c = component('components/FloatingField.uvue', {props: {modelValue:'KiraTest88',selectOnError:true}})
  c.run("props.error = '请核对密码'"); c.flush(); c.tick(100)
  c.run('props.active = false'); c.flush(); c.tick(1000)
  assert.equal(c.run('requestFocus.value'), false); assert.equal(c.jobs.size, 0)
  c.run('props.active = true; props.duration = 0; props.errorRevision++'); c.flush()
  assert.equal(c.run('shakeX.value'), 0); assert.equal(c.run('requestFocus.value'), true)
  c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('password meter retargets to the latest input and stops when hidden', () => {
  const c = component('components/PasswordStrength.uvue')
  c.run("props.value = 'simple88'"); c.flush(); c.tick(80)
  c.run("props.value = 'Kira!Test1234'"); c.flush(); c.tick(300)
  assert.equal(c.run('quality.value.score'), 4); assert.equal(c.run('label.value'), '更稳妥')
  assert.equal(c.run('checked.value'), true)
  c.run("props.value = 'bad pass'; props.active = false"); c.flush()
  assert.equal(c.run('quality.value.score'), 0); assert.equal(c.run('label.value'), '先检查格式')
  assert.equal(c.jobs.size, 0); c.hooks.unmount()
})

test('local field errors prevent native saves and haptics obey feedback preference', async () => {
  let saves = 0, buzzes = 0
  const p = page({phone:{saveConfig() { saves++ }},uni:{vibrateShort() { buzzes++ }}})
  p.run("form.password = 'short'"); await p.run('saveConnection()')
  assert.equal(saves, 0); assert.equal(buzzes, 1); assert.match(p.run('formErrors.password'), /8–128/)
  p.run("clearFieldError('password'); form.password = 'KiraTest88'; form.fingerprint = 'bad'; effects.feedback = false")
  await p.run('saveConnection()')
  assert.equal(saves, 0); assert.equal(buzzes, 1); assert.match(p.run('formErrors.fingerprint'), /64/)
  assert.equal(p.nativeState.connected, false); p.hooks.unmount()
})

test('server authentication rejection produces one field hint without discarding the password', () => {
  let buzzes = 0
  const p = page({uni:{vibrateShort() { buzzes++ }}})
  p.nativeState.running = true; p.run('refresh()')
  p.nativeState.running = false; p.nativeState.status = '连接密码或指定手机不匹配'
  const password = p.run('form.password')
  p.run('refresh(); refresh()')
  assert.equal(buzzes, 1); assert.match(p.run('formErrors.password'), /不匹配/)
  assert.equal(p.run('form.password'), password); p.hooks.unmount()
})

test('background sheets and deck springs settle and cancel delayed detail clicks', () => {
  const sheet = component('components/SpringSheet.uvue', {props:{open:true}})
  sheet.tick(100); sheet.run('props.active = false'); sheet.flush()
  assert.equal(sheet.run('progress.value'), 1); assert.equal(sheet.jobs.size, 0)
  sheet.hooks.unmount()
  const deck = component('components/SwipeDeck.uvue', {props:{cards:[{},{},{}]}})
  deck.run('settle(1)'); deck.tick(80); deck.run('props.duration = 0'); deck.flush()
  assert.equal(deck.jobs.size, 0); assert.deepEqual(deck.events.at(-1), ['change',1])
  deck.run('props.active = false'); deck.flush(); deck.run('onSelect(0,null)'); deck.tick(500)
  assert.equal(deck.events.some(e=>e[0]==='select'), false); deck.hooks.unmount()
})

test('holding an intermediate sticky header discards an obsolete flick before snapping', () => {
  const c = component('components/StickyDetail.uvue')
  c.run(`start(${touch(100)}); offset.value = 120; velocity = -2; time = Date.now()`)
  c.tick(200); c.run('end()'); c.tick(550)
  assert.equal(c.run('scrollTarget.value'), 180)
  c.hooks.unmount(); assert.equal(c.jobs.size, 0)
})

test('navigation pauses behind overlays and spreads three tabs across its full width', () => {
  const c = component('components/LiquidNav.uvue')
  c.run('props.page = 4'); c.flush(); c.tick(100)
  c.run('props.active = false'); c.flush()
  assert.equal(c.jobs.size, 0); assert.equal(c.run('head.value'), 2)
  c.run('select(1)'); assert.equal(c.events.length, 0)
  c.run('props.active = true'); c.flush(); assert.equal(c.jobs.size, 0)
  assert.equal(c.run('cell.value * items.length'),c.run('props.width'))
  c.run('select(1)'); assert.deepEqual(c.events.at(-1), ['change',1])
  c.hooks.unmount()
})

test('linked text changes only its own line, retargets and drops background callbacks', () => {
  const a = component('components/LinkedText.uvue', {props:{value:'准备连接'}})
  const b = component('components/LinkedText.uvue', {props:{value:'203.0.113.10:5267'}})
  a.run("props.value = '正在连接'"); a.flush(); a.tick(100)
  a.run("props.value = '手机已就绪'"); a.flush(); a.tick(720)
  assert.equal(a.run('displayed.value'), '手机已就绪'); assert.equal(a.jobs.size, 0)
  assert.equal(b.run('displayed.value'), '203.0.113.10:5267'); assert.equal(b.jobs.size, 0)
  a.run("props.value = '已停止'"); a.flush(); a.run('props.active = false'); a.flush()
  assert.equal(a.run('displayed.value'), '已停止'); assert.equal(a.jobs.size, 0)
  a.hooks.unmount(); b.hooks.unmount()
})

test('hero swipes respect direction and threshold, cancel on hide and never start control', () => {
  const c = component('components/ConnectionHero.uvue')
  c.run(`swipeStart(${touch(180)}); swipeMove(${touch(230)}); swipeEnd()`)
  assert.equal(c.run('back.value'), false); assert.match(c.run('swipeHint.value'), /向左/)
  c.run(`swipeStart(${touch(250)}); swipeMove(${touch(206)}); swipeEnd()`); c.tick(600)
  assert.equal(c.run('back.value'), false)
  c.run(`swipeStart(${touch(250)}); swipeMove(${touch(170)}); swipeEnd()`); c.tick(520)
  assert.equal(c.run('back.value'), true)
  c.run(`swipeStart(${touch(100)}); swipeMove(${touch(120,220)}); swipeEnd()`); c.tick(520)
  assert.equal(c.run('back.value'), true, 'vertical scrolling must not flip the card')
  c.run('moved = false; setup(0)'); assert.deepEqual(c.events.at(-1), ['setup',0])
  c.run(`swipeStart(${touch(100)}); swipeMove(${touch(180)}); swipeEnd(); props.active = false`); c.flush()
  assert.equal(c.run('back.value'), false); assert.equal(c.jobs.size, 0)
  assert.equal(c.events.some(e=>e[0]==='press'), false); c.hooks.unmount()
})

test('missing setup entries preserve drafts and open their preparation without replaying the guide', () => {
  let permissions = 0, starts = 0
  const p = page({phone:{openAccessibility(){permissions++},startConnection(){starts++}}})
  p.run("page.value = 4; form.address = 'draft:5267'; heroSetup(0)"); assert.equal(p.run('page.value'),1)
  assert.equal(p.run('guideOpen.value'),false); assert.equal(starts,0)
  assert.equal(p.run('form.address'),'draft:5267')
  p.nativeState.accessibility = false; p.run('refresh(); heroSetup(1)'); assert.equal(permissions,1)
  assert.equal(p.run('guideOpen.value'),false)
  p.hooks.unmount()
})

test('updates require separate check, download and install actions with real state feedback', () => {
  const snapshot = {status:'idle',version:'',detail:'',progress:0}
  const calls = []
  const c = component('components/UpdatePanel.uvue', {phone:{
    readUpdateState:()=>JSON.stringify(snapshot),
    checkUpdate(){calls.push('check');snapshot.status='checking'},
    downloadUpdate(){calls.push('download');snapshot.status='downloading'},
    installUpdate(){calls.push('install');snapshot.status='permission'},
    cancelUpdate(){calls.push('cancel');snapshot.status='cancelled'}
  }})
  c.run('primary(); primary()'); assert.deepEqual(calls,['check'])
  Object.assign(snapshot,{status:'available',version:'1.0.1',notes:'改进连接'})
  c.tick(950); assert.equal(c.run('primaryLabel.value'),'下载新版'); assert.deepEqual(calls,['check'])
  c.run('primary(); primary()'); assert.deepEqual(calls,['check','download'])
  snapshot.progress=.35; c.tick(950); assert.equal(c.run('progress.value'),.35)
  snapshot.status='ready'; c.tick(950); assert.equal(c.run('primaryLabel.value'),'安装更新')
  assert.deepEqual(calls,['check','download'],'a completed download must not open the installer automatically')
  c.run('primary()'); assert.deepEqual(calls,['check','download','install'])
  c.tick(1900); assert.deepEqual(calls,['check','download','install'],'permission return must not automatically install')
  c.hooks.unmount(); assert.equal(c.jobs.size,0)
})

test('update UI hides without cancelling a background download, and explicit cancel is retryable', () => {
  const snapshot={status:'downloading',version:'1.0.1',progress:.5}; let cancels=0, reads=0
  const c=component('components/UpdatePanel.uvue',{phone:{
    readUpdateState(){reads++;return JSON.stringify(snapshot)},
    cancelUpdate(){cancels++;snapshot.status='cancelled'}
  }})
  const before=reads; c.run('props.active=false'); c.flush(); c.tick(5000)
  assert.equal(reads,before); assert.equal(cancels,0); assert.equal(c.jobs.size,0)
  c.run('props.active=true'); c.flush(); c.run("invoke('cancelUpdate')")
  assert.equal(cancels,1); assert.equal(c.run('canDownload.value'),true)
  c.hooks.unmount(); assert.equal(c.jobs.size,0); assert.equal(cancels,1)
})

test('intro entrance is staggered, uses the chosen speed and leaves no background work', () => {
  const c = component('components/PageIntro.uvue', {props:{title:'把你的手机交给 Kira 来操作',width:220,duration:600}})
  assert.equal(c.run('shown.value'),false)
  c.tick(16)
  assert.equal(c.run('shown.value'),true)
  assert.equal(c.run('partStyle(0).transitionDuration'),'600ms')
  assert.ok(parseFloat(c.run('partStyle(3).transitionDelay')) > parseFloat(c.run('partStyle(1).transitionDelay')))
  c.tick(1000); assert.equal(c.jobs.size,0)
  c.run('props.active=false'); c.flush()
  assert.equal(c.run('partStyle(3).transitionDuration'),'0ms')
  c.run('props.active=true'); c.flush(); c.hooks.unmount(); c.tick(1000)
  assert.equal(c.jobs.size,0); assert.equal(c.run('shown.value'),true)
})

test('turning off entrance motion cancels a pending reveal and keeps all copy visible', () => {
  const c = component('components/PageIntro.uvue')
  c.run('props.duration=0'); c.flush(); c.tick(1000)
  assert.equal(c.run('shown.value'),true); assert.equal(c.jobs.size,0)
  assert.equal(c.run('partStyle(3).transitionDelay'),'0ms')
  c.hooks.unmount()
})

test('balanced headings preserve words and do not leave a short final fragment', () => {
  const c = component('components/PageIntro.uvue')
  assert.equal(c.run("balanceHeading('KiraAI 手机助手',14)"),'KiraAI 手机助手')
  const lines = c.run("balanceHeading('让每一台手机都能成为你的 AI 助手',12)").split('\n')
  assert.equal(lines.length,2)
  assert.ok(lines.every(line=>line.length>=5))
  assert.equal(lines.join('').replaceAll(' ',''),'让每一台手机都能成为你的AI助手')
  assert.ok(!c.run("balanceHeading('连接 KiraAI 的服务器',8)").includes('Kira\nAI'))
  assert.equal(c.run("balanceHeading('第一行\\n第二行',5)"),'第一行\n第二行')
  c.hooks.unmount()
})

test('numeric cells retain their total width across digit changes and download milestones', () => {
  const c = component('components/StableNumber.uvue')
  const width = value => c.run(`numberCells(${JSON.stringify(value)},5).reduce((n,cell)=>n+cell.width,0)`)
  assert.equal(width('9.9'),width('10.0'))
  assert.equal(width('0.0'),width('200.0'))
  assert.equal(c.run("numberCells('111',3).reduce((n,cell)=>n+cell.width,0)"),c.run("numberCells('888',3).reduce((n,cell)=>n+cell.width,0)"))
  assert.equal(c.run("numberCells('4',3).map(cell=>cell.char).join('').trim()"),'4')
})

test('about is the single drawer entry for project, updates and motion settings', () => {
  const p = page()
  assert.equal(p.run("drawerItems.filter(item=>item.key==='about').length"),1)
  assert.equal(p.run("drawerItems.find(item=>item.key==='about').page"),2)
  assert.equal(p.run("drawerItems.some(item=>item.key==='prefs')"),false)
  assert.equal(p.run('JSON.stringify(navOrder)'),'[0,1,4]')
  const c = component('components/LiquidNav.uvue')
  assert.equal(c.run('items.length'),3)
  assert.equal(c.run('items.some(item=>item.id===2)'),false)
  p.hooks.unmount(); c.hooks.unmount()
})

test('update red dots follow newer versions across pages without triggering downloads', () => {
  const snapshot={status:'idle',version:''}; let quiet=0, downloads=0
  const p=page({phone:{readUpdateState:()=>JSON.stringify(snapshot),checkUpdateQuietly(){quiet++},downloadUpdate(){downloads++}}})
  p.nativeState.version='1.0.0';p.hooks.show()
  assert.equal(p.run('hasAppUpdate.value'),false)
  Object.assign(snapshot,{status:'available',version:'1.0.1'});p.tick(2000)
  assert.equal(p.run('hasAppUpdate.value'),true)
  p.run('applyPage(2)');assert.equal(p.run('hasAppUpdate.value'),true)
  p.run('applyPage(0)');assert.equal(p.run('hasAppUpdate.value'),true)
  assert.equal(quiet,1);assert.equal(downloads,0)
  p.hooks.hide();const status=p.run('updateNotice.status');snapshot.status='latest';snapshot.version='';p.tick(6000)
  assert.equal(p.run('updateNotice.status'),status);assert.equal(p.jobs.size,0)
  p.hooks.show();assert.equal(p.run('hasAppUpdate.value'),false)
  p.hooks.unmount();assert.equal(p.jobs.size,0)
})

test('offline automatic update checks stay quiet and project links require a user action', () => {
  let opened=0
  const p=page({phone:{readUpdateState(){throw Error('offline')},checkUpdateQuietly(){throw Error('offline')},
    projectUrl:()=> 'https://github.com/fcll32/kiraai-phone-assistant',openProject(){opened++}}})
  p.hooks.show();p.hooks.ready();p.tick(4000)
  assert.equal(p.toasts.length,0);assert.equal(p.run('hasAppUpdate.value'),false);assert.equal(opened,0)
  p.run('openProject()');assert.equal(opened,1)
  p.hooks.unmount()
})

test('update badge version comparison is numeric and rejects unknown or malformed versions', () => {
  const p=page()
  assert.equal(p.run("hasNewerUpdate('1.10.0','1.9.9')"),true)
  for(const [next,current] of [['1.0.0','1.0.0'],['1.0.0','1.0.1'],['oops','1.0.0'],['1.0.1','—'],['1.0.1234567890','1.0.0']])
    assert.equal(p.run(`hasNewerUpdate(${JSON.stringify(next)},${JSON.stringify(current)})`),false)
  p.hooks.unmount()
})
