import React from 'react'

import CourseGradesLeaderboard from '@components/Dashboard/Pages/Course/CourseGradesLeaderboard/CourseGradesLeaderboard'


export default async function CourseGradesPage({
  params,
}: {
  params: Promise<{ orgslug: string; courseuuid: string }>
}) {
  const { courseuuid } = await params
  return <CourseGradesLeaderboard courseUUID={courseuuid} />
}
