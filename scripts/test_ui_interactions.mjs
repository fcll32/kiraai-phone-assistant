import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const source = readFileSync(new URL('../uni-app/lib/interactions.js', import.meta.url), 'utf8')
const { selectionState, toggleAll, readiness, nextSetupStep } = await import('data:text/javascript,' + encodeURIComponent(source))

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
