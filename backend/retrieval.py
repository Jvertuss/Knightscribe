from database import get_connection


def search_course_context(
    course_id: int,
    query: str,
    lecture_id: str | None = None,
    max_sources: int = 6,
):
    """
    Search professor-approved course documents,
    lecture transcripts, and whiteboard content
    for information relevant to a student's question.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # ---------------------------------------------
            # Search professor-provided reference material
            # ---------------------------------------------
            cursor.execute(
                """
                SELECT
                    dc.id AS chunk_id,
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
                    max_sources,
                ),
            )

            document_results = cursor.fetchall()

            # ---------------------------------------------
            # Search lecture transcripts
            # ---------------------------------------------

            if lecture_id:
                cursor.execute(
                    """
                    SELECT
                        ts.id AS segment_id,
                        l.id AS lecture_id,
                        l.title,
                        ts.text AS content,
                        ts.start_seconds,

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
                        max_sources,
                    ),
                )

            else:
                cursor.execute(
                    """
                    SELECT
                        ts.id AS segment_id,
                        l.id AS lecture_id,
                        l.title,
                        ts.text AS content,
                        ts.start_seconds,

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
                        max_sources,
                    ),
                )

            lecture_results = cursor.fetchall()

            # ---------------------------------------------------------
            # WHITEBOARD CONTENT
            # ---------------------------------------------------------

            if lecture_id:
                cursor.execute(
                    """
                    SELECT
                        be.id,
                        l.id AS lecture_id,
                        l.title,
                        be.timestamp_seconds,
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
                    """,
                    (
                        query,
                        course_id,
                        lecture_id,
                        query,
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
                    """,
                    (
                        query,
                        course_id,
                        query,
                    ),
                )

            board_matches = cursor.fetchall()

    # ---------------------------------------------
    # Convert everything into one source format
    # ---------------------------------------------

    sources = []

    for result in document_results:
        sources.append(
            {
                "source_type": "document",
                "document_id": result["document_id"],
                "title": result["title"],
                "content": result["content"],
                "source_location": result["source_location"],
                "lecture_id": None,
                "timestamp_seconds": None,
                "relevance": float(result["relevance"]),
            }
        )

    for result in lecture_results:
        sources.append(
            {
                "source_type": "lecture",
                "document_id": None,
                "title": result["title"],
                "content": result["content"],
                "source_location": None,
                "lecture_id": result["lecture_id"],
                "timestamp_seconds": result["start_seconds"],
                "relevance": float(result["relevance"]),
            }
        )
    
    for match in board_matches:
        content_parts = []

        if match["ocr_text"]:
            content_parts.append(match["ocr_text"])

        if match["description"]:
            content_parts.append(match["description"])

        sources.append(
            {
                "source_type": "whiteboard",
                "document_id": None,
                "title": match["title"],
                "content": " ".join(content_parts),
                "source_location": None,
                "lecture_id": match["lecture_id"],
                "timestamp_seconds": match["timestamp_seconds"],
                "relevance": float(match["relevance"]),
            }
        )    

    sources.sort(
        key=lambda source: source["relevance"],
        reverse=True,
    )

    return sources[:max_sources]