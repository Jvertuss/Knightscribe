
import os

from dotenv import load_dotenv
from fastapi import HTTPException

from database import get_connection

from permissions import (
    require_course_access,
    require_course_owner,
    require_lecture_permission,
    require_document_permission,
)


load_dotenv()

COURSE_ID = 1
LECTURE_ID = "lecture_2026-10-10_demo"
DOCUMENT_ID = 1

# Set these to the emails of your test accounts.
PROFESSOR_EMAIL = os.getenv(
    "TEST_PROFESSOR_EMAIL",
    "testprofessor@example.com"
)
STUDENT_EMAIL = os.getenv(
    "TEST_STUDENT_EMAIL",
    "teststudent@example.com"
)


def get_test_user(email):
    """Retrieve an existing test account from Neon."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, email, role
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cur.fetchone()

    if user is None:
        raise RuntimeError(
            f"No test user found for {email}. "
            "Check the test account email."
        )

    return user


def expect_allowed(description, action):
    """Verify that an authorized action succeeds."""

    try:
        action()

    except HTTPException as error:
        raise AssertionError(
            f"{description} failed. "
            f"HTTP {error.status_code}: {error.detail}"
        ) from error

    print(f"PASS: {description}")


def expect_denied(description, action):
    """Verify that a restricted action returns HTTP 403."""

    try:
        action()

    except HTTPException as error:
        assert error.status_code == 403, (
            f"{description}: Expected HTTP 403, "
            f"got HTTP {error.status_code}"
        )

        print(f"PASS: {description} (HTTP 403)")
        return

    raise AssertionError(
        f"{description}: Access was incorrectly allowed!"
    )


def main():

    print("\n=== KNIGHTSCRIBE PERMISSION TESTS ===\n")

    # Fetch the actual accounts stored in Neon.
    professor = get_test_user(PROFESSOR_EMAIL)
    student = get_test_user(STUDENT_EMAIL)

    print("Professor:", professor["name"])
    print("Professor role:", professor["role"])

    print("Student:", student["name"])
    print("Student role:", student["role"])

    assert professor["role"] == "creator", (
        "Professor must have creator role"
    )

    assert student["role"] == "viewer", (
        "Student must have viewer role"
    )

    print("\n--- PROFESSOR TESTS ---")

    expect_allowed(
        "Professor can access owned course",
        lambda: require_course_owner(
            COURSE_ID, professor
        )
    )

    expect_allowed(
        "Professor can access own lecture transcript",
        lambda: require_lecture_permission(
            LECTURE_ID,
            professor,
            "can_view_transcript"
        )
    )

    print("\n--- STUDENT TESTS ---")

    expect_allowed(
        "Enrolled student can access course",
        lambda: require_course_access(
            COURSE_ID, student
        )
    )

    expect_allowed(
        "Student can view lecture transcript",
        lambda: require_lecture_permission(
            LECTURE_ID,
            student,
            "can_view_transcript"
        )
    )

    expect_denied(
        "Student cannot view lecture video",
        lambda: require_lecture_permission(
            LECTURE_ID,
            student,
            "can_view_video"
        )
    )

    expect_allowed(
        "Student can view Week 3 document",
        lambda: require_document_permission(
            DOCUMENT_ID,
            student,
            "can_view"
        )
    )

    expect_denied(
        "Student cannot download Week 3 document",
        lambda: require_document_permission(
            DOCUMENT_ID,
            student,
            "can_download"
        )
    )

    expect_denied(
        "Student cannot manage professor's course",
        lambda: require_course_owner(
            COURSE_ID,
            student
        )
    )

    print("\n================================")
    print("ALL AUTHORIZED PERMISSION TESTS PASSED!")
    print("================================")


if __name__ == "__main__":
    main()
