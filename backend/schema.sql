-- =========================================================
-- KnightScribe Database Schema
-- =========================================================


-- ---------------------------------------------------------
-- COURSES
-- ---------------------------------------------------------
-- Represents a class using KnightScribe.
-- Example: EEL 4742 - Embedded Systems
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS courses (
    id BIGSERIAL PRIMARY KEY,

    name TEXT NOT NULL,

    code TEXT,

    professor_name TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------
-- LECTURES
-- ---------------------------------------------------------
-- One recorded classroom session.
--
-- The id is intentionally TEXT because Jack's Raspberry Pi
-- already creates IDs such as:
--
-- lecture_2026-09-26_14-31-22
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS lectures (
    id TEXT PRIMARY KEY,

    course_id BIGINT REFERENCES courses(id)
        ON DELETE CASCADE,

    title TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'recording'
        CHECK (
            status IN (
                'recording',
                'processing',
                'completed',
                'error'
            )
        ),

    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    ended_at TIMESTAMPTZ,

    live_summary TEXT,

    final_summary TEXT,

    recording_url TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------
-- TRANSCRIPT SEGMENTS
-- ---------------------------------------------------------
-- Stores small timestamped pieces of the transcript instead
-- of one giant transcript.
--
-- Example:
-- start_seconds = 842.4
-- end_seconds   = 848.7
-- text          = "Newton's second law states..."
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS transcript_segments (
    id BIGSERIAL PRIMARY KEY,

    lecture_id TEXT NOT NULL
        REFERENCES lectures(id)
        ON DELETE CASCADE,

    chunk_number INTEGER,

    start_seconds DOUBLE PRECISION NOT NULL,

    end_seconds DOUBLE PRECISION NOT NULL,

    text TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (start_seconds >= 0),

    CHECK (end_seconds >= start_seconds)
);


-- ---------------------------------------------------------
-- BOARD EVENTS
-- ---------------------------------------------------------
-- Stores meaningful whiteboard states.
--
-- The actual image can live in object storage later.
-- PostgreSQL stores the location and information about it.
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS board_events (
    id BIGSERIAL PRIMARY KEY,

    lecture_id TEXT NOT NULL
        REFERENCES lectures(id)
        ON DELETE CASCADE,

    timestamp_seconds DOUBLE PRECISION NOT NULL,

    image_url TEXT,

    ocr_text TEXT,

    description TEXT,

    event_type TEXT DEFAULT 'board_changed',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (timestamp_seconds >= 0)
);


-- ---------------------------------------------------------
-- COURSE DOCUMENTS
-- ---------------------------------------------------------
-- Materials uploaded by the professor.
--
-- Examples:
-- PowerPoint
-- PDF
-- textbook
-- notes
-- worksheet
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS course_documents (
    id BIGSERIAL PRIMARY KEY,

    course_id BIGINT NOT NULL
        REFERENCES courses(id)
        ON DELETE CASCADE,

    title TEXT NOT NULL,

    document_type TEXT,

    file_url TEXT,

    extracted_text TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------
-- COURSE SETTINGS
-- ---------------------------------------------------------
-- Lets the professor control how students can use
-- KnightScribe for a particular course.
--
-- This includes both AI permissions and access to
-- captured lecture content.
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS course_settings (
    course_id BIGINT PRIMARY KEY
        REFERENCES courses(id)
        ON DELETE CASCADE,

    explanations_allowed BOOLEAN NOT NULL DEFAULT TRUE,

    hints_allowed BOOLEAN NOT NULL DEFAULT TRUE,

    final_answers_allowed BOOLEAN NOT NULL DEFAULT FALSE,

    practice_questions_allowed BOOLEAN NOT NULL DEFAULT TRUE,

    ai_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    recording_view_allowed BOOLEAN NOT NULL DEFAULT TRUE,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------
-- INDEXES
-- ---------------------------------------------------------
-- These make common KnightScribe lookups faster.
-- ---------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_lectures_course_id
ON lectures(course_id);


CREATE INDEX IF NOT EXISTS idx_transcript_lecture_id
ON transcript_segments(lecture_id);


CREATE INDEX IF NOT EXISTS idx_transcript_lecture_time
ON transcript_segments(
    lecture_id,
    start_seconds
);


CREATE INDEX IF NOT EXISTS idx_board_lecture_id
ON board_events(lecture_id);


CREATE INDEX IF NOT EXISTS idx_board_lecture_time
ON board_events(
    lecture_id,
    timestamp_seconds
);


CREATE INDEX IF NOT EXISTS idx_documents_course_id
ON course_documents(course_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_transcript_unique_chunk
ON transcript_segments(
    lecture_id,
    chunk_number
);

-- ---------------------------------------------------------
-- QUIZ QUESTIONS
-- ---------------------------------------------------------
-- Practice questions generated from lecture/course material.
--
-- correct_option uses a zero-based index:
-- 0 = first option
-- 1 = second option
-- 2 = third option
-- etc.
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS quiz_questions (
    id BIGSERIAL PRIMARY KEY,

    lecture_id TEXT NOT NULL
        REFERENCES lectures(id)
        ON DELETE CASCADE,

    question TEXT NOT NULL,

    options TEXT[] NOT NULL,

    correct_option INTEGER NOT NULL,

    explanation TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (cardinality(options) >= 2),

    CHECK (correct_option >= 0),

    CHECK (correct_option < cardinality(options))
);


CREATE INDEX IF NOT EXISTS idx_quiz_questions_lecture_id
ON quiz_questions(lecture_id);

-- ---------------------------------------------------------
-- REFERENCE MATERIAL IMPROVEMENTS
-- ---------------------------------------------------------
-- Extra metadata for professor-provided course documents.
-- ---------------------------------------------------------

ALTER TABLE course_documents
ADD COLUMN IF NOT EXISTS original_filename TEXT;

ALTER TABLE course_documents
ADD COLUMN IF NOT EXISTS processing_status TEXT
NOT NULL DEFAULT 'ready'
CHECK (
    processing_status IN (
        'uploaded',
        'processing',
        'ready',
        'error'
    )
);

ALTER TABLE course_documents
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
NOT NULL DEFAULT NOW();


-- ---------------------------------------------------------
-- DOCUMENT CHUNKS
-- ---------------------------------------------------------
-- Documents are split into smaller searchable pieces.
--
-- Example:
-- document = Physics Textbook Chapter 4
--
-- chunk 0 = Newton's Second Law definition
-- chunk 1 = force example
-- chunk 2 = acceleration example
--
-- source_location can contain:
-- "Page 83"
-- "Slide 12"
-- "Section 4.2"
-- etc.
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,

    document_id BIGINT NOT NULL
        REFERENCES course_documents(id)
        ON DELETE CASCADE,

    chunk_index INTEGER NOT NULL,

    content TEXT NOT NULL,

    source_location TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (chunk_index >= 0),

    UNIQUE (
        document_id,
        chunk_index
    )
);


CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
ON document_chunks(document_id);

