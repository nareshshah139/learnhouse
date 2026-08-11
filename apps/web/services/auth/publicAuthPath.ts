const PUBLIC_AUTH_ALIASES: Readonly<Record<string, string>> = {
  '/auth/login': '/login',
  '/auth/signup': '/signup',
  '/auth/forgot': '/forgot',
  '/auth/reset': '/reset',
  '/auth/verify-email': '/verify-email',
}

/**
 * Translate internal Next.js auth page paths that may have leaked into old
 * bookmarks or messages back to their supported public URLs. Real callback
 * routes under /auth remain untouched.
 */
export function getPublicAuthAlias(pathname: string): string | null {
  return PUBLIC_AUTH_ALIASES[pathname] ?? null
}
