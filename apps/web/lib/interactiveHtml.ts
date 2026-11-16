import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'

export { MAX_INTERACTIVE_HTML_BYTES, readInteractiveHtmlFile, interactiveHtmlDocument } from './interactiveHtmlCore'

async function interactiveHtmlRequest(activityUuid: string, method: 'GET' | 'PUT', token?: string, html?: string): Promise<string> {
  const response = await fetch(
    `${getAPIUrl()}activities/${encodeURIComponent(activityUuid)}/interactive-html`,
    RequestBodyWithAuthHeader(method, method === 'PUT' ? { html } : null, null, token)
  )
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : `Request failed (HTTP ${response.status}).`
    throw new Error(detail)
  }
  if (typeof body?.html !== 'string') throw new Error('The server returned an invalid HTML lesson.')
  return body.html
}

export const getInteractiveHtml = (activityUuid: string, token?: string) => interactiveHtmlRequest(activityUuid, 'GET', token)
export const putInteractiveHtml = (activityUuid: string, html: string, token?: string) => interactiveHtmlRequest(activityUuid, 'PUT', token, html)
