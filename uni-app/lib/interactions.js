export const effectKeys = ['feedback', 'cards', 'transition']
export const speedDurations = [180, 320, 500]
export function animationDuration(base, speed, enabled = true) {
  const index = Number.isInteger(speed) && speed >= 0 && speed < speedDurations.length ? speed : 1
  return enabled ? Math.round(base * speedDurations[index] / speedDurations[1]) : 0
}
export function selectionState(effects) {
  const count = effectKeys.filter(key => effects[key]).length
  return { count, all: count === effectKeys.length, partial: count > 0 && count < effectKeys.length }
}
export function toggleAll(effects) {
  const enabled = !selectionState(effects).all
  return { feedback: enabled, cards: enabled, transition: enabled }
}
export function readiness(state) {
  return [state.configured === true, state.accessibility === true, state.connected === true]
}
export function nextSetupStep(state) {
  const index = readiness(state).findIndex(ready => !ready)
  return index < 0 ? 2 : index
}
export function hasNewerUpdate(version, installed) {
  const parse = value => typeof value === 'string' && /^\d{1,9}\.\d{1,9}\.\d{1,9}$/.test(value) ? value.split('.').map(Number) : null
  const next = parse(version), current = parse(installed)
  if (!next || !current) return false
  for (let i = 0; i < 3; i++) if (next[i] !== current[i]) return next[i] > current[i]
  return false
}

// These are read-only state indicators, never optimistic switch positions.
export function companionSignals(state, voice, mic, shield, effects) {
  const connected = state.connected === true
  const connecting = state.running === true && !connected
  const calling = voice.active === true && ['listening', 'recording', 'thinking', 'synthesizing', 'playing'].includes(voice.status)
  const joining = voice.active === true && voice.status === 'connecting'
  const enabledEffects = effectKeys.some(key => effects[key] === true)
  const listening = ['listening', 'recording', 'playing'].includes(voice.status)
  return [
    { key: 'connection', title: '手机连接', enabled: connected, note: connected ? '已连接' : connecting ? '连接中' : '未连接', sticker: connected ? 'connected' : connecting ? 'link' : 'rest' },
    { key: 'call', title: 'App 通话', enabled: calling, note: joining ? '接通中' : calling ? voice.muted === true ? '已静音' : voice.status === 'playing' ? '正在回应' : '通话中' : '未通话', sticker: joining ? 'link' : calling ? voice.muted === true ? 'rest' : listening ? 'call' : 'guide' : 'rest' },
    { key: 'accessibility', title: '无障碍', enabled: state.accessibility === true, note: state.accessibility === true ? '已开启' : '未开启', sticker: state.accessibility === true ? 'device' : 'guide' },
    { key: 'privacy', title: '防截屏', enabled: shield === true, note: shield === true ? '已保护' : '未开启', sticker: shield === true ? 'shield' : 'rest' },
    { key: 'effects', title: '界面动效', enabled: enabledEffects, note: enabledEffects ? '已开启' : '已关闭', sticker: enabledEffects ? 'about' : 'rest' },
    { key: 'experiment', title: '麦克风实验', enabled: mic.active === true, note: mic.active === true ? '测试中' : '未运行', sticker: mic.active === true ? 'device' : 'rest' }
  ]
}
