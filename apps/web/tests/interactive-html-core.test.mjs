import { test } from 'node:test'
import assert from 'node:assert/strict'
import { interactiveHtmlDocument, readInteractiveHtmlFile, MAX_INTERACTIVE_HTML_BYTES } from '../lib/interactiveHtmlCore.ts'

test('security policy precedes even a complete untrusted HTML document', () => {
  const html = '<!doctype html><html><head><script>1</script></head></html>'
  const result = interactiveHtmlDocument(html)
  assert.ok(result.indexOf('Content-Security-Policy') < result.indexOf(html))
  assert.match(result, /connect-src 'none'/)
  assert.match(result, /form-action 'none'/)
  assert.match(result, /frame-src 'self'/)
  assert.match(result, /script-src 'unsafe-inline' https:\/\/unpkg\.com/)
  assert.match(result, /style-src 'unsafe-inline' https:\/\/fonts\.googleapis\.com/)
  assert.match(result, /font-src data: https:\/\/fonts\.gstatic\.com/)
  assert.doesNotMatch(result, /https:;/)
})

test('file validation preserves valid source and rejects invalid inputs', async () => {
  assert.equal(await readInteractiveHtmlFile(new File(['<script>2</script>'], 'lesson.HTML')), '<script>2</script>')
  await assert.rejects(readInteractiveHtmlFile(new File(['x'], 'lesson.js')), /\.html or \.htm/)
  await assert.rejects(readInteractiveHtmlFile(new File([], 'lesson.html')), /non-empty/)
  assert.equal(MAX_INTERACTIVE_HTML_BYTES, 10 * 1024 * 1024)
  const atLimit = 'x'.repeat(10 * 1024 * 1024)
  assert.equal(await readInteractiveHtmlFile(new File([atLimit], 'lesson.html')), atLimit)
  await assert.rejects(readInteractiveHtmlFile(new File([atLimit, 'x'], 'lesson.html')), /10 MiB/)
  await assert.rejects(readInteractiveHtmlFile(new File([new Uint8Array([0xff])], 'lesson.html')), /UTF-8/)
  await assert.rejects(readInteractiveHtmlFile(new File(['\0'], 'lesson.html')), /null bytes/)
})
