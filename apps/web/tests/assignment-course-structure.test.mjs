import { afterEach, describe, expect, test } from 'bun:test'

import { loadAssignmentCourseStructure } from '../app/orgs/[orgslug]/dash/assignments/_components/assignmentCourseStructure.ts'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('assignment course structure', () => {
  test('loads course metadata so the chapter picker receives chapters', async () => {
    const calls = []
    globalThis.fetch = async (url, options) => {
      calls.push({ url: String(url), options })
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: 7,
          course_uuid: 'course_demo',
          chapters: [{ id: 11, name: 'First Chapter' }],
        }),
      }
    }

    const result = await loadAssignmentCourseStructure('demo', 'test-token')

    expect(result.chapters).toHaveLength(1)
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toEndWith(
      '/api/v1/courses/course_demo/meta?slim=true&with_unpublished_activities=true'
    )
    expect(calls[0].options.headers.get('Authorization')).toBe('Bearer test-token')
  })
})
