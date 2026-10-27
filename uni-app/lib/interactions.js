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
