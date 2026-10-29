import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const source = readFileSync(new URL('../uni-app/lib/interactions.js', import.meta.url), 'utf8')
const { selectionState, toggleAll, readiness, nextSetupStep, companionSignals } = await import('data:text/javascript,' + encodeURIComponent(source))

test('parent selection reflects every combination of child controls', () => {
  for (let mask = 0; mask < 8; mask++) {
    const flags = { feedback: !!(mask & 1), cards: !!(mask & 2), transition: !!(mask & 4) }
    assert.equal(selectionState(flags).all, mask === 7)
    assert.equal(selectionState(flags).partial, mask > 0 && mask < 7)
    assert.deepEqual(toggleAll(flags), { feedback: mask !== 7, cards: mask !== 7, transition: mask !== 7 })
  }
})
test('connection preparation never counts a running handshake as connected', () => {
  const state = { configured: true, accessibility: true, running: true, connected: false }
  assert.deepEqual(readiness(state), [true, true, false])
  assert.equal(nextSetupStep(state), 2)
  state.connected = true
  assert.deepEqual(readiness(state), [true, true, true])
  state.accessibility = false
  assert.equal(nextSetupStep(state), 1)
  state.configured = false
  assert.equal(nextSetupStep(state), 0)
})
test('untrusted truthy values cannot mark setup checks complete', () => {
  assert.deepEqual(readiness({ configured: 'false', accessibility: 1, connected: 'true' }), [false, false, false])
})

test('companion signals follow confirmed feature states and change expression when stopped', () => {
  const state = { running: true, connected: false, accessibility: false }
  const voice = { active: false, status: 'idle' }, mic = { active: false }
  const effects = { feedback: false, cards: false, transition: false }
  let signals = companionSignals(state, voice, mic, false, effects)
  assert.equal(signals.length, 6)
  assert.equal(signals[0].note, '连接中')
  assert.equal(signals[0].enabled, false)
  state.connected = true
  const connected = companionSignals(state, voice, mic, false, effects)[0]
  assert.equal(connected.enabled, true)
  assert.notEqual(connected.sticker, signals[0].sticker)
  state.running = false; state.connected = false
  signals = companionSignals(state, voice, mic, false, effects)
  assert.equal(signals[0].note, '未连接')
  assert.notEqual(signals[0].sticker, connected.sticker)
  state.accessibility = true; voice.active = true; voice.status = 'listening'; mic.active = true
  effects.cards = true
  signals = companionSignals(state, voice, mic, true, effects)
  assert.deepEqual(signals.map(s => s.enabled), [false, true, true, true, true, true])
  const listening = signals[1].sticker
  voice.muted = true
  signals = companionSignals(state, voice, mic, true, effects)
  assert.equal(signals[1].enabled, true)
  assert.equal(signals[1].note, '已静音')
  assert.notEqual(signals[1].sticker, listening)
})

test('companion signals cannot claim connection or permissions from truthy strings', () => {
  const signals = companionSignals({ connected: 'true', running: 'true', accessibility: 1 },
    { active: 'true', status: 'listening' }, { active: 1 }, 'true', { cards: 'true' })
  assert.equal(signals.some(s => s.enabled), false)
  const joining = companionSignals({}, { active: true, status: 'connecting' }, {}, false, {})[1]
  assert.equal(joining.enabled, false)
  assert.equal(joining.note, '接通中')
})
