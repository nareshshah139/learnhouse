import { describe, expect, test } from 'bun:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MentionText } from '../components/Objects/Communities/MentionHighlight'

describe('community mention rendering', () => {
  test('highlights usernames but preserves punctuation and escapes HTML', () => {
    const html = renderToStaticMarkup(<MentionText text={'Hi @alice, <script>bad()</script> @bob.'} />)
    expect(html).toContain('>@alice</span>,')
    expect(html).toContain('>@bob</span>.')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
  test('does not highlight email addresses, code or URL paths', () => {
    const html = renderToStaticMarkup(<MentionText text={'alice@example.com `@code` ```@block``` https://example.com/@path'} />)
    expect(html).not.toContain('<span')
  })
})
