
import os
import logging

from dotenv import load_dotenv
from fastapi import HTTPException
from google import genai
from google.genai import types, errors
from pydantic import ValidationError

from schemas import AIRequest, AIResponse
from prompts import SYSTEM_PROMPT, build_user_prompt


# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Gemini model
MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.8-flash"
)


def generate_ai_answer(request: AIRequest) -> AIResponse:
    """
    Generate a Gemini answer using supplied
    professor-approved course context.
    """

    # 1. Handle missing context
    if not request.context:
        return AIResponse(
            answer=(
                "The provided course materials do not "
                "contain enough information to answer "
                "this question."
            ),
            source_ids=[]
        )

    # 2. Load Gemini API key
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key is not configured."
        )

    # 3. Build prompt from lecture context
    user_prompt = build_user_prompt(
        question=request.question,
        mode=request.mode,
        context=request.context
    )

    # 4. Send request to Gemini
    try:
        with genai.Client(api_key=api_key) as client:
            response = client.models.generate_content(
                model=MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=AIResponse,
                    max_output_tokens=2048
                )
            )

    except errors.APIError as error:
        logger.error(
            "Gemini API failed with status: %s",
            error.code
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Gemini API request failed "
                f"(provider status {error.code})."
            )
        ) from error

    # 5. Validate Gemini's generated response
    try:
        if isinstance(response.parsed, AIResponse):
            result = response.parsed
        elif response.parsed is not None:
            result = AIResponse.model_validate(
                response.parsed
            )
        else:
            result = AIResponse.model_validate_json(
                response.text or ""
            )

    except (ValidationError, ValueError, TypeError) as error:
        logger.warning(
            "Gemini returned an invalid response."
        )

        raise HTTPException(
            status_code=502,
            detail="Gemini returned an invalid answer."
        ) from error

    # 6. Validate source IDs
    valid_ids = {
        item.source_id for item in request.context
    }

    result.source_ids = list(dict.fromkeys(
        source_id
        for source_id in result.source_ids
        if source_id in valid_ids
    ))

    # 7. Reject answers with no valid citations
    if not result.source_ids:
        return AIResponse(
            answer=(
                "I couldn't find enough supported "
                "information in the provided course "
                "materials to answer this request."
            ),
            source_ids=[]
        )

    # 8. Return structured AI response
    return result
