"""
api/quiz.py

Day 6 — Adaptive Quiz & Diagnostic Agent endpoints.

Endpoints:
  POST /quiz/generate             Generate a quiz for a document
  GET  /quiz/{quiz_id}            Retrieve a specific quiz
  POST /quiz/{quiz_id}/submit     Submit answers for grading
  GET  /quiz/history              List all quizzes for the authenticated user
  GET  /quiz/status               Module status

Day 6 Quiz pipeline:
  POST /quiz/generate:
    1. Authenticate user (same dev stub as chat.py; JWT in Day 7)
    2. Verify document ownership + READY status
    3. Detect weak topics from quiz history (accuracy < 60%)
    4. Retrieve ~3 parent chunks from Qdrant (user + document filters)
    5. Generate structured MCQs grounded in retrieved material
    6. Pydantic-validate all generated questions
    7. Persist quiz to PostgreSQL
    8. Return QuizResponse

  POST /quiz/{quiz_id}/submit:
    1. Authenticate user
    2. Verify quiz ownership
    3. Load quiz from DB
    4. Compare submitted_answer == correct_answer  (DETERMINISTIC — no LLM)
    5. Calculate score and percentage (application code only)
    6. Persist QuizAttempt to PostgreSQL
    7. Return QuizSubmitResponse

Security:
  - user_id ALWAYS derived from get_current_user() dependency.
  - Users can only access their own quizzes and attempts.
  - Qdrant retrieval always filtered by authenticated user_id AND document_id.
  - API keys never returned to frontend or logged.

No SSE / streaming on Day 6. SSE is deferred to Day 7.
No frontend changes on Day 6.
"""

import json
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.db.database import get_db
from app.models.document import Document
from app.models.quiz import Quiz
from app.models.quiz_attempt import QuizAttempt
from app.schemas.quiz_schemas import (
    QuizGenerateRequest,
    QuizSubmitRequest,
    QuizResponse,
    QuizSubmitResponse,
    QuizHistoryItem,
    QuizQuestion,
    QuestionResult,
)
from app.services.quiz_service import (
    detect_weak_topics,
    retrieve_chunks_for_quiz,
    generate_quiz_questions,
    save_quiz,
    grade_quiz_attempt,
    save_quiz_attempt,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quiz", tags=["Quiz"])


from app.api.auth import get_current_user  # Day 7 authenticated user dependency



# ─── Internal helpers ──────────────────────────────────────────────────────────

def _get_document_or_raise(
    document_id: str,
    user_id: str,
    db: DBSession,
    require_ready: bool = True,
) -> Document:
    """
    Fetch and verify document ownership and optionally READY status.

    Raises:
        404: Document not found.
        403: Document belongs to a different user.
        422: Document is not READY (if require_ready=True).
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )
    if document.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this document.",
        )
    if require_ready and document.status != "READY":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Document is not ready (status: {document.status}). "
                "Wait for processing to complete before generating a quiz."
            ),
        )
    return document


def _get_quiz_or_raise(quiz_id: str, user_id: str, db: DBSession) -> Quiz:
    """
    Fetch and verify quiz ownership.

    Raises:
        404: Quiz not found.
        403: Quiz belongs to a different user.
    """
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if quiz is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quiz '{quiz_id}' not found.",
        )
    if quiz.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this quiz.",
        )
    return quiz


def _parse_quiz_questions(quiz: Quiz) -> List[QuizQuestion]:
    """Parse stored JSON questions into validated QuizQuestion list."""
    try:
        raw = json.loads(quiz.questions)
        return [QuizQuestion(**q) for q in raw]
    except Exception as exc:
        logger.error("Failed to parse quiz questions for quiz_id=%s: %s", quiz.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Quiz data is corrupted and cannot be retrieved.",
        )


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=QuizResponse, status_code=status.HTTP_201_CREATED)
def generate_quiz(
    request: QuizGenerateRequest,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    POST /quiz/generate — Generate an adaptive quiz from a document.

    Day-6 Pipeline:
      1. Verify document ownership + READY status.
      2. Determine topic:
         a. If topic is provided in the request: use it directly.
         b. If not: detect weak topics from quiz history (accuracy < 60%).
            If no weak topics exist: use a general topic prompt.
      3. Retrieve ~3 parent chunks from Qdrant (user + document security filters).
      4. Generate structured MCQs grounded in retrieved material.
      5. Pydantic-validate all generated questions.
      6. Persist quiz to PostgreSQL.
      7. Return QuizResponse.

    Security:
      - user_id is from get_current_user() — never trusted from browser.
      - Qdrant retrieval always filters by both user_id AND document_id.
    """
    document_id = request.document_id

    # Step 1: Verify document ownership + READY
    document = _get_document_or_raise(document_id, current_user, db, require_ready=True)

    # Step 2: Determine topic
    if request.topic:
        topic = request.topic.strip()
        logger.info("Quiz: User-supplied topic='%s' for doc=%s", topic, document_id)
    else:
        weak_topics = detect_weak_topics(
            user_id=current_user,
            document_id=document_id,
            db=db,
        )
        if weak_topics:
            topic = weak_topics[0]
            logger.info(
                "Quiz: Detected weak topic='%s' for user=%s doc=%s",
                topic, current_user, document_id,
            )
        else:
            # No history or all topics strong — use document subject or general
            topic = document.subject or "General Study Material"
            logger.info(
                "Quiz: No weak topics detected. Using general topic='%s'", topic
            )

    # Step 3: Retrieve ~3 parent chunks
    try:
        parent_results = retrieve_chunks_for_quiz(
            topic=topic,
            document_id=document_id,
            user_id=current_user,
        )
    except RuntimeError as exc:
        logger.error("Quiz retrieval failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document retrieval service is temporarily unavailable. Please try again.",
        )

    if not parent_results:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No relevant content found in the document for topic '{topic}'. "
                "Try a different topic or ensure the document has been processed."
            ),
        )

    # Step 4 & 5: Generate and validate MCQs
    try:
        questions = generate_quiz_questions(
            topic=topic,
            parent_results=parent_results,
            num_questions=request.num_questions,
        )
    except (RuntimeError, ValueError) as exc:
        logger.error("Quiz generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Quiz generation failed: {str(exc)}",
        )

    # Step 6: Persist quiz
    try:
        quiz = save_quiz(
            user_id=current_user,
            document_id=document_id,
            topic=topic,
            questions=questions,
            db=db,
        )
    except Exception as exc:
        logger.error("Quiz persistence failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save quiz. Please try again.",
        )

    logger.info(
        "Quiz generated: quiz_id=%s, topic='%s', questions=%d",
        quiz.id, topic, len(questions),
    )

    return QuizResponse(
        quiz_id=quiz.id,
        document_id=quiz.document_id,
        topic=quiz.topic,
        questions=questions,
        created_at=quiz.created_at.isoformat() if quiz.created_at else "",
    )


@router.get("/history", response_model=List[QuizHistoryItem])
def get_quiz_history(
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    GET /quiz/history — Return the authenticated user's quiz history.

    Returns quizzes in descending creation order (newest first).
    Each entry includes a summary of the latest attempt if available.

    Security:
      - Only returns quizzes owned by the authenticated user.
      - Never exposes another user's quizzes.
    """
    quizzes = (
        db.query(Quiz)
        .filter(Quiz.user_id == current_user)
        .order_by(Quiz.created_at.desc())
        .all()
    )

    history = []
    for quiz in quizzes:
        try:
            questions_data = json.loads(quiz.questions)
            num_questions = len(questions_data)
        except Exception:
            num_questions = 0

        # Fetch latest attempt for this quiz
        latest_attempt = (
            db.query(QuizAttempt)
            .filter(
                QuizAttempt.quiz_id == quiz.id,
                QuizAttempt.user_id == current_user,
            )
            .order_by(QuizAttempt.created_at.desc())
            .first()
        )

        item = QuizHistoryItem(
            quiz_id=quiz.id,
            document_id=quiz.document_id,
            topic=quiz.topic,
            num_questions=num_questions,
            created_at=quiz.created_at.isoformat() if quiz.created_at else "",
        )

        if latest_attempt:
            item.latest_attempt_id = latest_attempt.id
            item.latest_score = latest_attempt.score
            item.latest_percentage = latest_attempt.percentage
            item.latest_attempt_at = (
                latest_attempt.created_at.isoformat()
                if latest_attempt.created_at
                else ""
            )

        history.append(item)

    return history


@router.get("/status")
def quiz_status():
    """Status check for the quiz module."""
    return {
        "status": "active",
        "day": 6,
        "features": [
            "Adaptive Quiz & Diagnostic Agent (Agent 4)",
            "Weak-topic detection (accuracy < 60% threshold)",
            "Topic-based Qdrant retrieval (~3 parent chunks)",
            "Structured MCQ generation (Pydantic-validated)",
            "Deterministic auto-grading (no LLM for scoring)",
            "Quiz persistence (PostgreSQL)",
            "Quiz attempt persistence (PostgreSQL)",
            "Quiz history (user-isolated)",
            "Document + user security filters enforced",
        ],
        "deferred": [
            "SSE streaming (Day 7)",
            "Frontend quiz UI (Day 7)",
        ],
    }


@router.get("/{quiz_id}", response_model=QuizResponse)
def get_quiz(
    quiz_id: str,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    GET /quiz/{quiz_id} — Retrieve a specific quiz.

    Security:
      - Returns 404 if quiz does not exist.
      - Returns 403 if quiz belongs to a different user.
    """
    quiz = _get_quiz_or_raise(quiz_id, current_user, db)
    questions = _parse_quiz_questions(quiz)

    return QuizResponse(
        quiz_id=quiz.id,
        document_id=quiz.document_id,
        topic=quiz.topic,
        questions=questions,
        created_at=quiz.created_at.isoformat() if quiz.created_at else "",
    )


@router.post("/{quiz_id}/submit", response_model=QuizSubmitResponse)
def submit_quiz(
    quiz_id: str,
    request: QuizSubmitRequest,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    POST /quiz/{quiz_id}/submit — Submit answers for a quiz.

    Grading is DETERMINISTIC:
      submitted_answer == correct_answer  (exact string comparison after strip)

    The LLM is NEVER called to determine correctness.
    Score and percentage are calculated by application code only.

    Flow:
      1. Authenticate user.
      2. Verify quiz ownership.
      3. Load quiz from DB.
      4. Grade answers deterministically.
      5. Calculate score + percentage.
      6. Persist QuizAttempt.
      7. Return QuizSubmitResponse.

    Security:
      - Users can only submit their own quizzes.
      - Quiz ownership verified before grading.
    """
    # Step 1 & 2: Verify quiz ownership
    quiz = _get_quiz_or_raise(quiz_id, current_user, db)

    # Step 3 & 4: Grade deterministically
    try:
        score, percentage, results = grade_quiz_attempt(
            quiz=quiz,
            submitted_answers=request.answers,
        )
    except ValueError as exc:
        logger.error("Quiz grading failed for quiz_id=%s: %s", quiz_id, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Step 6: Persist attempt
    try:
        attempt = save_quiz_attempt(
            quiz_id=quiz_id,
            user_id=current_user,
            submitted_answers=request.answers,
            score=score,
            percentage=percentage,
            db=db,
        )
    except Exception as exc:
        logger.error("Failed to save quiz attempt: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save quiz attempt. Please try again.",
        )

    # Step 7: Return result
    question_results = [QuestionResult(**r) for r in results]

    logger.info(
        "Quiz submitted: quiz_id=%s, attempt_id=%s, score=%d, pct=%.1f%%",
        quiz_id, attempt.id, score, percentage,
    )

    return QuizSubmitResponse(
        quiz_id=quiz_id,
        attempt_id=attempt.id,
        score=score,
        total=len(results),
        percentage=round(percentage, 2),
        results=question_results,
    )
