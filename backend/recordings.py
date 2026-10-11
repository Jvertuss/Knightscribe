"""
Lecture recordings stored in the database.

The classroom Pi compresses each finished lecture (480p, ~1 Mbit/s, so a
5-minute demo lecture is roughly 30 MB) and uploads it here. Students then
watch it from GET /lectures/{id}/recording, which serves the video in pieces
so the browser can start playing at once and skip around.

This is sized for short demo lectures. Long lectures belong in file storage
(for example Cloudflare R2) with only their link kept in the database.
"""

import re

from fastapi import APIRouter, Header, HTTPException, Request, Response

from database import get_connection
from lecture_video import prepare_in_background


router = APIRouter(tags=["Recordings"])

MAX_UPLOAD_BYTES = 150 * 1024 * 1024   # refuse anything larger (an uncompressed recording)
PIECE_BYTES = 2 * 1024 * 1024          # how much one range request returns at most

_table_ready = False


def _ensure_table(cursor):
    """Create the recordings table the first time it is needed."""
    global _table_ready
    if _table_ready:
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lecture_recordings (
            lecture_id TEXT PRIMARY KEY
                REFERENCES lectures(id) ON DELETE CASCADE,
            content_type TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            data BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Store the video uncompressed (it already is compressed), so reading one
    # piece only fetches that piece instead of the whole file.
    cursor.execute(
        "ALTER TABLE lecture_recordings ALTER COLUMN data SET STORAGE EXTERNAL"
    )
    _table_ready = True


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """
    "bytes=START-END" -> (start, end), both inclusive and clipped to the file.
    None when there is no usable range (send the start of the file instead).
    """
    if not header:
        return None
    match = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", header)
    if not match or (match.group(1) == "" and match.group(2) == ""):
        return None
    if match.group(1) == "":  # "bytes=-500" = the last 500 bytes
        length = int(match.group(2))
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else size - 1
    if start >= size:
        raise HTTPException(
            status_code=416,
            detail="Requested range is outside the recording",
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, min(end, size - 1)


@router.put("/lectures/{lecture_id}/recording")
async def upload_recording(lecture_id: str, request: Request):
    """
    Save a lecture's video (the raw MP4 file as the request body).
    Uploading again replaces the old video.
    """
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="The recording is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The recording is too large; compress it before uploading",
        )
    content_type = request.headers.get("content-type", "video/mp4").split(";")[0]

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM lectures WHERE id = %s", (lecture_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Lecture not found")

            _ensure_table(cursor)
            cursor.execute(
                """
                INSERT INTO lecture_recordings (lecture_id, content_type, size_bytes, data)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (lecture_id) DO UPDATE SET
                    content_type = EXCLUDED.content_type,
                    size_bytes = EXCLUDED.size_bytes,
                    data = EXCLUDED.data,
                    created_at = NOW()
                """,
                (lecture_id, content_type, len(data), data),
            )

    # give the AI chat its copy of the video now, so students' first question doesn't wait for it
    prepare_in_background(lecture_id)
    return {"lecture_id": lecture_id, "size_bytes": len(data)}


@router.get("/lectures/{lecture_id}/recording")
def get_recording(
    lecture_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
):
    """
    Stream a lecture's video. Follows the professor's recording setting,
    like GET /lectures/{lecture_id} does.
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_table(cursor)
            cursor.execute(
                """
                SELECT
                    r.size_bytes,
                    r.content_type,
                    COALESCE(cs.recording_view_allowed, FALSE) AS allowed
                FROM lecture_recordings AS r
                JOIN lectures AS l ON l.id = r.lecture_id
                LEFT JOIN course_settings AS cs ON cs.course_id = l.course_id
                WHERE r.lecture_id = %s
                """,
                (lecture_id,),
            )
            found = cursor.fetchone()
            if found is None:
                raise HTTPException(status_code=404, detail="Recording not found")
            if not found["allowed"]:
                raise HTTPException(
                    status_code=403,
                    detail="The professor has turned off recordings for this course",
                )

            size = found["size_bytes"]
            wanted = parse_range(range_header, size)
            if wanted is None:  # no range asked (a download, not the video player): the whole file
                start, end = 0, size - 1
            else:
                start, end = wanted[0], min(wanted[1], wanted[0] + PIECE_BYTES - 1)  # one piece per request

            cursor.execute(
                """
                SELECT substring(data FROM %s FOR %s) AS piece
                FROM lecture_recordings
                WHERE lecture_id = %s
                """,
                (start + 1, end - start + 1, lecture_id),  # SQL counts from 1
            )
            piece = bytes(cursor.fetchone()["piece"])

    headers = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
    if wanted is None:
        return Response(content=piece, media_type=found["content_type"], headers=headers)
    headers["Content-Range"] = f"bytes {start}-{start + len(piece) - 1}/{size}"
    # partial: the browser asks for the next piece as it plays
    return Response(content=piece, status_code=206, media_type=found["content_type"], headers=headers)
