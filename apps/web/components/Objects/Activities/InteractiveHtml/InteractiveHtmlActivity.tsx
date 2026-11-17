'use client'

import React from 'react'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { getInteractiveHtml, interactiveHtmlDocument, putInteractiveHtml, readInteractiveHtmlFile } from '@/lib/interactiveHtml'

export function InteractiveHtmlFrame({ html, title }: { html: string; title: string }) {
  return (
    <iframe
      title={title}
      srcDoc={interactiveHtmlDocument(html)}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      className="w-full min-h-[480px] h-[75vh] border-0 rounded-xl bg-white"
    />
  )
}

export default function InteractiveHtmlActivity({ activity, editable = false }: { activity: any; editable?: boolean }) {
  const session = useLHSession() as any
  const token = session?.data?.tokens?.access_token
  const uuid = activity?.activity_uuid as string | undefined
  const [html, setHtml] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [message, setMessage] = React.useState<string | null>(null)

  React.useEffect(() => {
    let active = true
    setHtml(null)
    setError(null)
    setLoading(true)
    if (!uuid) {
      setError('The lesson could not be identified.')
      setLoading(false)
      return () => { active = false }
    }
    getInteractiveHtml(uuid, token).then((source) => {
      if (active) setHtml(source)
    }).catch((err: unknown) => {
      if (active) setError(err instanceof Error ? err.message : 'Unable to load the HTML lesson.')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [uuid, token])

  const replaceFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !uuid) return
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      const source = await readInteractiveHtmlFile(file)
      setHtml(await putInteractiveHtml(uuid, source, token))
      setMessage('HTML lesson updated.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update the HTML lesson.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="w-full px-6 py-6 space-y-4">
      <p className="text-sm text-gray-600">
        This lesson runs in an isolated frame. Inline JavaScript and CSS, scripts from unpkg.com,
        and Google Fonts are allowed; other external resources, fetch requests, and form submissions are blocked.
        Third-party scripts can run in the lesson and the frame can navigate away. Do not enter passwords or secrets in an untrusted lesson.
      </p>
      {editable && (
        <label className="block text-sm font-medium text-gray-700">
          Replace HTML file (.html or .htm, maximum 10 MiB)
          <input className="mt-2 block w-full text-sm" type="file" accept=".html,.htm,text/html" disabled={saving} onChange={replaceFile} />
        </label>
      )}
      {saving && <p role="status" className="text-sm text-gray-600">Saving HTML lesson...</p>}
      {message && <p role="status" className="text-sm text-green-700">{message}</p>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {loading ? <p role="status" className="text-sm text-gray-600">Loading HTML lesson...</p> : html !== null ? (
        <InteractiveHtmlFrame html={html} title={activity?.name || 'Interactive HTML lesson'} />
      ) : null}
    </section>
  )
}
