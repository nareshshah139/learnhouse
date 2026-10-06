import { getConfig } from '@services/config/config'

export const recoveryHeaders = {
  'Cache-Control': 'no-store',
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
}

export function recoveryOrigin(): URL {
  const domain = getConfig('NEXT_PUBLIC_LEARNHOUSE_DOMAIN')
  if (!domain) throw new Error('Recovery origin is not configured')
  const scheme = getConfig('NEXT_PUBLIC_LEARNHOUSE_HTTPS') === 'true' ? 'https' : 'http'
  const url = new URL(domain.includes('://') ? domain : `${scheme}://${domain}`)
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
      !['http:', 'https:'].includes(url.protocol) ||
      (url.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
    throw new Error('Recovery origin is not configured')
  }
  return url
}

export function isRecoveryRequestAllowed(request: Request, origin: URL, requireOrigin: boolean): boolean {
  return request.headers.get('host') === origin.host &&
    (!requireOrigin || request.headers.get('origin') === origin.origin)
}

export async function readRecoveryBody(request: Request): Promise<Record<string, unknown> | null> {
  const length = request.headers.get('content-length')
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > 4096)) return null
  const reader = request.body?.getReader()
  if (!reader) return null
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let size = 0
  let raw = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > 4096) { await reader.cancel(); return null }
      raw += decoder.decode(value, { stream: true })
    }
    raw += decoder.decode()
    const body = JSON.parse(raw)
    return body && typeof body === 'object' && !Array.isArray(body) ? body : null
  } catch { return null }
  finally { reader.releaseLock() }
}
