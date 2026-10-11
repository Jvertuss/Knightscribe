
from fastapi import HTTPException

from database import get_connection


# Only these permission columns can be queried.
LECTURE_PERMISSIONS = {
    "can_join_live",
    "can_view_video",
    "can_view_audio",
    "can_view_transcript",
    "can_view_summary",
    "can_view_board",
    "can_download",
}

DOCUMENT_PERMISSIONS = {
    "can_view",
    "can_download",
}


def get_course(course_id: int):
    """Retrieve a course from Neon."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, creator_id
                FROM courses
                WHERE id = %s
                """,
                (course_id,)
            )
            course = cur.fetchone()

    if course is None:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    return course


def is_course_owner(course: dict, user: dict) -> bool:
    """Check whether a professor owns this course."""

    return (
        user["role"] == "creator"
        and course["creator_id"] is not None
        and course["creator_id"] == user["id"]
    )


def require_course_owner(
    course_id: int,
    current_user: dict
):
    """Allow only the professor who owns the course."""

    course = get_course(course_id)

    if not is_course_owner(course, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only the course owner can perform this action"
        )

    return course


def require_course_access(
    course_id: int,
    current_user: dict
):
    """Allow course owner or enrolled student."""

    course = get_course(course_id)

    # Professor who owns the course
    if is_course_owner(course, current_user):
        return course

    # Other users must be enrolled students
    if current_user["role"] != "viewer":
        raise HTTPException(
            status_code=403,
            detail="Course access denied"
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM course_memberships
                WHERE course_id = %s
                  AND user_id = %s
                """,
                (course_id, current_user["id"])
            )

            membership = cur.fetchone()

    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="You are not enrolled in this course"
        )

    return course


def require_lecture_permission(
    lecture_id: str,
    current_user: dict,
    permission: str
):
    """Check individual lecture access."""

    if permission not in LECTURE_PERMISSIONS:
        raise ValueError("Unknown lecture permission")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, course_id
                FROM lectures
                WHERE id = %s
                """,
                (lecture_id,)
            )

            lecture = cur.fetchone()

    if lecture is None:
        raise HTTPException(
            status_code=404,
            detail="Lecture not found"
        )

    course_id = lecture["course_id"]

    if course_id is None:
        raise HTTPException(
            status_code=403,
            detail="Lecture is not assigned to a course"
        )

    course = require_course_access(
        course_id, current_user
    )

    # Course owner can manage their own lectures
    if is_course_owner(course, current_user):
        return lecture

    # Permission comes from a fixed allowlist.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {permission} AS allowed
                FROM lecture_access
                WHERE lecture_id = %s
                  AND viewer_id = %s
                """,
                (lecture_id, current_user["id"])
            )

            access = cur.fetchone()

    if access is None or not access["allowed"]:
        raise HTTPException(
            status_code=403,
            detail="Lecture permission denied"
        )

    return lecture


def require_document_permission(
    document_id: int,
    current_user: dict,
    permission: str
):
    """Check individual document access."""

    if permission not in DOCUMENT_PERMISSIONS:
        raise ValueError("Unknown document permission")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, course_id
                FROM course_documents
                WHERE id = %s
                """,
                (document_id,)
            )

            document = cur.fetchone()

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    course = require_course_access(
        document["course_id"], current_user
    )

    if is_course_owner(course, current_user):
        return document

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {permission} AS allowed
                FROM course_document_access
                WHERE document_id = %s
                  AND viewer_id = %s
                """,
                (document_id, current_user["id"])
            )

            access = cur.fetchone()

    if access is None or not access["allowed"]:
        raise HTTPException(
            status_code=403,
            detail="Document permission denied"
        )

    return document
