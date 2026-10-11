"""
The student chatbot: POST /courses/{course_id}/ask

It answers ONLY from this course's material: the professor's reference
documents plus what was said in the lectures (transcript). Nothing from the
internet or the model's general knowledge. Board / slide text is left out on
purpose: the classroom camera's OCR misreads it, so it is shown to students
as photos only.

1. Check the professor's course settings (AI on/off, hints, explanations,
   final answers). The browser's own copy of the settings is never trusted.
2. Gather course material: a keyword search across the course's documents and
   transcripts, plus the current lecture's whole transcript.
3. Ask Gemini (ai_service.generate_ai_answer), which must cite the sources it
   used; answers without a valid citation are replaced by "not enough info".
4. Return the answer and the cited sources, so the page can link to them.
"""

import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ai_service import generate_ai_answer
from context_adapter import prepare_ai_context
from database import get_connection
from retrieval import search_course_context
from schemas import AIMode, AIRequest, ContextItem


router = APIRouter(tags=["AI chat"])

MAX_SEARCH_SOURCES = 8
LECTURE_TEXT_LIMIT = 12000  # characters of the current lecture's transcript always included

# the chat buttons on the student page -> the AI's answer style
MODES = {
    "ask": AIMode.ASK,
    "hint": AIMode.HINT,
    "explain": AIMode.EXPLAIN,
    "answer": AIMode.ANSWER,
}

# the professor's switch that must be on for each button
REQUIRED_SETTING = {
    "hint": ("hints_allowed", "Your professor has turned off hints for this course."),
    "explain": ("explanations_allowed", "Your professor has turned off explanations for this course."),
    "answer": ("final_answers_allowed", "Your professor has turned off final answers for this course."),
}


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    mode: Literal["ask", "hint", "explain", "answer"] = "ask"
    lecture_id: str | None = None  # the lecture the student has open


def keyword_query(message: str) -> str:
    """
    "What does Newton's second law say?" -> "newton or second or law or say".
    The course search needs every word of a plain question to match; joining the
    words with OR finds passages that share any of them (best matches first).
    """
    words = re.findall(r"[A-Za-z0-9]{3,}", message.lower())
    return " or ".join(dict.fromkeys(words)) or message


def lecture_context(lecture_id: str) -> list[ContextItem]:
    """The open lecture's transcript, oldest first."""
    items: list[ContextItem] = []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT title FROM lectures WHERE id = %s", (lecture_id,))
            lecture = cursor.fetchone()
            if lecture is None:
                return items
            cursor.execute(
                """
                SELECT id, start_seconds, text
                FROM transcript_segments
                WHERE lecture_id = %s
                ORDER BY start_seconds
                """,
                (lecture_id,),
            )
            used = 0
            for row in cursor.fetchall():
                text = (row["text"] or "").strip()
                if not text:
                    continue
                if used + len(text) > LECTURE_TEXT_LIMIT:
                    break
                used += len(text)
                items.append(ContextItem(
                    source_id=f"transcript:{row['id']}",
                    source_type="transcript",
                    title=lecture["title"],
                    content=text,
                    lecture_id=lecture_id,
                    timestamp_seconds=row["start_seconds"],
                ))
    return items


@router.post("/courses/{course_id}/ask")
def ask(course_id: int, request: AskRequest):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # 1. the professor's settings, read from the database
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COALESCE(cs.ai_enabled, FALSE) AS ai_enabled,
                    COALESCE(cs.hints_allowed, FALSE) AS hints_allowed,
                    COALESCE(cs.explanations_allowed, FALSE) AS explanations_allowed,
                    COALESCE(cs.final_answers_allowed, FALSE) AS final_answers_allowed
                FROM courses AS c
                LEFT JOIN course_settings AS cs ON cs.course_id = c.id
                WHERE c.id = %s
                """,
                (course_id,),
            )
            settings = cursor.fetchone()
            if settings is None:
                raise HTTPException(status_code=404, detail="Course not found")
            if request.lecture_id:
                cursor.execute(
                    "SELECT id FROM lectures WHERE id = %s AND course_id = %s",
                    (request.lecture_id, course_id),
                )
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail="Lecture not found in this course")

    if not settings["ai_enabled"]:
        raise HTTPException(status_code=403, detail="AI help is turned off for this course.")
    if request.mode in REQUIRED_SETTING:
        setting, refusal = REQUIRED_SETTING[request.mode]
        if not settings[setting]:
            raise HTTPException(status_code=403, detail=refusal)

    # 2. course material: keyword search across the course + the open lecture itself
    found = search_course_context(
        course_id=course_id,
        query=keyword_query(message),
        lecture_id=request.lecture_id,
        max_sources=MAX_SEARCH_SOURCES,
    )
    found = [item for item in found if item.get("source_type") != "whiteboard"]  # OCR text: not reliable
    context = [ContextItem(**item) for item in prepare_ai_context(found)]
    if request.lecture_id:
        seen = {item.source_id for item in context}
        context += [item for item in lecture_context(request.lecture_id) if item.source_id not in seen]

    # 3. Gemini, grounded in that material only
    result = generate_ai_answer(AIRequest(question=message, mode=MODES[request.mode], context=context))

    # 4. the answer + the sources it cited
    by_id = {item.source_id: item for item in context}
    sources = [
        {
            "source_id": source_id,
            "source_type": by_id[source_id].source_type.value,
            "title": by_id[source_id].title,
            "source_location": by_id[source_id].source_location,
            "lecture_id": by_id[source_id].lecture_id,
            "timestamp_seconds": by_id[source_id].timestamp_seconds,
        }
        for source_id in result.source_ids
        if source_id in by_id
    ]
    return {"answer": result.answer, "mode": request.mode, "sources": sources}
