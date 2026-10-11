"""
Lecture transcription with Whisper (faster-whisper), on the backend's computer.

The classroom Pi records the microphone in 15-second WAV pieces. Its cloud.py
uploads each finished piece here:

    PUT /lectures/{lecture_id}/audio/{index}?start=<seconds>   (body: the WAV file)

A background worker transcribes the pieces one by one and saves the lines in
transcript_segments, timed on the recording's clock. A piece's lines are
numbered index * 1000 + n, so uploading a piece again replaces its lines.

GET /whisper tells the Pi whether Whisper is available here (the Pi then sends
audio; otherwise it sends its own streaming transcript, as before).
GET /lectures/{lecture_id}/audio/pending says how many pieces are still waiting.

Settings (environment): WHISPER_MODEL (default small.en), WHISPER_THREADS (4).
Needs: pip install -r requirements-whisper.txt
"""

import io
import logging
import os
import queue
import threading
import wave

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request

from database import get_connection


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Whisper transcription"])

MODEL_NAME = os.getenv("WHISPER_MODEL", "small.en")
THREADS = int(os.getenv("WHISPER_THREADS", "4"))
LINES_PER_PIECE = 1000
# Whisper invents stock phrases over silence: drop them when it is unsure
STOCK_PHRASES = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "okay"}

try:
    from faster_whisper import WhisperModel
    AVAILABLE = True
except ImportError:  # Whisper not installed here: the Pi keeps sending its own transcript
    AVAILABLE = False

_jobs: "queue.Queue[tuple[str, int, float, np.ndarray]]" = queue.Queue()
_pending: dict[str, int] = {}          # lecture -> pieces queued or being transcribed
_previous: dict[str, str] = {}         # lecture -> last words, as context for the next piece
_lock = threading.Lock()
_model = None
_worker_started = False


def _read_wav(data: bytes) -> np.ndarray:
    """16 kHz mono 16-bit WAV (what the Pi records) -> float32 samples."""
    with wave.open(io.BytesIO(data)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("audio must be 16 kHz mono 16-bit WAV")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _transcribe(samples: np.ndarray, previous: str) -> list[tuple[float, float, str]]:
    global _model
    if _model is None:
        logger.info("loading Whisper model %s", MODEL_NAME)
        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=THREADS)
    segments, _ = _model.transcribe(
        samples,
        language="en",
        beam_size=1,
        vad_filter=True,                      # skip silence: faster, fewer invented words
        condition_on_previous_text=False,     # stops the model repeating itself
        initial_prompt=previous[-150:] or None,
    )
    lines = []
    for s in segments:
        text = s.text.strip()
        if not text or s.no_speech_prob >= 0.8:
            continue
        if text.lower().strip(" .!,") in STOCK_PHRASES and (s.no_speech_prob > 0.3 or s.avg_logprob < -0.6):
            continue
        lines.append((s.start, s.end, text))
    return lines


def _worker():
    while True:
        lecture_id, index, start, samples = _jobs.get()
        try:
            lines = _transcribe(samples, _previous.get(lecture_id, ""))
            first = index * LINES_PER_PIECE
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    # replace this piece's lines (a piece can be uploaded again)
                    cursor.execute(
                        "DELETE FROM transcript_segments WHERE lecture_id = %s AND chunk_number BETWEEN %s AND %s",
                        (lecture_id, first, first + LINES_PER_PIECE - 1),
                    )
                    for n, (a, b, text) in enumerate(lines[:LINES_PER_PIECE]):
                        cursor.execute(
                            """
                            INSERT INTO transcript_segments (lecture_id, chunk_number, start_seconds, end_seconds, text)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (lecture_id, chunk_number) DO UPDATE SET
                                start_seconds = EXCLUDED.start_seconds,
                                end_seconds = EXCLUDED.end_seconds,
                                text = EXCLUDED.text
                            """,
                            (lecture_id, first + n, round(start + a, 2), round(start + max(a, b), 2), text),
                        )
            if lines:
                _previous[lecture_id] = (_previous.get(lecture_id, "") + " " + " ".join(t for _, _, t in lines))[-300:]
        except Exception as error:  # one bad piece must not stop the lecture
            logger.warning("Whisper failed on %s piece %s: %s", lecture_id, index, error)
        finally:
            with _lock:
                _pending[lecture_id] = max(0, _pending.get(lecture_id, 1) - 1)
            _jobs.task_done()


def _start_worker():
    global _worker_started
    with _lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True).start()
            _worker_started = True


def _preload():  # load the model when the server starts, so the first lecture doesn't wait for it
    global _model
    try:
        if _model is None:
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=THREADS)
            logger.info("Whisper model %s ready", MODEL_NAME)
    except Exception as error:
        logger.warning("Whisper model could not be loaded yet: %s", error)


if AVAILABLE:
    threading.Thread(target=_preload, daemon=True).start()


@router.get("/whisper")
def whisper_status():
    return {"available": AVAILABLE, "model": MODEL_NAME if AVAILABLE else None, "queued": _jobs.qsize()}


@router.put("/lectures/{lecture_id}/audio/{index}")
async def upload_audio_piece(
    lecture_id: str,
    index: int,
    request: Request,
    start: float = Query(..., ge=0, description="where this piece starts on the recording clock, in seconds"),
):
    if not AVAILABLE:
        raise HTTPException(status_code=503, detail="Whisper isn't installed on this server.")
    if index < 0 or index > 100000:
        raise HTTPException(status_code=400, detail="Bad piece number")
    try:
        samples = _read_wav(await request.body())
    except (ValueError, wave.Error, EOFError) as error:
        raise HTTPException(status_code=400, detail=f"Unreadable audio: {error}")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM lectures WHERE id = %s", (lecture_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Lecture not found")
    _start_worker()
    with _lock:
        _pending[lecture_id] = _pending.get(lecture_id, 0) + 1
    _jobs.put((lecture_id, index, start, samples))
    return {"lecture_id": lecture_id, "index": index, "queued": True}


@router.get("/lectures/{lecture_id}/audio/pending")
def audio_pending(lecture_id: str):
    with _lock:
        return {"lecture_id": lecture_id, "pending": _pending.get(lecture_id, 0)}
