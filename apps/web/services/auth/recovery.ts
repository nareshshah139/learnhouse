export type RecoveryLink = { link: string; expires_at: string }
export class RecoveryRequestError extends Error {}

export async function issueRecoveryLink(orgId: number, targetId: number, accessToken: string, signal: AbortSignal): Promise<RecoveryLink> {
  const response = await fetch('/api/recovery/issue', {
    method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ org_id: orgId, target_id: targetId }),
  })
  if (!response.ok) {
    throw new RecoveryRequestError(response.status === 403 ? 'Recovery is limited to single-organization learners and current organization Admins. Check the account and your sign-in policy.' : response.status === 401 ? 'Sign in again before creating a recovery link.' : response.status === 429 ? 'Too many requests. Try again in a few minutes.' : 'Could not create a recovery link. Please try again.')
  }
  return await response.json()
}
