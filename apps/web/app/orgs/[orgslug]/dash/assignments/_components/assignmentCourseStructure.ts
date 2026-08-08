import { getCourseMetadata } from '@services/courses/courses'

/**
 * Load the full course shape required by the assignment creation wizard.
 *
 * The basic `/courses/{uuid}` response deliberately omits chapters. Using it
 * here made every course look chapterless and blocked assignment creation from
 * the global Assignments dashboard.
 */
export function loadAssignmentCourseStructure(
  courseUuid: string,
  accessToken: string | null | undefined
) {
  return getCourseMetadata(courseUuid, null, accessToken, {
    slim: true,
    withUnpublishedActivities: true,
  })
}
