"""
The lecture recording as context for the AI chat.

Gemini can watch video, so for a recorded lecture the chatbot also gets the
recording itself: it can answer about what was written on the board, shown on
slides or demonstrated, not only what was said.

Uploading a video to Gemini takes a while, so each lecture's recording is
uploaded once (in the background, as soon as the Pi uploads it) and Gemini's
file is remembered in lecture_ai_videos. Gemini deletes files after 48 hours;
after that the next question uploads it again.
"""

import io
import logging
import os
import threading
import time

from google import genai
from google.genai import types

from database import get_connection


logger = logging.getLogger(__name__)

KEEP_HOURS = 44      # Gemini keeps uploaded files for 48 hours: reuse ours for a little less
READY_WAIT = 45      # seconds a chat question waits for a video Gemini is still processing

_busy: set[str] = set()   # lectures being uploaded right now
_busy_lock = threading.Lock()
_table_ready = False


def _ensure_table(cursor):
    global _table_ready
    if _table_ready:
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lecture_ai_videos (
            lecture_id TEXT PRIMARY KEY
                REFERENCES lectures(id) ON DELETE CASCADE,
            file_name TEXT NOT NULL,
            file_uri TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    _table_ready = True


def _client():
    key = os.getenv("GEMINI_API_KEY")
    return genai.Client(api_key=key) if key else None


def _state(file) -> str:
    state = getattr(file, "state", None)
    return getattr(state, "name", str(state or ""))


def _forget(lecture_id: str):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_table(cursor)
            cursor.execute("DELETE FROM lecture_ai_videos WHERE lecture_id = %s", (lecture_id,))


def prepare_video(lecture_id: str) -> dict | None:
    """
    Make sure Gemini has this lecture's recording; upload it if needed.
    -> {"name", "uri", "mime"} or None (no recording, no key, or another upload is running).
    """
    client = _client()
    if client is None:
        return None
    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_table(cursor)
            cursor.execute(
                "SELECT to_regclass('lecture_recordings') IS NOT NULL AS has_table"
            )
            if not cursor.fetchone()["has_table"]:
                return None
            cursor.execute(
                "SELECT size_bytes, content_type FROM lecture_recordings WHERE lecture_id = %s",
                (lecture_id,),
            )
            recording = cursor.fetchone()
            if recording is None:
                return None
            cursor.execute(
                """
                SELECT file_name, file_uri, mime_type FROM lecture_ai_videos
                WHERE lecture_id = %s AND size_bytes = %s
                  AND uploaded_at > NOW() - make_interval(hours => %s)
                """,
                (lecture_id, recording["size_bytes"], KEEP_HOURS),
            )
            cached = cursor.fetchone()
    if cached:
        return {"name": cached["file_name"], "uri": cached["file_uri"], "mime": cached["mime_type"]}

    with _busy_lock:
        if lecture_id in _busy:
            return None  # already uploading (e.g. the background upload): don't upload twice
        _busy.add(lecture_id)
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT data FROM lecture_recordings WHERE lecture_id = %s", (lecture_id,))
                data = bytes(cursor.fetchone()["data"])
        mime = recording["content_type"] or "video/mp4"
        uploaded = client.files.upload(
            file=io.BytesIO(data),
            config=types.UploadFileConfig(mime_type=mime, display_name=lecture_id),
        )
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO lecture_ai_videos (lecture_id, file_name, file_uri, mime_type, size_bytes)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (lecture_id) DO UPDATE SET
                        file_name = EXCLUDED.file_name, file_uri = EXCLUDED.file_uri,
                        mime_type = EXCLUDED.mime_type, size_bytes = EXCLUDED.size_bytes,
                        uploaded_at = NOW()
                    """,
                    (lecture_id, uploaded.name, uploaded.uri, mime, len(data)),
                )
        logger.info("lecture video uploaded to Gemini: %s", lecture_id)
        return {"name": uploaded.name, "uri": uploaded.uri, "mime": mime}
    finally:
        with _busy_lock:
            _busy.discard(lecture_id)


def prepare_in_background(lecture_id: str):
    """Start uploading the recording to Gemini now, so the first question doesn't wait."""
    def run():
        try:
            info = prepare_video(lecture_id)
            if info:
                video_part(lecture_id, info)  # also waits until Gemini has processed it
        except Exception as error:  # the chat falls back to the transcript; nothing else depends on this
            logger.warning("preparing the lecture video for the AI failed: %s", error)

    threading.Thread(target=run, daemon=True).start()


def video_part(lecture_id: str, info: dict | None = None) -> types.Part | None:
    """
    The lecture recording as a Gemini input, once Gemini has processed it.
    None when there is no recording or it isn't ready: the chat then uses the transcript only.
    """
    client = _client()
    try:
        info = info or prepare_video(lecture_id)
        if not info or client is None:
            return None
        deadline = time.time() + READY_WAIT
        while True:
            state = _state(client.files.get(name=info["name"]))
            if state == "ACTIVE":
                return types.Part.from_uri(file_uri=info["uri"], mime_type=info["mime"])
            if state == "FAILED":
                _forget(lecture_id)
                return None
            if time.time() > deadline:
                return None  # still processing: answer from the transcript this time
            time.sleep(2)
    except Exception as error:  # e.g. Gemini already deleted the file (48 h): upload it again next time
        logger.warning("lecture video not usable (%s): %s", lecture_id, error)
        try:
            _forget(lecture_id)
        except Exception:
            pass
        return None
