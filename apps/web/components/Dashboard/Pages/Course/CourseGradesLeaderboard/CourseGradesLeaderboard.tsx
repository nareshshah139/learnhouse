'use client'

import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, LockKeyhole, Medal, RefreshCw, Search, Trophy } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { queryKeys } from '@/lib/query/keys'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import UserAvatar from '@components/Objects/UserAvatar'
import { getCourseGradeLeaderboard } from '@services/courses/courses'
import { getUserAvatarMediaDirectory } from '@services/media/media'

type LeaderboardUser = {
  id: number
  user_uuid: string
  username: string
  first_name: string
  last_name: string
  avatar_image: string
}

type LeaderboardRow = {
  rank: number
  user: LeaderboardUser
  average_percentage: number
  graded_assignments: number
  assigned_assignments: number
  coverage_percentage: number
}

type LeaderboardResponse = {
  course_uuid: string
  summary: {
    learners: number
    course_average_percentage: number
    top_score_percentage: number
    graded_submissions: number
    course_assignments: number
  }
  rankings: LeaderboardRow[]
}

const medalStyles: Record<number, string> = {
  1: 'text-amber-500',
  2: 'text-slate-400',
  3: 'text-orange-500',
}

const formatPercentage = (value: number) => `${value.toFixed(2).replace(/\.00$/, '')}%`

function learnerName(user: LeaderboardUser) {
  return `${user.first_name || ''} ${user.last_name || ''}`.trim() || `@${user.username}`
}

function scoreColor(score: number) {
  if (score >= 90) return 'bg-emerald-500'
  if (score >= 75) return 'bg-sky-500'
  if (score >= 60) return 'bg-amber-500'
  return 'bg-rose-500'
}

function Rank({ rank }: { rank: number }) {
  if (rank <= 3) {
    return (
      <div className="flex w-8 items-center justify-center" aria-label={`Rank ${rank}`}>
        <Medal className={medalStyles[rank]} fill="currentColor" size={22} strokeWidth={1.6} />
      </div>
    )
  }
  return <span className="block w-8 text-center text-sm font-semibold text-gray-500">{rank}</span>
}

function LearnerIdentity({ user }: { user: LeaderboardUser }) {
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

function LeaderboardSkeleton() {
  return (
    <div className="space-y-3 p-5" aria-label="Loading course grades">
      {[0, 1, 2, 3, 4].map((row) => (
        <div key={row} className="flex animate-pulse items-center gap-4 py-2">
          <div className="h-6 w-8 rounded bg-gray-100" />
          <div className="h-9 w-9 rounded-full bg-gray-100" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-36 rounded bg-gray-100" />
            <div className="h-2.5 w-24 rounded bg-gray-100" />
          </div>
          <div className="h-4 w-14 rounded bg-gray-100" />
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

  const leaderboard = useQuery<LeaderboardResponse>({
    queryKey: queryKeys.courses.gradeLeaderboard(courseUUID),
    queryFn: () => getCourseGradeLeaderboard(courseUUID, accessToken),
    enabled: !!courseUUID && !!accessToken,
    staleTime: 30_000,
  })

  const rows = useMemo(() => {
    const allRows = leaderboard.data?.rankings ?? []
    const query = searchQuery.trim().toLocaleLowerCase()
    if (!query) return allRows
    return allRows.filter((row) => {
      const user = row.user
      return [learnerName(user), user.username]
        .join(' ')
        .toLocaleLowerCase()
        .includes(query)
    })
  }, [leaderboard.data?.rankings, searchQuery])

  const summary = leaderboard.data?.summary

  return (
    <section className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-8 lg:px-10">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-semibold tracking-[-0.025em] text-gray-950">
            {t('dashboard.courses.grades.title', { defaultValue: 'Course grades' })}
          </h1>
          <p className="mt-2 text-sm leading-6 text-gray-600">
            {t('dashboard.courses.grades.description', {
              defaultValue: 'Rankings use each learner’s average normalized percentage across graded assignments.',
            })}
          </p>
          <div className="mt-3 flex items-center gap-1.5 text-xs font-medium text-gray-500">
            <LockKeyhole size={14} aria-hidden="true" />
            {t('dashboard.courses.grades.private', {
              defaultValue: 'Private to course graders and organization administrators',
            })}
          </div>
        </div>
        <button
          type="button"
          onClick={() => leaderboard.refetch()}
          disabled={leaderboard.isFetching}
          className="inline-flex min-h-10 items-center justify-center gap-2 self-start rounded-xl border border-gray-200 bg-white px-3.5 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={leaderboard.isFetching ? 'animate-spin' : ''} size={16} />
          {t('common.refresh', { defaultValue: 'Refresh' })}
        </button>
      </header>

      <div className="mt-7 overflow-hidden rounded-2xl border border-gray-200 bg-white">
        <div className="grid grid-cols-2 divide-x divide-y divide-gray-100 sm:grid-cols-4 sm:divide-y-0">
          {[
            {
              label: t('dashboard.courses.grades.learners', { defaultValue: 'Ranked learners' }),
              value: summary?.learners ?? 0,
            },
            {
              label: t('dashboard.courses.grades.average', { defaultValue: 'Course average' }),
              value: formatPercentage(summary?.course_average_percentage ?? 0),
            },
            {
              label: t('dashboard.courses.grades.top_score', { defaultValue: 'Top score' }),
              value: formatPercentage(summary?.top_score_percentage ?? 0),
            },
            {
              label: t('dashboard.courses.grades.graded_work', { defaultValue: 'Graded submissions' }),
              value: summary?.graded_submissions ?? 0,
            },
          ].map((stat) => (
            <div key={stat.label} className="px-4 py-5 sm:px-6">
              <p className="text-xs font-medium text-gray-500">{stat.label}</p>
              <p className="mt-1.5 text-xl font-semibold tracking-[-0.02em] text-gray-950">{stat.value}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 overflow-hidden rounded-2xl border border-gray-200 bg-white">
        <div className="flex flex-col gap-3 border-b border-gray-100 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold text-gray-950">
              <Trophy size={18} className="text-amber-500" aria-hidden="true" />
              {t('dashboard.courses.grades.leaderboard', { defaultValue: 'Leaderboard' })}
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              {t('dashboard.courses.grades.coverage_note', {
                defaultValue: 'Coverage shows graded assignments out of the assignments currently associated with each learner.',
              })}
            </p>
          </div>
          <label className="relative block w-full sm:w-72">
            <span className="sr-only">
              {t('dashboard.courses.grades.search', { defaultValue: 'Search learners' })}
            </span>
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t('dashboard.courses.grades.search', { defaultValue: 'Search learners' })}
              className="h-10 w-full rounded-xl border border-gray-200 bg-gray-50 pl-9 pr-3 text-sm text-gray-900 outline-none transition-colors placeholder:text-gray-400 focus:border-gray-400 focus:bg-white focus:ring-2 focus:ring-gray-900/10"
            />
          </label>
        </div>

        {leaderboard.isLoading ? <LeaderboardSkeleton /> : null}

        {leaderboard.isError ? (
          <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
            <AlertCircle className="text-rose-500" size={28} aria-hidden="true" />
            <h3 className="mt-3 text-sm font-semibold text-gray-950">
              {t('dashboard.courses.grades.error_title', { defaultValue: 'Course grades could not be loaded' })}
            </h3>
            <p className="mt-1 max-w-md text-sm text-gray-500">
              {t('dashboard.courses.grades.error_description', {
                defaultValue: 'Check your connection and try refreshing the leaderboard.',
              })}
            </p>
            <button
              type="button"
              onClick={() => leaderboard.refetch()}
              className="mt-4 rounded-xl bg-gray-950 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2"
            >
              {t('common.try_again', { defaultValue: 'Try again' })}
            </button>
          </div>
        ) : null}

        {!leaderboard.isLoading && !leaderboard.isError && rows.length === 0 ? (
          <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
            <Trophy className="text-gray-300" size={30} aria-hidden="true" />
            <h3 className="mt-3 text-sm font-semibold text-gray-950">
              {searchQuery
                ? t('dashboard.courses.grades.no_search_results', { defaultValue: 'No learners match this search' })
                : t('dashboard.courses.grades.empty_title', { defaultValue: 'No graded work yet' })}
            </h3>
            <p className="mt-1 max-w-md text-sm text-gray-500">
              {searchQuery
                ? t('dashboard.courses.grades.no_search_description', { defaultValue: 'Try another name or username.' })
                : t('dashboard.courses.grades.empty_description', {
                    defaultValue: 'Learners appear here after at least one assignment has been graded.',
                  })}
            </p>
          </div>
        ) : null}

        {!leaderboard.isLoading && !leaderboard.isError && rows.length > 0 ? (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[720px] border-collapse">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50/80 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-500">
                    <th className="w-20 px-5 py-3">{t('dashboard.courses.grades.rank', { defaultValue: 'Rank' })}</th>
                    <th className="px-3 py-3">{t('dashboard.courses.grades.learner', { defaultValue: 'Learner' })}</th>
                    <th className="w-64 px-3 py-3">{t('dashboard.courses.grades.score', { defaultValue: 'Average score' })}</th>
                    <th className="w-44 px-5 py-3 text-right">{t('dashboard.courses.grades.coverage', { defaultValue: 'Grading coverage' })}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {rows.map((row) => (
                    <tr key={row.user.id} className="transition-colors hover:bg-gray-50/70">
                      <td className="px-5 py-4"><Rank rank={row.rank} /></td>
                      <td className="px-3 py-4"><LearnerIdentity user={row.user} /></td>
                      <td className="px-3 py-4">
                        <div className="flex items-center gap-3">
                          <span className="w-14 text-right text-sm font-semibold tabular-nums text-gray-950">
                            {formatPercentage(row.average_percentage)}
                          </span>
                          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                            <div
                              className={`h-full rounded-full ${scoreColor(row.average_percentage)}`}
                              style={{ width: `${row.average_percentage}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-4 text-right">
                        <span className="text-sm font-semibold tabular-nums text-gray-800">
                          {row.graded_assignments}/{row.assigned_assignments}
                        </span>
                        <span className="ml-2 text-xs text-gray-400">
                          {formatPercentage(row.coverage_percentage)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="divide-y divide-gray-100 md:hidden">
              {rows.map((row) => (
                <article key={row.user.id} className="px-4 py-4">
                  <div className="flex items-center gap-3">
                    <Rank rank={row.rank} />
                    <div className="min-w-0 flex-1"><LearnerIdentity user={row.user} /></div>
                    <span className="text-sm font-semibold tabular-nums text-gray-950">
                      {formatPercentage(row.average_percentage)}
                    </span>
                  </div>
                  <div className="ml-11 mt-3 flex items-center gap-3">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
                      <div
                        className={`h-full rounded-full ${scoreColor(row.average_percentage)}`}
                        style={{ width: `${row.average_percentage}%` }}
                      />
                    </div>
                    <span className="text-xs tabular-nums text-gray-500">
                      {row.graded_assignments}/{row.assigned_assignments} graded
                    </span>
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
