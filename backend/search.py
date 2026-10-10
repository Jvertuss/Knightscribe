from database import get_connection


def search_course_memory(
    course_id: int,
    query: str,
    lecture_id: str | None = None,
    max_results: int = 10,
):
    """
    Search KnightScribe's course memory.

    Searches:
    - Lecture transcript segments
    - Whiteboard OCR/descriptions
    - Professor reference materials
    """

    results = []

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # -------------------------------------------------
            # REFERENCE DOCUMENTS
            # -------------------------------------------------

            cursor.execute(
                """
                SELECT
                    dc.id,
                    cd.id AS document_id,
                    cd.title,
                    dc.content,
                    dc.source_location,

                    ts_rank_cd(
                        to_tsvector(
                            'english',
                            dc.content
                        ),
                        websearch_to_tsquery(
                            'english',
                            %s
                        )
                    ) AS relevance

                FROM document_chunks AS dc

                JOIN course_documents AS cd
                    ON cd.id = dc.document_id

                WHERE cd.course_id = %s
                  AND cd.processing_status = 'ready'

                  AND to_tsvector(
                        'english',
                        dc.content
                      )
                      @@
                      websearch_to_tsquery(
                        'english',
                        %s
                      )

                ORDER BY relevance DESC

                LIMIT %s
                """,
                (
                    query,
                    course_id,
                    query,
                    max_results,
                ),
            )

            document_matches = cursor.fetchall()

            # -------------------------------------------------
            # TRANSCRIPTS
            # -------------------------------------------------

            if lecture_id:
                cursor.execute(
                    """
                    SELECT
                        ts.id,
                        l.id AS lecture_id,
                        l.title,
                        ts.text,
                        ts.start_seconds,
                        ts.end_seconds,

                        ts_rank_cd(
                            to_tsvector(
                                'english',
                                ts.text
                            ),
                            websearch_to_tsquery(
                                'english',
                                %s
                            )
                        ) AS relevance

                    FROM transcript_segments AS ts

                    JOIN lectures AS l
                        ON l.id = ts.lecture_id

                    WHERE l.course_id = %s
                      AND l.id = %s

                      AND to_tsvector(
                            'english',
                            ts.text
                          )
                          @@
                          websearch_to_tsquery(
                            'english',
                            %s
                          )

                    ORDER BY relevance DESC

                    LIMIT %s
                    """,
                    (
                        query,
                        course_id,
                        lecture_id,
                        query,
                        max_results,
                    ),
                )

            else:
                cursor.execute(
                    """
                    SELECT
                        ts.id,
                        l.id AS lecture_id,
                        l.title,
                        ts.text,
                        ts.start_seconds,
                        ts.end_seconds,

                        ts_rank_cd(
                            to_tsvector(
                                'english',
                                ts.text
                            ),
                            websearch_to_tsquery(
                                'english',
                                %s
                            )
                        ) AS relevance

                    FROM transcript_segments AS ts

                    JOIN lectures AS l
                        ON l.id = ts.lecture_id

                    WHERE l.course_id = %s

                      AND to_tsvector(
                            'english',
                            ts.text
                          )
                          @@
                          websearch_to_tsquery(
                            'english',
                            %s
                          )

                    ORDER BY relevance DESC

                    LIMIT %s
                    """,
                    (
                        query,
                        course_id,
                        query,
                        max_results,
                    ),
                )

            transcript_matches = cursor.fetchall()

            # -------------------------------------------------
            # WHITEBOARD EVENTS
            # -------------------------------------------------

            if lecture_id:
                cursor.execute(
                    """
                    SELECT
                        be.id,
                        l.id AS lecture_id,
                        l.title,
                        be.timestamp_seconds,
                        be.image_url,
                        be.ocr_text,
                        be.description,

                        ts_rank_cd(
                            to_tsvector(
                                'english',
                                COALESCE(be.ocr_text, '')
                                || ' '
                                || COALESCE(be.description, '')
                            ),
                            websearch_to_tsquery(
                                'english',
                                %s
                            )
                        ) AS relevance

                    FROM board_events AS be

                    JOIN lectures AS l
                        ON l.id = be.lecture_id

                    WHERE l.course_id = %s
                      AND l.id = %s

                      AND to_tsvector(
                            'english',
                            COALESCE(be.ocr_text, '')
                            || ' '
                            || COALESCE(be.description, '')
                          )
                          @@
                          websearch_to_tsquery(
                            'english',
                            %s
                          )

                    ORDER BY relevance DESC

                    LIMIT %s
                    """,
                    (
                        query,
                        course_id,
                        lecture_id,
                        query,
                        max_results,
                    ),
                )

            else:
                cursor.execute(
                    """
                    SELECT
                        be.id,
                        l.id AS lecture_id,
                        l.title,
                        be.timestamp_seconds,
                        be.image_url,
                        be.ocr_text,
                        be.description,

                        ts_rank_cd(
                            to_tsvector(
                                'english',
                                COALESCE(be.ocr_text, '')
                                || ' '
                                || COALESCE(be.description, '')
                            ),
                            websearch_to_tsquery(
                                'english',
                                %s
                            )
                        ) AS relevance

                    FROM board_events AS be

                    JOIN lectures AS l
                        ON l.id = be.lecture_id

                    WHERE l.course_id = %s

                      AND to_tsvector(
                            'english',
                            COALESCE(be.ocr_text, '')
                            || ' '
                            || COALESCE(be.description, '')
                          )
                          @@
                          websearch_to_tsquery(
                            'english',
                            %s
                          )

                    ORDER BY relevance DESC

                    LIMIT %s
                    """,
                    (
                        query,
                        course_id,
                        query,
                        max_results,
                    ),
                )

            board_matches = cursor.fetchall()

    # -----------------------------------------------------
    # Normalize all source types into one response shape.
    # -----------------------------------------------------

    for match in document_matches:
        results.append(
            {
                "source_type": "document",
                "title": match["title"],
                "content": match["content"],
                "document_id": match["document_id"],
                "source_location": match["source_location"],
                "lecture_id": None,
                "timestamp_seconds": None,
                "image_url": None,
                "relevance": float(match["relevance"]),
            }
        )

    for match in transcript_matches:
        results.append(
            {
                "source_type": "transcript",
                "title": match["title"],
                "content": match["text"],
                "document_id": None,
                "source_location": None,
                "lecture_id": match["lecture_id"],
                "timestamp_seconds": match["start_seconds"],
                "image_url": None,
                "relevance": float(match["relevance"]),
            }
        )

    for match in board_matches:
        content_parts = []

        if match["ocr_text"]:
            content_parts.append(match["ocr_text"])

        if match["description"]:
            content_parts.append(match["description"])

        results.append(
            {
                "source_type": "whiteboard",
                "title": match["title"],
                "content": " ".join(content_parts),
                "document_id": None,
                "source_location": None,
                "lecture_id": match["lecture_id"],
                "timestamp_seconds": match["timestamp_seconds"],
                "image_url": match["image_url"],
                "relevance": float(match["relevance"]),
            }
        )

    results.sort(
        key=lambda result: result["relevance"],
        reverse=True,
    )

    return results[:max_results]