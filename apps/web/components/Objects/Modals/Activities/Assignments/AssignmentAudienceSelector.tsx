'use client'

import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, UserRound, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useOrg } from '@components/Contexts/OrgContext'
import { queryKeys } from '@/lib/query/keys'
import { getUserGroups } from '@services/usergroups/usergroups'
import { asArray } from '@services/utils/ts/requests'
import type { AssignmentAudienceMode } from '@services/courses/assignmentAudience'

type UserGroup = {
  usergroup_uuid: string
  name: string
  description?: string | null
}

export default function AssignmentAudienceSelector({
  mode,
  selectedGroupUuids,
  onModeChange,
  onSelectedGroupUuidsChange,
  accessToken,
  disabled,
}: {
  mode: AssignmentAudienceMode
  selectedGroupUuids: string[]
  onModeChange: (_mode: AssignmentAudienceMode) => void
  onSelectedGroupUuidsChange: (_uuids: string[]) => void
  accessToken: string
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const { data: groups, isLoading } = useQuery({
    queryKey: queryKeys.usergroups.list(org?.id),
    queryFn: () => getUserGroups(org.id, accessToken),
    select: (response: any) => asArray<UserGroup>(response),
    enabled: mode === 'groups' && !!org?.id && !!accessToken,
    staleTime: 60_000,
  })

  const toggleGroup = (uuid: string) => {
    if (selectedGroupUuids.includes(uuid)) {
      onSelectedGroupUuidsChange(selectedGroupUuids.filter((item) => item !== uuid))
    } else {
      onSelectedGroupUuidsChange([...selectedGroupUuids, uuid])
    }
  }

  return (
    <div className="rounded-xl nice-shadow p-4 space-y-3">
      <div>
        <p className="text-sm font-medium text-gray-700">
          {t('dashboard.assignments.audience.title', { defaultValue: 'Assignment audience' })}
        </p>
        <p className="text-[10px] text-gray-500 mt-0.5">
          {t('dashboard.assignments.audience.description', {
            defaultValue: 'Choose who receives this brief. Submissions, feedback, and grades always remain individual.',
          })}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <AudienceOption
          active={mode === 'all'}
          disabled={disabled}
          icon={<UserRound size={17} />}
          title={t('dashboard.assignments.audience.all_title', { defaultValue: 'All learners' })}
          description={t('dashboard.assignments.audience.all_description', { defaultValue: 'Every enrolled learner receives it.' })}
          onClick={() => onModeChange('all')}
        />
        <AudienceOption
          active={mode === 'groups'}
          disabled={disabled}
          icon={<Users size={17} />}
          title={t('dashboard.assignments.audience.groups_title', { defaultValue: 'Selected groups' })}
          description={t('dashboard.assignments.audience.groups_description', { defaultValue: 'Only members of chosen teams receive it.' })}
          onClick={() => onModeChange('groups')}
        />
      </div>

      {mode === 'groups' && (
        <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-3 space-y-2">
          {isLoading ? (
            <p className="text-xs text-gray-500">
              {t('dashboard.assignments.audience.loading', { defaultValue: 'Loading user groups…' })}
            </p>
          ) : !groups || groups.length === 0 ? (
            <p className="text-xs text-amber-700">
              {t('dashboard.assignments.audience.empty', {
                defaultValue: 'No user groups exist yet. Create the teams under Users → User Groups first.',
              })}
            </p>
          ) : (
            <div className="max-h-40 overflow-y-auto space-y-1 pr-1">
              {groups.map((group) => {
                const selected = selectedGroupUuids.includes(group.usergroup_uuid)
                return (
                  <button
                    key={group.usergroup_uuid}
                    type="button"
                    disabled={disabled}
                    aria-pressed={selected}
                    onClick={() => toggleGroup(group.usergroup_uuid)}
                    className={`w-full flex items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors ${
                      selected
                        ? 'border-rose-200 bg-rose-50 text-rose-800'
                        : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                    } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <span className={`h-4 w-4 rounded border flex items-center justify-center flex-none ${
                      selected ? 'border-rose-500 bg-rose-500 text-white' : 'border-gray-300 bg-white'
                    }`}>
                      {selected && <Check size={11} strokeWidth={3} />}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-xs font-semibold truncate">{group.name}</span>
                      {group.description && (
                        <span className="block text-[10px] text-gray-500 truncate">{group.description}</span>
                      )}
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          <p className="text-[10px] leading-relaxed text-gray-500">
            {t('dashboard.assignments.audience.individual_grading_note', {
              defaultValue: 'Each member completes their own submission and receives an independent grade and feedback.',
            })}
          </p>
          {selectedGroupUuids.length === 0 && !isLoading && !!groups?.length && (
            <p className="text-[10px] font-semibold text-rose-600">
              {t('dashboard.assignments.audience.select_required', { defaultValue: 'Select at least one group.' })}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function AudienceOption({
  active,
  disabled,
  icon,
  title,
  description,
  onClick,
}: {
  active: boolean
  disabled?: boolean
  icon: React.ReactNode
  title: string
  description: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={active}
      onClick={onClick}
      className={`relative flex items-start gap-2.5 rounded-xl border p-3 text-left transition-colors ${
        active
          ? 'border-gray-900 bg-gray-50 ring-1 ring-gray-900'
          : 'border-gray-200 bg-white hover:bg-gray-50'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      <span className={active ? 'text-gray-900' : 'text-gray-400'}>{icon}</span>
      <span>
        <span className="block text-xs font-bold text-gray-900">{title}</span>
        <span className="block text-[10px] text-gray-500 mt-0.5 leading-snug">{description}</span>
      </span>
      {active && <Check size={13} className="absolute right-2 top-2 text-gray-900" strokeWidth={3} />}
    </button>
  )
}
