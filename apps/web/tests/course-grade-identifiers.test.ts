import { describe, expect, test } from 'bun:test'

import { toCourseResourceUuid } from '../services/courses/courseIdentifiers'

describe('course grade API identifiers', () => {
  test('adds the resource prefix used by the API to learner-route UUIDs', () => {
    expect(toCourseResourceUuid('75d99e2d-e465-4b61-97f9-3826c6ffdcf0'))
      .toBe('course_75d99e2d-e465-4b61-97f9-3826c6ffdcf0')
  })

  test('preserves the prefixed UUID used by staff routes', () => {
    expect(toCourseResourceUuid('course_75d99e2d-e465-4b61-97f9-3826c6ffdcf0'))
      .toBe('course_75d99e2d-e465-4b61-97f9-3826c6ffdcf0')
  })
})
