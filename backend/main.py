from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal

from database import get_connection
from document_processing import extract_document
from retrieval import search_course_context
from search import search_course_memory


app = FastAPI(
    title="KnightScribe API",
    description="Backend API for the KnightScribe classroom memory system",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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


class LectureCompleteUpdate(BaseModel):
    final_summary: str
    recording_url: str | None = None


class CourseSettingsUpdate(BaseModel):
    explanations_allowed: bool
    hints_allowed: bool
    final_answers_allowed: bool
    practice_questions_allowed: bool
    ai_enabled: bool
    recording_view_allowed: bool


class QuizQuestionCreate(BaseModel):
    question: str
    options: list[str]
    correct_option: int
    explanation: str | None = None


class QuizAnswerSubmit(BaseModel):
    selected_option: int


class ReferenceChunkCreate(BaseModel):
    content: str
    source_location: str | None = None


class CourseDocumentCreate(BaseModel):
    title: str
    document_type: str
    original_filename: str | None = None
    file_url: str | None = None
    chunks: list[ReferenceChunkCreate]


class AIContextRequest(BaseModel):
    message: str

    mode: Literal[
        "explain",
        "hint",
        "answer"
    ] = "explain"

    lecture_id: str | None = None

    max_sources: int = 6

class BoardEventCreate(BaseModel):
    timestamp_seconds: float
    image_url: str | None = None
    ocr_text: str | None = None
    description: str | None = None
    event_type: str = "board_changed"

class LectureStreamUpdate(BaseModel):
    stream_status: Literal[
        "offline",
        "starting",
        "live",
        "ended",
        "error"
    ]

    stream_protocol: Literal[
        "hls",
        "webrtc",
        "mjpeg",
        "other"
    ] | None = None

    live_stream_url: str | None = None


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

            # Get the lecture and apply the professor's
            # recording-view permission.
            cursor.execute(
                """
                SELECT
                    l.id,
                    l.course_id,
                    l.title,
                    l.status,
                    l.started_at,
                    l.ended_at,
                    l.live_summary,
                    l.final_summary,
                    l.stream_status,
                    l.stream_protocol,
                    l.live_stream_url,
                    l.stream_updated_at,

                    COALESCE(
                        cs.recording_view_allowed,
                        FALSE
                    ) AS recording_view_allowed,

                    CASE
                        WHEN COALESCE(
                            cs.recording_view_allowed,
                            FALSE
                        )
                        THEN l.recording_url
                        ELSE NULL
                    END AS recording_url

                FROM lectures AS l

                LEFT JOIN course_settings AS cs
                    ON cs.course_id = l.course_id

                WHERE l.id = %s
                """,
                (lecture_id,),
            )

            lecture = cursor.fetchone()

            if lecture is None:
                raise HTTPException(
                    status_code=404,
                    detail="Lecture not found"
                )

            # Get all timestamped transcript segments
            # belonging to this lecture.
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

@app.put("/lectures/{lecture_id}/complete")
def complete_lecture(
    lecture_id: str,
    update: LectureCompleteUpdate,
):
    """
    Save final lecture results and mark processing complete.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE lectures
                SET
                    status = 'completed',
                    final_summary = %s,
                    recording_url = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING
                    id,
                    status,
                    final_summary,
                    recording_url,
                    updated_at
                """,
                (
                    update.final_summary,
                    update.recording_url,
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

@app.get("/courses/{course_id}/settings")
def get_course_settings(course_id: int):
    """
    Retrieve the professor-controlled settings for a course.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    course_id,
                    explanations_allowed,
                    hints_allowed,
                    final_answers_allowed,
                    practice_questions_allowed,
                    ai_enabled,
                    recording_view_allowed,
                    updated_at
                FROM course_settings
                WHERE course_id = %s
                """,
                (course_id,),
            )

            settings = cursor.fetchone()

            if settings is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course settings not found"
                )

    return settings

@app.put("/courses/{course_id}/settings")
def update_course_settings(
    course_id: int,
    settings: CourseSettingsUpdate,
):
    """
    Create or update the professor-controlled settings
    for a course.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM courses
                WHERE id = %s
                """,
                (course_id,),
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course not found"
                )

            cursor.execute(
                """
                INSERT INTO course_settings (
                    course_id,
                    explanations_allowed,
                    hints_allowed,
                    final_answers_allowed,
                    practice_questions_allowed,
                    ai_enabled,
                    recording_view_allowed
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)

                ON CONFLICT (course_id)

                DO UPDATE SET
                    explanations_allowed =
                        EXCLUDED.explanations_allowed,

                    hints_allowed =
                        EXCLUDED.hints_allowed,

                    final_answers_allowed =
                        EXCLUDED.final_answers_allowed,

                    practice_questions_allowed =
                        EXCLUDED.practice_questions_allowed,

                    ai_enabled =
                        EXCLUDED.ai_enabled,

                    recording_view_allowed =
                        EXCLUDED.recording_view_allowed,

                    updated_at = NOW()

                RETURNING
                    course_id,
                    explanations_allowed,
                    hints_allowed,
                    final_answers_allowed,
                    practice_questions_allowed,
                    ai_enabled,
                    recording_view_allowed,
                    updated_at
                """,
                (
                    course_id,
                    settings.explanations_allowed,
                    settings.hints_allowed,
                    settings.final_answers_allowed,
                    settings.practice_questions_allowed,
                    settings.ai_enabled,
                    settings.recording_view_allowed,
                ),
            )

            updated_settings = cursor.fetchone()

    return updated_settings

@app.get("/courses")
def get_courses():
    """
    Retrieve all KnightScribe courses.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    code,
                    professor_name,
                    created_at
                FROM courses
                ORDER BY created_at DESC
                """
            )

            courses = cursor.fetchall()

    return courses

@app.get("/courses/{course_id}")
def get_course(course_id: int):
    """
    Retrieve one KnightScribe course.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    code,
                    professor_name,
                    created_at
                FROM courses
                WHERE id = %s
                """,
                (course_id,),
            )

            course = cursor.fetchone()

            if course is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course not found"
                )

    return course

@app.get("/courses/{course_id}/lectures")
def get_course_lectures(course_id: int):
    """
    Retrieve all lectures belonging to a course.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM courses
                WHERE id = %s
                """,
                (course_id,),
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course not found"
                )

            cursor.execute(
                """
                SELECT
                    id,
                    title,
                    status,
                    started_at,
                    ended_at,
                    live_summary,
                    final_summary
                FROM lectures
                WHERE course_id = %s
                ORDER BY started_at DESC
                """,
                (course_id,),
            )

            lectures = cursor.fetchall()

    return lectures

@app.post("/lectures/{lecture_id}/quiz-questions")
def create_quiz_question(
    lecture_id: str,
    quiz: QuizQuestionCreate,
):
    """
    Store a practice quiz question for a lecture.
    """

    if len(quiz.options) < 2:
        raise HTTPException(
            status_code=400,
            detail="A quiz question must have at least two options"
        )

    if quiz.correct_option < 0 or quiz.correct_option >= len(quiz.options):
        raise HTTPException(
            status_code=400,
            detail="correct_option is outside the available options"
        )

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
                INSERT INTO quiz_questions (
                    lecture_id,
                    question,
                    options,
                    correct_option,
                    explanation
                )
                VALUES (%s, %s, %s, %s, %s)

                RETURNING
                    id,
                    lecture_id,
                    question,
                    options,
                    correct_option,
                    explanation,
                    created_at
                """,
                (
                    lecture_id,
                    quiz.question,
                    quiz.options,
                    quiz.correct_option,
                    quiz.explanation,
                ),
            )

            created_question = cursor.fetchone()

    return created_question

@app.get("/lectures/{lecture_id}/quiz-questions")
def get_quiz_questions(lecture_id: str):
    """
    Return student-visible practice questions.

    Correct answers and explanations are intentionally
    hidden until the student submits an answer.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    l.id,
                    COALESCE(
                        cs.practice_questions_allowed,
                        FALSE
                    ) AS practice_questions_allowed
                FROM lectures AS l

                LEFT JOIN course_settings AS cs
                    ON cs.course_id = l.course_id

                WHERE l.id = %s
                """,
                (lecture_id,),
            )

            lecture = cursor.fetchone()

            if lecture is None:
                raise HTTPException(
                    status_code=404,
                    detail="Lecture not found"
                )

            if not lecture["practice_questions_allowed"]:
                raise HTTPException(
                    status_code=403,
                    detail="Practice questions are disabled for this course"
                )

            cursor.execute(
                """
                SELECT
                    id,
                    lecture_id,
                    question,
                    options,
                    created_at
                FROM quiz_questions
                WHERE lecture_id = %s
                ORDER BY id
                """,
                (lecture_id,),
            )

            questions = cursor.fetchall()

    return questions

@app.post("/quiz-questions/{question_id}/answer")
def answer_quiz_question(
    question_id: int,
    answer: QuizAnswerSubmit,
):
    """
    Check a student's answer to a practice question.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    q.id,
                    q.question,
                    q.options,
                    q.correct_option,
                    q.explanation,

                    COALESCE(
                        cs.practice_questions_allowed,
                        FALSE
                    ) AS practice_questions_allowed

                FROM quiz_questions AS q

                JOIN lectures AS l
                    ON l.id = q.lecture_id

                LEFT JOIN course_settings AS cs
                    ON cs.course_id = l.course_id

                WHERE q.id = %s
                """,
                (question_id,),
            )

            question = cursor.fetchone()

            if question is None:
                raise HTTPException(
                    status_code=404,
                    detail="Quiz question not found"
                )

            if not question["practice_questions_allowed"]:
                raise HTTPException(
                    status_code=403,
                    detail="Practice questions are disabled for this course"
                )

    options = question["options"]

    if answer.selected_option < 0 or answer.selected_option >= len(options):
        raise HTTPException(
            status_code=400,
            detail="selected_option is outside the available options"
        )

    is_correct = (
        answer.selected_option == question["correct_option"]
    )

    return {
        "question_id": question_id,
        "correct": is_correct,
        "selected_option": answer.selected_option,
        "correct_option": question["correct_option"],
        "correct_answer": options[question["correct_option"]],
        "explanation": question["explanation"],
    }

@app.post("/courses/{course_id}/documents")
def create_course_document(
    course_id: int,
    document: CourseDocumentCreate,
):
    """
    Store professor-approved reference material
    and its searchable text chunks.
    """

    if len(document.chunks) == 0:
        raise HTTPException(
            status_code=400,
            detail="Reference material must contain at least one text chunk"
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # Make sure the course exists.
            cursor.execute(
                """
                SELECT id
                FROM courses
                WHERE id = %s
                """,
                (course_id,),
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course not found"
                )

            # Keep a complete extracted-text copy too.
            extracted_text = "\n\n".join(
                chunk.content
                for chunk in document.chunks
            )

            cursor.execute(
                """
                INSERT INTO course_documents (
                    course_id,
                    title,
                    document_type,
                    original_filename,
                    file_url,
                    extracted_text,
                    processing_status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'ready'
                )

                RETURNING
                    id,
                    course_id,
                    title,
                    document_type,
                    original_filename,
                    file_url,
                    processing_status,
                    created_at,
                    updated_at
                """,
                (
                    course_id,
                    document.title,
                    document.document_type,
                    document.original_filename,
                    document.file_url,
                    extracted_text,
                ),
            )

            created_document = cursor.fetchone()

            document_id = created_document["id"]

            saved_chunks = []

            for chunk_index, chunk in enumerate(document.chunks):

                cursor.execute(
                    """
                    INSERT INTO document_chunks (
                        document_id,
                        chunk_index,
                        content,
                        source_location
                    )
                    VALUES (%s, %s, %s, %s)

                    RETURNING
                        id,
                        document_id,
                        chunk_index,
                        content,
                        source_location
                    """,
                    (
                        document_id,
                        chunk_index,
                        chunk.content,
                        chunk.source_location,
                    ),
                )

                saved_chunks.append(
                    cursor.fetchone()
                )

    created_document["chunks"] = saved_chunks

    return created_document

@app.get("/courses/{course_id}/documents")
def get_course_documents(course_id: int):
    """
    Retrieve the reference materials available
    to KnightScribe for a course.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM courses
                WHERE id = %s
                """,
                (course_id,),
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course not found"
                )

            cursor.execute(
                """
                SELECT
                    id,
                    course_id,
                    title,
                    document_type,
                    original_filename,
                    file_url,
                    processing_status,
                    created_at,
                    updated_at
                FROM course_documents
                WHERE course_id = %s
                ORDER BY created_at DESC
                """,
                (course_id,),
            )

            documents = cursor.fetchall()

    return documents

@app.get("/courses/{course_id}/documents/{document_id}")
def get_course_document(
    course_id: int,
    document_id: int,
):
    """
    Retrieve one reference document and all
    searchable chunks belonging to it.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    course_id,
                    title,
                    document_type,
                    original_filename,
                    file_url,
                    processing_status,
                    created_at,
                    updated_at
                FROM course_documents
                WHERE id = %s
                  AND course_id = %s
                """,
                (
                    document_id,
                    course_id,
                ),
            )

            document = cursor.fetchone()

            if document is None:
                raise HTTPException(
                    status_code=404,
                    detail="Reference document not found"
                )

            cursor.execute(
                """
                SELECT
                    id,
                    chunk_index,
                    content,
                    source_location
                FROM document_chunks
                WHERE document_id = %s
                ORDER BY chunk_index
                """,
                (document_id,),
            )

            chunks = cursor.fetchall()

    document["chunks"] = chunks

    return document

@app.post("/courses/{course_id}/documents/upload")
async def upload_course_document(
    course_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(None),
):
    """
    Upload a real professor-approved PDF, PowerPoint,
    or text file and automatically extract searchable text.
    """

    MAX_FILE_SIZE = 20 * 1024 * 1024

    filename = file.filename

    if not filename:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file must have a filename"
        )

    file_data = await file.read()

    if len(file_data) == 0:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty"
        )

    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Uploaded file is larger than the 20 MB limit"
        )

    try:
        document_type, extracted_chunks = extract_document(
            filename,
            file_data,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Could not process uploaded document: {error}"
        )

    document_title = title or filename

    extracted_text = "\n\n".join(
        chunk["content"]
        for chunk in extracted_chunks
    )

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # Verify that the course exists.
            cursor.execute(
                """
                SELECT id
                FROM courses
                WHERE id = %s
                """,
                (course_id,),
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course not found"
                )

            # Store document metadata.
            cursor.execute(
                """
                INSERT INTO course_documents (
                    course_id,
                    title,
                    document_type,
                    original_filename,
                    file_url,
                    extracted_text,
                    processing_status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    NULL,
                    %s,
                    'ready'
                )

                RETURNING
                    id,
                    course_id,
                    title,
                    document_type,
                    original_filename,
                    file_url,
                    processing_status,
                    created_at,
                    updated_at
                """,
                (
                    course_id,
                    document_title,
                    document_type,
                    filename,
                    extracted_text,
                ),
            )

            created_document = cursor.fetchone()

            document_id = created_document["id"]

            saved_chunks = []

            for chunk_index, chunk in enumerate(
                extracted_chunks
            ):
                cursor.execute(
                    """
                    INSERT INTO document_chunks (
                        document_id,
                        chunk_index,
                        content,
                        source_location
                    )
                    VALUES (%s, %s, %s, %s)

                    RETURNING
                        id,
                        document_id,
                        chunk_index,
                        content,
                        source_location
                    """,
                    (
                        document_id,
                        chunk_index,
                        chunk["content"],
                        chunk["source_location"],
                    ),
                )

                saved_chunks.append(
                    cursor.fetchone()
                )

    created_document["chunks"] = saved_chunks

    return created_document

@app.post("/courses/{course_id}/ai-context")
def get_ai_context(
    course_id: int,
    request: AIContextRequest,
):
    """
    Retrieve professor-approved context for the AI tutor.

    This endpoint does not use the internet and does not
    generate the final AI response itself.
    """

    if not request.message.strip():
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )

    if request.max_sources < 1 or request.max_sources > 10:
        raise HTTPException(
            status_code=400,
            detail="max_sources must be between 1 and 10"
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    c.id,

                    COALESCE(
                        cs.ai_enabled,
                        FALSE
                    ) AS ai_enabled,

                    COALESCE(
                        cs.explanations_allowed,
                        FALSE
                    ) AS explanations_allowed,

                    COALESCE(
                        cs.hints_allowed,
                        FALSE
                    ) AS hints_allowed,

                    COALESCE(
                        cs.final_answers_allowed,
                        FALSE
                    ) AS final_answers_allowed

                FROM courses AS c

                LEFT JOIN course_settings AS cs
                    ON cs.course_id = c.id

                WHERE c.id = %s
                """,
                (course_id,),
            )

            course = cursor.fetchone()

            if course is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course not found"
                )

            if not course["ai_enabled"]:
                raise HTTPException(
                    status_code=403,
                    detail="AI tutor is disabled for this course"
                )

            if (
                request.mode == "explain"
                and not course["explanations_allowed"]
            ):
                raise HTTPException(
                    status_code=403,
                    detail="AI explanations are disabled for this course"
                )

            if (
                request.mode == "hint"
                and not course["hints_allowed"]
            ):
                raise HTTPException(
                    status_code=403,
                    detail="AI hints are disabled for this course"
                )

            if (
                request.mode == "answer"
                and not course["final_answers_allowed"]
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Final AI answers are disabled for this course"
                )

            if request.lecture_id:
                cursor.execute(
                    """
                    SELECT id
                    FROM lectures
                    WHERE id = %s
                      AND course_id = %s
                    """,
                    (
                        request.lecture_id,
                        course_id,
                    ),
                )

                if cursor.fetchone() is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Lecture not found in this course"
                    )

    sources = search_course_context(
        course_id=course_id,
        query=request.message,
        lecture_id=request.lecture_id,
        max_sources=request.max_sources,
    )

    return {
        "course_id": course_id,
        "message": request.message,
        "mode": request.mode,
        "internet_used": False,
        "source_count": len(sources),
        "sources": sources,
    }

@app.post("/lectures/{lecture_id}/board-events")
def create_board_event(
    lecture_id: str,
    event: BoardEventCreate,
):
    """
    Store a timestamped whiteboard snapshot/event.
    """

    if event.timestamp_seconds < 0:
        raise HTTPException(
            status_code=400,
            detail="timestamp_seconds cannot be negative"
        )

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
                INSERT INTO board_events (
                    lecture_id,
                    timestamp_seconds,
                    image_url,
                    ocr_text,
                    description,
                    event_type
                )
                VALUES (%s, %s, %s, %s, %s, %s)

                RETURNING
                    id,
                    lecture_id,
                    timestamp_seconds,
                    image_url,
                    ocr_text,
                    description,
                    event_type,
                    created_at
                """,
                (
                    lecture_id,
                    event.timestamp_seconds,
                    event.image_url,
                    event.ocr_text,
                    event.description,
                    event.event_type,
                ),
            )

            created_event = cursor.fetchone()

    return created_event

@app.get("/lectures/{lecture_id}/board-events")
def get_board_events(lecture_id: str):
    """
    Retrieve a lecture's whiteboard snapshots
    in timestamp order.
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
                SELECT
                    id,
                    lecture_id,
                    timestamp_seconds,
                    image_url,
                    ocr_text,
                    description,
                    event_type,
                    created_at
                FROM board_events
                WHERE lecture_id = %s
                ORDER BY timestamp_seconds
                """,
                (lecture_id,),
            )

            events = cursor.fetchall()

    return events

@app.put("/lectures/{lecture_id}/stream")
def update_lecture_stream(
    lecture_id: str,
    update: LectureStreamUpdate,
):
    """
    Update the live-stream metadata for a lecture.

    KnightScribe stores only the stream location/status.
    The video itself does not pass through this API.
    """

    if (
        update.stream_status == "live"
        and not update.live_stream_url
    ):
        raise HTTPException(
            status_code=400,
            detail="A live stream must include live_stream_url"
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE lectures
                SET
                    stream_status = %s,
                    stream_protocol = %s,
                    live_stream_url = %s,
                    stream_updated_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s

                RETURNING
                    id,
                    stream_status,
                    stream_protocol,
                    live_stream_url,
                    stream_updated_at
                """,
                (
                    update.stream_status,
                    update.stream_protocol,
                    update.live_stream_url,
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

@app.get("/lectures/{lecture_id}/stream")
def get_lecture_stream(lecture_id: str):
    """
    Retrieve the current live-stream metadata
    for a lecture.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    stream_status,
                    stream_protocol,
                    live_stream_url,
                    stream_updated_at
                FROM lectures
                WHERE id = %s
                """,
                (lecture_id,),
            )

            stream = cursor.fetchone()

            if stream is None:
                raise HTTPException(
                    status_code=404,
                    detail="Lecture not found"
                )

    return stream

@app.get("/lectures/{lecture_id}/timeline")
def get_lecture_timeline(lecture_id: str):
    """
    Return transcript and whiteboard events in one
    timestamp-synchronized lecture timeline.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # Verify that the lecture exists.
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

            # Get transcript segments.
            cursor.execute(
                """
                SELECT
                    id,
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

            # Get whiteboard events.
            cursor.execute(
                """
                SELECT
                    id,
                    timestamp_seconds,
                    image_url,
                    ocr_text,
                    description,
                    event_type
                FROM board_events
                WHERE lecture_id = %s
                ORDER BY timestamp_seconds
                """,
                (lecture_id,),
            )

            board_events = cursor.fetchall()

    timeline = []

    for segment in transcript_segments:
        timeline.append(
            {
                "type": "transcript",
                "timestamp_seconds": segment["start_seconds"],
                "data": {
                    "id": segment["id"],
                    "start_seconds": segment["start_seconds"],
                    "end_seconds": segment["end_seconds"],
                    "text": segment["text"],
                },
            }
        )

    for event in board_events:
        timeline.append(
            {
                "type": "whiteboard",
                "timestamp_seconds": event["timestamp_seconds"],
                "data": {
                    "id": event["id"],
                    "image_url": event["image_url"],
                    "ocr_text": event["ocr_text"],
                    "description": event["description"],
                    "event_type": event["event_type"],
                },
            }
        )

    timeline.sort(
        key=lambda item: item["timestamp_seconds"]
    )

    return {
        "lecture_id": lecture_id,
        "event_count": len(timeline),
        "timeline": timeline,
    }

@app.get("/courses/{course_id}/search")
def search_course(
    course_id: int,
    q: str = Query(
        ...,
        min_length=2,
        description="Text to search for"
    ),
    lecture_id: str | None = None,
    max_results: int = Query(
        10,
        ge=1,
        le=25,
    ),
):
    """
    Search KnightScribe's course memory.

    Searches professor reference material,
    lecture transcripts, and whiteboard content.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT id
                FROM courses
                WHERE id = %s
                """,
                (course_id,),
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Course not found"
                )

            if lecture_id:
                cursor.execute(
                    """
                    SELECT id
                    FROM lectures
                    WHERE id = %s
                      AND course_id = %s
                    """,
                    (
                        lecture_id,
                        course_id,
                    ),
                )

                if cursor.fetchone() is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Lecture not found in this course"
                    )

    results = search_course_memory(
        course_id=course_id,
        query=q,
        lecture_id=lecture_id,
        max_results=max_results,
    )

    return {
        "course_id": course_id,
        "query": q,
        "lecture_id": lecture_id,
        "result_count": len(results),
        "results": results,
    }

@app.get("/lectures/{lecture_id}/context-window")
def get_lecture_context_window(
    lecture_id: str,
    start_seconds: float = Query(
        ...,
        ge=0,
        description="Start of the requested lecture window in seconds"
    ),
    end_seconds: float = Query(
        ...,
        ge=0,
        description="End of the requested lecture window in seconds"
    ),
):
    """
    Return transcript and whiteboard content from a specific
    time window of a lecture.

    This provides the course-only context used by features
    such as 'What Did I Miss?'.
    """

    if end_seconds <= start_seconds:
        raise HTTPException(
            status_code=400,
            detail="end_seconds must be greater than start_seconds"
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # Verify lecture exists.
            cursor.execute(
                """
                SELECT
                    id,
                    course_id,
                    title
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

            # Transcript segments that overlap the requested window.
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
                  AND end_seconds >= %s
                  AND start_seconds <= %s
                ORDER BY start_seconds
                """,
                (
                    lecture_id,
                    start_seconds,
                    end_seconds,
                ),
            )

            transcript_segments = cursor.fetchall()

            # Whiteboard events that occurred inside the window.
            cursor.execute(
                """
                SELECT
                    id,
                    timestamp_seconds,
                    image_url,
                    ocr_text,
                    description,
                    event_type
                FROM board_events
                WHERE lecture_id = %s
                  AND timestamp_seconds >= %s
                  AND timestamp_seconds <= %s
                ORDER BY timestamp_seconds
                """,
                (
                    lecture_id,
                    start_seconds,
                    end_seconds,
                ),
            )

            board_events = cursor.fetchall()

    return {
        "lecture_id": lecture["id"],
        "course_id": lecture["course_id"],
        "title": lecture["title"],
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "transcript_segments": transcript_segments,
        "board_events": board_events,
    }