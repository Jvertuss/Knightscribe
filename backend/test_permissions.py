
from uuid import uuid4

from fastapi import HTTPException

from database import get_connection
from permissions import (
    get_course,
    require_course_access,
    require_course_owner,
    require_lecture_permission,
    require_document_permission,
)


def expect_denied(description, action, expected_status):
    try:
        action()
    except HTTPException as error:
        assert error.status_code == expected_status, (
            f"{description}: Expected {expected_status}, "
            f"got {error.status_code}"
        )
        print(f"PASS: {description} (HTTP {error.status_code})")
    else:
        raise AssertionError(
            f"{description}: Access was incorrectly allowed"
        )


def main():
    # Use a random user ID that has no enrollment or
    # permissions in the database.
    fake_student = {
        "id": uuid4(),
        "role": "viewer"
    }

    fake_professor = {
        "id": uuid4(),
        "role": "creator"
    }

    # Find an existing course without modifying anything.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM courses ORDER BY id LIMIT 1"
            )
            course = cur.fetchone()

    print("\nStarting permission tests...\n")

    # A missing course must return 404.
    expect_denied(
        "Missing course is rejected",
        lambda: get_course(-1),
        404
    )

    if course is not None:
        course_id = course["id"]

        print(f"Testing existing course ID: {course_id}")

        # A student who is not enrolled must be denied.
        expect_denied(
            "Unenrolled student is denied",
            lambda: require_course_access(
                course_id, fake_student
            ),
            403
        )

        # A professor who doesn't own the course
        # must also be denied.
        expect_denied(
            "Non-owner professor is denied",
            lambda: require_course_owner(
                course_id, fake_professor
            ),
            403
        )
    else:
        print("SKIP: No courses exist yet")

    # Missing resources must not be accessible.
    expect_denied(
        "Missing lecture is rejected",
        lambda: require_lecture_permission(
            "nonexistent-test-lecture",
            fake_student,
            "can_view_transcript"
        ),
        404
    )

    expect_denied(
        "Missing document is rejected",
        lambda: require_document_permission(
            -1,
            fake_student,
            "can_view"
        ),
        404
    )

    print("\nALL PERMISSION DENIAL TESTS PASSED!")


if __name__ == "__main__":
    main()
