from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from database import get_connection


app = FastAPI(
    title="KnightScribe API",
    description="Backend API for the KnightScribe classroom memory system",
    version="0.2.0",
)

class LectureCreate(BaseModel):
    id: str
    course_id: int
    title: str


class TranscriptSegmentCreate(BaseModel):
    chunk_number: int
    start_seconds: float
    end_seconds: float
    text: str


class LiveSummaryUpdate(BaseModel):
    live_summary: str

@app.get("/")
def home():
    return {
        "message": "KnightScribe backend is running"
    }


@app.get("/health")
def health():
    """
    Verify that both FastAPI and the Neon database
    are working.
    """

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

        return {
            "status": "ok",
            "database": "connected"
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Database connection failed: {error}"
        )


@app.get("/lectures/{lecture_id}")
def get_lecture(lecture_id: str):
    """
    Retrieve one lecture and its timestamped
    transcript segments.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    course_id,
                    title,
                    status,
                    started_at,
                    ended_at,
                    live_summary,
                    final_summary,
                    recording_url
                FROM lectures
                WHERE id = %s
                """,
                (lecture_id,),
            )

            lecture = cursor.fetchone()

            if lecture is None:
                raise HTTPException(
                    status_code=404,
                    detail="Lecture not found"
                )

            cursor.execute(
                """
                SELECT
                    id,
                    chunk_number,
                    start_seconds,
                    end_seconds,
                    text
                FROM transcript_segments
                WHERE lecture_id = %s
                ORDER BY start_seconds
                """,
                (lecture_id,),
            )

            transcript_segments = cursor.fetchall()

    lecture["transcript_segments"] = transcript_segments

    return lecture

@app.post("/lectures")
def create_lecture(lecture: LectureCreate):
    """
    Create a new KnightScribe lecture.
    """

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO lectures (
                        id,
                        course_id,
                        title,
                        status
                    )
                    VALUES (%s, %s, %s, 'recording')
                    RETURNING
                        id,
                        course_id,
                        title,
                        status,
                        started_at
                    """,
                    (
                        lecture.id,
                        lecture.course_id,
                        lecture.title,
                    ),
                )

                created_lecture = cursor.fetchone()

        return created_lecture

    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Could not create lecture: {error}"
        )

@app.post("/lectures/{lecture_id}/transcript")
def add_transcript_segment(
    lecture_id: str,
    segment: TranscriptSegmentCreate,
):
    """
    Add or update one timestamped transcript chunk.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM lectures
                WHERE id = %s
                """,
                (lecture_id,),
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Lecture not found"
                )

            cursor.execute(
                """
                INSERT INTO transcript_segments (
                    lecture_id,
                    chunk_number,
                    start_seconds,
                    end_seconds,
                    text
                )
                VALUES (%s, %s, %s, %s, %s)

                ON CONFLICT (
                    lecture_id,
                    chunk_number
                )

                DO UPDATE SET
                    start_seconds = EXCLUDED.start_seconds,
                    end_seconds = EXCLUDED.end_seconds,
                    text = EXCLUDED.text

                RETURNING
                    id,
                    lecture_id,
                    chunk_number,
                    start_seconds,
                    end_seconds,
                    text
                """,
                (
                    lecture_id,
                    segment.chunk_number,
                    segment.start_seconds,
                    segment.end_seconds,
                    segment.text,
                ),
            )

            saved_segment = cursor.fetchone()

    return saved_segment

@app.put("/lectures/{lecture_id}/live-summary")
def update_live_summary(
    lecture_id: str,
    update: LiveSummaryUpdate,
):
    """
    Update the rolling What Did I Miss? summary.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE lectures
                SET
                    live_summary = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING
                    id,
                    status,
                    live_summary,
                    updated_at
                """,
                (
                    update.live_summary,
                    lecture_id,
                ),
            )

            lecture = cursor.fetchone()

            if lecture is None:
                raise HTTPException(
                    status_code=404,
                    detail="Lecture not found"
                )

    return lecture

@app.post("/lectures/{lecture_id}/end")
def end_lecture(lecture_id: str):
    """
    Mark a lecture as finished recording.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE lectures
                SET
                    status = 'processing',
                    ended_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING
                    id,
                    status,
                    started_at,
                    ended_at
                """,
                (lecture_id,),
            )

            lecture = cursor.fetchone()

            if lecture is None:
                raise HTTPException(
                    status_code=404,
                    detail="Lecture not found"
                )

    return lecture

