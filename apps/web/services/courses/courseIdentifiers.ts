/**
 * Course URLs use the clean UUID, but the API stores course resources with a
 * `course_` prefix. Gradebook calls can originate from either learner or staff
 * routes, so always send the canonical resource UUID to the API.
 */
export function toCourseResourceUuid(courseUuid: string): string {
  const normalized = courseUuid.trim()
  return normalized.startsWith('course_') ? normalized : `course_${normalized}`
}
