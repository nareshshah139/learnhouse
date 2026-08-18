// @ts-nocheck -- Bun + happy-dom test globals are intentionally outside the Next.js DOM types.
import React, { act } from 'react'
import { afterEach, describe, expect, mock, test } from 'bun:test'
import { createRoot } from 'react-dom/client'
import { Window } from 'happy-dom'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

mock.module('next/link', () => ({
  default: ({ href, children, ...props }: React.ComponentProps<'a'>) => (
    <a href={href} {...props}>{children}</a>
  ),
}))

mock.module('@services/config/config', () => ({
  getUriWithOrg: (_orgslug: string, path: string) => path,
}))

const { default: CourseGradesLink } = await import(
  '../components/Pages/Courses/CourseGradesLink'
)

afterEach(() => {
  document.body.innerHTML = ''
})

describe('learner course grades navigation', () => {
  test('links activity navigation to the learner-facing gradebook', async () => {
    const browser = new Window({ url: 'https://learnhouse.example/course/course-123/activity/activity-456' })
    Object.assign(globalThis, {
      window: browser,
      document: browser.document,
      navigator: browser.navigator,
    })

    const container = browser.document.createElement('div')
    browser.document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(
        <CourseGradesLink
          orgslug="gd-fde"
          courseuuid="course-123"
          variant="toolbar"
        />,
      )
    })

    const link = container.querySelector('a')
    expect(link?.getAttribute('href')).toBe('/course/course-123/grades')
    expect(link?.getAttribute('aria-label')).toBe('View course grades')
    expect(link?.textContent).toContain('Grades')

    await act(async () => root.unmount())
    browser.close()
  })
})
