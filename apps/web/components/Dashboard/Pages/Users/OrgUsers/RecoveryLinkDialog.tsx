'use client'

import React, { useEffect, useRef, useState } from 'react'
import * as Sentry from '@sentry/nextjs'
import posthog from 'posthog-js'
import { Check, Copy, KeyRound, Loader2 } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@components/ui/dialog'
import { issueRecoveryLink, RecoveryLink, RecoveryRequestError } from '@services/auth/recovery'
import { markDocumentRecoverySensitive } from '@services/auth/recoveryPrivacy'

export type RecoveryRecipient = { id: number; first_name: string; last_name: string; email: string }

export default function RecoveryLinkDialog({ recipient, orgId, accessToken, onClose }: {
  recipient: RecoveryRecipient; orgId: number; accessToken: string; onClose: () => void
}) {
  const [result, setResult] = useState<RecoveryLink | null>(null)
  const [pending, setPending] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => { controller.current?.abort() }, [])

  function close() {
    if (pending) return
    setResult(null)
    setCopied(false)
    setError('')
    onClose()
  }

  async function generate() {
    if (pending) return
    setPending(true)
    setError('')
    setCopied(false)
    setResult(null)
    const abort = new AbortController()
    controller.current = abort
    try {
      markDocumentRecoverySensitive()
      posthog.stopSessionRecording()
      await Sentry.getReplay()?.stop()
      if (abort.signal.aborted) return
      const link = await issueRecoveryLink(orgId, recipient.id, accessToken, abort.signal)
      if (!abort.signal.aborted) setResult(link)
    } catch (failure) {
      if (!abort.signal.aborted) setError(failure instanceof RecoveryRequestError ? failure.message : 'Could not create a private recovery link. Refresh the page and try again.')
    } finally {
      if (!abort.signal.aborted) setPending(false)
    }
  }

  async function copy() {
    if (!result || pending) return
    try { await navigator.clipboard.writeText(result.link); setCopied(true) }
    catch { setError('Copy was blocked by your browser. Select the link and copy it manually.') }
  }

  return <Dialog open onOpenChange={(open) => { if (!open) close() }}>
    <DialogContent data-recovery-private closeDisabled={pending} className="ph-no-capture ph-mask sentry-block w-[calc(100vw-2rem)] max-w-lg max-h-[calc(100dvh-2rem)] overflow-y-auto p-7 sm:p-8" onEscapeKeyDown={(event) => { if (pending) event.preventDefault() }} onInteractOutside={(event) => { if (pending) event.preventDefault() }}>
      <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-xl bg-gray-100 text-gray-700"><KeyRound className="h-5 w-5" aria-hidden="true" /></div>
      <DialogTitle className="text-xl">Create a recovery link</DialogTitle>
      <DialogDescription className="mt-3 leading-relaxed">For <span className="font-semibold text-gray-800">{recipient.first_name} {recipient.last_name}</span><br />{recipient.email}</DialogDescription>
      <p className="mt-5 text-sm leading-relaxed text-gray-600">The learner chooses their own password. This does not change their courses, assignments, role, or two-factor authentication.</p>
      <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-relaxed text-amber-950">
        Anyone with this link can change this learner’s password. Share it privately with this learner only. It expires in 15 minutes and works once. Generating another link replaces the previous one.
      </div>
      {result && <div className="mt-5">
        <label htmlFor="recovery-link" className="text-sm font-semibold text-gray-800">One-use recovery link</label>
        <input id="recovery-link" readOnly value={result.link} autoComplete="off" spellCheck={false} onFocus={(event) => event.target.select()} className="mt-2 w-full rounded-lg border border-gray-300 bg-gray-50 px-3 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-gray-400" />
        <p className="mt-2 text-xs text-gray-500">Expires {new Date(result.expires_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })}. The link disappears when you close this dialog.</p>
      </div>}
      <p role="status" aria-live="polite" className="mt-4 min-h-5 text-sm text-red-700">{error || (copied ? 'Link copied. Share it privately with this learner.' : '')}</p>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={close} disabled={pending} className="rounded-lg border border-gray-200 px-4 py-2.5 text-sm font-medium disabled:opacity-50">Close</button>
        <button type="button" onClick={generate} disabled={pending} className={`flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium disabled:opacity-50 ${result ? 'border border-gray-300 text-gray-700' : 'bg-gray-900 text-white'}`}>
          {pending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}{pending ? 'Creating…' : result ? 'Replace link' : 'Generate link'}
        </button>
        {result && <button type="button" onClick={copy} disabled={pending} className="flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50">{copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}{copied ? 'Copied' : 'Copy link'}</button>}
      </div>
    </DialogContent>
  </Dialog>
}
