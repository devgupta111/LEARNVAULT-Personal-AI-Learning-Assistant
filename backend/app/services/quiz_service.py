"""
services/quiz_service.py

Day 6 — Adaptive Quiz & Diagnostic Agent (Agent 4).

Responsibilities:
  - Identifies weak topics (accuracy < 60%) from the user's quiz history.
  - Retrieves approximately 3 relevant parent chunks from Qdrant using the
    existing embedding + Qdrant + reranker pipeline (no new retrieval code).
  - Generates structured MCQs grounded in retrieved study material.
  - Validates all LLM output using Pydantic before saving.
  - Stores quizzes and attempts in PostgreSQL.
  - Performs DETERMINISTIC auto-grading (submitted_answer == correct_answer).

What the quiz service does NOT do:
  - Use LLM to decide whether an MCQ answer is correct (score is app-calculated).
  - Bypass user_id / document_id security filters.
  - Access another user's documents or quizzes.
  - Use outside knowledge for question generation (only retrieved material).

Security:
  - user_id is ALWAYS derived from get_current_user() — never trusted from browser.
  - Qdrant retrieval always uses authenticated user_id AND document_id.
  - Quiz ownership is verified on every access.

Weak-topic threshold: accuracy < 60% (brain.md spec).
Quiz retrieval: approximately 3 parent chunks per weak topic.
"""

import json
import logging
import re
import uuid
from typing import List, Dict, Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.quiz import Quiz
from app.models.quiz_attempt import QuizAttempt
from app.schemas.quiz_schemas import QuizQuestion

logger = logging.getLogger(__name__)

# Weak topic threshold (brain.md spec: accuracy < 60%)
WEAK_TOPIC_THRESHOLD = 0.60

# Number of parent chunks to retrieve per weak topic (brain.md spec: ~3)
QUIZ_RETRIEVAL_TOP_K = 3

# Number of Qdrant candidates before reranking
QUIZ_RETRIEVAL_TOP_N = 9

QUIZ_SYSTEM_PROMPT = """You are an expert educational quiz generator for a student study assistant.

Your job is to create multiple-choice questions (MCQs) grounded ENTIRELY in the provided study material.

CRITICAL RULES:
1. ALL questions must be based on information PRESENT in the provided context.
2. Do NOT use outside knowledge or invent facts.
3. Each question must have exactly 4 options.
4. correct_answer must be exactly one of the options (verbatim match).
5. explanation should briefly explain why the correct answer is right.

Output ONLY valid JSON as an array of objects. Each object must match:
{
  "question": "...",
  "options": ["option A", "option B", "option C", "option D"],
  "correct_answer": "option A",
  "topic": "...",
  "explanation": "..."
}

Do NOT include markdown, preamble, or any text outside the JSON array.
Output ONLY the JSON array: [ {...}, {...}, ... ]"""


def _get_quiz_client() -> Tuple[object, str]:
    """
    Obtain the Groq client and model name for quiz generation.

    Uses QUIZ_API_KEY if configured; otherwise falls back to RAG_API_KEY.
    Uses QUIZ_MODEL (default: openai/gpt-oss-120b).

    Raises:
        RuntimeError: If neither QUIZ_API_KEY nor RAG_API_KEY is configured.
            Set QUIZ_API_KEY=<your-groq-api-key> in your .env file.
    """
    api_key = settings.QUIZ_API_KEY or settings.RAG_API_KEY
    if not api_key:
        raise RuntimeError(
            "Neither QUIZ_API_KEY nor RAG_API_KEY is configured. "
            "Set QUIZ_API_KEY=<your-groq-api-key> in your .env file."
        )

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except ImportError as exc:
        raise RuntimeError(
            "The 'groq' package is required. Install it with: pip install groq"
        ) from exc

    model = settings.QUIZ_MODEL or "openai/gpt-oss-120b"
    logger.debug("Quiz: using model=%s with QUIZ_API_KEY", model)
    return client, model


def detect_weak_topics(
    user_id: str,
    document_id: str,
    db: DBSession,
) -> List[str]:
    """
    Identify weak topics for a given user and document using quiz history.

    Weak topic rule (brain.md spec): accuracy < 60%
    Accuracy = (correct answers) / (total questions) across ALL attempts for a topic.

    Args:
        user_id:     Authenticated user (never trusted from browser).
        document_id: Authenticated document.
        db:          SQLAlchemy session.

    Returns:
        List of weak topic strings (empty if no history or all topics are strong).
    """
    # Fetch all quizzes for this user+document ordered newest first
    quizzes = (
        db.query(Quiz)
        .filter(Quiz.user_id == user_id, Quiz.document_id == document_id)
        .order_by(Quiz.created_at.desc())
        .all()
    )

    if not quizzes:
        return []

    # Map each unique topic to its latest attempt accuracy
    latest_topic_acc: Dict[str, float] = {}

    for quiz in quizzes:
        topic = quiz.topic or "General"
        if topic in latest_topic_acc:
            continue  # Already obtained the newest result for this topic

        latest_attempt = (
            db.query(QuizAttempt)
            .filter(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user_id)
            .order_by(QuizAttempt.created_at.desc())
            .first()
        )

        if latest_attempt is not None:
            # QuizAttempt stores percentage (0-100) or score
            acc = latest_attempt.percentage / 100.0 if latest_attempt.percentage is not None else (
                latest_attempt.score / 5.0
            )
            latest_topic_acc[topic] = acc

    weak_topics = [
        topic for topic, acc in latest_topic_acc.items()
        if acc < WEAK_TOPIC_THRESHOLD
    ]

    logger.info(
        "Weak topic detection for user=%s doc=%s: weak_topics=%s",
        user_id, document_id, weak_topics,
    )
    return weak_topics



def retrieve_chunks_for_quiz(
    topic: str,
    document_id: str,
    user_id: str,
) -> List[Dict]:
    """
    Retrieve approximately QUIZ_RETRIEVAL_TOP_K parent chunks for quiz generation.

    Reuses the existing search_and_rerank pipeline with authenticated filters.
    This is NOT new retrieval code — it reuses the Day-4 pipeline.

    Security:
        Always filters by authenticated user_id AND document_id.
        Never retrieves chunks from another user's documents.

    Args:
        topic:       Search query / topic for retrieval.
        document_id: Authenticated document ID (security filter).
        user_id:     Authenticated user ID (security filter).

    Returns:
        List of parent context dicts (may be fewer than QUIZ_RETRIEVAL_TOP_K
        if the document doesn't have enough relevant content).
    """
    from app.services.reranker_service import search_and_rerank

    try:
        parent_results, is_weak = search_and_rerank(
            query=topic,
            document_id=document_id,
            user_id=user_id,
            top_n=QUIZ_RETRIEVAL_TOP_N,
            threshold=0.0,           # Accept all results for quiz context — grading is handled by LLM
            top_k=QUIZ_RETRIEVAL_TOP_K,
        )
        logger.info(
            "Quiz retrieval: topic='%s', retrieved %d parent chunks (is_weak=%s)",
            topic, len(parent_results), is_weak,
        )
        return parent_results
    except Exception as exc:
        logger.error("Quiz retrieval failed for topic='%s': %s", topic, exc)
        raise RuntimeError(f"Quiz retrieval failed: {exc}") from exc


def generate_quiz_questions(
    topic: str,
    parent_results: List[Dict],
    num_questions: int = 5,
) -> List[QuizQuestion]:
    """
    Generate structured MCQs grounded in the retrieved study material.

    Uses the QUIZ_API_KEY / QUIZ_MODEL LLM to generate questions.
    Validates all output with Pydantic before returning.
    Rejects malformed output rather than passing invalid questions silently.

    Args:
        topic:          Topic label for the questions.
        parent_results: Retrieved parent context chunks (from retrieve_chunks_for_quiz).
        num_questions:  Number of MCQs to generate.

    Returns:
        List of validated QuizQuestion objects.

    Raises:
        RuntimeError: If LLM call fails or output cannot be parsed/validated.
        ValueError:   If the LLM produces 0 valid questions after validation.
    """
    if not parent_results:
        raise ValueError("No study material retrieved — cannot generate quiz questions.")

    # Build context block
    context_blocks = []
    for i, ctx in enumerate(parent_results, start=1):
        page_start = ctx.get("page_start", "?")
        page_end = ctx.get("page_end", "?")
        text = ctx.get("parent_text") or ctx.get("text") or ""
        context_blocks.append(
            f"[Passage {i} | Page {page_start}-{page_end}]\n{text[:3000]}"
        )
    context_str = "\n\n".join(context_blocks)

    user_message = (
        f"TOPIC: {topic}\n\n"
        f"STUDY MATERIAL:\n{context_str}\n\n"
        f"Generate exactly {num_questions} multiple-choice questions based ONLY on "
        f"the study material above. Output ONLY a JSON array of {num_questions} objects."
    )

    messages = [
        {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        client, model = _get_quiz_client()
        logger.info(
            "Quiz generation: topic='%s', num_questions=%d, model=%s",
            topic, num_questions, model,
        )

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 4096,
            "stream": False,
        }

        response = client.chat.completions.create(**kwargs)
        raw_content = response.choices[0].message.content or "[]"

    except Exception as exc:
        logger.error("Quiz LLM call failed: %s", exc)
        raise RuntimeError(f"Quiz generation LLM error: {exc}") from exc

    # Parse JSON — handle both raw array and common wrapping patterns
    parsed_list = None
    try:
        parsed_list = json.loads(raw_content)
    except json.JSONDecodeError:
        # Try to extract a JSON array from the raw content
        match = re.search(r"\[.*?\]", raw_content, re.DOTALL)
        if match:
            try:
                parsed_list = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if not isinstance(parsed_list, list):
        logger.error(
            "Quiz: LLM output is not a JSON array. Raw: %s",
            raw_content[:300],
        )
        raise RuntimeError(
            "Quiz generation failed: LLM did not return a valid JSON array of questions."
        )

    # Validate each question with Pydantic
    valid_questions: List[QuizQuestion] = []
    for i, item in enumerate(parsed_list):
        if not isinstance(item, dict):
            logger.warning("Quiz: Skipping non-dict item at index %d", i)
            continue
        try:
            q = QuizQuestion(
                question=item.get("question", ""),
                options=item.get("options", []),
                correct_answer=item.get("correct_answer", ""),
                topic=item.get("topic", topic),
                explanation=item.get("explanation", ""),
            )
            # Additional validation: correct_answer must be in options
            if q.correct_answer not in q.options:
                logger.warning(
                    "Quiz: Question %d has correct_answer '%s' not in options %s. Skipping.",
                    i, q.correct_answer, q.options,
                )
                continue
            valid_questions.append(q)
        except Exception as exc:
            logger.warning("Quiz: Question %d failed Pydantic validation: %s", i, exc)
            continue

    if not valid_questions:
        raise ValueError(
            "Quiz generation failed: no valid questions survived Pydantic validation. "
            "LLM output may have been malformed."
        )

    logger.info(
        "Quiz generation: %d/%d questions passed validation for topic='%s'",
        len(valid_questions), len(parsed_list), topic,
    )
    return valid_questions


def save_quiz(
    user_id: str,
    document_id: str,
    topic: str,
    questions: List[QuizQuestion],
    db: DBSession,
) -> Quiz:
    """
    Persist a validated quiz to PostgreSQL and return the Quiz ORM object.

    Args:
        user_id:     Authenticated user (security: always derived from JWT, not browser).
        document_id: Authenticated document.
        topic:       Primary topic label.
        questions:   Validated QuizQuestion list.
        db:          SQLAlchemy database session.

    Returns:
        Quiz ORM object with id populated.
    """
    questions_json = json.dumps(
        [q.model_dump() for q in questions],
        ensure_ascii=False,
    )
    quiz = Quiz(
        id=str(uuid.uuid4()),
        user_id=user_id,
        document_id=document_id,
        topic=topic,
        questions=questions_json,
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    logger.info(
        "Quiz saved: quiz_id=%s, user=%s, doc=%s, topic='%s', questions=%d",
        quiz.id, user_id, document_id, topic, len(questions),
    )
    return quiz


def grade_quiz_attempt(
    quiz: Quiz,
    submitted_answers: List[str],
) -> Tuple[int, float, List[Dict]]:
    """
    Grade a quiz attempt DETERMINISTICALLY.

    Correctness rule (brain.md spec):
        submitted_answer == correct_answer (exact string comparison after strip)

    The LLM is NEVER called to determine correctness.
    Score and percentage are calculated by this function — application code only.

    Args:
        quiz:              The Quiz ORM object being attempted.
        submitted_answers: List of submitted answer strings (indexed to match questions).

    Returns:
        Tuple of:
          - score (int): number of correct answers
          - percentage (float): score / total * 100
          - results (List[dict]): per-question result dicts with
            question, submitted_answer, correct_answer, is_correct, explanation
    """
    try:
        questions_data = json.loads(quiz.questions)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("Failed to parse quiz questions JSON: %s", exc)
        raise ValueError("Quiz data is corrupted and cannot be graded.") from exc

    total = len(questions_data)
    if total == 0:
        return 0, 0.0, []

    # Pad submitted answers with empty strings if fewer answers than questions
    padded_answers = list(submitted_answers) + [""] * max(0, total - len(submitted_answers))

    score = 0
    results = []

    for i, q_data in enumerate(questions_data):
        correct = q_data.get("correct_answer", "").strip()
        submitted = padded_answers[i].strip() if i < len(padded_answers) else ""

        # DETERMINISTIC grading — no LLM
        is_correct = (submitted == correct)
        if is_correct:
            score += 1

        results.append({
            "question": q_data.get("question", ""),
            "submitted_answer": submitted,
            "correct_answer": correct,
            "is_correct": is_correct,
            "explanation": q_data.get("explanation", ""),
        })

    percentage = (score / total * 100) if total > 0 else 0.0

    logger.info(
        "Quiz graded deterministically: quiz_id=%s, score=%d/%d (%.1f%%)",
        quiz.id, score, total, percentage,
    )
    return score, percentage, results


def save_quiz_attempt(
    quiz_id: str,
    user_id: str,
    submitted_answers: List[str],
    score: int,
    percentage: float,
    db: DBSession,
) -> QuizAttempt:
    """
    Persist a quiz attempt to PostgreSQL.

    Args:
        quiz_id:           Quiz being attempted.
        user_id:           Authenticated user.
        submitted_answers: List of submitted answer strings.
        score:             Number of correct answers (deterministic, not LLM).
        percentage:        score / total * 100 (deterministic, not LLM).
        db:                SQLAlchemy database session.

    Returns:
        QuizAttempt ORM object with id populated.
    """
    answers_json = json.dumps(submitted_answers, ensure_ascii=False)
    attempt = QuizAttempt(
        id=str(uuid.uuid4()),
        quiz_id=quiz_id,
        user_id=user_id,
        answers=answers_json,
        score=score,
        percentage=percentage,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    logger.info(
        "QuizAttempt saved: attempt_id=%s, quiz_id=%s, user=%s, score=%d, pct=%.1f%%",
        attempt.id, quiz_id, user_id, score, percentage,
    )
    return attempt
