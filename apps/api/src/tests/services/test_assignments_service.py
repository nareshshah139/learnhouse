"""Tests for src/services/courses/activities/assignments.py (CRUD operations).

Covers the newly-async CRUD functions that were migrated from sync SQLModel
Session to AsyncSession in this PR:
  create_assignment, read_assignment, read_assignment_from_activity_uuid,
  update_assignment, delete_assignment, delete_assignment_from_activity_uuid,
  create_assignment_task, read_assignment_tasks, read_assignment_task,
  update_assignment_task, delete_assignment_task,
  handle_assignment_task_submission, read_assignment_submissions,
  read_user_assignment_submissions, read_user_assignment_submissions_me,
  update_assignment_submission, delete_assignment_submission,
  grade_assignment_submission, get_grade_assignment_submission,
  mark_activity_as_done_for_user, get_assignments_from_course,
  get_course_grade_leaderboard,
  _block_api_tokens.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from src.db.courses.assignments import (
    Assignment,
    AssignmentCreate,
    AssignmentRead,
    AssignmentTask,
    AssignmentTaskCreate,
    AssignmentTaskRead,
    AssignmentTaskSubmission,
    AssignmentTaskSubmissionCreate,
    AssignmentTaskSubmissionRead,
    AssignmentTaskSubmissionUpdate,
    AssignmentTaskTypeEnum,
    AssignmentUpdate,
    AssignmentUserSubmission,
    AssignmentUserSubmissionCreate,
    AssignmentUserSubmissionRead,
    AssignmentUserSubmissionStatus,
    GradingTypeEnum,
)
from src.db.courses.certifications import CertificateUser, Certifications
from src.db.courses.course_discussion_grades import CourseDiscussionGrade
from src.db.trail_runs import TrailRun
from src.db.trail_steps import TrailStep
from src.db.trails import Trail
from src.db.users import APITokenUser, User
from src.services.courses.activities.assignments import (
    _block_api_tokens,
    _check_number_answer,
    _is_assignment_past_due,
    create_assignment,
    create_assignment_submission,
    create_assignment_task,
    delete_assignment,
    delete_assignment_from_activity_uuid,
    delete_assignment_submission,
    delete_assignment_task,
    delete_assignment_task_submission,
    get_assignments_from_course,
    get_course_grade_leaderboard,
    get_grade_assignment_submission,
    grade_assignment_submission,
    handle_assignment_task_submission,
    mark_activity_as_done_for_user,
    put_assignment_task_reference_file,
    put_assignment_task_submission_file,
    read_assignment,
    read_assignment_from_activity_uuid,
    read_assignment_submissions,
    read_assignment_task,
    read_assignment_task_submissions,
    read_assignment_tasks,
    read_user_assignment_submissions,
    read_user_assignment_submissions_me,
    read_user_assignment_task_submissions,
    read_user_assignment_task_submissions_me,
    read_user_assignment_task_submissions_me_batch,
    retry_assignment_submission,
    update_assignment,
    update_assignment_submission,
    update_assignment_task,
    update_assignment_task_submission,
    upsert_course_discussion_grade,
    upsert_course_grade_weights,
)

# ---------------------------------------------------------------------------
# Module-level patches applied to all tests
# ---------------------------------------------------------------------------

_PATCH_RBAC = "src.services.courses.activities.assignments.check_resource_access"
_PATCH_LIMITS = "src.services.courses.activities.assignments.check_limits_with_usage"
_PATCH_INCREASE = "src.services.courses.activities.assignments.increase_feature_usage"
_PATCH_DECREASE = "src.services.courses.activities.assignments.decrease_feature_usage"
_PATCH_AUTH_ROLES = (
    "src.services.courses.activities.assignments.authorization_verify_based_on_roles"
)
_PATCH_DISPATCH = "src.services.courses.activities.assignments.dispatch_webhooks"
_PATCH_TRACK = "src.services.courses.activities.assignments.track"
_PATCH_CERT = (
    "src.services.courses.activities.assignments."
    "check_course_completion_and_create_certificate"
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------












async def _make_trail(db, org_id, course_id, activity_id, user_id):
    trail = Trail(
        org_id=org_id,
        user_id=user_id,
        trail_uuid="trail_assign_test",
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(trail)
    await db.commit()
    await db.refresh(trail)
    run = TrailRun(
        trail_id=trail.id,
        course_id=course_id,
        org_id=org_id,
        user_id=user_id,
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    step = TrailStep(
        complete=False,
        teacher_verified=False,
        grade="",
        trailrun_id=run.id,
        trail_id=trail.id,
        activity_id=activity_id,
        course_id=course_id,
        org_id=org_id,
        user_id=user_id,
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    return trail, run, step


# ---------------------------------------------------------------------------
# _block_api_tokens
# ---------------------------------------------------------------------------


class TestBlockApiTokens:
    def test_raises_403_for_api_token_user(self):
        token_user = APITokenUser(id=1, org_id=1)
        with pytest.raises(HTTPException) as exc:
            _block_api_tokens(token_user)
        assert exc.value.status_code == 403

    def test_passes_for_public_user(self, regular_user):
        _block_api_tokens(regular_user)  # should not raise


# ---------------------------------------------------------------------------
# create_assignment
# ---------------------------------------------------------------------------


class TestCreateAssignment:
    async def test_raises_404_when_course_not_found(
        self, mock_request, db, org, chapter, activity, admin_user
    ):
        obj = AssignmentCreate(
            title="T",
            description="D",
            due_date="2030-01-01",
            grading_type=GradingTypeEnum.NUMERIC,
            org_id=org.id,
            course_id=9999,
            chapter_id=chapter.id,
            activity_id=activity.id,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_LIMITS, new_callable=AsyncMock), \
             patch(_PATCH_INCREASE, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await create_assignment(mock_request, obj, admin_user, db)
        assert exc.value.status_code == 404

    async def test_creates_assignment_successfully(
        self, mock_request, db, org, course, chapter, activity, admin_user
    ):
        obj = AssignmentCreate(
            title="New Assignment",
            description="Desc",
            due_date="2030-01-01",
            grading_type=GradingTypeEnum.NUMERIC,
            org_id=org.id,
            course_id=course.id,
            chapter_id=chapter.id,
            activity_id=activity.id,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_LIMITS, new_callable=AsyncMock), \
             patch(_PATCH_INCREASE, new_callable=AsyncMock):
            result = await create_assignment(mock_request, obj, admin_user, db)
        assert isinstance(result, AssignmentRead)
        assert result.title == "New Assignment"

    async def test_rejects_activity_from_another_course(
        self, mock_request, db, org, course, chapter, activity, admin_user
    ):
        # SECURITY: RBAC only authorizes `course`, so a client-supplied activity
        # that belongs to a DIFFERENT course must be rejected (400) rather than
        # creating a dangling / cross-course assignment.
        from src.db.courses.activities import (
            Activity, ActivityTypeEnum, ActivitySubTypeEnum,
        )
        foreign = Activity(
            id=7777, name="Foreign", activity_uuid="activity_foreign_7777",
            activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
            activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE,
            published=True, org_id=org.id, course_id=course.id + 999, content={},
            creation_date="2024-01-01", update_date="2024-01-01",
        )
        db.add(foreign)
        await db.commit()

        obj = AssignmentCreate(
            title="T", description="D", due_date="2030-01-01",
            grading_type=GradingTypeEnum.NUMERIC, org_id=org.id,
            course_id=course.id, chapter_id=chapter.id, activity_id=foreign.id,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_LIMITS, new_callable=AsyncMock), \
             patch(_PATCH_INCREASE, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await create_assignment(mock_request, obj, admin_user, db)
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# read_assignment
# ---------------------------------------------------------------------------


class TestReadAssignment:
    async def test_raises_404_when_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await read_assignment(mock_request, "nonexistent", admin_user, db)
        assert exc.value.status_code == 404

    async def test_returns_assignment_read(
        self, mock_request, db, assignment, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await read_assignment(
                mock_request, assignment.assignment_uuid, admin_user, db
            )
        assert isinstance(result, AssignmentRead)
        assert result.assignment_uuid == assignment.assignment_uuid


# ---------------------------------------------------------------------------
# read_assignment_from_activity_uuid
# ---------------------------------------------------------------------------


class TestReadAssignmentFromActivityUuid:
    async def test_raises_404_when_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await read_assignment_from_activity_uuid(
                    mock_request, "bad-uuid", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_returns_assignment_for_activity(
        self, mock_request, db, assignment, activity, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await read_assignment_from_activity_uuid(
                mock_request, activity.activity_uuid, admin_user, db
            )
        assert isinstance(result, AssignmentRead)
        assert result.activity_uuid == activity.activity_uuid


# ---------------------------------------------------------------------------
# update_assignment
# ---------------------------------------------------------------------------


class TestUpdateAssignment:
    async def test_raises_404_when_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await update_assignment(
                    mock_request, "nonexistent", AssignmentUpdate(title="X"), admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_updates_assignment_title(
        self, mock_request, db, assignment, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await update_assignment(
                mock_request,
                assignment.assignment_uuid,
                AssignmentUpdate(title="Updated Title"),
                admin_user,
                db,
            )
        assert result.title == "Updated Title"


# ---------------------------------------------------------------------------
# delete_assignment
# ---------------------------------------------------------------------------


class TestDeleteAssignment:
    async def test_raises_404_when_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DECREASE, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await delete_assignment(mock_request, "nonexistent", admin_user, db)
        assert exc.value.status_code == 404

    async def test_deletes_assignment(
        self, mock_request, db, assignment, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DECREASE, new_callable=AsyncMock):
            result = await delete_assignment(
                mock_request, assignment.assignment_uuid, admin_user, db
            )
        assert result["message"] == "Assignment deleted"
        remaining = (await db.execute(
            select(Assignment).where(Assignment.id == assignment.id)
        )).scalars().first()
        assert remaining is None


# ---------------------------------------------------------------------------
# delete_assignment_from_activity_uuid
# ---------------------------------------------------------------------------


class TestDeleteAssignmentFromActivityUuid:
    async def test_raises_404_when_activity_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DECREASE, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await delete_assignment_from_activity_uuid(
                    mock_request, "nonexistent-activity", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, activity, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DECREASE, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await delete_assignment_from_activity_uuid(
                    mock_request, activity.activity_uuid, admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_deletes_assignment_by_activity_uuid(
        self, mock_request, db, assignment, activity, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DECREASE, new_callable=AsyncMock):
            result = await delete_assignment_from_activity_uuid(
                mock_request, activity.activity_uuid, admin_user, db
            )
        assert result["message"] == "Assignment deleted"


# ---------------------------------------------------------------------------
# create_assignment_task
# ---------------------------------------------------------------------------


class TestCreateAssignmentTask:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user
    ):
        obj = AssignmentTaskCreate(
            title="T",
            description="D",
            hint="",
            assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
            contents={},
            max_grade_value=10,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await create_assignment_task(mock_request, "nonexistent", obj, admin_user, db)
        assert exc.value.status_code == 404

    def test_negative_max_grade_value_is_rejected(self):
        # A negative max would subtract from the assignment total and could hand
        # out a certificate on a vacuous pass; the request models must reject it.
        from pydantic import ValidationError
        from src.db.courses.assignments import AssignmentTaskUpdate
        with pytest.raises(ValidationError):
            AssignmentTaskCreate(
                title="T", description="D", hint="",
                assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
                contents={}, max_grade_value=-5,
            )
        with pytest.raises(ValidationError):
            AssignmentTaskUpdate(max_grade_value=-1)

    async def test_creates_task_successfully(
        self, mock_request, db, assignment, admin_user
    ):
        obj = AssignmentTaskCreate(
            title="New Task",
            description="Desc",
            hint="",
            assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
            contents={"prompt": "x"},
            max_grade_value=50,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await create_assignment_task(
                mock_request, assignment.assignment_uuid, obj, admin_user, db
            )
        assert isinstance(result, AssignmentTaskRead)
        assert result.title == "New Task"


# ---------------------------------------------------------------------------
# read_assignment_tasks
# ---------------------------------------------------------------------------


class TestReadAssignmentTasks:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await read_assignment_tasks(mock_request, "nonexistent", admin_user, db)
        assert exc.value.status_code == 404

    async def test_returns_task_list(
        self, mock_request, db, assignment, assignment_task, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await read_assignment_tasks(
                mock_request, assignment.assignment_uuid, admin_user, db
            )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].assignment_task_uuid == assignment_task.assignment_task_uuid


# ---------------------------------------------------------------------------
# read_assignment_task
# ---------------------------------------------------------------------------


class TestReadAssignmentTask:
    async def test_raises_404_when_task_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await read_assignment_task(mock_request, "nonexistent", admin_user, db)
        assert exc.value.status_code == 404

    async def test_returns_task(
        self, mock_request, db, assignment_task, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await read_assignment_task(
                mock_request, assignment_task.assignment_task_uuid, admin_user, db
            )
        assert isinstance(result, AssignmentTaskRead)
        assert result.assignment_task_uuid == assignment_task.assignment_task_uuid


# ---------------------------------------------------------------------------
# update_assignment_task
# ---------------------------------------------------------------------------


class TestUpdateAssignmentTask:
    async def test_raises_404_when_task_not_found(
        self, mock_request, db, admin_user
    ):
        from src.db.courses.assignments import AssignmentTaskUpdate
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await update_assignment_task(
                    mock_request, "nonexistent", AssignmentTaskUpdate(title="X"), admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_updates_task_title(
        self, mock_request, db, assignment_task, admin_user
    ):
        from src.db.courses.assignments import AssignmentTaskUpdate
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await update_assignment_task(
                mock_request,
                assignment_task.assignment_task_uuid,
                AssignmentTaskUpdate(title="Updated Task"),
                admin_user,
                db,
            )
        assert result.title == "Updated Task"


# ---------------------------------------------------------------------------
# delete_assignment_task
# ---------------------------------------------------------------------------


class TestDeleteAssignmentTask:
    async def test_raises_404_when_task_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await delete_assignment_task(mock_request, "nonexistent", admin_user, db)
        assert exc.value.status_code == 404

    async def test_deletes_task(
        self, mock_request, db, assignment_task, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await delete_assignment_task(
                mock_request, assignment_task.assignment_task_uuid, admin_user, db
            )
        assert result["message"] == "Assignment Task deleted"


# ---------------------------------------------------------------------------
# handle_assignment_task_submission
# ---------------------------------------------------------------------------


class TestHandleAssignmentTaskSubmission:
    async def test_raises_404_when_task_not_found(
        self, mock_request, db, regular_user
    ):
        obj = AssignmentTaskSubmissionUpdate(
            task_submission={"answer": "x"},
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await handle_assignment_task_submission(
                    mock_request, "nonexistent", obj, regular_user, db
                )
        assert exc.value.status_code == 404

    async def test_creates_new_submission(
        self, mock_request, db, assignment_task, regular_user
    ):
        obj = AssignmentTaskSubmissionUpdate(
            task_submission={"answer": "hello"},
        )
        # First call: is_instructor check → False
        # Second call: enrollment check → True (user is enrolled)
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, side_effect=[False, True]):
            result = await handle_assignment_task_submission(
                mock_request, assignment_task.assignment_task_uuid, obj, regular_user, db
            )
        assert isinstance(result, AssignmentTaskSubmissionRead)

    async def test_updates_existing_submission(
        self, mock_request, db, assignment_task, task_submission, regular_user
    ):
        obj = AssignmentTaskSubmissionUpdate(
            task_submission={"answer": "updated"},
        )
        # is_instructor → False, enrollment → True
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, side_effect=[False, True]):
            result = await handle_assignment_task_submission(
                mock_request, assignment_task.assignment_task_uuid, obj, regular_user, db
            )
        assert isinstance(result, AssignmentTaskSubmissionRead)

    async def test_regular_user_cannot_self_assign_grade(
        self, mock_request, db, assignment_task, regular_user
    ):
        # SECURITY: a non-instructor submitting with a non-zero grade is
        # rejected — students cannot grade their own work.
        obj = AssignmentTaskSubmissionUpdate(
            task_submission={"answer": "x"},
            grade=50,
        )
        # is_instructor → False, enrollment → True
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, side_effect=[False, True]):
            with pytest.raises(HTTPException) as exc:
                await handle_assignment_task_submission(
                    mock_request, assignment_task.assignment_task_uuid, obj, regular_user, db
                )
        assert exc.value.status_code == 403
        assert "grade" in exc.value.detail.lower()

    async def test_instructor_autosave_with_zero_grade_saves_progress(
        self, mock_request, db, assignment_task, regular_user
    ):
        # An instructor taking their own course autosaves quiz answers through
        # this path with no target uuid. The quiz autosave sends grade=0 and
        # feedback="" — a placeholder, not a grade — and it must save, not raise
        # "the learner has no submission for it".
        obj = AssignmentTaskSubmissionUpdate(
            task_submission={"answer": "hello"},
            grade=0,
            task_submission_grade_feedback="",
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await handle_assignment_task_submission(
                mock_request, assignment_task.assignment_task_uuid, obj, regular_user, db
            )
        assert isinstance(result, AssignmentTaskSubmissionRead)

    async def test_instructor_real_grade_without_target_still_rejected(
        self, mock_request, db, assignment_task, regular_user
    ):
        # The integrity guard stays: a real grade with no target submission uuid
        # would otherwise write a phantom instructor-owned row while the learner's
        # grade never moves, so it must fail loudly.
        obj = AssignmentTaskSubmissionUpdate(
            task_submission={"answer": "x"},
            grade=80,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await handle_assignment_task_submission(
                    mock_request, assignment_task.assignment_task_uuid, obj, regular_user, db
                )
        assert exc.value.status_code == 400
        assert "no submission" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# read_assignment_submissions
# ---------------------------------------------------------------------------


class TestReadAssignmentSubmissions:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await read_assignment_submissions(mock_request, "nonexistent", admin_user, db)
        assert exc.value.status_code == 404

    async def test_returns_submissions_list(
        self, mock_request, db, assignment, user_submission, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await read_assignment_submissions(
                mock_request, assignment.assignment_uuid, admin_user, db
            )
        assert isinstance(result, list)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# read_user_assignment_submissions
# ---------------------------------------------------------------------------


class TestReadUserAssignmentSubmissions:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await read_user_assignment_submissions(
                    mock_request, "nonexistent", 1, admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_returns_user_submissions(
        self, mock_request, db, assignment, user_submission, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await read_user_assignment_submissions(
                mock_request, assignment.assignment_uuid, regular_user.id, admin_user, db
            )
        assert isinstance(result, list)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# read_user_assignment_submissions_me
# ---------------------------------------------------------------------------


class TestReadUserAssignmentSubmissionsMe:
    async def test_delegates_to_read_user_submissions(
        self, mock_request, db, assignment, user_submission, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False):
            result = await read_user_assignment_submissions_me(
                mock_request, assignment.assignment_uuid, regular_user, db
            )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# update_assignment_submission
# ---------------------------------------------------------------------------


class TestUpdateAssignmentSubmission:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user, regular_user
    ):
        obj = AssignmentUserSubmissionCreate(
            user_id=regular_user.id,
            assignment_id=9999,
            grade=0,
            submission_status=AssignmentUserSubmissionStatus.SUBMITTED,
            attempt_number=1,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await update_assignment_submission(
                    mock_request, regular_user.id, "nonexistent", obj, admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_raises_404_when_submission_not_found(
        self, mock_request, db, assignment, admin_user, regular_user
    ):
        obj = AssignmentUserSubmissionCreate(
            user_id=regular_user.id,
            assignment_id=assignment.id,
            grade=0,
            submission_status=AssignmentUserSubmissionStatus.SUBMITTED,
            attempt_number=1,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await update_assignment_submission(
                    mock_request,
                    regular_user.id,
                    assignment.assignment_uuid,
                    obj,
                    admin_user,
                    db,
                )
        assert exc.value.status_code == 404

    async def test_updates_submission(
        self, mock_request, db, assignment, user_submission, admin_user, regular_user
    ):
        obj = AssignmentUserSubmissionCreate(
            user_id=regular_user.id,
            assignment_id=assignment.id,
            grade=90,
            submission_status=AssignmentUserSubmissionStatus.GRADED,
            attempt_number=1,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await update_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                obj,
                admin_user,
                db,
            )
        assert isinstance(result, AssignmentUserSubmissionRead)


# ---------------------------------------------------------------------------
# delete_assignment_submission
# ---------------------------------------------------------------------------


class TestDeleteAssignmentSubmission:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await delete_assignment_submission(
                    mock_request, regular_user.id, "nonexistent", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_raises_404_when_submission_not_found(
        self, mock_request, db, assignment, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await delete_assignment_submission(
                    mock_request,
                    regular_user.id,
                    assignment.assignment_uuid,
                    admin_user,
                    db,
                )
        assert exc.value.status_code == 404

    async def test_deletes_submission(
        self, mock_request, db, assignment, user_submission, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await delete_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                admin_user,
                db,
            )
        assert result["message"] == "Assignment User Submission deleted"


# ---------------------------------------------------------------------------
# grade_assignment_submission
# ---------------------------------------------------------------------------


class TestGradeAssignmentSubmission:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await grade_assignment_submission(
                    mock_request, regular_user.id, "nonexistent", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_raises_404_when_submission_not_found(
        self, mock_request, db, assignment, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await grade_assignment_submission(
                    mock_request,
                    regular_user.id,
                    assignment.assignment_uuid,
                    admin_user,
                    db,
                )
        assert exc.value.status_code == 404

    async def test_grades_submission(
        self,
        mock_request,
        db,
        assignment,
        assignment_task,
        user_submission,
        task_submission,
        admin_user,
        regular_user,
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_CERT, new_callable=AsyncMock):
            result = await grade_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                admin_user,
                db,
            )
        assert "message" in result
        assert "display_grade" in result


# ---------------------------------------------------------------------------
# _apply_grade_and_finalize: manually_graded skip
# ---------------------------------------------------------------------------


class TestManuallyGradedSkipsVerification:
    """Regression guard for the per-task manual grading override.

    The aggregate grading pass runs server-side re-verification on
    SERVER_VERIFIED_TASK_TYPES (SHORT_ANSWER, NUMBER_ANSWER, QUIZ, FORM,
    CODE). When a teacher has manually graded a task, that verification
    must be skipped so the override survives.
    """

    async def _make_task_submission(
        self, db, assignment_task, regular_user, *, ts_id, uuid_suffix,
        grade, feedback, manually_graded, answer,
    ):
        ts = AssignmentTaskSubmission(
            id=ts_id,
            assignment_task_submission_uuid=f"ats_{uuid_suffix}",
            task_submission={"answer": answer},
            grade=grade,
            task_submission_grade_feedback=feedback,
            manually_graded=manually_graded,
            assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
            user_id=regular_user.id,
            activity_id=assignment_task.activity_id,
            course_id=assignment_task.course_id,
            chapter_id=assignment_task.chapter_id,
            assignment_task_id=assignment_task.id,
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(ts)
        await db.commit()
        await db.refresh(ts)
        return ts

    async def test_manual_grade_survives_wrong_answer(
        self,
        mock_request,
        db,
        assignment,
        assignment_task,
        user_submission,
        admin_user,
        regular_user,
    ):
        # SHORT_ANSWER task expects "4"; student submitted "5" (wrong). The
        # auto-verifier would compute 0, but the teacher set grade=100 with
        # manually_graded=True — the override must hold.
        ts = await self._make_task_submission(
            db, assignment_task, regular_user,
            ts_id=41, uuid_suffix="manual",
            grade=100, feedback="Graded by teacher : @badr",
            manually_graded=True, answer="5",
        )

        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_CERT, new_callable=AsyncMock):
            result = await grade_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                admin_user,
                db,
            )

        await db.refresh(ts)
        assert ts.grade == 100
        assert ts.task_submission_grade_feedback == "Graded by teacher : @badr"
        assert ts.manually_graded is True
        assert result["grade"] == 100
        # The breakdown exposes manually_graded so the modal can render a chip.
        task_breakdown = result["tasks"][0]
        assert task_breakdown["manually_graded"] is True

    async def test_non_manual_wrong_answer_is_overwritten(
        self,
        mock_request,
        db,
        assignment,
        assignment_task,
        user_submission,
        admin_user,
        regular_user,
    ):
        # Same wrong answer but manually_graded=False: the verifier must
        # overwrite the stale stored grade and stamp its own feedback.
        # This locks in the anti-tampering behavior so a future change to
        # the skip condition doesn't accidentally disable verification.
        ts = await self._make_task_submission(
            db, assignment_task, regular_user,
            ts_id=42, uuid_suffix="auto",
            grade=100, feedback="Stale client grade",
            manually_graded=False, answer="5",
        )

        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_CERT, new_callable=AsyncMock):
            result = await grade_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                admin_user,
                db,
            )

        await db.refresh(ts)
        assert ts.grade == 0
        assert ts.task_submission_grade_feedback == "Server-verified: incorrect"
        assert result["grade"] == 0
        task_breakdown = result["tasks"][0]
        assert task_breakdown["manually_graded"] is False

    async def test_task_without_submission_is_skipped(
        self,
        mock_request,
        db,
        assignment,
        assignment_task,
        user_submission,
        admin_user,
        regular_user,
    ):
        # The assignment has a task but the student never submitted it. The
        # re-verification loop must skip it (ts is None) without error and the
        # un-submitted task contributes 0 to the aggregate grade.
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_CERT, new_callable=AsyncMock):
            result = await grade_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                admin_user,
                db,
            )

        assert result["grade"] == 0
        task_breakdown = result["tasks"][0]
        assert task_breakdown["submitted"] is False
        assert task_breakdown["manually_graded"] is False


# ---------------------------------------------------------------------------
# get_grade_assignment_submission
# ---------------------------------------------------------------------------


class TestGetGradeAssignmentSubmission:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await get_grade_assignment_submission(
                    mock_request, regular_user.id, "nonexistent", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_raises_404_when_submission_not_found(
        self, mock_request, db, assignment, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await get_grade_assignment_submission(
                    mock_request,
                    regular_user.id,
                    assignment.assignment_uuid,
                    admin_user,
                    db,
                )
        assert exc.value.status_code == 404

    async def test_returns_grade_object(
        self,
        mock_request,
        db,
        assignment,
        assignment_task,
        graded_submission,
        task_submission,
        admin_user,
        regular_user,
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await get_grade_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                admin_user,
                db,
            )
        assert "display_grade" in result
        assert "tasks" in result


# ---------------------------------------------------------------------------
# mark_activity_as_done_for_user
# ---------------------------------------------------------------------------


class TestMarkActivityAsDoneForUser:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await mark_activity_as_done_for_user(
                    mock_request, regular_user.id, "nonexistent", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_raises_404_when_user_not_enrolled(
        self, mock_request, db, assignment, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await mark_activity_as_done_for_user(
                    mock_request,
                    regular_user.id,
                    assignment.assignment_uuid,
                    admin_user,
                    db,
                )
        assert exc.value.status_code == 404

    async def test_marks_activity_done(
        self,
        mock_request,
        db,
        org,
        course,
        assignment,
        activity,
        admin_user,
        regular_user,
    ):
        _, _, step = await _make_trail(
            db, org.id, course.id, activity.id, regular_user.id
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_CERT, new_callable=AsyncMock):
            result = await mark_activity_as_done_for_user(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                admin_user,
                db,
            )
        assert result["message"] == "Activity marked as done for user"
        await db.refresh(step)
        assert step.complete is True


# ---------------------------------------------------------------------------
# get_assignments_from_course
# ---------------------------------------------------------------------------


class TestGetAssignmentsFromCourse:
    async def test_raises_404_when_course_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await get_assignments_from_course(mock_request, "nonexistent", admin_user, db)
        assert exc.value.status_code == 404

    async def test_returns_assignments_for_course(
        self, mock_request, db, course, assignment, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await get_assignments_from_course(
                mock_request, course.course_uuid, admin_user, db
            )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].assignment_uuid == assignment.assignment_uuid


class TestCourseGradeLeaderboard:
    async def test_learner_route_uuid_without_prefix_loads_gradebook(
        self,
        mock_request,
        db,
        course,
        assignment_task,
        graded_submission,
        regular_user,
    ):
        """The public course URL omits ``course_`` but must use the same data."""
        learner_route_uuid = course.course_uuid.removeprefix("course_")

        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False):
            result = await get_course_grade_leaderboard(
                mock_request, learner_route_uuid, regular_user, db
            )

        assert result["course_uuid"] == course.course_uuid
        assert result["can_manage"] is False
        assert result["summary"]["learners"] == 1
        assert result["gradebook"][0]["user"]["id"] == regular_user.id

    async def test_groups_normalized_assignment_and_discussion_grades_by_week(
        self,
        mock_request,
        db,
        org,
        course,
        chapter,
        activity,
        assignment,
        assignment_task,
        graded_submission,
        admin_user,
        regular_user,
    ):
        assignment.title = "Week 1 assignment"
        db.add(assignment)
        second_learner = User(
            id=3,
            username="second-learner",
            first_name="Second",
            last_name="Learner",
            email="second@example.com",
            password="hashed_password",
            user_uuid="user_second_learner",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        second_assignment = Assignment(
            id=11,
            title="Week 1 scaled assignment",
            description="Uses a different point scale",
            due_date="2030-01-02",
            published=True,
            grading_type=GradingTypeEnum.NUMERIC,
            org_id=org.id,
            course_id=course.id,
            chapter_id=chapter.id,
            activity_id=activity.id,
            assignment_uuid="assignment_scaled",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        second_task = AssignmentTask(
            id=21,
            title="Scaled Task",
            description="Two hundred point task",
            hint="",
            reference_file=None,
            assignment_type=AssignmentTaskTypeEnum.OTHER,
            contents={},
            max_grade_value=200,
            assignment_id=second_assignment.id,
            org_id=org.id,
            course_id=course.id,
            chapter_id=chapter.id,
            activity_id=activity.id,
            assignment_task_uuid="assignmenttask_scaled",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        regular_second_grade = AssignmentUserSubmission(
            id=32,
            user_id=regular_user.id,
            assignment_id=second_assignment.id,
            grade=150,
            submission_status=AssignmentUserSubmissionStatus.GRADED,
            assignmentusersubmission_uuid="aus_regular_scaled",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        second_learner_grade = AssignmentUserSubmission(
            id=33,
            user_id=second_learner.id,
            assignment_id=assignment.id,
            grade=90,
            submission_status=AssignmentUserSubmissionStatus.GRADED,
            assignmentusersubmission_uuid="aus_second_learner",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        regular_discussion_grade = CourseDiscussionGrade(
            course_id=course.id,
            user_id=regular_user.id,
            week_number=1,
            score=0,
            max_score=100,
            graded_by_id=admin_user.id,
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        second_discussion_grade = CourseDiscussionGrade(
            course_id=course.id,
            user_id=second_learner.id,
            week_number=1,
            score=88,
            max_score=100,
            graded_by_id=admin_user.id,
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add_all(
            [
                second_learner,
                second_assignment,
                second_task,
                regular_second_grade,
                second_learner_grade,
                regular_discussion_grade,
                second_discussion_grade,
            ]
        )
        await db.commit()

        with patch(_PATCH_RBAC, new_callable=AsyncMock) as rbac, \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await get_course_grade_leaderboard(
                mock_request, course.course_uuid, admin_user, db
            )

        rbac.assert_awaited_once()
        assert result["can_manage"] is True
        assert result["summary"] == {
            "learners": 2,
            "weeks": 1,
            "ranked_components": 2,
            "ranked_weeks": 1,
        }
        assert result["weeks"] == [
            {
                "week_number": 1,
                "label": "Week 1",
                "assignment_weight": 75,
                "discussion_weight": 25,
            }
        ]
        assert [row["user"]["username"] for row in result["gradebook"]] == [
            "second-learner",
            "regular",
        ]
        second_result, regular_result = result["gradebook"]
        assert second_result["cumulative_percentage"] == 89.5
        assert second_result["rank"] == 1
        assert regular_result["cumulative_percentage"] == 60.0
        assert regular_result["rank"] == 2
        assert regular_result["graded_components"] == 2
        assert regular_result["ranked_components"] == 2
        regular_week = regular_result["weeks"]["1"]
        assert regular_week["assignment"] == {
            "percentage": 80.0,
            "graded_count": 2,
            "assigned_count": 2,
            "status": "graded",
        }
        assert regular_week["discussion"]["percentage"] == 0.0
        assert second_result["weeks"]["1"]["discussion"]["percentage"] == 88.0
        assert "email" not in second_result["user"]

    async def test_enrolled_learner_can_view_full_gradebook_read_only(
        self,
        mock_request,
        db,
        org,
        course,
        activity,
        assignment,
        assignment_task,
        graded_submission,
        regular_user,
    ):
        classmate = User(
            id=3,
            username="classmate",
            first_name="Class",
            last_name="Mate",
            email="classmate@example.com",
            password="hashed_password",
            user_uuid="user_classmate_gradebook",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        classmate_submission = AssignmentUserSubmission(
            id=98,
            user_id=classmate.id,
            assignment_id=assignment.id,
            grade=92,
            submission_status=AssignmentUserSubmissionStatus.GRADED,
            assignmentusersubmission_uuid="aus_classmate_gradebook",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        draft_assignment = Assignment(
            id=12,
            title="Week 2 draft assignment",
            description="Not released",
            due_date="2030-01-02",
            published=False,
            grading_type=GradingTypeEnum.NUMERIC,
            org_id=org.id,
            course_id=course.id,
            chapter_id=assignment.chapter_id,
            activity_id=assignment.activity_id,
            assignment_uuid="assignment_week_2_draft",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        draft_submission = AssignmentUserSubmission(
            id=99,
            user_id=regular_user.id,
            assignment_id=draft_assignment.id,
            grade=100,
            submission_status=AssignmentUserSubmissionStatus.GRADED,
            assignmentusersubmission_uuid="aus_week_2_draft",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add_all([classmate, classmate_submission, draft_assignment, draft_submission])
        await db.commit()
        await _make_trail(db, org.id, course.id, activity.id, regular_user.id)
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False):
            result = await get_course_grade_leaderboard(
                mock_request, course.course_uuid, regular_user, db
            )

        assert result["can_manage"] is False
        assert result["weeks"] == [
            {
                "week_number": 1,
                "label": "Week 1",
                "assignment_weight": 75,
                "discussion_weight": 25,
            }
        ]
        assert len(result["gradebook"]) == 2
        assert {row["user"]["id"] for row in result["gradebook"]} == {
            regular_user.id,
            classmate.id,
        }
        assert result["summary"]["ranked_components"] == 1
        assert result["summary"]["ranked_weeks"] == 1
        assert result["gradebook"][0]["user"]["id"] == classmate.id
        assert result["gradebook"][0]["cumulative_percentage"] == 92.0
        assert result["gradebook"][0]["rank"] == 1
        assert result["gradebook"][1]["cumulative_percentage"] == 85.0
        assert result["gradebook"][1]["rank"] == 2

    async def test_missing_active_component_counts_as_zero_and_ties_share_rank(
        self,
        mock_request,
        db,
        course,
        assignment,
        assignment_task,
        graded_submission,
        admin_user,
        regular_user,
    ):
        discussion_only_learner = User(
            id=3,
            username="discussion-only",
            first_name="Discussion",
            last_name="Only",
            email="discussion-only@example.com",
            password="hashed_password",
            user_uuid="user_discussion_only",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        discussion_grade = CourseDiscussionGrade(
            course_id=course.id,
            user_id=discussion_only_learner.id,
            week_number=1,
            score=75,
            max_score=100,
            graded_by_id=admin_user.id,
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        graded_submission.grade = 25
        db.add_all([graded_submission, discussion_only_learner, discussion_grade])
        await db.commit()

        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await get_course_grade_leaderboard(
                mock_request, course.course_uuid, admin_user, db
            )

        assert result["summary"]["ranked_components"] == 2
        assert [row["cumulative_percentage"] for row in result["gradebook"]] == [
            18.75,
            18.75,
        ]
        assert [row["rank"] for row in result["gradebook"]] == [1, 1]
        by_username = {
            row["user"]["username"]: row for row in result["gradebook"]
        }
        assert by_username["regular"]["graded_components"] == 1
        assert by_username["discussion-only"]["graded_components"] == 1

    async def test_staff_can_set_week_specific_grade_weights(
        self,
        mock_request,
        db,
        course,
        assignment_task,
        graded_submission,
        admin_user,
        regular_user,
    ):
        discussion_grade = CourseDiscussionGrade(
            course_id=course.id,
            user_id=regular_user.id,
            week_number=2,
            score=50,
            max_score=100,
            graded_by_id=admin_user.id,
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(discussion_grade)
        await db.commit()

        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await upsert_course_grade_weights(
                mock_request,
                course.course_uuid,
                2,
                60,
                40,
                admin_user,
                db,
            )

        assert result == {
            "week_number": 2,
            "assignment_weight": 60,
            "discussion_weight": 40,
        }
        await db.refresh(course)
        assert course.extra_metadata["gradebook_weights"]["2"] == {
            "assignment": 60,
            "discussion": 40,
        }

        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            leaderboard = await get_course_grade_leaderboard(
                mock_request, course.course_uuid, admin_user, db
            )

        # Week 1 contains the 85% assignment. Week 2 contains only discussion,
        # so its configured 40% is normalized while Assignment remains inactive.
        assert leaderboard["gradebook"][0]["cumulative_percentage"] == 67.5
        assert leaderboard["weeks"][1]["assignment_weight"] == 60
        assert leaderboard["weeks"][1]["discussion_weight"] == 40

    async def test_week_specific_grade_weights_must_total_100(
        self, mock_request, db, course, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await upsert_course_grade_weights(
                    mock_request,
                    course.course_uuid,
                    1,
                    75,
                    30,
                    admin_user,
                    db,
                )

        assert exc.value.status_code == 422

    async def test_non_enrolled_viewer_is_denied(
        self, mock_request, db, course, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False):
            with pytest.raises(HTTPException) as exc:
                await get_course_grade_leaderboard(
                    mock_request, course.course_uuid, admin_user, db
                )
        assert exc.value.status_code == 403

    async def test_staff_can_create_and_replace_discussion_grade(
        self,
        mock_request,
        db,
        course,
        assignment,
        graded_submission,
        admin_user,
        regular_user,
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            created = await upsert_course_discussion_grade(
                mock_request,
                course.course_uuid,
                regular_user.id,
                1,
                97,
                100,
                admin_user,
                db,
            )
            replaced = await upsert_course_discussion_grade(
                mock_request,
                course.course_uuid,
                regular_user.id,
                1,
                88,
                100,
                admin_user,
                db,
            )

        assert created["percentage"] == 97.0
        assert replaced["percentage"] == 88.0
        rows = list(
            (
                await db.execute(
                    select(CourseDiscussionGrade).where(
                        CourseDiscussionGrade.course_id == course.id,
                        CourseDiscussionGrade.user_id == regular_user.id,
                    )
                )
            ).scalars().all()
        )
        assert len(rows) == 1
        assert rows[0].score == 88

    async def test_discussion_grade_rejects_score_above_maximum(
        self, mock_request, db, course, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await upsert_course_discussion_grade(
                    mock_request,
                    course.course_uuid,
                    regular_user.id,
                    1,
                    101,
                    100,
                    admin_user,
                    db,
                )
        assert exc.value.status_code == 422

    async def test_staff_can_grade_enrolled_learner_without_assignment_row(
        self,
        mock_request,
        db,
        org,
        course,
        activity,
        admin_user,
        regular_user,
    ):
        await _make_trail(db, org.id, course.id, activity.id, regular_user.id)
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await upsert_course_discussion_grade(
                mock_request,
                course.course_uuid,
                regular_user.id,
                1,
                0,
                100,
                admin_user,
                db,
            )

        assert result["score"] == 0
        assert result["percentage"] == 0.0

    async def test_returns_404_for_unknown_course(
        self, mock_request, db, admin_user
    ):
        with pytest.raises(HTTPException) as exc:
            await get_course_grade_leaderboard(
                mock_request, "course_missing", admin_user, db
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# put_assignment_task_reference_file
# ---------------------------------------------------------------------------


class TestPutAssignmentTaskReferenceFile:
    async def test_raises_404_when_task_not_found(self, mock_request, db, admin_user):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await put_assignment_task_reference_file(
                    mock_request, db, "nonexistent_task", admin_user, None
                )
        assert exc.value.status_code == 404

    async def test_updates_task_without_file(
        self, mock_request, db, admin_user, assignment_task
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await put_assignment_task_reference_file(
                mock_request,
                db,
                assignment_task.assignment_task_uuid,
                admin_user,
                None,
            )
        assert result.assignment_task_uuid == assignment_task.assignment_task_uuid


# ---------------------------------------------------------------------------
# put_assignment_task_submission_file
# ---------------------------------------------------------------------------


class TestPutAssignmentTaskSubmissionFile:
    async def test_raises_404_when_task_not_found(self, mock_request, db, admin_user):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await put_assignment_task_submission_file(
                    mock_request, db, "nonexistent_task", admin_user, None
                )
        assert exc.value.status_code == 404

    async def test_returns_none_when_no_file(
        self, mock_request, db, admin_user, assignment_task
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await put_assignment_task_submission_file(
                mock_request,
                db,
                assignment_task.assignment_task_uuid,
                admin_user,
                None,
            )
        assert result is None


# ---------------------------------------------------------------------------
# handle_assignment_task_submission — UUID fallback branch (line 1342)
# ---------------------------------------------------------------------------


class TestHandleAssignmentTaskSubmissionUuidBranch:
    async def test_finds_submission_by_uuid_when_user_task_not_found(
        self, mock_request, db, admin_user, assignment_task, task_submission
    ):
        """Covers the UUID-specific lookup branch.

        `task_submission` belongs to `regular_user` (id=2). Calling as `admin_user`
        (id=1) still updates the submission identified by UUID."""
        payload = AssignmentTaskSubmissionUpdate(
            assignment_task_submission_uuid=task_submission.assignment_task_submission_uuid,
            task_submission={"answer": "updated"},
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await handle_assignment_task_submission(
                mock_request,
                assignment_task.assignment_task_uuid,
                payload,
                admin_user,
                db,
            )
        assert result is not None

    async def test_explicit_uuid_updates_target_submission_when_submitter_has_own_row(
        self, mock_request, db, admin_user, assignment_task, task_submission
    ):
        admin_submission = AssignmentTaskSubmission(
            id=41,
            assignment_task_submission_uuid="ats_admin_same_task",
            task_submission={"answer": "admin original"},
            grade=0,
            task_submission_grade_feedback="",
            assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
            user_id=admin_user.id,
            activity_id=assignment_task.activity_id,
            course_id=assignment_task.course_id,
            chapter_id=assignment_task.chapter_id,
            assignment_task_id=assignment_task.id,
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(admin_submission)
        await db.commit()

        payload = AssignmentTaskSubmissionUpdate(
            assignment_task_submission_uuid=task_submission.assignment_task_submission_uuid,
            task_submission={"answer": "teacher update for learner"},
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await handle_assignment_task_submission(
                mock_request,
                assignment_task.assignment_task_uuid,
                payload,
                admin_user,
                db,
            )

        await db.refresh(task_submission)
        await db.refresh(admin_submission)
        assert result.assignment_task_submission_uuid == task_submission.assignment_task_submission_uuid
        assert task_submission.task_submission == {"answer": "teacher update for learner"}
        assert admin_submission.task_submission == {"answer": "admin original"}

    async def test_uuid_lookup_is_scoped_to_route_task(
        self, mock_request, db, admin_user, assignment, assignment_task, task_submission
    ):
        other_task = AssignmentTask(
            id=21,
            title="Other task",
            description="A second task for scoping checks",
            hint="",
            reference_file=None,
            assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
            contents={"prompt": "What is 3+3?"},
            max_grade_value=100,
            assignment_id=assignment.id,
            org_id=assignment_task.org_id,
            course_id=assignment_task.course_id,
            chapter_id=assignment_task.chapter_id,
            activity_id=assignment_task.activity_id,
            assignment_task_uuid="assignmenttask_other",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(other_task)
        await db.commit()

        payload = AssignmentTaskSubmissionUpdate(
            assignment_task_submission_uuid=task_submission.assignment_task_submission_uuid,
            task_submission={"answer": "wrong task update"},
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await handle_assignment_task_submission(
                    mock_request,
                    other_task.assignment_task_uuid,
                    payload,
                    admin_user,
                    db,
                )

        await db.refresh(task_submission)
        assert exc.value.status_code == 404
        assert task_submission.task_submission == {"answer": "4"}


# ---------------------------------------------------------------------------
# read_user_assignment_task_submissions
# ---------------------------------------------------------------------------


class TestReadUserAssignmentTaskSubmissions:
    async def test_raises_404_when_task_not_found(
        self, mock_request, db, admin_user, regular_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await read_user_assignment_task_submissions(
                    mock_request, "nonexistent", regular_user.id, admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_raises_404_when_submission_not_found(
        self, mock_request, db, admin_user, regular_user, assignment_task
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await read_user_assignment_task_submissions(
                    mock_request,
                    assignment_task.assignment_task_uuid,
                    regular_user.id,
                    admin_user,
                    db,
                )
        assert exc.value.status_code == 404

    async def test_returns_submission(
        self, mock_request, db, admin_user, regular_user, assignment_task, task_submission
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await read_user_assignment_task_submissions(
                mock_request,
                assignment_task.assignment_task_uuid,
                regular_user.id,
                admin_user,
                db,
            )
        assert result.assignment_task_submission_uuid == task_submission.assignment_task_submission_uuid


# ---------------------------------------------------------------------------
# read_user_assignment_task_submissions_me_batch
# ---------------------------------------------------------------------------


class TestReadUserAssignmentTaskSubmissionsMeBatch:
    async def test_raises_404_when_assignment_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await read_user_assignment_task_submissions_me_batch(
                    mock_request, "nonexistent", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_returns_batch_map(
        self, mock_request, db, admin_user, assignment, assignment_task
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await read_user_assignment_task_submissions_me_batch(
                mock_request, assignment.assignment_uuid, admin_user, db
            )
        assert isinstance(result, dict)
        assert assignment_task.assignment_task_uuid in result


# ---------------------------------------------------------------------------
# read_user_assignment_task_submissions_me
# ---------------------------------------------------------------------------


class TestReadUserAssignmentTaskSubmissionsMe:
    async def test_raises_404_when_task_not_found(self, mock_request, db, admin_user):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await read_user_assignment_task_submissions_me(
                    mock_request, "nonexistent", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_returns_none_when_no_submission(
        self, mock_request, db, admin_user, assignment_task
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await read_user_assignment_task_submissions_me(
                mock_request, assignment_task.assignment_task_uuid, admin_user, db
            )
        assert result is None

    async def test_returns_submission(
        self, mock_request, db, admin_user, regular_user, assignment_task, task_submission
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await read_user_assignment_task_submissions_me(
                mock_request, assignment_task.assignment_task_uuid, regular_user, db
            )
        assert result is not None
        assert result.assignment_task_submission_uuid == task_submission.assignment_task_submission_uuid


# ---------------------------------------------------------------------------
# read_assignment_task_submissions
# ---------------------------------------------------------------------------


class TestReadAssignmentTaskSubmissions:
    async def test_raises_404_when_task_not_found(self, mock_request, db, admin_user):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await read_assignment_task_submissions(
                    mock_request, "nonexistent", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_returns_submissions_list(
        self, mock_request, db, admin_user, assignment_task, task_submission
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await read_assignment_task_submissions(
                mock_request, assignment_task.assignment_task_uuid, admin_user, db
            )
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].assignment_task_submission_uuid == task_submission.assignment_task_submission_uuid


# ---------------------------------------------------------------------------
# update_assignment_task_submission
# ---------------------------------------------------------------------------


class TestUpdateAssignmentTaskSubmission:
    async def test_raises_404_when_submission_not_found(
        self, mock_request, db, admin_user
    ):
        payload = AssignmentTaskSubmissionUpdate(task_submission={"answer": "x"})
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await update_assignment_task_submission(
                    mock_request, "nonexistent_uuid", payload, admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_updates_submission(
        self, mock_request, db, admin_user, assignment_task, task_submission
    ):
        payload = AssignmentTaskSubmissionUpdate(task_submission={"answer": "new_answer"})
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await update_assignment_task_submission(
                mock_request,
                task_submission.assignment_task_submission_uuid,
                payload,
                admin_user,
                db,
            )
        assert result.assignment_task_submission_uuid == task_submission.assignment_task_submission_uuid

    async def test_non_instructor_grade_and_feedback_stripped(
        self, mock_request, db, regular_user, assignment_task, task_submission
    ):
        """Covers lines 1709-1718: a non-instructor updating their OWN task
        submission has grade / feedback / assignment_task_id / assignment_type
        forced to None so they cannot self-grade."""
        original_grade = task_submission.grade  # 100
        payload = AssignmentTaskSubmissionCreate(
            assignment_task_submission_uuid=task_submission.assignment_task_submission_uuid,
            user_id=regular_user.id,
            activity_id=assignment_task.activity_id,
            course_id=assignment_task.course_id,
            chapter_id=assignment_task.chapter_id,
            assignment_task_id=task_submission.assignment_task_id,
            task_submission={"answer": "tampered"},
            grade=5,
            task_submission_grade_feedback="I deserve full marks",
            assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
        )
        # is_instructor -> False; submission belongs to regular_user
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False):
            result = await update_assignment_task_submission(
                mock_request,
                task_submission.assignment_task_submission_uuid,
                payload,
                regular_user,
                db,
            )
        # task_submission content WAS updated, but grade/feedback were NOT
        assert result.task_submission == {"answer": "tampered"}
        assert result.grade == original_grade
        await db.refresh(task_submission)
        assert task_submission.grade == original_grade
        assert task_submission.task_submission_grade_feedback == "Correct"

    async def test_non_instructor_other_users_submission_raises_403(
        self, mock_request, db, admin_user, assignment_task, task_submission
    ):
        """Covers lines 1710-1714: non-instructor editing someone else's
        submission is rejected with 403. task_submission belongs to
        regular_user (id 2); we call as admin_user (id 1) but force
        is_instructor -> False."""
        payload = AssignmentTaskSubmissionCreate(
            assignment_task_submission_uuid=task_submission.assignment_task_submission_uuid,
            user_id=admin_user.id,
            activity_id=assignment_task.activity_id,
            course_id=assignment_task.course_id,
            chapter_id=assignment_task.chapter_id,
            assignment_task_id=task_submission.assignment_task_id,
            task_submission={"answer": "hijack"},
            grade=0,
            task_submission_grade_feedback="",
            assignment_type=AssignmentTaskTypeEnum.SHORT_ANSWER,
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False):
            with pytest.raises(HTTPException) as exc:
                await update_assignment_task_submission(
                    mock_request,
                    task_submission.assignment_task_submission_uuid,
                    payload,
                    admin_user,
                    db,
                )
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# delete_assignment_task_submission
# ---------------------------------------------------------------------------


class TestDeleteAssignmentTaskSubmission:
    async def test_raises_404_when_submission_not_found(
        self, mock_request, db, admin_user
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await delete_assignment_task_submission(
                    mock_request, "nonexistent", admin_user, db
                )
        assert exc.value.status_code == 404

    async def test_deletes_submission(
        self, mock_request, db, admin_user, task_submission
    ):
        with patch(_PATCH_RBAC, new_callable=AsyncMock):
            result = await delete_assignment_task_submission(
                mock_request,
                task_submission.assignment_task_submission_uuid,
                admin_user,
                db,
            )
        assert result["message"] == "Assignment Task Submission deleted"


# ---------------------------------------------------------------------------
# create_assignment_submission — new TrailRun / TrailStep branches + auto_grading
# ---------------------------------------------------------------------------

_PATCH_TRAIL_PRESENCE = "src.services.courses.activities.assignments.check_trail_presence"
_PATCH_CERT_CHECK = (
    "src.services.courses.activities.assignments."
    "check_course_completion_and_create_certificate"
)
_PATCH_GRADE_FINALIZE = (
    "src.services.courses.activities.assignments._apply_grade_and_finalize"
)


class TestCreateAssignmentSubmission:
    async def test_creates_trailrun_and_trailstep_when_missing(
        self, mock_request, db, admin_user, assignment, course, activity
    ):
        """Covers lines 1915-1916 (new TrailRun) and 1940-1941 (new TrailStep)."""
        trail = Trail(
            org_id=course.org_id,
            user_id=admin_user.id,
            trail_uuid="trail_submit_test",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(trail)
        await db.commit()
        await db.refresh(trail)

        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_TRAIL_PRESENCE, new_callable=AsyncMock, return_value=trail), \
             patch(_PATCH_CERT, new_callable=AsyncMock), \
             patch(_PATCH_CERT_CHECK, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock):
            result = await create_assignment_submission(
                mock_request,
                assignment.assignment_uuid,
                admin_user,
                db,
            )
        assert result.submission_status == AssignmentUserSubmissionStatus.SUBMITTED

    async def test_auto_grading_path(
        self, mock_request, db, admin_user, assignment, course, activity, assignment_task
    ):
        """Covers the auto_grading branch (lines 1967-1989)."""
        assignment.auto_grading = True
        db.add(assignment)
        await db.commit()

        trail = Trail(
            org_id=course.org_id,
            user_id=admin_user.id,
            trail_uuid="trail_autograding",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(trail)
        await db.commit()
        await db.refresh(trail)

        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_TRAIL_PRESENCE, new_callable=AsyncMock, return_value=trail), \
             patch(_PATCH_CERT, new_callable=AsyncMock), \
             patch(_PATCH_CERT_CHECK, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock), \
             patch(_PATCH_GRADE_FINALIZE, new_callable=AsyncMock):
            result = await create_assignment_submission(
                mock_request,
                assignment.assignment_uuid,
                admin_user,
                db,
            )
        assert result.submission_status == AssignmentUserSubmissionStatus.SUBMITTED


# ---------------------------------------------------------------------------
# delete_assignment_submission — certification revocation branch (lines 2292-2297)
# ---------------------------------------------------------------------------


class TestDeleteAssignmentSubmissionCertRevocation:
    async def test_revokes_certificate_when_present(
        self, mock_request, db, assignment, user_submission, admin_user, regular_user, course
    ):
        """Covers the certification revocation path in delete_assignment_submission."""
        cert = Certifications(
            certification_uuid="cert_test_uuid",
            course_id=course.id,
            config={},
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(cert)
        await db.commit()
        await db.refresh(cert)

        cert_user = CertificateUser(
            user_id=regular_user.id,
            certification_id=cert.id,
            user_certification_uuid="certuser_test_uuid",
            created_at=str(datetime.now()),
            updated_at=str(datetime.now()),
        )
        db.add(cert_user)
        await db.commit()

        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await delete_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                admin_user,
                db,
            )
        assert result["message"] == "Assignment User Submission deleted"


# ---------------------------------------------------------------------------
# _is_assignment_past_due (lines 85-93)
# ---------------------------------------------------------------------------


class TestIsAssignmentPastDue:
    def test_past_iso_date_returns_true(self):
        a = SimpleNamespace(due_date="2000-01-01")
        assert _is_assignment_past_due(a) is True

    def test_past_iso_datetime_returns_true(self):
        a = SimpleNamespace(due_date="2000-01-01T12:00:00")
        assert _is_assignment_past_due(a) is True

    def test_future_iso_date_returns_false(self):
        a = SimpleNamespace(due_date="2999-01-01")
        assert _is_assignment_past_due(a) is False

    def test_empty_string_returns_false(self):
        assert _is_assignment_past_due(SimpleNamespace(due_date="")) is False

    def test_whitespace_only_returns_false(self):
        assert _is_assignment_past_due(SimpleNamespace(due_date="   ")) is False

    def test_none_returns_false(self):
        assert _is_assignment_past_due(SimpleNamespace(due_date=None)) is False

    def test_missing_attribute_returns_false(self):
        assert _is_assignment_past_due(SimpleNamespace()) is False

    def test_garbage_string_returns_false(self):
        assert _is_assignment_past_due(SimpleNamespace(due_date="not-a-date")) is False

    def test_tz_aware_past_date_returns_true(self):
        # tz-aware ISO string in the distant past -> stripped to naive -> past
        a = SimpleNamespace(due_date="2000-01-01T00:00:00+00:00")
        assert _is_assignment_past_due(a) is True

    def test_due_today_date_only_returns_false(self):
        # A date-only deadline of "today" must remain submittable for the whole
        # day (date inputs have no time component) -> not past due.
        today = datetime.now().date().isoformat()
        a = SimpleNamespace(due_date=today)
        assert _is_assignment_past_due(a) is False

    def test_due_yesterday_date_only_returns_true(self):
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
        a = SimpleNamespace(due_date=yesterday)
        assert _is_assignment_past_due(a) is True

    def test_due_today_earlier_time_returns_true(self):
        # When an explicit past time-of-day is given for today, it IS past due.
        earlier = (datetime.now() - timedelta(hours=1)).replace(microsecond=0).isoformat()
        a = SimpleNamespace(due_date=earlier)
        assert _is_assignment_past_due(a) is True


# ---------------------------------------------------------------------------
# Due-date enforcement (lines 1338-1342 + 1857-1861)
# ---------------------------------------------------------------------------


class TestDueDateEnforcement:
    async def _set_due(self, db, assignment, due_date):
        assignment.due_date = due_date
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)

    async def test_handle_task_submission_non_instructor_past_due_raises_403(
        self, mock_request, db, assignment, assignment_task, regular_user
    ):
        await self._set_due(db, assignment, "2000-01-01")
        obj = AssignmentTaskSubmissionUpdate(task_submission={"answer": "x"})
        # is_instructor -> False, enrollment read -> True
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, side_effect=[False, True]):
            with pytest.raises(HTTPException) as exc:
                await handle_assignment_task_submission(
                    mock_request, assignment_task.assignment_task_uuid, obj, regular_user, db
                )
        assert exc.value.status_code == 403
        assert "deadline has passed" in exc.value.detail

    async def test_handle_task_submission_instructor_past_due_allowed(
        self, mock_request, db, assignment, assignment_task, admin_user
    ):
        await self._set_due(db, assignment, "2000-01-01")
        obj = AssignmentTaskSubmissionUpdate(task_submission={"answer": "x"})
        # is_instructor -> True bypasses the due-date check entirely
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await handle_assignment_task_submission(
                mock_request, assignment_task.assignment_task_uuid, obj, admin_user, db
            )
        assert isinstance(result, AssignmentTaskSubmissionRead)

    async def test_create_submission_non_instructor_past_due_raises_403(
        self, mock_request, db, assignment, course, activity, regular_user
    ):
        await self._set_due(db, assignment, "2000-01-01")
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await create_assignment_submission(
                    mock_request, assignment.assignment_uuid, regular_user, db
                )
        assert exc.value.status_code == 403
        assert "deadline has passed" in exc.value.detail

    async def test_create_submission_instructor_past_due_allowed(
        self, mock_request, db, assignment, course, activity, admin_user
    ):
        await self._set_due(db, assignment, "2000-01-01")
        trail = Trail(
            org_id=course.org_id,
            user_id=admin_user.id,
            trail_uuid="trail_pastdue_instructor",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(trail)
        await db.commit()
        await db.refresh(trail)
        # is_instructor -> True; due-date check skipped, submission proceeds
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_TRAIL_PRESENCE, new_callable=AsyncMock, return_value=trail), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True), \
             patch(_PATCH_CERT, new_callable=AsyncMock), \
             patch(_PATCH_CERT_CHECK, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock):
            result = await create_assignment_submission(
                mock_request, assignment.assignment_uuid, admin_user, db
            )
        assert result.submission_status == AssignmentUserSubmissionStatus.SUBMITTED

    async def test_create_submission_non_instructor_no_due_date_allowed(
        self, mock_request, db, assignment, course, activity, regular_user
    ):
        await self._set_due(db, assignment, "")
        trail = Trail(
            org_id=course.org_id,
            user_id=regular_user.id,
            trail_uuid="trail_nodue",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(trail)
        await db.commit()
        await db.refresh(trail)
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_TRAIL_PRESENCE, new_callable=AsyncMock, return_value=trail), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False), \
             patch(_PATCH_CERT, new_callable=AsyncMock), \
             patch(_PATCH_CERT_CHECK, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock):
            result = await create_assignment_submission(
                mock_request, assignment.assignment_uuid, regular_user, db
            )
        assert result.submission_status == AssignmentUserSubmissionStatus.SUBMITTED


# ---------------------------------------------------------------------------
# update_assignment_submission — protected-field stripping (lines 2252-2254)
# ---------------------------------------------------------------------------


class TestUpdateAssignmentSubmissionProtectedFields:
    """Covers the non-instructor protected-field stripping (lines 2252-2254).

    NOTE: ``AssignmentUserSubmissionCreate`` only *declares* ``assignment_id``;
    extra kwargs (grade/submission_status/user_id) are silently dropped by
    pydantic, so ``assignment_id`` is the single protected field that actually
    survives onto the payload object and exercises the ``hasattr``/``setattr``
    stripping path. We assert via ``assignment_id`` reassignment, which is the
    real exploit the strip guards against.
    """

    async def test_non_instructor_cannot_reassign_submission_to_another_assignment(
        self, mock_request, db, org, course, chapter, activity, assignment,
        user_submission, regular_user,
    ):
        original_assignment_id = user_submission.assignment_id  # 10
        # A second assignment the attacker tries to move their submission onto.
        other = Assignment(
            id=11,
            title="Other Assignment",
            description="another",
            due_date="2030-01-01",
            published=True,
            grading_type=GradingTypeEnum.NUMERIC,
            auto_grading=False,
            org_id=org.id,
            course_id=course.id,
            chapter_id=chapter.id,
            activity_id=activity.id,
            assignment_uuid="assignment_other",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(other)
        await db.commit()

        obj = AssignmentUserSubmissionCreate(assignment_id=other.id)
        # is_instructor -> False; submission belongs to regular_user
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False):
            result = await update_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                obj,
                regular_user,
                db,
            )
        # assignment_id was stripped to None -> NOT written; stays original
        assert result.assignment_id == original_assignment_id
        await db.refresh(user_submission)
        assert user_submission.assignment_id == original_assignment_id

    async def test_instructor_cannot_reassign_assignment_id(
        self, mock_request, db, org, course, chapter, activity, assignment,
        user_submission, admin_user, regular_user,
    ):
        # SECURITY: the row's assignment_id is fixed by the URL/lookup keys.
        # Even an instructor must NOT be able to reparent a submission onto a
        # different assignment via the request body (assignment ids are global
        # integers — this would be a cross-tenant write).
        other = Assignment(
            id=12,
            title="Other Assignment 2",
            description="another",
            due_date="2030-01-01",
            published=True,
            grading_type=GradingTypeEnum.NUMERIC,
            auto_grading=False,
            org_id=org.id,
            course_id=course.id,
            chapter_id=chapter.id,
            activity_id=activity.id,
            assignment_uuid="assignment_other2",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(other)
        await db.commit()

        obj = AssignmentUserSubmissionCreate(assignment_id=other.id)
        # is_instructor -> True, but assignment_id is still stripped for everyone.
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await update_assignment_submission(
                mock_request,
                regular_user.id,
                assignment.assignment_uuid,
                obj,
                admin_user,
                db,
            )
        # Unchanged: the submission still belongs to the original assignment.
        assert result.assignment_id == assignment.id


class TestAssignmentIntegrityGuards:
    """Guards added after an audit found several ways to corrupt graded work."""

    async def _set_due(self, db, assignment, due_date):
        assignment.due_date = due_date
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)

    async def _user_submission(self, db, assignment, user, status):
        sub = AssignmentUserSubmission(
            assignment_id=assignment.id,
            user_id=user.id,
            assignmentusersubmission_uuid=f"assignmentusersubmission_{uuid4()}",
            submission_status=status,
            grade=0,
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        return sub

    async def test_learner_cannot_edit_answers_after_submitting(
        self, mock_request, db, assignment, assignment_task, regular_user
    ):
        """Answers freeze at hand-in.

        Otherwise a learner who has been shown the answer key (show_correct_answers
        reveals it post-grade) could replay the correct answers, and the next
        re-grade — which re-derives from the CURRENT stored answers — would score
        the tampered version.
        """
        await self._user_submission(
            db, assignment, regular_user, AssignmentUserSubmissionStatus.GRADED
        )
        obj = AssignmentTaskSubmissionUpdate(task_submission={"answer": "tampered"})
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, side_effect=[False, True]):
            with pytest.raises(HTTPException) as exc:
                await handle_assignment_task_submission(
                    mock_request, assignment_task.assignment_task_uuid, obj, regular_user, db
                )
        assert exc.value.status_code == 403
        assert "already been handed in" in exc.value.detail

    async def test_learner_can_still_edit_answers_while_pending(
        self, mock_request, db, assignment, assignment_task, regular_user
    ):
        """A PENDING row is an attempt in progress — saving must keep working."""
        await self._user_submission(
            db, assignment, regular_user, AssignmentUserSubmissionStatus.PENDING
        )
        obj = AssignmentTaskSubmissionUpdate(task_submission={"answer": "draft"})
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, side_effect=[False, True]):
            result = await handle_assignment_task_submission(
                mock_request, assignment_task.assignment_task_uuid, obj, regular_user, db
            )
        assert isinstance(result, AssignmentTaskSubmissionRead)

    async def test_instructor_grade_without_target_submission_is_rejected(
        self, mock_request, db, assignment_task, admin_user
    ):
        """Grading a task the learner never submitted used to write the grade to
        the INSTRUCTOR's own row, force it to 0, and report success."""
        obj = AssignmentTaskSubmissionUpdate(grade=8)
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            with pytest.raises(HTTPException) as exc:
                await handle_assignment_task_submission(
                    mock_request, assignment_task.assignment_task_uuid, obj, admin_user, db
                )
        assert exc.value.status_code == 400
        assert "no submission" in exc.value.detail

    async def test_instructor_answer_without_target_submission_still_allowed(
        self, mock_request, db, assignment_task, admin_user
    ):
        """An instructor taking their own course saves ANSWERS through the same
        path with no target uuid — the grade guard must not catch that."""
        obj = AssignmentTaskSubmissionUpdate(task_submission={"answer": "x"})
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True):
            result = await handle_assignment_task_submission(
                mock_request, assignment_task.assignment_task_uuid, obj, admin_user, db
            )
        assert isinstance(result, AssignmentTaskSubmissionRead)

    async def test_retry_past_due_is_rejected(
        self, mock_request, db, assignment, course, regular_user
    ):
        """Retry wipes answers, grade, trail step and certificate. Past the
        deadline the learner can never resubmit, so this destroyed graded work."""
        assignment.allow_retries = True
        await self._set_due(db, assignment, "2000-01-01")
        await self._user_submission(
            db, assignment, regular_user, AssignmentUserSubmissionStatus.GRADED
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=False):
            with pytest.raises(HTTPException) as exc:
                await retry_assignment_submission(
                    mock_request, assignment.assignment_uuid, regular_user, db
                )
        assert exc.value.status_code == 403
        assert "deadline has passed" in exc.value.detail

    async def test_grading_a_pending_submission_is_rejected(
        self, mock_request, db, assignment, course, regular_user, admin_user
    ):
        """A PENDING row is a retry in flight with its task rows deleted.
        Grading it summed an empty set, wrote 0, and locked the learner out."""
        await self._user_submission(
            db, assignment, regular_user, AssignmentUserSubmissionStatus.PENDING
        )
        with patch(_PATCH_RBAC, new_callable=AsyncMock), \
             patch(_PATCH_AUTH_ROLES, new_callable=AsyncMock, return_value=True), \
             patch(_PATCH_DISPATCH, new_callable=AsyncMock), \
             patch(_PATCH_TRACK, new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc:
                await grade_assignment_submission(
                    mock_request, regular_user.id, assignment.assignment_uuid, admin_user, db
                )
        assert exc.value.status_code == 400
        assert "not handed in" in exc.value.detail


class TestNumberAnswerSignedThousands:
    """Signed thousands-grouped numbers were parsed as decimals."""

    def test_negative_grouped_integer_matches(self):
        assert _check_number_answer("-1,000", -1000, 0) is True

    def test_plus_signed_grouped_integer_matches(self):
        assert _check_number_answer("+1,000", 1000, 0) is True

    def test_negative_multi_group_matches(self):
        assert _check_number_answer("-1,234,567", -1234567, 0) is True

    def test_negative_grouped_decimal_matches(self):
        assert _check_number_answer("-1,000.50", -1000.5, 0) is True

    def test_european_decimal_still_parsed_as_decimal(self):
        """The disambiguation this regex feeds must not regress: a bare
        "3,14" is still a European decimal, not three-thousand-fourteen."""
        assert _check_number_answer("3,14", 3.14, 0) is True
