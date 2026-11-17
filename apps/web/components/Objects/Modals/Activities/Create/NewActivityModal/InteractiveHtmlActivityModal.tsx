import React from 'react'
import { readInteractiveHtmlFile } from '@/lib/interactiveHtml'

export default function InteractiveHtmlActivityModal({ submitInteractiveHtml, chapterId, course }: any) {
  const [name, setName] = React.useState('')
  const [file, setFile] = React.useState<File | null>(null)
  const [draftUuid, setDraftUuid] = React.useState<string | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file || saving) return
    setError(null)
    setSaving(true)
    try {
      const html = await readInteractiveHtmlFile(file)
      await submitInteractiveHtml({
        name, chapter_id: chapterId, course_id: course.id,
        activity_type: 'TYPE_DYNAMIC', activity_sub_type: 'SUBTYPE_DYNAMIC_HTML',
        content: {}, published: false, published_version: 1, version: 1,
      }, html, draftUuid, setDraftUuid)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create the HTML lesson.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-gray-600">Upload a self-contained UTF-8 HTML file, up to 10 MiB. Inline CSS and JavaScript, scripts from unpkg.com, and Google Fonts are allowed. Other external resources, fetch requests, and form submissions are blocked.</p>
      <p className="text-sm text-gray-600">Third-party scripts can run in the lesson and the frame can navigate away. Do not ask learners to enter passwords or secrets in untrusted lessons.</p>
      <label className="block text-sm font-medium text-gray-700">
        Lesson name
        <input className="mt-2 block w-full h-9 px-3 rounded-lg border border-gray-200" value={name} onChange={(event) => setName(event.target.value)} required disabled={Boolean(draftUuid) || saving} />
      </label>
      <label className="block text-sm font-medium text-gray-700">
        HTML file
        <input className="mt-2 block w-full text-sm" type="file" accept=".html,.htm,text/html" required disabled={saving} onChange={(event) => setFile(event.target.files?.[0] || null)} />
      </label>
      {draftUuid && <p className="text-sm text-gray-600">A draft has been created. Retry the upload here or open the draft in the course editor.</p>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <div className="flex justify-end">
        <button type="submit" disabled={saving || !file} className="h-9 px-4 rounded-lg bg-black text-white text-sm font-medium disabled:opacity-50">
          {saving ? 'Uploading...' : draftUuid ? 'Retry upload' : 'Create draft lesson'}
        </button>
      </div>
    </form>
  )
}
