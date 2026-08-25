import { describe, expect, test } from 'bun:test'

import {
  assignmentAudienceLockType,
  assignmentAudienceSyncPlan,
  isAssignmentAudienceValid,
} from '../services/courses/assignmentAudience'

describe('assignment audience', () => {
  test('keeps course-wide assignments public', () => {
    expect(assignmentAudienceLockType('all', ['group_one'])).toBe('public')
    expect(isAssignmentAudienceValid('all', [])).toBe(true)
  })

  test('requires at least one group for a group assignment', () => {
    expect(isAssignmentAudienceValid('groups', [])).toBe(false)
    expect(isAssignmentAudienceValid('groups', ['group_one'])).toBe(true)
    expect(assignmentAudienceLockType('groups', ['group_one'])).toBe('restricted')
  })

  test('computes idempotent additions and removals', () => {
    expect(assignmentAudienceSyncPlan(
      ['group_one', 'group_two'],
      ['group_two', 'group_three']
    )).toEqual({
      add: ['group_three'],
      remove: ['group_one'],
    })
  })
})
