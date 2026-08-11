// @ts-nocheck -- Bun + happy-dom test globals are intentionally outside the Next.js DOM types.
import React, { act } from 'react'
import { afterEach, describe, expect, mock, test } from 'bun:test'
import { createRoot } from 'react-dom/client'
import { Window } from 'happy-dom'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const signOutMock = mock(async () => {})

mock.module('next/navigation', () => ({
  useRouter: () => ({ refresh: () => {} }),
}))
mock.module('@components/Contexts/AuthContext', () => ({
  signOut: signOutMock,
}))
mock.module('@services/config/config', () => ({
  getPlatformUrl: () => '',
  getUriWithoutOrg: (path: string) => path,
}))
mock.module('@lib/errors/report', () => ({
  isReportingAvailable: () => false,
  openFeedbackDialog: () => {},
}))

const { default: ErrorActions } = await import(
  '../components/Objects/StyledElements/Error/ErrorActions'
)

afterEach(() => {
  signOutMock.mockClear()
})

describe('expired-session recovery', () => {
  test('Log back in clears the stale session before opening login', async () => {
    const browser = new Window({ url: 'https://learnhouse.example/course/abc' })
    Object.assign(globalThis, {
      window: browser,
      document: browser.document,
      navigator: browser.navigator,
    })

    const container = browser.document.createElement('div')
    browser.document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<ErrorActions resolutions={['login']} loginNext="/course/abc" />)
    })

    const login = container.firstElementChild?.firstElementChild as HTMLElement | undefined
    expect(login).toBeDefined()
    expect(login?.textContent).toContain('Log back in')

    await act(async () => {
      login?.click()
    })

    expect(signOutMock).toHaveBeenCalledWith({
      callbackUrl: '/login?next=%2Fcourse%2Fabc',
      redirect: true,
    })

    await act(async () => root.unmount())
    browser.close()
  })
})
