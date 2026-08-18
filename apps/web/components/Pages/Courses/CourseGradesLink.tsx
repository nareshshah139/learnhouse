import Link from 'next/link'
import { ArrowRight, GraduationCap } from 'lucide-react'

import { getUriWithOrg } from '@services/config/config'

type CourseGradesLinkVariant = 'card' | 'toolbar' | 'icon'

interface CourseGradesLinkProps {
  orgslug: string
  courseuuid: string
  variant?: CourseGradesLinkVariant
  label?: string
}

const variantClasses: Record<CourseGradesLinkVariant, string> = {
  card: 'group flex min-h-12 w-full items-center justify-between rounded-lg bg-white px-4 py-3 text-sm font-semibold text-gray-900 shadow-md shadow-gray-300/25 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2',
  toolbar: 'inline-flex min-h-10 items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-50 hover:text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2',
  icon: 'inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-900 focus-visible:ring-offset-2',
}

export default function CourseGradesLink({
  orgslug,
  courseuuid,
  variant = 'toolbar',
  label,
}: CourseGradesLinkProps) {
  const cleanCourseUuid = courseuuid.replace(/^course_/, '')
  const visibleLabel = label ?? (variant === 'card' ? 'View course grades' : 'Grades')

  return (
    <Link
      href={getUriWithOrg(orgslug, `/course/${cleanCourseUuid}/grades`)}
      aria-label="View course grades"
      title={variant === 'icon' ? 'View course grades' : undefined}
      className={variantClasses[variant]}
    >
      <span className={variant === 'icon' ? 'sr-only' : 'inline-flex min-w-0 items-center gap-2'}>
        {variant !== 'icon' ? <GraduationCap size={18} className="shrink-0 text-gray-500" aria-hidden="true" /> : null}
        {visibleLabel}
      </span>
      {variant === 'icon' ? (
        <GraduationCap size={18} aria-hidden="true" />
      ) : variant === 'card' ? (
        <ArrowRight
          size={16}
          className="shrink-0 text-gray-400 transition-transform group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      ) : null}
    </Link>
  )
}
