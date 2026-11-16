import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { runInNewContext } from 'node:vm'
import { interactiveHtmlDocument } from '../lib/interactiveHtmlCore.ts'

const require = createRequire(import.meta.url)
const ts = require('typescript')

function load(source, fetch) {
  const compiled = ts.transpileModule(readFileSync(new URL(source, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText
  const testModule = { exports: {} }
  const imports = (name) => {
    if (name === '@services/config/config') return { getAPIUrl: () => 'https://example.invalid/api/' }
    if (name === '@services/utils/ts/requests') return {
      RequestBodyWithAuthHeader: (method, data, _next, token) => ({ method, body: data === null ? null : JSON.stringify(data), token }),
    }
    if (name === './interactiveHtmlCore') return {}
    throw new Error(`Unexpected import: ${name}`)
  }
  runInNewContext('(function(require, module, exports, fetch, Error) { ' + compiled + '\n})')(
    imports, testModule, testModule.exports, fetch, Error,
  )
  return testModule.exports
}

test('HTML GET and PUT use the intended activity and preserve authorization and content', async () => {
  const calls = []
  const api = load('../lib/interactiveHtml.ts', async (url, options) => {
    calls.push({ url, options })
    return { ok: true, json: async () => ({ html: '<script>2</script>' }) }
  })
  assert.equal(await api.getInteractiveHtml('activity_123', 'access'), '<script>2</script>')
  assert.equal(await api.putInteractiveHtml('activity_123', '<script>2</script>', 'access'), '<script>2</script>')
  assert.equal(calls[0].url, 'https://example.invalid/api/activities/activity_123/interactive-html')
  assert.equal(calls[0].options.method, 'GET')
  assert.equal(calls[0].options.token, 'access')
  assert.equal(calls[1].options.method, 'PUT')
  assert.equal(calls[1].options.body, '{"html":"<script>2</script>"}')
})

test('API errors and malformed responses fail rather than reporting success', async () => {
  const denied = load('../lib/interactiveHtml.ts', async () => ({ ok: false, status: 403, json: async () => ({ detail: 'Access denied' }) }))
  await assert.rejects(denied.getInteractiveHtml('activity_123'), /Access denied/)
  const malformed = load('../lib/interactiveHtml.ts', async () => ({ ok: true, json: async () => ({}) }))
  await assert.rejects(malformed.getInteractiveHtml('activity_123'), /invalid HTML lesson/)
  const activities = load('../services/courses/activities.ts', async () => ({ ok: false, status: 413, json: async () => ({ detail: 'Too large' }) }))
  await assert.rejects(activities.createActivity({}, 1, 1, 'access'), /Too large/)
})

test('the rendered iframe has an opaque-origin script-only sandbox', () => {
  const compiled = ts.transpileModule(readFileSync(new URL('../components/Objects/Activities/InteractiveHtml/InteractiveHtmlActivity.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText
  const testModule = { exports: {} }
  const imports = (name) => {
    if (name === 'react') return require('react')
    if (name === '@components/Contexts/LHSessionContext') return { useLHSession() {} }
    if (name === '@/lib/interactiveHtml') return { interactiveHtmlDocument }
    throw new Error(`Unexpected import: ${name}`)
  }
  runInNewContext('(function(require, module, exports) { ' + compiled + '\n})')(imports, testModule, testModule.exports)
  const react = require('react')
  const { renderToStaticMarkup } = require('react-dom/server')
  const markup = renderToStaticMarkup(react.createElement(testModule.exports.InteractiveHtmlFrame, { title: 'Demo', html: '<script>2</script>' }))
  assert.match(markup, /sandbox="allow-scripts"/)
  assert.match(markup, /title="Demo"/)
  assert.doesNotMatch(markup, /allow-same-origin|allow-forms/)
})
