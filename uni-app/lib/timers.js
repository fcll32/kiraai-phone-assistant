// Own every delayed frame, including callbacks scheduled from nextTick.
export function createTimeoutScope() {
  const pending = new Set()
  let disposed = false
  function after(callback, delay) {
    if (disposed) return null
    const id = setTimeout(() => {
      pending.delete(id)
      if (!disposed) callback()
    }, delay)
    pending.add(id)
    return id
  }
  function cancel(id) { clearTimeout(id); pending.delete(id) }
  function clear() { pending.forEach(id => clearTimeout(id)); pending.clear() }
  function dispose() { disposed = true; clear() }
  return { after, cancel, clear, dispose }
}
