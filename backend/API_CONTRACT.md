# KnightScribe Backend API Contract

## Public Backend

Base URL:

https://knightscribe-api.onrender.com

Swagger:

https://knightscribe-api.onrender.com/docs


## Courses

GET /courses

GET /courses/{course_id}

GET /courses/{course_id}/lectures


## Lectures

POST /lectures

GET /lectures/{lecture_id}

POST /lectures/{lecture_id}/end

PUT /lectures/{lecture_id}/complete


## Transcript

POST /lectures/{lecture_id}/transcript


## Live Summary

PUT /lectures/{lecture_id}/live-summary


## Whiteboard

POST /lectures/{lecture_id}/board-events

GET /lectures/{lecture_id}/board-events


## Unified Timeline

GET /lectures/{lecture_id}/timeline

## Lecture Context Window

GET /lectures/{lecture_id}/context-window

Query parameters:

- start_seconds - beginning of requested lecture window
- end_seconds - end of requested lecture window

Returns:

- Transcript segments overlapping the requested time range
- Whiteboard events occurring inside the requested time range

This endpoint provides the lecture context used by features such as
"What Did I Miss?"


## Course Memory Search

GET /courses/{course_id}/search

Query parameters:

- q - search text
- lecture_id - optional lecture filter
- max_results - optional result limit

Searches:

- Professor reference materials
- Lecture transcripts
- Whiteboard OCR and descriptions

Results include source type, lecture timestamp, slide/page location,
and whiteboard image URL when applicable.

## Live Video Metadata

PUT /lectures/{lecture_id}/stream

GET /lectures/{lecture_id}/stream


## Quiz Questions

POST /lectures/{lecture_id}/quiz-questions

GET /lectures/{lecture_id}/quiz-questions

POST /quiz-questions/{question_id}/answer


## Professor Course Settings

GET /courses/{course_id}/settings

PUT /courses/{course_id}/settings


## Professor Reference Materials

POST /courses/{course_id}/documents

POST /courses/{course_id}/documents/upload

GET /courses/{course_id}/documents

GET /courses/{course_id}/documents/{document_id}


## AI Retrieval

POST /courses/{course_id}/ai-context

The AI retrieval endpoint searches only KnightScribe course material:

- Professor reference documents
- Lecture transcripts
- Whiteboard OCR and descriptions

Results may include slide/page references or lecture timestamps.

It does not perform internet searches.

The final chatbot endpoint will be added after AI-service integration.

## Important Integration Rules

### Lecture IDs

Lecture IDs are strings such as:

lecture_2026-10-10_11-30-00


### Timestamps

All lecture-relative timestamps use seconds.

Example:

842.4 = 14 minutes, 2.4 seconds


### Lecture Status

Possible values:

recording
processing
completed
error


### Stream Status

Possible values:

offline
starting
live
ended
error


### Stream Protocol

Possible values:

hls
webrtc
mjpeg
other


### Frontend

React should communicate with FastAPI.

React should NOT connect directly to Neon.


### Hardware / AI

Jack and Yoni should send processed data to FastAPI.

Large media files and live video should not be stored directly in PostgreSQL.