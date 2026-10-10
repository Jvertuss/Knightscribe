from fastapi import FastAPI, HTTPException

from database import get_connection


app = FastAPI(
    title="KnightScribe API",
    description="Backend API for the KnightScribe classroom memory system",
    version="0.2.0",
)


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