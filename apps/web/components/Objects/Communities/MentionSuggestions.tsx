'use client'
import React, { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'

export function mentionAtCursor(text: string) {
  return /(?:^|\s)@([\w.-]*)$/.exec(text)
}

export function MentionSuggestions({ communityUuid, query, onSelect }: {
  communityUuid?: string; query: string | null; onSelect: (_username: string) => void
}) {
  const pathname = usePathname()
  const uuid = communityUuid || (pathname.match(/\/community\/([^/]+)/)?.[1] ? `community_${pathname.match(/\/community\/([^/]+)/)![1]}` : '')
  const session = useLHSession() as any
  const token = session?.data?.tokens?.access_token
  const [users, setUsers] = useState<{username: string; name: string}[]>([])
  const [status, setStatus] = useState('')
  useEffect(() => {
    setUsers([])
    if (query === null || !uuid || !token) return
    const controller = new AbortController()
    setStatus('Searching…')
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`${getAPIUrl()}communities/${encodeURIComponent(uuid)}/mention-candidates?q=${encodeURIComponent(query)}`, {
          ...RequestBodyWithAuthHeader('GET', null, null, token), signal: controller.signal,
        })
        if (!response.ok) throw new Error('Unable to load people')
        const data = await response.json()
        if (!controller.signal.aborted) { setUsers(data); setStatus(data.length ? '' : 'No matching members') }
      } catch { if (!controller.signal.aborted) setStatus('Unable to load people') }
    }, 200)
    return () => { clearTimeout(timer); controller.abort() }
  }, [query, uuid, token])
  if (query === null || !uuid || !token) return null
  return <div className="border rounded-lg bg-white shadow-sm p-2 max-h-52 overflow-auto" aria-label="People to mention">
    {status && <p role="status" className="text-xs text-gray-500 p-2">{status}</p>}
    {users.map(user => <button key={user.username} type="button"
      onMouseDown={e => e.preventDefault()} onClick={() => onSelect(user.username)}
      className="block w-full text-left rounded px-3 py-2 text-sm hover:bg-gray-100 focus:bg-gray-100">
      <span className="font-medium">{user.name}</span> <span className="text-gray-500">@{user.username}</span>
    </button>)}
    <p className="text-xs text-gray-500 p-1">Select a person to notify them when you post. Up to 20 people per post.</p>
  </div>
}
