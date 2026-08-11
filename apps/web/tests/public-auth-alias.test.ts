import { describe, expect, test } from 'bun:test'
import { getPublicAuthAlias } from '../services/auth/publicAuthPath'

describe('public auth route aliases', () => {
  test('maps leaked internal auth page URLs to their public routes', () => {
    expect(getPublicAuthAlias('/auth/login')).toBe('/login')
    expect(getPublicAuthAlias('/auth/signup')).toBe('/signup')
    expect(getPublicAuthAlias('/auth/forgot')).toBe('/forgot')
    expect(getPublicAuthAlias('/auth/reset')).toBe('/reset')
    expect(getPublicAuthAlias('/auth/verify-email')).toBe('/verify-email')
  })

  test('does not intercept real auth callbacks or magic links', () => {
    expect(getPublicAuthAlias('/auth/callback/google')).toBeNull()
    expect(getPublicAuthAlias('/auth/sso/callback')).toBeNull()
    expect(getPublicAuthAlias('/auth/magic')).toBeNull()
  })
})
