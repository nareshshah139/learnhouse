import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'

import AssignmentMarkdown from '../components/Objects/Activities/Assignment/AssignmentMarkdown'

const rubric = `## Universal grading criteria

**Week shape:** D1–2 build · D3 measure · D4–5 analysis.

| Criterion | Weight | A 4/4 looks like |
|---|---|---|
| Measurement rigor | 25% | Every number is reproducible. |

Upload one \`.zip\` archive.`

describe('AssignmentMarkdown', () => {
  test('renders assignment headings, emphasis, tables, and inline code as HTML', () => {
    const html = renderToStaticMarkup(<AssignmentMarkdown content={rubric} />)

    expect(html).toContain('<h2')
    expect(html).toContain('<strong')
    expect(html).toContain('<table')
    expect(html).toContain('<th')
    expect(html).toContain('<code')
    expect(html).not.toContain('|---|')
  })

  test('does not render raw HTML from assignment content', () => {
    const html = renderToStaticMarkup(
      <AssignmentMarkdown content={'Safe text<script>alert(1)</script>'} />
    )

    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
})
