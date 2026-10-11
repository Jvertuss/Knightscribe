
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AIMode(str, Enum):
    EXPLAIN = "explain"
    SUMMARIZE = "summarize"
    STUDY_GUIDE = "study_guide"
    QUIZ = "quiz"


class SourceType(str, Enum):
    DOCUMENT = "document"
    TRANSCRIPT = "transcript"
    BOARD_EVENT = "board_event"


class ContextItem(BaseModel):
    source_id: str
    source_type: SourceType
    title: str
    content: str
    source_location: Optional[str] = None
    lecture_id: Optional[str] = None
    timestamp_seconds: Optional[float] = None


class AIRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: AIMode = AIMode.EXPLAIN
    context: list[ContextItem] = Field(
        default_factory=list
    )


class AIResponse(BaseModel):
    answer: str
    source_ids: list[str] = Field(
        default_factory=list
    )
