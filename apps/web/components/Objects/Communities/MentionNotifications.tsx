'use client'
import React, { useEffect, useState } from 'react'
import { Bell, X } from 'lucide-react'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { getAPIUrl, getUriWithOrg } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'
import Link from 'next/link'

type Notification = { id: number; read: boolean; actor: string; title: string; href: string }
export function MentionNotifications() {
  const session = useLHSession() as any
  const org = useOrg() as any
  const token = session?.data?.tokens?.access_token
  const [items, setItems] = useState<Notification[]>([])
  const [open, setOpen] = useState(false)
  const [error, setError] = useState(false)
  useEffect(() => {
    setItems([])
    if (!token || !org?.id) return
    let stale = false
    const load = async () => {
      try {
        const res = await fetch(`${getAPIUrl()}mentions/notifications?org_id=${org.id}`, RequestBodyWithAuthHeader('GET', null, null, token))
        if (!res.ok) throw new Error('Notification request failed')
        const data = await res.json()
        if (!stale) { setItems(data); setError(false) }
      } catch { if (!stale) setError(true) }
    }
    load()
    const timer = setInterval(load, 30000)
    return () => { stale = true; clearInterval(timer) }
  }, [token, org?.id, open])
  if (!token) return null
  const unread = items.filter(item => !item.read).length
  return <div className="relative">
    <button type="button" aria-label={`Mention notifications${unread ? `, ${unread} unread` : ''}`} aria-expanded={open}
      onClick={() => setOpen(!open)} className="relative rounded-lg p-3 hover:bg-gray-100 focus-visible:outline focus-visible:outline-2">
      <Bell size={20} />
      {unread > 0 && <span className="absolute -right-1 -top-1 bg-red-600 text-white rounded-full text-xs px-1">{unread}</span>}
    </button>
    {open && <div className="absolute right-0 top-full z-50 w-80 max-w-[85vw] max-h-96 overflow-auto break-words rounded-xl bg-white shadow-lg p-3" onKeyDown={e => { if (e.key === 'Escape') setOpen(false) }}>
      <div className="flex justify-between items-center"><h2 className="font-semibold text-sm">Mentions</h2><button type="button" className="p-3 rounded hover:bg-gray-100" onClick={() => setOpen(false)} aria-label="Close notifications"><X size={18} /></button></div>
      {error && <p role="status" className="text-sm p-3">Could not refresh notifications. Retrying shortly.</p>}
      {!error && !items.length && <p className="text-sm text-gray-500 p-3">No mentions yet.</p>}
      {items.map(item => <div key={item.id} className={`p-2 rounded-lg mt-1 ${item.read ? '' : 'bg-blue-50'}`}>
        <Link className="block text-sm" href={getUriWithOrg(org.slug, item.href)} onClick={() => setOpen(false)}>
          <strong>{item.actor}</strong> mentioned you in <span className="underline">{item.title}</span>
        </Link>
        {!item.read && <button type="button" className="text-xs text-blue-700 mt-1" onClick={async () => {
          try {
            const res = await fetch(`${getAPIUrl()}mentions/notifications/${item.id}/read`, RequestBodyWithAuthHeader('PATCH', null, null, token))
            if (!res.ok) throw new Error('Mark read failed')
            setItems(prev => prev.map(n => n.id === item.id ? { ...n, read: true } : n))
          } catch { setError(true) }
        }}>Mark as read</button>}
      </div>)}
    </div>}
  </div>
}
