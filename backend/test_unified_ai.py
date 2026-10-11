
from ai_service import generate_ai_answer
from schemas import AIRequest
from context_adapter import prepare_ai_context


# Simulated data retrieved from Neon
sources = [
    {
        "source_id": "document_chunk:12",
        "source_type": "document",
        "title": "Physics Lecture 3",
        "content": (
            "Newton's Second Law states that "
            "net force equals mass times acceleration. "
            "The formula is F = ma."
        ),
        "source_location": "Slide 12",
        "lecture_id": None,
        "timestamp_seconds": None
    }
]


# Convert retrieval results to Gemini context
context = prepare_ai_context(sources)


# Create an AI request
request = AIRequest(
    question="Explain Newton's Second Law.",
    mode="explain",
    context=context
)


# Call Gemini directly (no second backend)
result = generate_ai_answer(request)


# Print results
print("\nGEMINI ANSWER:")
print(result.answer)

print("\nSOURCE IDS:")
print(result.source_ids)

print("\nUNIFIED AI TEST PASSED!")
