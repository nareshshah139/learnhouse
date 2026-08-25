export type AssignmentAudienceMode = 'all' | 'groups'

export function assignmentAudienceLockType(
  mode: AssignmentAudienceMode,
  selectedGroupUuids: string[]
): 'public' | 'restricted' {
  return mode === 'groups' && selectedGroupUuids.length > 0
    ? 'restricted'
    : 'public'
}

export function isAssignmentAudienceValid(
  mode: AssignmentAudienceMode,
  selectedGroupUuids: string[]
): boolean {
  return mode === 'all' || selectedGroupUuids.length > 0
}

export function assignmentAudienceSyncPlan(
  currentGroupUuids: string[],
  selectedGroupUuids: string[]
): { add: string[]; remove: string[] } {
  const current = new Set(currentGroupUuids)
  const selected = new Set(selectedGroupUuids)

  return {
    add: [...selected].filter((uuid) => !current.has(uuid)),
    remove: [...current].filter((uuid) => !selected.has(uuid)),
  }
}
