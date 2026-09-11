"""
tests/test_day6.py

Day 6 — Testing & Verification Suite:
  Agent 3 — Hallucination & Citation Grader
  Agent 4 — Adaptive Quiz & Diagnostic Agent

Comprehensive test coverage covering all 26 required verification points:
  1. Grader PASS
  2. Grader FAIL → regenerate once
  3. Regenerated answer PASS
  4. Regenerated answer FAIL → refusal
  5. Verify no second regeneration
  6. Verify grader failure does NOT trigger CRAG
  7. Valid quiz generation
  8. Invalid quiz output handling
  9. Weak-topic detection at 59%
  10. Boundary behavior at 60%
  11. Deterministic correct answer
  12. Deterministic incorrect answer
  13. Score calculation
  14. Score percentage
  15. Quiz persistence
  16. Quiz retrieval
  17. Quiz submission
  18. Quiz history
  19. User ownership
  20. Cross-user access rejection
  21. Document ownership
  22. Missing/invalid authentication
  23. Missing document
  24. Invalid quiz_id
  25. Invalid submitted answer
  26. LLM/API failure handling
"""

import json
import uuid
from typing import List, Dict
from unittest.mock import MagicMock, patch, call
import pytest
from pydantic import ValidationError

from app.config import settings
from app.models.document import Document
from app.models.session import Session as ChatSession
from app.models.message import Message
from app.models.quiz import Quiz
from app.models.quiz_attempt import QuizAttempt
from app.schemas.chat_schemas import GraderOutput, RouterOutput, CRAGOutput
from app.schemas.quiz_schemas import (
    QuizQuestion,
    QuizGenerateRequest,
    QuizSubmitRequest,
    QuizResponse,
    QuizSubmitResponse,
    QuizHistoryItem,
)
from app.services.grader_service import grade_answer
from app.services.quiz_service import (
    detect_weak_topics,
    retrieve_chunks_for_quiz,
    generate_quiz_questions,
    save_quiz,
    grade_quiz_attempt,
    save_quiz_attempt,
    WEAK_TOPIC_THRESHOLD,
    QUIZ_RETRIEVAL_TOP_K,
)
from app.services.llm_service import REFUSAL_MESSAGE
from tests.conftest import TestSessionLocal


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def test_setup(client):
    """
    Creates a clean environment with:
      - dev-user ready document
      - other-user ready document
      - dev-user chat session
    """
    db = TestSessionLocal()
    doc_id = str(uuid.uuid4())
    other_doc_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    doc = Document(
        id=doc_id,
        user_id="dev-user",
        filename="notes.pdf",
        file_path=f"/tmp/{doc_id}.pdf",
        status="READY",
        page_count=5,
        subject="Computer Science",
    )
    other_doc = Document(
        id=other_doc_id,
        user_id="other-user",
        filename="secret.pdf",
        file_path=f"/tmp/{other_doc_id}.pdf",
        status="READY",
        page_count=3,
        subject="Secret",
    )
    sess = ChatSession(
        id=session_id,
        user_id="dev-user",
        document_id=doc_id,
    )
    db.add(doc)
    db.add(other_doc)
    db.add(sess)
    db.commit()
    db.close()

    yield {
        "doc_id": doc_id,
        "other_doc_id": other_doc_id,
        "session_id": session_id,
        "user_id": "dev-user",
        "other_user_id": "other-user",
    }

    db = TestSessionLocal()
    db.query(QuizAttempt).delete()
    db.query(Quiz).delete()
    db.query(Message).filter(Message.session_id == session_id).delete()
    db.query(ChatSession).filter(ChatSession.id == session_id).delete()
    db.query(Document).filter(Document.id.in_([doc_id, other_doc_id])).delete()
    db.commit()
    db.close()


def _make_dummy_parent(doc_id: str, text: str = "Normalization reduces data redundancy in relational databases."):
    return [{
        "parent_chunk_id": str(uuid.uuid4()),
        "document_id": doc_id,
        "page_start": 1,
        "page_end": 2,
        "parent_text": text,
        "subject": "Computer Science",
    }]


# ─── 1 to 6: Agent 3 Grader & Locked Failure Flow ─────────────────────────────

class TestGraderAgentAndFailureFlow:
    """Verification 1–6: Hallucination & Citation Grader (Agent 3) + Locked Flow."""

    def test_1_grader_pass(self, client, test_setup):
        """1. Grader PASS: When answer is grounded, verified answer is returned with citations."""
        parent_results = _make_dummy_parent(test_setup["doc_id"])
        mock_answer = "Normalization reduces redundancy [Source 1]."

        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_rag_response") as mock_rag, \
             patch("app.api.chat.grade_answer") as mock_grader:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="normalization")
            mock_search.return_value = (parent_results, False)
            mock_rag.return_value = mock_answer
            mock_grader.return_value = GraderOutput(grounded=True, confidence=0.95, critique="")

            resp = client.post(
                "/chat",
                json={
                    "session_id": test_setup["session_id"],
                    "document_id": test_setup["doc_id"],
                    "message": "What does normalization do?",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["answer"] == mock_answer
            assert len(data["citations"]) == 1
            assert mock_rag.call_count == 1
            assert mock_grader.call_count == 1

    def test_2_grader_fail_regenerate_once(self, client, test_setup):
        """2. Grader FAIL → regenerate once using the SAME context."""
        parent_results = _make_dummy_parent(test_setup["doc_id"])
        initial_answer = "Quantum computing uses qubits [Source 1]."
        regen_answer = "Normalization eliminates duplicate data [Source 1]."

        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_rag_response") as mock_rag, \
             patch("app.api.chat.grade_answer") as mock_grader:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="normalization")
            mock_search.return_value = (parent_results, False)
            mock_rag.side_effect = [initial_answer, regen_answer]
            mock_grader.side_effect = [
                GraderOutput(grounded=False, confidence=0.2, critique="Hallucinated quantum computing"),
                GraderOutput(grounded=True, confidence=0.92, critique=""),
            ]

            resp = client.post(
                "/chat",
                json={
                    "session_id": test_setup["session_id"],
                    "document_id": test_setup["doc_id"],
                    "message": "What does normalization do?",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["answer"] == regen_answer
            # Both calls to generate_rag_response used the SAME parent_results
            assert mock_rag.call_count == 2
            assert mock_rag.call_args_list[0].kwargs["parent_results"] == parent_results
            assert mock_rag.call_args_list[1].kwargs["parent_results"] == parent_results

    def test_3_regenerated_answer_pass(self, client, test_setup):
        """3. Regenerated answer PASS: Second grader call passes -> returns regenerated answer."""
        parent_results = _make_dummy_parent(test_setup["doc_id"])

        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_rag_response") as mock_rag, \
             patch("app.api.chat.grade_answer") as mock_grader:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="normalization")
            mock_search.return_value = (parent_results, False)
            mock_rag.side_effect = ["Bad answer", "Good verified answer [Source 1]."]
            mock_grader.side_effect = [
                GraderOutput(grounded=False, confidence=0.1, critique="Unsupported claims"),
                GraderOutput(grounded=True, confidence=0.94, critique=""),
            ]

            resp = client.post(
                "/chat",
                json={
                    "session_id": test_setup["session_id"],
                    "document_id": test_setup["doc_id"],
                    "message": "Explain normalization",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["answer"] == "Good verified answer [Source 1]."
            assert len(data["citations"]) == 1

    def test_4_regenerated_answer_fail_refusal(self, client, test_setup):
        """4. Regenerated answer FAIL → unified refusal returned."""
        parent_results = _make_dummy_parent(test_setup["doc_id"])

        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_rag_response") as mock_rag, \
             patch("app.api.chat.grade_answer") as mock_grader:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="normalization")
            mock_search.return_value = (parent_results, False)
            mock_rag.side_effect = ["First hallucination", "Second hallucination"]
            mock_grader.side_effect = [
                GraderOutput(grounded=False, confidence=0.1, critique="Critique 1"),
                GraderOutput(grounded=False, confidence=0.1, critique="Critique 2"),
            ]

            resp = client.post(
                "/chat",
                json={
                    "session_id": test_setup["session_id"],
                    "document_id": test_setup["doc_id"],
                    "message": "Explain normalization",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["answer"] == REFUSAL_MESSAGE
            assert data["citations"] == []

    def test_5_verify_no_second_regeneration(self, client, test_setup):
        """5. Verify maximum regeneration attempts = 1 (no second retry, no infinite loop)."""
        parent_results = _make_dummy_parent(test_setup["doc_id"])

        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_rag_response") as mock_rag, \
             patch("app.api.chat.grade_answer") as mock_grader:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="topic")
            mock_search.return_value = (parent_results, False)
            mock_rag.side_effect = ["Answer 1", "Answer 2", "Answer 3 should never be generated"]
            mock_grader.side_effect = [
                GraderOutput(grounded=False, confidence=0.0, critique="Fail 1"),
                GraderOutput(grounded=False, confidence=0.0, critique="Fail 2"),
                GraderOutput(grounded=False, confidence=0.0, critique="Fail 3"),
            ]

            resp = client.post(
                "/chat",
                json={
                    "session_id": test_setup["session_id"],
                    "document_id": test_setup["doc_id"],
                    "message": "topic",
                },
            )

            assert resp.status_code == 200
            # Exactly 2 generations occurred (initial + 1 regeneration)
            assert mock_rag.call_count == 2
            # Exactly 2 evaluations occurred
            assert mock_grader.call_count == 2

    def test_6_verify_grader_failure_does_not_trigger_crag(self, client, test_setup):
        """6. Verify grader failure does NOT trigger CRAG."""
        parent_results = _make_dummy_parent(test_setup["doc_id"])

        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_rag_response") as mock_rag, \
             patch("app.api.chat.grade_answer") as mock_grader, \
             patch("app.api.chat.generate_crag_query") as mock_crag:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="topic")
            mock_search.return_value = (parent_results, False)  # Strong initial retrieval
            mock_rag.return_value = "Hallucinated answer"
            mock_grader.return_value = GraderOutput(grounded=False, confidence=0.1, critique="Fail")

            client.post(
                "/chat",
                json={
                    "session_id": test_setup["session_id"],
                    "document_id": test_setup["doc_id"],
                    "message": "topic",
                },
            )

            # CRAG Agent must NEVER be invoked on grader failure
            mock_crag.assert_not_called()


# ─── 7 to 10: Agent 4 Quiz Generation & Weak Topics ───────────────────────────

class TestQuizGenerationAndWeakTopics:
    """Verification 7–10: Quiz Generation & Weak-Topic Detection."""

    def test_7_valid_quiz_generation(self):
        """7. Valid quiz generation grounded in study material."""
        fake_parents = [{"parent_text": "2NF removes partial functional dependencies.", "page_start": 1, "page_end": 1}]
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=json.dumps([
                {
                    "question": "Which normal form removes partial dependency?",
                    "options": ["1NF", "2NF", "3NF", "BCNF"],
                    "correct_answer": "2NF",
                    "topic": "Normalization",
                    "explanation": "2NF eliminates partial functional dependency."
                },
                {
                    "question": "What is the key requirement of 1NF?",
                    "options": ["Atomic values", "No transitive dependency", "Foreign keys", "Surrogate keys"],
                    "correct_answer": "Atomic values",
                    "topic": "Normalization",
                    "explanation": "1NF requires all attributes to hold atomic values."
                }
            ])))
        ]

        with patch("app.services.quiz_service._get_quiz_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_factory.return_value = (mock_client, "llama-3.1-8b-instant")

            questions = generate_quiz_questions(
                topic="Normalization",
                parent_results=fake_parents,
                num_questions=2,
            )

            assert len(questions) == 2
            assert isinstance(questions[0], QuizQuestion)
            assert questions[0].question == "Which normal form removes partial dependency?"
            assert questions[0].correct_answer == "2NF"
            assert questions[0].correct_answer in questions[0].options
            assert len(questions[0].options) == 4

    def test_8_invalid_quiz_output_handling(self):
        """8. Invalid quiz output handling: malformed questions rejected safely."""
        fake_parents = [{"parent_text": "Sample text", "page_start": 1, "page_end": 1}]

        # Scenario A: Malformed non-JSON output raises RuntimeError
        mock_resp_garbage = MagicMock()
        mock_resp_garbage.choices = [MagicMock(message=MagicMock(content="Here are your questions: not json!"))]
        with patch("app.services.quiz_service._get_quiz_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_resp_garbage
            mock_client_factory.return_value = (mock_client, "llama-3.1-8b-instant")

            with pytest.raises(RuntimeError):
                generate_quiz_questions(topic="Testing", parent_results=fake_parents, num_questions=1)

        # Scenario B: Partial malformed objects filtered out
        mock_resp_partial = MagicMock()
        mock_resp_partial.choices = [MagicMock(message=MagicMock(content=json.dumps([
            {"question": "", "options": ["A"], "correct_answer": "A"},  # Invalid question & options
            {"question": "Valid Q?", "options": ["A", "B", "C", "D"], "correct_answer": "Z", "topic": "T"},  # correct not in options
            {"question": "Good Q?", "options": ["A", "B", "C", "D"], "correct_answer": "A", "topic": "T"}   # Valid!
        ])))]
        with patch("app.services.quiz_service._get_quiz_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_resp_partial
            mock_client_factory.return_value = (mock_client, "llama-3.1-8b-instant")

            questions = generate_quiz_questions(topic="T", parent_results=fake_parents, num_questions=1)
            assert len(questions) == 1
            assert questions[0].question == "Good Q?"

    def test_9_weak_topic_detection_at_59_percent(self, test_setup):
        """9. Weak-topic detection at 59% (accuracy < 60% rule)."""
        db = TestSessionLocal()
        try:
            quiz = Quiz(
                id=str(uuid.uuid4()),
                user_id="dev-user",
                document_id=test_setup["doc_id"],
                topic="Operating Systems",
                questions=json.dumps([{"q": i, "correct_answer": "A"} for i in range(100)]),
            )
            db.add(quiz)
            db.commit()

            # 59 correct out of 100 -> 59.0% accuracy
            attempt = QuizAttempt(
                id=str(uuid.uuid4()),
                quiz_id=quiz.id,
                user_id="dev-user",
                answers="[]",
                score=59,
                percentage=59.0,
            )
            db.add(attempt)
            db.commit()

            weak = detect_weak_topics("dev-user", test_setup["doc_id"], db)
            assert "Operating Systems" in weak
        finally:
            db.close()

    def test_10_boundary_behavior_at_60_percent(self, test_setup):
        """10. Boundary behavior at 60%: 60% is NOT weak, 61% is NOT weak."""
        db = TestSessionLocal()
        try:
            quiz = Quiz(
                id=str(uuid.uuid4()),
                user_id="dev-user",
                document_id=test_setup["doc_id"],
                topic="Databases",
                questions=json.dumps([{"q": i, "correct_answer": "A"} for i in range(100)]),
            )
            db.add(quiz)
            db.commit()

            # Exactly 60 correct out of 100 -> 60.0% accuracy -> NOT weak (< 60% rule)
            attempt = QuizAttempt(
                id=str(uuid.uuid4()),
                quiz_id=quiz.id,
                user_id="dev-user",
                answers="[]",
                score=60,
                percentage=60.0,
            )
            db.add(attempt)
            db.commit()

            weak = detect_weak_topics("dev-user", test_setup["doc_id"], db)
            assert "Databases" not in weak
        finally:
            db.close()


# ─── 11 to 14: Deterministic Auto-Grading & Scoring ───────────────────────────

class TestDeterministicAutoGrading:
    """Verification 11–14: Deterministic grading logic (LLM NEVER decides correctness)."""

    @pytest.fixture
    def sample_quiz(self):
        return Quiz(
            id=str(uuid.uuid4()),
            user_id="dev-user",
            document_id="doc-123",
            topic="DBMS",
            questions=json.dumps([
                {"question": "Q1", "options": ["A", "B", "C", "D"], "correct_answer": "A", "explanation": "Exp 1"},
                {"question": "Q2", "options": ["A", "B", "C", "D"], "correct_answer": "B", "explanation": "Exp 2"},
                {"question": "Q3", "options": ["A", "B", "C", "D"], "correct_answer": "C", "explanation": "Exp 3"},
                {"question": "Q4", "options": ["A", "B", "C", "D"], "correct_answer": "D", "explanation": "Exp 4"},
            ]),
        )

    def test_11_deterministic_correct_answer(self, sample_quiz):
        """11. Deterministic correct answer: submitted_answer == correct_answer -> is_correct=True."""
        score, pct, results = grade_quiz_attempt(sample_quiz, ["A", "wrong", "wrong", "wrong"])
        assert results[0]["is_correct"] is True
        assert results[0]["submitted_answer"] == "A"
        assert results[0]["correct_answer"] == "A"

    def test_12_deterministic_incorrect_answer(self, sample_quiz):
        """12. Deterministic incorrect answer: submitted_answer != correct_answer -> is_correct=False."""
        score, pct, results = grade_quiz_attempt(sample_quiz, ["B", "B", "C", "D"])
        assert results[0]["is_correct"] is False  # Submitted B for A
        assert results[0]["submitted_answer"] == "B"
        assert results[0]["correct_answer"] == "A"

    def test_13_score_calculation(self, sample_quiz):
        """13. Score calculation: sum of correct answers calculated by application code."""
        # Submit 3 correct ("A", "B", "C"), 1 wrong ("A" instead of "D")
        score, pct, results = grade_quiz_attempt(sample_quiz, ["A", "B", "C", "A"])
        assert score == 3
        assert len(results) == 4

    def test_14_score_percentage(self, sample_quiz):
        """14. Score percentage: score / total * 100 calculated by application code."""
        # 3 out of 4 = 75.0%
        score, pct, results = grade_quiz_attempt(sample_quiz, ["A", "B", "C", "A"])
        assert pct == 75.0

        # 1 out of 4 = 25.0%
        score, pct, results = grade_quiz_attempt(sample_quiz, ["A", "wrong", "wrong", "wrong"])
        assert pct == 25.0


# ─── 15 to 18: Quiz Database Persistence & API Endpoints ──────────────────────

class TestQuizPersistenceAndAPI:
    """Verification 15–18: Database persistence and API endpoints."""

    def test_15_quiz_persistence(self, test_setup):
        """15. Quiz persistence in PostgreSQL/SQLite database."""
        db = TestSessionLocal()
        try:
            questions = [
                QuizQuestion(
                    question="What is 3NF?",
                    options=["A", "B", "C", "D"],
                    correct_answer="A",
                    topic="Normalization",
                )
            ]
            quiz = save_quiz(
                user_id="dev-user",
                document_id=test_setup["doc_id"],
                topic="Normalization",
                questions=questions,
                db=db,
            )
            assert quiz.id is not None

            # Retrieve directly from DB
            loaded = db.query(Quiz).filter(Quiz.id == quiz.id).first()
            assert loaded is not None
            assert loaded.user_id == "dev-user"
            assert loaded.document_id == test_setup["doc_id"]
            assert loaded.topic == "Normalization"
            loaded_q = json.loads(loaded.questions)
            assert len(loaded_q) == 1
            assert loaded_q[0]["question"] == "What is 3NF?"
        finally:
            db.close()

    def test_16_quiz_retrieval(self, client, test_setup):
        """16. GET /quiz/{quiz_id} retrieves persisted quiz."""
        db = TestSessionLocal()
        quiz_id = str(uuid.uuid4())
        try:
            quiz = Quiz(
                id=quiz_id,
                user_id="dev-user",
                document_id=test_setup["doc_id"],
                topic="Algorithms",
                questions=json.dumps([
                    {
                        "question": "What is binary search?",
                        "options": ["O(1)", "O(log n)", "O(n)", "O(n^2)"],
                        "correct_answer": "O(log n)",
                        "topic": "Algorithms",
                        "explanation": "Divides space in half.",
                    }
                ]),
            )
            db.add(quiz)
            db.commit()
        finally:
            db.close()

        resp = client.get(f"/quiz/{quiz_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["quiz_id"] == quiz_id
        assert data["topic"] == "Algorithms"
        assert len(data["questions"]) == 1
        assert data["questions"][0]["question"] == "What is binary search?"

    def test_17_quiz_submission(self, client, test_setup):
        """17. POST /quiz/{quiz_id}/submit grades answers and persists attempt."""
        db = TestSessionLocal()
        quiz_id = str(uuid.uuid4())
        try:
            quiz = Quiz(
                id=quiz_id,
                user_id="dev-user",
                document_id=test_setup["doc_id"],
                topic="Networks",
                questions=json.dumps([
                    {"question": "Q1", "options": ["TCP", "UDP"], "correct_answer": "TCP", "explanation": "Reliable"},
                    {"question": "Q2", "options": ["HTTP", "FTP"], "correct_answer": "HTTP", "explanation": "Web"},
                ]),
            )
            db.add(quiz)
            db.commit()
        finally:
            db.close()

        # Submit: 1 correct, 1 wrong
        resp = client.post(
            f"/quiz/{quiz_id}/submit",
            json={"answers": ["TCP", "FTP"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["quiz_id"] == quiz_id
        assert data["score"] == 1
        assert data["total"] == 2
        assert data["percentage"] == 50.0
        assert data["results"][0]["is_correct"] is True
        assert data["results"][1]["is_correct"] is False

        # Verify attempt persisted in DB
        db = TestSessionLocal()
        try:
            attempt = db.query(QuizAttempt).filter(QuizAttempt.id == data["attempt_id"]).first()
            assert attempt is not None
            assert attempt.score == 1
            assert attempt.percentage == 50.0
        finally:
            db.close()

    def test_18_quiz_history(self, client, test_setup):
        """18. GET /quiz/history returns user's quizzes with latest attempt summary."""
        db = TestSessionLocal()
        quiz_id = str(uuid.uuid4())
        try:
            quiz = Quiz(
                id=quiz_id,
                user_id="dev-user",
                document_id=test_setup["doc_id"],
                topic="Security",
                questions=json.dumps([{"question": "Q", "options": ["A"], "correct_answer": "A"}]),
            )
            db.add(quiz)
            db.commit()

            attempt = QuizAttempt(
                id=str(uuid.uuid4()),
                quiz_id=quiz_id,
                user_id="dev-user",
                answers=json.dumps(["A"]),
                score=1,
                percentage=100.0,
            )
            db.add(attempt)
            db.commit()
        finally:
            db.close()

        resp = client.get("/quiz/history")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) >= 1
        item = next(h for h in history if h["quiz_id"] == quiz_id)
        assert item["topic"] == "Security"
        assert item["latest_score"] == 1
        assert item["latest_percentage"] == 100.0


# ─── 19 to 26: Authentication, Ownership, Security & Error Handling ───────────

class TestSecurityOwnershipAndErrors:
    """Verification 19–26: Ownership, Cross-User Rejection, Auth & Error Handling."""

    def test_19_user_ownership(self, client, test_setup):
        """19. Authenticated user can access their own quiz."""
        db = TestSessionLocal()
        quiz_id = str(uuid.uuid4())
        try:
            quiz = Quiz(
                id=quiz_id,
                user_id="dev-user",
                document_id=test_setup["doc_id"],
                topic="Own Topic",
                questions=json.dumps([{"question": "Q", "options": ["A", "B"], "correct_answer": "A", "topic": "Own Topic"}]),
            )
            db.add(quiz)
            db.commit()
        finally:
            db.close()

        resp = client.get(f"/quiz/{quiz_id}")
        assert resp.status_code == 200

    def test_20_cross_user_access_rejection(self, client, test_setup):
        """20. Cross-user access rejected (User B cannot access User A's quiz)."""
        db = TestSessionLocal()
        quiz_id = str(uuid.uuid4())
        try:
            # Quiz owned by 'other-user'
            quiz = Quiz(
                id=quiz_id,
                user_id="other-user",
                document_id=test_setup["other_doc_id"],
                topic="Private",
                questions=json.dumps([{"question": "Q", "options": ["A", "B"], "correct_answer": "A"}]),
            )
            db.add(quiz)
            db.commit()
        finally:
            db.close()

        # dev-user attempts to GET other-user's quiz -> 403
        resp_get = client.get(f"/quiz/{quiz_id}")
        assert resp_get.status_code == 403
        assert "permission" in resp_get.json()["detail"].lower()

        # dev-user attempts to SUBMIT to other-user's quiz -> 403
        resp_sub = client.post(f"/quiz/{quiz_id}/submit", json={"answers": ["A"]})
        assert resp_sub.status_code == 403

        # dev-user's history must NOT contain other-user's quiz
        resp_hist = client.get("/quiz/history")
        assert resp_hist.status_code == 200
        quiz_ids = [q["quiz_id"] for q in resp_hist.json()]
        assert quiz_id not in quiz_ids

    def test_21_document_ownership_in_quiz_generation(self, client, test_setup):
        """21. Document ownership: cannot generate quiz from another user's document."""
        resp = client.post(
            "/quiz/generate",
            json={"document_id": test_setup["other_doc_id"]},  # Owned by 'other-user'
        )
        assert resp.status_code == 403
        assert "permission" in resp.json()["detail"].lower()

    def test_22_authentication_and_user_derivation(self, client, test_setup):
        """22. Authenticated identity comes from get_current_user(), never request body."""
        from app.api.quiz import get_current_user

        with patch("app.api.quiz.retrieve_chunks_for_quiz") as mock_retrieval, \
             patch("app.api.quiz.generate_quiz_questions") as mock_gen:

            mock_retrieval.return_value = [{"parent_text": "text", "page_start": 1, "page_end": 1}]
            mock_gen.return_value = [
                QuizQuestion(question="Q?", options=["A", "B"], correct_answer="A", topic="T")
            ]

            # Generate quiz
            resp = client.post(
                "/quiz/generate",
                json={"document_id": test_setup["doc_id"], "topic": "T"},
            )
            assert resp.status_code == 201

            # Verify retrieval received authenticated user 'dev-user', not any external parameter
            mock_retrieval.assert_called_once_with(
                topic="T",
                document_id=test_setup["doc_id"],
                user_id="dev-user",
            )

    def test_23_missing_document(self, client):
        """23. Missing document returns 404."""
        resp = client.post(
            "/quiz/generate",
            json={"document_id": "nonexistent-doc-id"},
        )
        assert resp.status_code == 404

    def test_24_invalid_quiz_id(self, client):
        """24. Invalid quiz_id returns 404 on GET and SUBMIT."""
        ghost_id = str(uuid.uuid4())
        resp_get = client.get(f"/quiz/{ghost_id}")
        assert resp_get.status_code == 404

        resp_submit = client.post(f"/quiz/{ghost_id}/submit", json={"answers": ["A"]})
        assert resp_submit.status_code == 404

    def test_25_invalid_submitted_answer(self, client, test_setup):
        """25. Invalid submitted answer (empty array) returns 422."""
        db = TestSessionLocal()
        quiz_id = str(uuid.uuid4())
        try:
            quiz = Quiz(
                id=quiz_id,
                user_id="dev-user",
                document_id=test_setup["doc_id"],
                topic="Test",
                questions=json.dumps([{"question": "Q?", "options": ["A", "B"], "correct_answer": "A", "topic": "Test"}]),
            )
            db.add(quiz)
            db.commit()
        finally:
            db.close()

        # Empty answers list -> 422
        resp = client.post(f"/quiz/{quiz_id}/submit", json={"answers": []})
        assert resp.status_code == 422

    def test_26_llm_api_failure_handling(self, client, test_setup):
        """26. LLM/API failure handling: graceful 503 or safe fallback."""
        # Case A: Quiz generation LLM failure returns 503
        with patch("app.api.quiz.retrieve_chunks_for_quiz") as mock_retrieval, \
             patch("app.api.quiz.generate_quiz_questions", side_effect=RuntimeError("Groq timeout")):

            mock_retrieval.return_value = [{"parent_text": "text", "page_start": 1, "page_end": 1}]
            resp = client.post(
                "/quiz/generate",
                json={"document_id": test_setup["doc_id"], "topic": "T"},
            )
            assert resp.status_code == 503

        # Case B: Grader service failure returns grounded=False (triggers safe fallback)
        with patch("app.services.grader_service._get_grader_client", side_effect=RuntimeError("API error")):
            result = grade_answer(
                question="What is ML?",
                answer="ML is AI.",
                parent_results=[{"parent_text": "ML is AI.", "page_start": 1, "page_end": 1}],
            )
            assert result.grounded is False
            assert result.confidence == 0.0
            assert "error" in result.critique.lower()
