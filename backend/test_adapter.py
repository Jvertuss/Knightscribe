
from context_adapter import prepare_ai_context

sample_sources = [
    {
        "source_id": "document_chunk:12",
        "source_type": "document",
        "title": "Physics Lecture",
        "content": "Newton's Second Law is F = ma.",
        "source_location": "Slide 4",
        "lecture_id": None,
        "timestamp_seconds": None,
        "relevance": 0.85
    }
]

context = prepare_ai_context(sample_sources)

assert len(context) == 1
assert context[0]["source_type"] == "document"
assert context[0]["source_id"] == "document_chunk:12"
assert context[0]["source_location"] == "Slide 4"

print("Context adapter passed!")
print(context)
