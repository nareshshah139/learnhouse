import { NextRequest } from 'next/server'
import { getServerAPIUrl } from '@services/config/config'
import { ACCESS_TOKEN_COOKIE } from '@services/auth/cookies'
import { isRecoveryRequestAllowed, readRecoveryBody, recoveryHeaders, recoveryOrigin } from '@services/auth/recoveryServer'

export const dynamic = 'force-dynamic'

function reply(data: unknown, status: number) {
  return Response.json(data, { status, headers: recoveryHeaders })
}

export async function POST(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  try {
    const origin = recoveryOrigin()
    if (!isRecoveryRequestAllowed(request, origin, true)) return reply({ detail: 'Invalid recovery request.' }, 403)
    const { action } = await context.params
    if (action !== 'issue' && action !== 'redeem') return reply({ detail: 'Not found.' }, 404)
    if (request.headers.get('content-type')?.split(';')[0] !== 'application/json') return reply({ detail: 'Invalid recovery request.' }, 400)
    const body = await readRecoveryBody(request)
    const keys = action === 'issue' ? ['org_id', 'target_id'] : ['secret', 'new_password']
    if (!body || typeof body !== 'object' || Object.keys(body).sort().join() !== keys.sort().join()) return reply({ detail: 'Invalid recovery request.' }, 400)
    const headers: Record<string, string> = { 'Content-Type': 'application/json', Origin: origin.origin }
    if (action === 'issue') {
      const token = request.headers.get('authorization') || (request.cookies.get(ACCESS_TOKEN_COOKIE)?.value ? `Bearer ${request.cookies.get(ACCESS_TOKEN_COOKIE)!.value}` : '')
      if (!token) return reply({ detail: 'Sign in again before creating a recovery link.' }, 401)
      headers.Authorization = token
    }
    const upstream = await fetch(`${getServerAPIUrl()}users/recovery-links/${action}`, {
      method: 'POST', headers, body: JSON.stringify(body), cache: 'no-store',
      credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(15000),
    })
    if (!upstream.ok) {
      const status = [400, 401, 403, 429].includes(upstream.status) ? upstream.status : 503
      if (action === 'redeem' && status === 400) {
        const failure = await upstream.json().catch(() => null)
        if (failure?.detail?.code === 'WEAK_PASSWORD') return reply({ code: 'WEAK_PASSWORD' }, 400)
      }
      return reply({ detail: status === 429 ? 'Too many recovery requests. Try again later.' : 'The recovery request could not be completed.' }, status)
    }
    if (action === 'redeem') return reply({ message: 'Password changed. Sign in with your new password.' }, 200)
    const result = await upstream.json()
    const link = new URL(result.link)
    if (link.origin !== origin.origin || link.pathname !== '/recover' || link.search || !/^#token=[A-Za-z0-9_-]{43}$/.test(link.hash) || !Number.isFinite(Date.parse(result.expires_at))) {
      return reply({ detail: 'Recovery is temporarily unavailable.' }, 503)
    }
    return reply({ link: link.href, expires_at: result.expires_at }, 200)
  } catch {
    return reply({ detail: 'Recovery is temporarily unavailable.' }, 503)
  }
}
