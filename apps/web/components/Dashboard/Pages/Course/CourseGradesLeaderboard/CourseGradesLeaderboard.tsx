'use client'

import React, { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  GraduationCap,
  Pencil,
  RefreshCw,
  Search,
  SlidersHorizontal,
  ShieldCheck,
  Trophy,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { queryKeys } from '@/lib/query/keys'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import UserAvatar from '@components/Objects/UserAvatar'
import {
  getCourseGradeLeaderboard,
  updateCourseDiscussionGrade,
  updateCourseGradeWeights,
} from '@services/courses/courses'
import { getUserAvatarMediaDirectory } from '@services/media/media'

type GradebookUser = {
  id: number
  user_uuid: string
  username: string
  first_name: string
  last_name: string
  avatar_image: string
}

type AssignmentGrade = {
  percentage: number | null
  graded_count: number
  assigned_count: number
  status: 'graded' | 'not_graded'
}

type DiscussionGrade = {
  percentage: number
  score: number
  max_score: number
  status: 'graded'
}

type WeekGrade = {
  assignment: AssignmentGrade
  discussion: DiscussionGrade | null
  weighted_percentage?: number | null
}

type GradebookWeek = {
  week_number: number
  label: string
  assignment_weight: number
  discussion_weight: number
}

type GradebookRow = {
  user: GradebookUser
  weeks: Record<string, WeekGrade>
  rank: number | null
  cumulative_percentage: number | null
  graded_components: number
  ranked_components: number
  ranked_weeks: number
}

type GradebookResponse = {
  course_uuid: string
  can_manage: boolean
  weeks: GradebookWeek[]
  summary: { learners: number; weeks: number; ranked_components: number; ranked_weeks: number }
  gradebook: GradebookRow[]
}

type GradeComponent = 'assignment' | 'discussion'
type SortKey = 'rank' | 'learner' | 'cumulative' | `week:${number}:${GradeComponent}`
type SortDirection = 'asc' | 'desc'

const formatPercentage = (value: number) => `${value.toFixed(2).replace(/\.00$/, '')}%`

function letterGrade(score: number) {
  if (score >= 90) return 'A'
  if (score >= 80) return 'B'
  if (score >= 70) return 'C'
  if (score >= 60) return 'D'
  return 'F'
}

function learnerName(user: GradebookUser) {
  return `${user.first_name || ''} ${user.last_name || ''}`.trim() || `@${user.username}`
}

function cumulativeDetail(row: GradebookRow) {
  const weekLabel = row.ranked_weeks === 1 ? 'week' : 'weeks'
  return `${row.graded_components}/${row.ranked_components} inputs · ${row.ranked_weeks} ${weekLabel}`
}

function gradebookErrorDescription(error: unknown) {
  const status = typeof error === 'object' && error !== null && 'status' in error
    ? Number((error as { status?: unknown }).status)
    : undefined

  if (status === 403) return 'You must be enrolled in this course to view its gradebook.'
  if (status === 404) return 'This course gradebook could not be found. Refresh the course page and try again.'
  return 'Course grades are temporarily unavailable. Please try again.'
}

function scoreSortKey(weekNumber: number, component: GradeComponent): SortKey {
  return `week:${weekNumber}:${component}`
}

function rowSortValue(row: GradebookRow, sortKey: SortKey): number | string | null {
  if (sortKey === 'rank') return row.rank
  if (sortKey === 'learner') return `${learnerName(row.user)} ${row.user.username}`.toLocaleLowerCase()
  if (sortKey === 'cumulative') return row.cumulative_percentage

  const [, weekNumber, component] = sortKey.split(':') as [string, string, GradeComponent]
  const week = row.weeks[weekNumber]
  return component === 'assignment'
    ? week?.assignment?.percentage ?? null
    : week?.discussion?.percentage ?? null
}

function SortButton({
  label,
  sortKey,
  activeSortKey,
  direction,
  onSort,
  centered = false,
  ariaLabel,
}: {
  label: string
  sortKey: SortKey
  activeSortKey: SortKey
  direction: SortDirection
  onSort: (_key: SortKey) => void
  centered?: boolean
  ariaLabel?: string
}) {
  const active = activeSortKey === sortKey
  const Icon = active ? (direction === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown

  return (
    <button
      type="button"
      onClick={() => onSort(sortKey)}
      className={`inline-flex min-h-8 items-center gap-1.5 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-gray-200/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-1 ${centered ? 'justify-center' : ''}`}
      aria-label={ariaLabel ?? `Sort by ${label}`}
    >
      <span>{label}</span>
      <Icon size={13} className={active ? 'text-gray-800' : 'text-gray-400'} aria-hidden="true" />
    </button>
  )
}

function LearnerIdentity({ user }: { user: GradebookUser }) {
  const avatarUrl = user.avatar_image
    ? getUserAvatarMediaDirectory(user.user_uuid, user.avatar_image)
    : ''

  return (
    <div className="flex min-w-0 items-center gap-3">
      <UserAvatar
        avatar_url={avatarUrl}
        predefined_avatar={avatarUrl ? undefined : 'empty'}
        rounded="rounded-full"
        width={36}
      />
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-gray-950">{learnerName(user)}</p>
        <p className="truncate text-xs text-gray-500">@{user.username}</p>
      </div>
    </div>
  )
}

function GradeValue({ percentage, detail }: { percentage: number | null | undefined; detail?: string }) {
  if (percentage === null || percentage === undefined) {
    return <span className="text-sm font-medium text-gray-400">Not graded</span>
  }

  return (
    <div>
      <p className="text-sm font-semibold tabular-nums text-gray-950">
        {formatPercentage(percentage)} <span className="text-gray-400">·</span> {letterGrade(percentage)}
      </p>
      {detail ? <p className="mt-0.5 text-xs tabular-nums text-gray-500">{detail}</p> : null}
    </div>
  )
}

function DiscussionGradeEditor({
  grade,
  isSaving,
  onSave,
}: {
  grade: DiscussionGrade | null
  isSaving: boolean
  onSave: (_score: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [score, setScore] = useState(String(grade?.score ?? ''))

  if (!editing) {
    return (
      <div className="group flex items-center justify-between gap-2">
        <GradeValue
          percentage={grade?.percentage}
          detail={grade ? `${grade.score} / ${grade.max_score} points` : undefined}
        />
        <button
          type="button"
          onClick={() => {
            setScore(String(grade?.score ?? ''))
            setEditing(true)
          }}
          className="rounded-lg p-1.5 text-gray-400 opacity-100 transition hover:bg-gray-100 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100"
          aria-label="Edit discussion grade"
        >
          <Pencil size={14} />
        </button>
      </div>
    )
  }

  const numericScore = Number(score)
  const valid = score.trim() !== '' && Number.isInteger(numericScore) && numericScore >= 0 && numericScore <= 100

  return (
    <div className="flex items-center gap-2">
      <label className="sr-only">Discussion score out of 100</label>
      <input
        type="number"
        min={0}
        max={100}
        step={1}
        value={score}
        onChange={(event) => setScore(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setEditing(false)
          if (event.key === 'Enter' && valid) {
            onSave(numericScore)
            setEditing(false)
          }
        }}
        autoFocus
        className="h-9 w-20 rounded-lg border border-gray-300 bg-white px-2 text-sm tabular-nums text-gray-950 outline-none focus:border-gray-500 focus:ring-2 focus:ring-gray-900/10"
      />
      <span className="text-xs text-gray-400">/100</span>
      <button
        type="button"
        disabled={!valid || isSaving}
        onClick={() => {
          onSave(numericScore)
          setEditing(false)
        }}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gray-950 text-white hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40"
        aria-label="Save discussion grade"
      >
        <Check size={15} />
      </button>
    </div>
  )
}

function WeekWeightControl({
  week,
  canManage,
  isSaving,
  onSave,
}: {
  week: GradebookWeek
  canManage: boolean
  isSaving: boolean
  onSave: (_assignmentWeight: number, _discussionWeight: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [discussionWeight, setDiscussionWeight] = useState(String(week.discussion_weight))
  const numericDiscussionWeight = Number(discussionWeight)
  const valid = discussionWeight.trim() !== ''
    && Number.isInteger(numericDiscussionWeight)
    && numericDiscussionWeight >= 0
    && numericDiscussionWeight <= 100
  const assignmentWeight = valid ? 100 - numericDiscussionWeight : week.assignment_weight

  if (!editing) {
    const content = (
      <>
        <span className="font-semibold text-gray-800">{week.label}</span>
        <span className="text-gray-500">Assignment {week.assignment_weight}%</span>
        <span className="text-gray-300" aria-hidden="true">·</span>
        <span className="text-gray-500">Discussion {week.discussion_weight}%</span>
        {canManage ? (
          isSaving
            ? <RefreshCw size={12} className="animate-spin text-gray-400" aria-hidden="true" />
            : <Pencil size={12} className="text-gray-400" aria-hidden="true" />
        ) : null}
      </>
    )

    return canManage ? (
      <button
        type="button"
        disabled={isSaving}
        onClick={() => {
          setDiscussionWeight(String(week.discussion_weight))
          setEditing(true)
        }}
        className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 px-3 text-xs transition-colors hover:border-gray-300 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-1 disabled:cursor-wait disabled:opacity-60"
        aria-label={`Edit ${week.label} weighting`}
      >
        {content}
      </button>
    ) : (
      <div className="inline-flex min-h-9 items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 px-3 text-xs">
        {content}
      </div>
    )
  }

  const save = () => {
    if (!valid) return
    onSave(assignmentWeight, numericDiscussionWeight)
    setEditing(false)
  }

  return (
    <div className="flex min-h-9 flex-wrap items-center gap-2 rounded-xl border border-gray-300 bg-white px-2.5 py-1.5 text-xs">
      <span className="font-semibold text-gray-800">{week.label}</span>
      <span className="text-gray-500">Assignment {assignmentWeight}%</span>
      <label className="flex items-center gap-1.5 text-gray-600">
        Discussion
        <input
          type="number"
          min={0}
          max={100}
          step={1}
          value={discussionWeight}
          onChange={(event) => setDiscussionWeight(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setEditing(false)
            if (event.key === 'Enter') save()
          }}
          autoFocus
          className="h-8 w-16 rounded-lg border border-gray-300 bg-white px-2 text-base tabular-nums text-gray-950 outline-none focus:border-gray-500 focus:ring-2 focus:ring-gray-900/10"
          aria-label={`${week.label} discussion weight percentage`}
        />
        %
      </label>
      <button
        type="button"
        disabled={!valid || isSaving}
        onClick={save}
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gray-950 text-white hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-40"
        aria-label={`Save ${week.label} weighting`}
      >
        <Check size={14} />
      </button>
    </div>
  )
}

function GradebookSkeleton() {
  return (
    <div className="space-y-3 p-5" aria-label="Loading course grades">
      {[0, 1, 2, 3, 4].map((row) => (
        <div key={row} className="flex animate-pulse items-center gap-4 py-2">
          <div className="h-9 w-9 rounded-full bg-gray-100" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-36 rounded bg-gray-100" />
            <div className="h-2.5 w-24 rounded bg-gray-100" />
          </div>
          <div className="h-4 w-20 rounded bg-gray-100" />
          <div className="h-4 w-20 rounded bg-gray-100" />
        </div>
      ))}
    </div>
  )
}

export default function CourseGradesLeaderboard({ courseUUID }: { courseUUID: string }) {
  const { t } = useTranslation()
  const session = useLHSession() as any
  const accessToken = session?.data?.tokens?.access_token
  const [searchQuery, setSearchQuery] = useState('')
  const [savingCell, setSavingCell] = useState('')
  const [savingWeight, setSavingWeight] = useState<number | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('rank')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const queryClient = useQueryClient()

  const gradebook = useQuery<GradebookResponse>({
    queryKey: queryKeys.courses.gradeLeaderboard(courseUUID),
    queryFn: () => getCourseGradeLeaderboard(courseUUID, accessToken),
    enabled: !!courseUUID && !!accessToken,
    staleTime: 30_000,
  })

  const discussionMutation = useMutation({
    mutationFn: ({ userId, weekNumber, score }: { userId: number; weekNumber: number; score: number }) =>
      updateCourseDiscussionGrade(courseUUID, userId, weekNumber, score, accessToken),
    onMutate: ({ userId, weekNumber }) => setSavingCell(`${userId}:${weekNumber}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.courses.gradeLeaderboard(courseUUID) }),
    onSettled: () => setSavingCell(''),
  })

  const weightMutation = useMutation({
    mutationFn: ({
      weekNumber,
      assignmentWeight,
      discussionWeight,
    }: {
      weekNumber: number
      assignmentWeight: number
      discussionWeight: number
    }) => updateCourseGradeWeights(
      courseUUID,
      weekNumber,
      assignmentWeight,
      discussionWeight,
      accessToken
    ),
    onMutate: ({ weekNumber }) => setSavingWeight(weekNumber),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.courses.gradeLeaderboard(courseUUID) }),
    onSettled: () => setSavingWeight(null),
  })

  const rows = useMemo(() => {
    const allRows = gradebook.data?.gradebook ?? []
    const query = searchQuery.trim().toLocaleLowerCase()
    const filteredRows = query
      ? allRows.filter((row) =>
        [learnerName(row.user), row.user.username].join(' ').toLocaleLowerCase().includes(query)
      )
      : allRows

    return [...filteredRows].sort((first, second) => {
      const firstValue = rowSortValue(first, sortKey)
      const secondValue = rowSortValue(second, sortKey)

      if (firstValue === null && secondValue === null) return learnerName(first.user).localeCompare(learnerName(second.user))
      if (firstValue === null) return 1
      if (secondValue === null) return -1

      const comparison = typeof firstValue === 'string' && typeof secondValue === 'string'
        ? firstValue.localeCompare(secondValue)
        : Number(firstValue) - Number(secondValue)
      if (comparison !== 0) return sortDirection === 'asc' ? comparison : -comparison

      const rankComparison = (first.rank ?? Number.MAX_SAFE_INTEGER) - (second.rank ?? Number.MAX_SAFE_INTEGER)
      if (rankComparison !== 0) return rankComparison
      return learnerName(first.user).localeCompare(learnerName(second.user))
    })
  }, [gradebook.data?.gradebook, searchQuery, sortDirection, sortKey])

  const weeks = gradebook.data?.weeks ?? []
  const canManage = gradebook.data?.can_manage ?? false

  const handleSort = (nextSortKey: SortKey) => {
    if (nextSortKey === sortKey) {
      setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')
      return
    }
    setSortKey(nextSortKey)
    setSortDirection(nextSortKey === 'rank' || nextSortKey === 'learner' ? 'asc' : 'desc')
  }

  return (
    <section className="mx-auto w-full max-w-[1440px] px-4 py-8 sm:px-8 lg:px-10">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-semibold tracking-[-0.025em] text-gray-950">
            {t('dashboard.courses.grades.leaderboard_title', { defaultValue: 'Course leaderboard' })}
          </h1>
          <p className="mt-2 text-sm leading-6 text-gray-600">
            {t('dashboard.courses.grades.leaderboard_description', {
              defaultValue: 'Cumulative ranking with assignment and discussion results shown separately for every course week.',
            })}
          </p>
          <div className="mt-3 flex items-center gap-1.5 text-xs font-medium text-gray-500">
            <ShieldCheck size={14} aria-hidden="true" />
            {canManage
              ? t('dashboard.courses.grades.staff_access', { defaultValue: 'You can update discussion grades' })
              : t('dashboard.courses.grades.learner_access', { defaultValue: 'Read-only class gradebook' })}
          </div>
        </div>
        <button
          type="button"
          onClick={() => gradebook.refetch()}
          disabled={gradebook.isFetching}
          className="inline-flex min-h-10 items-center justify-center gap-2 self-start rounded-xl border border-gray-200 bg-white px-3.5 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={gradebook.isFetching ? 'animate-spin' : ''} size={16} />
          {t('common.refresh', { defaultValue: 'Refresh' })}
        </button>
      </header>

      <div className="mt-7 grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
          <p className="text-xs font-medium text-gray-500">Learners</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-gray-950">{gradebook.data?.summary.learners ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white px-5 py-4">
          <p className="text-xs font-medium text-gray-500">Course weeks</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-gray-950">{gradebook.data?.summary.weeks ?? 0}</p>
        </div>
      </div>

      <div className="mt-6 overflow-hidden rounded-2xl border border-gray-200 bg-white">
        <div className="flex flex-col gap-3 border-b border-gray-100 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold text-gray-950">
              <GraduationCap size={18} className="text-gray-600" aria-hidden="true" />
              Rankings and weekly results
            </h2>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-gray-500">
              Cumulative rank averages each week&apos;s weighted score. Missing grades in an active column count as zero.
            </p>
            {weeks.length > 0 ? (
              <div className="mt-3 flex flex-wrap items-center gap-2" aria-label="Weekly grade weighting">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-500">
                  <SlidersHorizontal size={14} aria-hidden="true" />
                  Weighting
                </span>
                {weeks.map((week) => (
                  <WeekWeightControl
                    key={week.week_number}
                    week={week}
                    canManage={canManage}
                    isSaving={savingWeight === week.week_number}
                    onSave={(assignmentWeight, discussionWeight) => weightMutation.mutate({
                      weekNumber: week.week_number,
                      assignmentWeight,
                      discussionWeight,
                    })}
                  />
                ))}
              </div>
            ) : null}
            {weightMutation.isError ? (
              <p className="mt-2 text-xs font-medium text-rose-600" role="alert">
                The weekly weighting could not be saved. Please try again.
              </p>
            ) : null}
          </div>
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
            <div className="flex gap-2 md:hidden">
              <label className="min-w-0 flex-1">
                <span className="sr-only">Sort leaderboard</span>
                <select
                  value={sortKey}
                  onChange={(event) => handleSort(event.target.value as SortKey)}
                  className="h-10 w-full rounded-xl border border-gray-200 bg-gray-50 px-3 text-base text-gray-900 outline-none focus:border-gray-400 focus:bg-white focus:ring-2 focus:ring-gray-900/10"
                >
                  <option value="rank">Rank</option>
                  <option value="learner">Learner</option>
                  <option value="cumulative">Cumulative score</option>
                  {weeks.flatMap((week) => [
                    <option key={`${week.week_number}:assignment`} value={scoreSortKey(week.week_number, 'assignment')}>
                      {week.label} assignment
                    </option>,
                    <option key={`${week.week_number}:discussion`} value={scoreSortKey(week.week_number, 'discussion')}>
                      {week.label} discussion
                    </option>,
                  ])}
                </select>
              </label>
              <button
                type="button"
                onClick={() => setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-1"
                aria-label={`Sort ${sortDirection === 'asc' ? 'descending' : 'ascending'}`}
              >
                {sortDirection === 'asc' ? <ArrowUp size={16} /> : <ArrowDown size={16} />}
              </button>
            </div>
            <label className="relative block w-full sm:w-72">
              <span className="sr-only">Search learners</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search learners"
                className="h-10 w-full rounded-xl border border-gray-200 bg-gray-50 pl-9 pr-3 text-sm text-gray-900 outline-none transition-colors placeholder:text-gray-400 focus:border-gray-400 focus:bg-white focus:ring-2 focus:ring-gray-900/10"
              />
            </label>
          </div>
        </div>

        {gradebook.isLoading ? <GradebookSkeleton /> : null}

        {gradebook.isError ? (
          <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
            <AlertCircle className="text-rose-500" size={28} aria-hidden="true" />
            <h3 className="mt-3 text-sm font-semibold text-gray-950">Course grades could not be loaded</h3>
            <p className="mt-1 max-w-md text-sm text-gray-500">{gradebookErrorDescription(gradebook.error)}</p>
            <button
              type="button"
              onClick={() => gradebook.refetch()}
              className="mt-4 rounded-xl bg-gray-950 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
            >
              Try again
            </button>
          </div>
        ) : null}

        {!gradebook.isLoading && !gradebook.isError && rows.length === 0 ? (
          <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
            <GraduationCap className="text-gray-300" size={30} aria-hidden="true" />
            <h3 className="mt-3 text-sm font-semibold text-gray-950">
              {searchQuery ? 'No learners match this search' : 'No gradebook entries yet'}
            </h3>
            <p className="mt-1 max-w-md text-sm text-gray-500">
              {searchQuery ? 'Try another name or username.' : 'Learners appear here when assignments are associated with them.'}
            </p>
          </div>
        ) : null}

        {!gradebook.isLoading && !gradebook.isError && rows.length > 0 ? (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full border-separate border-spacing-0" style={{ minWidth: `${500 + weeks.length * 280}px` }}>
                <thead>
                  <tr className="bg-gray-50/90 text-left text-xs font-semibold text-gray-700">
                    <th
                      rowSpan={2}
                      scope="col"
                      aria-sort={sortKey === 'rank' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                      className="sticky left-0 z-30 w-[72px] border-b border-r border-gray-200 bg-gray-50 px-3 py-3 text-center"
                    >
                      <SortButton
                        label="Rank"
                        sortKey="rank"
                        activeSortKey={sortKey}
                        direction={sortDirection}
                        onSort={handleSort}
                        centered
                      />
                    </th>
                    <th
                      rowSpan={2}
                      scope="col"
                      aria-sort={sortKey === 'learner' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                      className="sticky left-[72px] z-20 w-[280px] border-b border-r border-gray-200 bg-gray-50 px-4 py-3"
                    >
                      <SortButton
                        label="Learner"
                        sortKey="learner"
                        activeSortKey={sortKey}
                        direction={sortDirection}
                        onSort={handleSort}
                      />
                    </th>
                    <th
                      rowSpan={2}
                      scope="col"
                      aria-sort={sortKey === 'cumulative' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                      className="w-[148px] border-b border-r border-gray-200 px-3 py-3"
                    >
                      <SortButton
                        label="Cumulative"
                        sortKey="cumulative"
                        activeSortKey={sortKey}
                        direction={sortDirection}
                        onSort={handleSort}
                      />
                    </th>
                    {weeks.map((week) => (
                      <th key={week.week_number} colSpan={2} className="border-b border-r border-gray-200 px-4 py-3 text-center last:border-r-0">
                        {week.label}
                      </th>
                    ))}
                  </tr>
                  <tr className="bg-gray-50/70 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                    {weeks.map((week) => (
                      <React.Fragment key={week.week_number}>
                        <th
                          scope="col"
                          aria-sort={sortKey === scoreSortKey(week.week_number, 'assignment') ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                          className="w-[140px] border-b border-r border-gray-200 px-2.5 py-2"
                        >
                          <SortButton
                            label={`Assignment ${week.assignment_weight}%`}
                            sortKey={scoreSortKey(week.week_number, 'assignment')}
                            activeSortKey={sortKey}
                            direction={sortDirection}
                            onSort={handleSort}
                            ariaLabel={`Sort by ${week.label} assignment score`}
                          />
                        </th>
                        <th
                          scope="col"
                          aria-sort={sortKey === scoreSortKey(week.week_number, 'discussion') ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                          className="w-[140px] border-b border-r border-gray-200 px-2.5 py-2 last:border-r-0"
                        >
                          <SortButton
                            label={`Discussion ${week.discussion_weight}%`}
                            sortKey={scoreSortKey(week.week_number, 'discussion')}
                            activeSortKey={sortKey}
                            direction={sortDirection}
                            onSort={handleSort}
                            ariaLabel={`Sort by ${week.label} discussion score`}
                          />
                        </th>
                      </React.Fragment>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.user.id} className="group hover:bg-gray-50/60">
                      <td className="sticky left-0 z-20 border-b border-r border-gray-100 bg-white px-3 py-4 text-center group-hover:bg-gray-50">
                        <span className="inline-flex min-w-9 items-center justify-center rounded-lg bg-gray-100 px-2 py-1 text-sm font-semibold tabular-nums text-gray-800">
                          {row.rank ? `#${row.rank}` : '—'}
                        </span>
                      </td>
                      <td className="sticky left-[72px] z-10 border-b border-r border-gray-100 bg-white px-4 py-4 group-hover:bg-gray-50">
                        <LearnerIdentity user={row.user} />
                      </td>
                      <td className="border-b border-r border-gray-100 px-3 py-4">
                        <GradeValue
                          percentage={row.cumulative_percentage}
                          detail={cumulativeDetail(row)}
                        />
                      </td>
                      {weeks.map((week) => {
                        const weekGrade = row.weeks[String(week.week_number)]
                        const assignment = weekGrade?.assignment
                        const discussion = weekGrade?.discussion ?? null
                        return (
                          <React.Fragment key={week.week_number}>
                            <td className="border-b border-r border-gray-100 px-4 py-4">
                              <GradeValue
                                percentage={assignment?.percentage}
                                detail={assignment?.assigned_count ? `${assignment.graded_count}/${assignment.assigned_count} graded` : undefined}
                              />
                            </td>
                            <td className="border-b border-r border-gray-100 px-4 py-4 last:border-r-0">
                              {canManage ? (
                                <DiscussionGradeEditor
                                  grade={discussion}
                                  isSaving={savingCell === `${row.user.id}:${week.week_number}`}
                                  onSave={(score) => discussionMutation.mutate({ userId: row.user.id, weekNumber: week.week_number, score })}
                                />
                              ) : (
                                <GradeValue
                                  percentage={discussion?.percentage}
                                  detail={discussion ? `${discussion.score} / ${discussion.max_score} points` : undefined}
                                />
                              )}
                            </td>
                          </React.Fragment>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="divide-y divide-gray-100 md:hidden">
              {rows.map((row) => (
                <article key={row.user.id} className="px-4 py-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <p className="mb-2 text-xs font-semibold tabular-nums text-gray-500">
                        {row.rank ? `Rank #${row.rank}` : 'Not ranked'}
                      </p>
                      <LearnerIdentity user={row.user} />
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="mb-1 flex items-center justify-end gap-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                        <Trophy size={12} aria-hidden="true" />
                        Cumulative
                      </p>
                      <GradeValue
                        percentage={row.cumulative_percentage}
                        detail={cumulativeDetail(row)}
                      />
                    </div>
                  </div>
                  <div className="mt-4 space-y-3">
                    {weeks.map((week) => {
                      const weekGrade = row.weeks[String(week.week_number)]
                      const discussion = weekGrade?.discussion ?? null
                      return (
                        <div key={week.week_number} className="rounded-xl border border-gray-200">
                          <h3 className="border-b border-gray-100 bg-gray-50 px-3 py-2 text-xs font-semibold text-gray-700">{week.label}</h3>
                          <div className="grid grid-cols-2 divide-x divide-gray-100">
                            <div className="min-w-0 p-3">
                              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                                Assignment · {week.assignment_weight}%
                              </p>
                              <GradeValue percentage={weekGrade?.assignment?.percentage} />
                            </div>
                            <div className="min-w-0 p-3">
                              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                                Discussion · {week.discussion_weight}%
                              </p>
                              {canManage ? (
                                <DiscussionGradeEditor
                                  grade={discussion}
                                  isSaving={savingCell === `${row.user.id}:${week.week_number}`}
                                  onSave={(score) => discussionMutation.mutate({ userId: row.user.id, weekNumber: week.week_number, score })}
                                />
                              ) : (
                                <GradeValue percentage={discussion?.percentage} />
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </article>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </section>
  )
}
