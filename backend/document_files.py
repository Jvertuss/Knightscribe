"""
The original files of the professor's reference material (PDF, PowerPoint,
text), so students can download them.

main.py's upload endpoint calls save_document_file() in the same transaction
that stores the document's text. Documents uploaded before this existed have
no file to download (only their text was kept).
"""

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from database import get_connection


router = APIRouter(tags=["Reference material"])

_table_ready = False


def _ensure_table(cursor):
    global _table_ready
    if _table_ready:
        return
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_document_files (
            document_id BIGINT PRIMARY KEY
                REFERENCES course_documents(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            data BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    _table_ready = True


def save_document_file(cursor, document_id: int, filename: str, content_type: str | None, data: bytes):
    _ensure_table(cursor)
    cursor.execute(
        """
        INSERT INTO course_document_files (document_id, filename, content_type, data)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (document_id) DO UPDATE SET
            filename = EXCLUDED.filename,
            content_type = EXCLUDED.content_type,
            data = EXCLUDED.data
        """,
        (document_id, filename, content_type or "application/octet-stream", data),
    )


@router.get("/courses/{course_id}/documents/{document_id}/file")
def download_document(course_id: int, document_id: int):
    """Download a reference document's original file."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            _ensure_table(cursor)
            cursor.execute(
                """
                SELECT f.filename, f.content_type, f.data
                FROM course_document_files AS f
                JOIN course_documents AS d ON d.id = f.document_id
                WHERE f.document_id = %s AND d.course_id = %s
                """,
                (document_id, course_id),
            )
            found = cursor.fetchone()
    if found is None:
        raise HTTPException(
            status_code=404,
            detail="This document's file isn't available (only its text was saved). Upload it again.",
        )
    name = found["filename"]
    return Response(
        content=bytes(found["data"]),
        media_type=found["content_type"],
        headers={
            # the original name, also for names with spaces or accents
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        },
    )
