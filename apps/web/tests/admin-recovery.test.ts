import { afterEach, describe, expect, mock, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { NextRequest } from 'next/server'
import { testConfig } from './fixtures/config'

mock.module('@services/config/config', () => testConfig)

const { GET } = await import('../app/recover/route')
const { POST } = await import('../app/api/recovery/[action]/route')
const { readRecoveryBody } = await import('../services/auth/recoveryServer')
const privacy = await import('../services/auth/recoveryPrivacy')
const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })
const secret = 'A'.repeat(43)
const origin = 'https://school.example.com'

function request(action: string, body: unknown, headers: Record<string, string> = {}) {
  return new NextRequest(`${origin}/api/recovery/${action}`, {
    method: 'POST', headers: { Host: 'school.example.com', Origin: origin, 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  })
}

async function document(cookie = '') {
  return GET(new Request(origin + '/recover', { headers: { Host: 'school.example.com', Cookie: cookie } }))
}

function browser(html: string, token = secret, status = 200, failure = {}) {
  const ids = ['recovery', 'password', 'confirm', 'submit', 'status', 'title', 'intro']
  const nodes: Record<string, any> = Object.fromEntries(ids.map(id => [id, { value: '', disabled: id === 'submit', hidden: false, textContent: '', focus() {} }]))
  let submit: Function = () => {}
  let pagehide: Function = () => {}
  let address = '#token=' + token
  const calls: any[] = []
  nodes.recovery.addEventListener = (_: string, handler: Function) => { submit = handler }
  runInNewContext(html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)![1], {
    URLSearchParams,
    window: { location: { hash: address }, history: { replaceState(_: unknown, __: unknown, url: string) { address = url } }, addEventListener(_: string, handler: Function) { pagehide = handler } },
    document: { getElementById: (id: string) => nodes[id] },
    fetch: async (...args: any[]) => { calls.push(args); return { ok: status === 200, status, json: async () => failure } },
  })
  return { nodes, calls, address: () => address, submit: () => submit({ preventDefault() {} }), pagehide: () => pagehide() }
}

describe('isolated learner recovery document', () => {
  test('cold and stale-cookie visits return private HTML with a fresh matching CSP nonce', async () => {
    const first = await document()
    const second = await document('LH_access=stale; LH_refresh=stale; LH_org=unrelated')
    for (const response of [first, second]) {
      expect(response.status).toBe(200)
      expect(response.headers.get('cache-control')).toBe('no-store')
      expect(response.headers.get('referrer-policy')).toBe('no-referrer')
      expect(response.headers.get('set-cookie')).toBeNull()
      const html = await response.text()
      const nonce = html.match(/<style nonce="([^"]+)"/)![1]
      expect(response.headers.get('content-security-policy')).toContain(`script-src 'nonce-${nonce}'`)
      expect(response.headers.get('content-security-policy')).toContain("frame-ancestors 'none'; base-uri 'none'")
      expect(html).toContain(`<script nonce="${nonce}">`)
      expect(html).not.toMatch(/_next|posthog|sentry|<script[^>]+src=|<iframe|localStorage|sessionStorage|type="hidden"/i)
    }
    expect(first.headers.get('content-security-policy')).not.toBe(second.headers.get('content-security-policy'))
  })

  test('rejects a different Host without reflecting it', async () => {
    const response = await GET(new Request(origin + '/recover', { headers: { Host: 'attacker.example.com' } }))
    expect(response.status).toBe(421)
    expect(await response.text()).not.toContain('attacker')
  })

  test('scrubs fragment immediately and sends the secret only in the fixed POST body', async () => {
    const page = browser(await (await document()).text())
    expect(page.address()).toBe('/recover')
    expect(JSON.stringify(page.nodes)).not.toContain(secret)
    page.nodes.password.value = 'ChosenPassword!123'
    page.nodes.confirm.value = 'DoesNotMatch!123'
    await page.submit()
    expect(page.calls.length).toBe(0)
    page.nodes.confirm.value = 'ChosenPassword!123'
    await page.submit()
    expect(page.calls.length).toBe(1)
    expect(page.calls[0][0]).toBe('/api/recovery/redeem')
    expect(page.calls[0][1].credentials).toBe('omit')
    expect(JSON.parse(page.calls[0][1].body)).toEqual({ secret, new_password: 'ChosenPassword!123' })
    expect(page.nodes.password.value).toBe('')
    expect(page.nodes.confirm.value).toBe('')
    expect(page.nodes.recovery.hidden).toBe(true)
    expect(page.nodes.status.textContent).toBe('You can sign in now.')
  })

  test('missing token disables submission and page exit clears the in-memory capability', async () => {
    const html = await (await document()).text()
    const missing = browser(html, '')
    expect(missing.nodes.recovery.hidden).toBe(true)
    expect(missing.calls).toEqual([])
    const page = browser(html)
    page.nodes.password.value = page.nodes.confirm.value = 'ChosenPassword!123'
    page.pagehide()
    expect(page.nodes.password.value).toBe('')
    expect(page.nodes.confirm.value).toBe('')
  })

  test('password rules match backend punctuation and weak-password responses leave the link usable', async () => {
    const html = await (await document()).text()
    for (const password of ['Letters123 ', 'Letters123é']) {
      const page = browser(html)
      page.nodes.password.value = page.nodes.confirm.value = password
      await page.submit()
      expect(page.calls).toEqual([])
      expect(page.nodes.status.textContent).toContain('requirements')
    }
    const page = browser(html, secret, 400, { code: 'WEAK_PASSWORD' })
    page.nodes.password.value = page.nodes.confirm.value = 'Letters123!'
    await page.submit()
    expect(page.nodes.status.textContent).toBe('Use a password that meets all the requirements above.')
    expect(page.nodes.submit.disabled).toBe(false)
    expect(page.nodes.recovery.hidden).toBe(false)
  })

  test('proxy pass-through precedes tenant or cookie resolution and static headers exclude recovery', () => {
    const proxy = readFileSync(new URL('../proxy.ts', import.meta.url), 'utf8')
    const start = proxy.indexOf('export default async function proxy')
    expect(proxy.indexOf("pathname === '/recover'", start)).toBeLessThan(proxy.indexOf('await getInstanceInfo()', start))
    const config = readFileSync(new URL('../next.config.js', import.meta.url), 'utf8')
    expect(config).toContain("source: '/:path((?!recover(?:/|$)|api/recovery(?:/|$)).*)'")
  })
})

describe('same-origin recovery adapter', () => {
  test('redeems without forwarding ambient cookies or Authorization', async () => {
    let sent: any
    globalThis.fetch = mock(async (url: RequestInfo | URL, options?: RequestInit) => { sent = { url, ...options }; return Response.json({ message: 'ok' }) }) as typeof fetch
    const response = await POST(request('redeem', { secret, new_password: 'ChosenPassword!123' }, { Cookie: 'LH_access=stale', Authorization: 'Bearer stale' }), { params: Promise.resolve({ action: 'redeem' }) })
    expect(response.status).toBe(200)
    expect(sent.url).toBe('https://api.example.com/api/v1/users/recovery-links/redeem')
    expect(sent.credentials).toBe('omit')
    expect(sent.headers).toEqual({ 'Content-Type': 'application/json', Origin: origin })
    expect(response.headers.get('cache-control')).toBe('no-store')
    expect(response.headers.get('set-cookie')).toBeNull()
  })

  test('issuer cookies can authenticate only the issue endpoint and the raw link stays out of errors', async () => {
    let headers: any
    globalThis.fetch = mock(async (_: RequestInfo | URL, options?: RequestInit) => { headers = options!.headers; return Response.json({ link: `${origin}/recover#token=${secret}`, expires_at: '2026-10-06T12:15:00Z' }) }) as typeof fetch
    const response = await POST(request('issue', { org_id: 1, target_id: 2 }, { Cookie: 'LH_access=synthetic-session' }), { params: Promise.resolve({ action: 'issue' }) })
    expect(response.status).toBe(200)
    expect(headers.Authorization).toBe('Bearer synthetic-session')
    expect((await response.json()).link).toBe(`${origin}/recover#token=${secret}`)
    globalThis.fetch = mock(async () => { throw new Error(secret) }) as typeof fetch
    const failed = await POST(request('redeem', { secret, new_password: secret }), { params: Promise.resolve({ action: 'redeem' }) })
    expect(failed.status).toBe(503)
    expect(await failed.text()).not.toContain(secret)
  })

  test('rejects wrong Origin, wrong Host, missing Origin, and unknown actions before forwarding', async () => {
    const fetch = mock(() => { throw new Error('Must not forward') })
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch
    const invalidHeaders: Record<string, string>[] = [{ Origin: 'https://attacker.example.com' }, { Host: 'attacker.example.com' }, { Origin: '' }]
    for (const headers of invalidHeaders) {
      const response = await POST(request('redeem', { secret, new_password: 'ChosenPassword!123' }, headers), { params: Promise.resolve({ action: 'redeem' }) })
      expect(response.status).toBe(403)
    }
    expect((await POST(request('inspect', {}), { params: Promise.resolve({ action: 'inspect' }) })).status).toBe(404)
    expect(fetch).not.toHaveBeenCalled()
  })

  test('bounded body reader cancels oversized chunked input', async () => {
    let cancelled = false
    const body = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array(4097)) }, cancel() { cancelled = true } })
    const request = new Request(origin, { method: 'POST', body, duplex: 'half' } as RequestInit)
    expect(await readRecoveryBody(request)).toBeNull()
    expect(cancelled).toBe(true)
  })

  test('only an allowlisted weak-password code crosses the adapter, never upstream error text', async () => {
    globalThis.fetch = mock(async () => Response.json({ detail: { code: 'WEAK_PASSWORD', message: secret, errors: [secret] } }, { status: 400 })) as typeof fetch
    const response = await POST(request('redeem', { secret, new_password: 'weak' }), { params: Promise.resolve({ action: 'redeem' }) })
    expect(response.status).toBe(400)
    expect(await response.json()).toEqual({ code: 'WEAK_PASSWORD' })
  })
})

test('recovery telemetry is dropped and the secret-bearing dialog is outside query caches', () => {
  expect(privacy.isRecoveryEvent({ request: { url: origin + '/api/recovery/issue' } })).toBe(true)
  expect(privacy.isRecoveryEvent({ transaction: '/api/v1/users/recovery-links/redeem' })).toBe(true)
  expect(privacy.isRecoveryEvent({ transaction: '/courses' })).toBe(false)
  privacy.markDocumentRecoverySensitive()
  expect(privacy.isRecoveryEvent({ transaction: '/courses' })).toBe(true)
  const dialog = readFileSync(new URL('../components/Dashboard/Pages/Users/OrgUsers/RecoveryLinkDialog.tsx', import.meta.url), 'utf8')
  expect(dialog).toContain('data-recovery-private')
  expect(dialog).toContain('max-h-[calc(100dvh-2rem)] overflow-y-auto')
  expect(dialog).toContain('w-[calc(100vw-2rem)]')
  expect(dialog).not.toMatch(/useQuery|useMutation|localStorage|sessionStorage|console\./)
  expect(dialog.indexOf('await Sentry.getReplay()?.stop()')).toBeLessThan(dialog.indexOf('await issueRecoveryLink('))
  const sentry = readFileSync(new URL('../sentry.client.config.ts', import.meta.url), 'utf8')
  expect(sentry).toContain('networkDetailDenyUrls')
  expect(sentry).toContain('beforeAddRecordingEvent: (event) => isRecoveryPrivate() ? null : event')
})

test('shared dialog close stays enabled by default and is disabled only for pending recovery', () => {
  const shared = readFileSync(new URL('../components/ui/dialog.tsx', import.meta.url), 'utf8')
  const recovery = readFileSync(new URL('../components/Dashboard/Pages/Users/OrgUsers/RecoveryLinkDialog.tsx', import.meta.url), 'utf8')
  expect(shared).toContain('closeDisabled = false')
  expect(shared).toContain('disabled={closeDisabled}')
  expect(recovery).toContain('closeDisabled={pending}')
  expect(recovery).toContain('if (pending) return')
})
