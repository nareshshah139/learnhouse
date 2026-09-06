'use client'
import React, { forwardRef, useRef, useState } from 'react'
import { MentionSuggestions, mentionAtCursor } from './MentionSuggestions'

export const MentionTextarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  communityUuid?: string
}>(({ communityUuid, onChange, onSelect, onKeyDown, ...props }, forwardedRef) => {
  const ref = useRef<HTMLTextAreaElement | null>(null)
  const [cursor, setCursor] = useState(0)
  const [dismissed, setDismissed] = useState(false)
  const text = String(props.value || '')
  const match = dismissed ? null : mentionAtCursor(text.slice(0, cursor))
  return <>
    <textarea {...props} ref={el => { ref.current = el; if (typeof forwardedRef === 'function') forwardedRef(el); else if (forwardedRef) forwardedRef.current = el }}
      onChange={e => { setCursor(e.target.selectionStart); setDismissed(false); onChange?.(e) }}
      onSelect={e => { setCursor(e.currentTarget.selectionStart); onSelect?.(e) }}
      onKeyDown={e => { if (e.key === 'Escape') setDismissed(true); onKeyDown?.(e) }} />
    <MentionSuggestions communityUuid={communityUuid} query={match?.[1] ?? null} onSelect={username => {
      const el = ref.current
      if (!el || !match) return
      const start = cursor - match[1].length - 1
      const value = `${text.slice(0, start)}@${username} ${text.slice(cursor)}`
      // The parent owns the value, as with a normal textarea change.
      onChange?.({ target: { value }, currentTarget: { value } } as React.ChangeEvent<HTMLTextAreaElement>)
      const end = start + username.length + 2
      setCursor(end); setDismissed(true)
      requestAnimationFrame(() => { el.focus(); el.setSelectionRange(end, end) })
    }} />
  </>
})
MentionTextarea.displayName = 'MentionTextarea'
