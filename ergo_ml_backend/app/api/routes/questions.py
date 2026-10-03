"""
Question helpers.

GET  /api/questions                       list all 40 assessment questions
POST /api/questions/{question_id}/match   which option does a free-form answer mean?
GET  /api/questions/matcher               matcher status (is the ML model loaded?)

The app calls /match while the person speaks or types, and shows
"Understood as: <option>" so they can confirm or correct it before saving.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.domain import answer_matcher as M
from app.domain.questions import QUESTIONS_BY_ID

router = APIRouter()


@router.get("")
def list_questions():
    """Return all 40 ErgoCare assessment questions (id, text, options, category)."""
    from app.domain.questions import QUESTIONS
    return QUESTIONS


class MatchIn(BaseModel):
    text: str = Field(..., max_length=1000)
    lang: Optional[str] = Field(None, pattern=r"^(en|hi|kn|auto)$")
    labels: Optional[List[str]] = Field(None, max_length=10)   # option labels shown on screen (translated)


@router.post("/{question_id}/match")
def match(question_id: int, payload: MatchIn):
    question = QUESTIONS_BY_ID.get(question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    result = M.match_answer(question, payload.text, lang=payload.lang, labels=payload.labels)
    return {"question_id": question_id, "text": payload.text, **result.as_dict()}


@router.get("/matcher")
def matcher_status():
    return {"model": M.MODEL_NAME, "semantic_loaded": M.semantic.available,
            "layers": ["exact", "number", "yes_no", "contains", "quantity", "frequency", "intensity", "semantic"]}
