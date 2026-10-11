
SOURCE_TYPE_MAP = {
    "document": "document",
    "lecture": "transcript",
    "whiteboard": "board_event"
}


def prepare_ai_context(sources: list[dict]) -> list[dict]:
    """
    Convert retrieved KnightScribe sources
    into the format expected by Gemini.
    """

    context = []

    for source in sources:

        source_type = SOURCE_TYPE_MAP.get(
            source.get("source_type")
        )

        if source_type is None:
            continue

        source_id = source.get("source_id")
        content = (source.get("content") or "").strip()

        if not source_id or not content:
            continue

        context.append({
            "source_id": source_id,
            "source_type": source_type,
            "title": source["title"],
            "content": content[:3000],
            "source_location": source.get(
                "source_location"
            ),
            "lecture_id": source.get("lecture_id"),
            "timestamp_seconds": source.get(
                "timestamp_seconds"
            )
        })

    return context
