// Approximate em widths for short, authored headings. Latin words stay intact;
// body copy and user-provided server addresses keep their normal wrapping.
function units(value) {
  return Array.from(value).reduce((sum, char) => sum + (/\s/.test(char) ? 0.32 : /[\x00-\x7f]/.test(char) ? 0.56 : 1), 0)
}
export function balanceHeading(value, capacity = 14) {
  const text = String(value || '').trim()
  if (!text || text.includes('\n') || units(text) <= capacity) return text
  const chars = Array.from(text), total = units(text)
  let best = '', score = Infinity
  for (let i = 1; i < chars.length; i++) {
    const before = chars[i - 1], after = chars[i]
    if (/[a-zA-Z0-9]/.test(before) && /[a-zA-Z0-9]/.test(after)) continue
    if (/[，。！？、；：）】》」』]/.test(after) || /[（【《「『]/.test(before)) continue
    const left = chars.slice(0, i).join('').trim(), right = chars.slice(i).join('').trim()
    const a = units(left), b = units(right)
    if (!a || !b || a > capacity || b > capacity) continue
    // Prefer balanced rows, with a small bonus for an existing phrase boundary.
    const candidate = Math.abs(a - b) + (Math.min(a, b) < Math.min(3, total / 3) ? 6 : 0) - (/\s|[，、：]/.test(before) ? 0.6 : 0)
    if (candidate < score) { score = candidate; best = left + '\n' + right }
  }
  return best || text
}

export function numberCells(value, reserve = 0) {
  const text = String(value ?? '').padStart(Math.max(0, Math.min(12, reserve)), '\u00a0')
  return Array.from(text).map(char => ({ char, width: /[.:]/.test(char) ? 0.34 : 0.64 }))
}
