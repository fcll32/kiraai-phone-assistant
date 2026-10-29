export function swipePage(position, velocity, width, count, releasedAfter = 0) {
  const speed = releasedAfter > 100 ? 0 : velocity
  return Math.max(0, Math.min(count - 1, Math.round(position + speed * 160 / Math.max(1, width))))
}
export function passwordStrength(value) {
  if (!value) return { score: 0, label: '等待输入', color: '#8a9baa' }
  const valid = /^[\x21-\x7e]{8,128}$/.test(value)
  if (!valid) return { score: 0, label: '先检查格式', color: '#bd5e61' }
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z\d]/].filter(rule => rule.test(value)).length
  const score = Math.min(4, 1 + (value.length >= 12 ? 1 : 0) + (kinds >= 2 ? 1 : 0) + (kinds >= 3 ? 1 : 0))
  return { score, label: ['等待输入', '比较简单', '日常可用', '较强', '更稳妥'][score], color: ['#8a9baa', '#bd5e61', '#bd8550', '#9b944a', '#43856d'][score] }
}
export function connectionFieldIssue(form) {
  if (!form.address.trim()) return { field: 'address', message: '请填写服务器地址，例如 203.0.113.10:5267' }
  if (!/^[\x21-\x7e]{8,128}$/.test(form.password.trim())) return { field: 'password', message: '连接密码需要 8–128 位英文、数字或符号，不含空格' }
  const pin = form.fingerprint.replace(/[\s:]/g, '')
  if (pin && !/^[0-9a-fA-F]{64}$/.test(pin)) return { field: 'fingerprint', message: '校验码需要完整的 64 位内容，请从插件页重新复制' }
  return null
}
export function spotlightBounds(rect, width, height) {
  const left = Math.max(8, Math.min(width - 48, rect.left - 6))
  const top = Math.max(8, Math.min(height - 48, rect.top - 6))
  return { left, top, width: Math.max(40, Math.min(width - left - 8, rect.width + 12)), height: Math.max(40, Math.min(height - top - 8, rect.height + 12)) }
}
