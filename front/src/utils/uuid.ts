/**
 * 生成 UUID v4 字符串。
 *
 * 优先使用 crypto.randomUUID()（需安全上下文 HTTPS / localhost），
 * 不可用时降级为基于 crypto.getRandomValues 的手动 v4 生成，
 * 最后兜底为 Date.now + Math.random 组合，确保非安全上下文下不崩溃。
 */
export function generateUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const buf = crypto.getRandomValues(new Uint8Array(16))
    buf[6] = (buf[6] & 0x0f) | 0x40
    buf[8] = (buf[8] & 0x3f) | 0x80
    const hex: string[] = []
    buf.forEach((b) => hex.push(b.toString(16).padStart(2, '0')))
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}-4${Math.random().toString(16).slice(2, 6)}-${(8 + Math.floor(Math.random() * 4)).toString(16)}${Math.random().toString(16).slice(2, 4)}-${Math.random().toString(16).slice(2, 14)}`
}
