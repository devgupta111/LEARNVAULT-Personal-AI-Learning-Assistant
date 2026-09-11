"""
models/quiz_attempt.py

SQLAlchemy ORM model for the quiz_attempts table.

A quiz_attempt is created when a student submits answers for a quiz.
Score and percentage are calculated DETERMINISTICALLY by application code —
the LLM is never called to evaluate correctness.

Brain.md schema:
    id, quiz_id, user_id, answers, score, created_at

Additional fields kept:
    percentage  — precomputed float for easy history queries
"""

import datetime
import uuid
from sqlalchemy import Column, String, Integer, Float, Text, DateTime
from sqlalchemy.sql import func

from app.db.base import Base


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # The quiz this attempt belongs to.
    quiz_id = Column(String(36), nullable=False, index=True)

    # Authenticated user who submitted this attempt.
    user_id = Column(String(36), nullable=False, index=True)

    # JSON-encoded list of submitted answer strings (one per question, indexed).
    answers = Column(Text, nullable=False)

    # Number of correct answers (deterministic: submitted == correct).
    score = Column(Integer, nullable=False, default=0)

    # Precomputed: score / total_questions * 100 (app code only, not LLM).
    percentage = Column(Float, nullable=False, default=0.0)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
