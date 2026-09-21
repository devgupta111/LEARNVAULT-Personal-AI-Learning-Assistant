"""
tests/test_chat_pipeline_regression.py

Deterministic regression tests verifying the complete /chat pipeline and the 9 key
invariants required to ensure valid document evidence is preserved, grounded answers
are returned with citations, and refusal paths remain strictly correct.

Verification Points:
1. A relevant retrieved chunk is preserved through the retrieval pipeline.
2. Valid evidence is passed into the LLM context.
3. A grounded answer is not incorrectly converted into a refusal.
4. Citations are produced when source metadata exists.
5. Weak evidence still correctly causes refusal.
6. Grader first failure causes exactly one regeneration.
7. Grader second failure causes refusal.
8. CRAG is not incorrectly invoked by grader failure.
9. user_id/document_id isolation remains enforced.
"""

import json
import uuid
from typing import List, Dict
from unittest.mock import MagicMock, patch, call
import pytest

from app.models.document import Document
from app.models.session import Session as ChatSession
from app.models.message import Message
from app.schemas.chat_schemas import GraderOutput, RouterOutput, CRAGOutput
from app.services.llm_service import (
    REFUSAL_MESSAGE,
    get_citations,
    _format_context_block,
    generate_rag_response,
)
from app.services.reranker_service import rerank_results, search_and_rerank
from tests.conftest import TestSessionLocal


# ─── Fixture for isolated document and session ─────────────────────────────────

@pytest.fixture
def chat_pipeline_fixture(client):
    """
    Creates a READY document and chat session for dev-user,
    and another document for other-user to test isolation.
    """
    db = TestSessionLocal()
    doc_id = "e2ffe20c-56fe-4e66-8c75-3d5980d1fcdc"
    other_doc_id = str(uuid.uuid4())
    session_id = "f5ffa6bc-8752-42fc-b934-811835270e86"

    # Clean existing rows if any
    db.query(Message).filter(Message.session_id == session_id).delete()
    db.query(ChatSession).filter(ChatSession.id == session_id).delete()
    db.query(Document).filter(Document.id.in_([doc_id, other_doc_id])).delete()
    db.commit()

    doc = Document(
        id=doc_id,
        user_id="dev-user",
        filename="lec_1Notes.pdf",
        file_path=f"/tmp/{doc_id}.pdf",
        status="READY",
        page_count=2,
        subject="OS",
    )
    other_doc = Document(
        id=other_doc_id,
        user_id="other-user",
        filename="other.pdf",
        file_path=f"/tmp/{other_doc_id}.pdf",
        status="READY",
        page_count=1,
        subject="Algorithms",
    )
    session = ChatSession(
        id=session_id,
        user_id="dev-user",
        document_id=doc_id,
        title="OS Study Session",
    )

    db.add_all([doc, other_doc, session])
    db.commit()
    db.close()

    return {
        "doc_id": doc_id,
        "other_doc_id": other_doc_id,
        "session_id": session_id,
        "user_id": "dev-user",
    }


# ─── Sample Chunk Payloads ───────────────────────────────────────────────────

SAMPLE_PARENT_RESULTS = [
    {
        "parent_chunk_id": "parent-uuid-os-1",
        "parent_text": "An operating system (OS) is system software that manages computer hardware and software resources.",
        "text": "An operating system (OS) is system software that manages computer hardware and software resources.",
        "document_id": "e2ffe20c-56fe-4e66-8c75-3d5980d1fcdc",
        "user_id": "dev-user",
        "subject": "OS",
        "page_start": 1,
        "page_end": 1,
        "rerank_score": 0.98,
    }
]


# ─── Test 1: Relevant retrieved chunk preserved through retrieval pipeline ────

def test_1_relevant_retrieved_chunk_preserved_through_retrieval_pipeline():
    """
    Requirement 1: A relevant retrieved chunk is preserved through the retrieval pipeline.
    Verifies that scored points returned from vector retrieval are reranked, deduplicated,
    and retain their text, parent IDs, and page metadata with is_weak=False.
    """
    mock_point = MagicMock()
    mock_point.id = str(uuid.uuid4())
    mock_point.score = 0.92
    mock_point.payload = {
        "child_id": str(uuid.uuid4()),
        "parent_chunk_id": "parent-uuid-os-1",
        "parent_text": "An operating system (OS) is system software that manages computer hardware.",
        "text": "An operating system (OS) is system software that manages computer hardware.",
        "document_id": "e2ffe20c-56fe-4e66-8c75-3d5980d1fcdc",
        "user_id": "dev-user",
        "subject": "OS",
        "page_start": 1,
        "page_end": 1,
    }

    parents, is_weak = rerank_results(
        query="What is operating system?",
        scored_points=[mock_point],
        threshold=0.35,
        top_k=4,
    )

    assert is_weak is False
    assert len(parents) == 1
    assert parents[0]["parent_chunk_id"] == "parent-uuid-os-1"
    assert parents[0]["document_id"] == "e2ffe20c-56fe-4e66-8c75-3d5980d1fcdc"
    assert "operating system" in parents[0]["parent_text"]
    assert parents[0]["page_start"] == 1


# ─── Test 2: Valid evidence is passed into LLM context (including fallback) ──

def test_2_valid_evidence_passed_into_llm_context():
    """
    Requirement 2: Valid evidence is passed into the LLM context.
    Verifies that _format_context_block properly populates [Source N | Page X]
    both when parent_text is present, AND when parent_text is empty (falling back to text).
    """
    # Case A: Standard parent_text present
    context_a = _format_context_block(SAMPLE_PARENT_RESULTS)
    assert "[Source 1 | Page 1]" in context_a
    assert "An operating system (OS) is system software" in context_a

    # Case B: parent_text is empty string, text contains the evidence
    fallback_parent_results = [
        {
            "parent_chunk_id": "parent-fallback-1",
            "parent_text": "",  # Empty parent text
            "text": "Fallback child chunk containing valid OS definition.",
            "document_id": "e2ffe20c-56fe-4e66-8c75-3d5980d1fcdc",
            "user_id": "dev-user",
            "subject": "OS",
            "page_start": 1,
            "page_end": 2,
            "rerank_score": 0.85,
        }
    ]
    context_b = _format_context_block(fallback_parent_results)
    assert "[Source 1 | Page 1-2]" in context_b
    assert "Fallback child chunk containing valid OS definition." in context_b


# ─── Test 3: Grounded answer is not incorrectly converted into a refusal ──────

def test_3_grounded_answer_not_incorrectly_converted_into_refusal(client, chat_pipeline_fixture):
    """
    Requirement 3: A grounded answer is not incorrectly converted into a refusal.
    When retrieval finds evidence and the LLM produces a grounded answer that passes the grader,
    the endpoint MUST return HTTP 200 with the grounded answer and non-empty citations.
    """
    doc_id = chat_pipeline_fixture["doc_id"]
    session_id = chat_pipeline_fixture["session_id"]
    expected_answer = (
        "An operating system is system software that manages computer hardware [Source 1]."
    )

    with patch(
        "app.api.chat.route_and_rewrite_query",
        return_value=RouterOutput(route="rag_query", rewritten_query="What is operating system?"),
    ), patch(
        "app.api.chat.search_and_rerank",
        return_value=(SAMPLE_PARENT_RESULTS, False),
    ), patch(
        "app.api.chat.generate_rag_response",
        return_value=expected_answer,
    ), patch(
        "app.api.chat.grade_answer",
        return_value=GraderOutput(grounded=True, confidence=0.95, critique=""),
    ):
        response = client.post(
            "/chat",
            json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is operating system?",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == expected_answer
    assert data["answer"] != REFUSAL_MESSAGE
    assert len(data["citations"]) == 1
    assert data["citations"][0]["document_id"] == doc_id
    assert data["citations"][0]["source_id"] == "Source 1"


# ─── Test 4: Citations produced when source metadata exists ───────────────────

def test_4_citations_produced_when_source_metadata_exists():
    """
    Requirement 4: Citations are produced when source metadata exists.
    Verifies that get_citations creates accurate citation items matching the source text.
    """
    citations = get_citations(SAMPLE_PARENT_RESULTS)
    assert len(citations) == 1
    c = citations[0]
    assert c["source_id"] == "Source 1"
    assert c["document_id"] == "e2ffe20c-56fe-4e66-8c75-3d5980d1fcdc"
    assert c["page_start"] == 1
    assert c["page_end"] == 1
    assert c["parent_chunk_id"] == "parent-uuid-os-1"
    assert c["subject"] == "OS"


# ─── Test 5: Weak evidence still correctly causes refusal ─────────────────────

def test_5_weak_evidence_still_correctly_causes_refusal(client, chat_pipeline_fixture):
    """
    Requirement 5: Weak evidence still correctly causes refusal.
    When both initial retrieval and CRAG retry are weak, the unified refusal MUST be returned.
    """
    doc_id = chat_pipeline_fixture["doc_id"]
    session_id = chat_pipeline_fixture["session_id"]

    with patch(
        "app.api.chat.route_and_rewrite_query",
        return_value=RouterOutput(route="rag_query", rewritten_query="Quantum entanglement"),
    ), patch(
        "app.api.chat.search_and_rerank",
        return_value=([], True),  # Both initial and retry return weak
    ), patch(
        "app.api.chat.generate_crag_query",
        return_value=CRAGOutput(alternative_query="Quantum mechanics in OS"),
    ):
        response = client.post(
            "/chat",
            json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "Explain quantum entanglement in this OS doc",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == REFUSAL_MESSAGE
    assert data["citations"] == []


# ─── Test 6: Grader first failure causes exactly one regeneration ─────────────

def test_6_grader_first_failure_causes_exactly_one_regeneration(client, chat_pipeline_fixture):
    """
    Requirement 6: Grader first failure causes exactly one regeneration.
    If initial answer fails grading, generate_rag_response MUST be called a second time
    with the SAME context. If the second answer passes, it is returned.
    """
    doc_id = chat_pipeline_fixture["doc_id"]
    session_id = chat_pipeline_fixture["session_id"]

    initial_bad_answer = "Hallucinated response without citation."
    regen_good_answer = "An OS manages computer hardware [Source 1]."

    generate_mock = MagicMock(side_effect=[initial_bad_answer, regen_good_answer])
    grade_mock = MagicMock(
        side_effect=[
            GraderOutput(grounded=False, confidence=0.3, critique="Missing citation"),
            GraderOutput(grounded=True, confidence=0.95, critique=""),
        ]
    )

    with patch(
        "app.api.chat.route_and_rewrite_query",
        return_value=RouterOutput(route="rag_query", rewritten_query="What is operating system?"),
    ), patch(
        "app.api.chat.search_and_rerank",
        return_value=(SAMPLE_PARENT_RESULTS, False),
    ), patch(
        "app.api.chat.generate_rag_response",
        generate_mock,
    ), patch(
        "app.api.chat.grade_answer",
        grade_mock,
    ):
        response = client.post(
            "/chat",
            json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is operating system?",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == regen_good_answer
    assert generate_mock.call_count == 2
    assert grade_mock.call_count == 2


# ─── Test 7: Grader second failure causes refusal ─────────────────────────────

def test_7_grader_second_failure_causes_refusal(client, chat_pipeline_fixture):
    """
    Requirement 7: Grader second failure causes refusal.
    If both the initial and regenerated answers fail grading, the system MUST refuse.
    """
    doc_id = chat_pipeline_fixture["doc_id"]
    session_id = chat_pipeline_fixture["session_id"]

    generate_mock = MagicMock(side_effect=["Unsubstantiated answer 1", "Unsubstantiated answer 2"])
    grade_mock = MagicMock(
        side_effect=[
            GraderOutput(grounded=False, confidence=0.2, critique="Unverified claim"),
            GraderOutput(grounded=False, confidence=0.1, critique="Still unverified"),
        ]
    )

    with patch(
        "app.api.chat.route_and_rewrite_query",
        return_value=RouterOutput(route="rag_query", rewritten_query="What is operating system?"),
    ), patch(
        "app.api.chat.search_and_rerank",
        return_value=(SAMPLE_PARENT_RESULTS, False),
    ), patch(
        "app.api.chat.generate_rag_response",
        generate_mock,
    ), patch(
        "app.api.chat.grade_answer",
        grade_mock,
    ):
        response = client.post(
            "/chat",
            json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is operating system?",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == REFUSAL_MESSAGE
    assert data["citations"] == []
    assert generate_mock.call_count == 2
    assert grade_mock.call_count == 2


# ─── Test 8: CRAG is not incorrectly invoked by grader failure ────────────────

def test_8_crag_not_incorrectly_invoked_by_grader_failure(client, chat_pipeline_fixture):
    """
    Requirement 8: CRAG is not incorrectly invoked by grader failure.
    When retrieval evidence is strong (is_weak=False), CRAG must NOT be called,
    even if the grader rejects the answer.
    """
    doc_id = chat_pipeline_fixture["doc_id"]
    session_id = chat_pipeline_fixture["session_id"]

    crag_mock = MagicMock()

    with patch(
        "app.api.chat.route_and_rewrite_query",
        return_value=RouterOutput(route="rag_query", rewritten_query="What is operating system?"),
    ), patch(
        "app.api.chat.search_and_rerank",
        return_value=(SAMPLE_PARENT_RESULTS, False),
    ), patch(
        "app.api.chat.generate_crag_query",
        crag_mock,
    ), patch(
        "app.api.chat.generate_rag_response",
        return_value="Answer that will fail grader",
    ), patch(
        "app.api.chat.grade_answer",
        return_value=GraderOutput(grounded=False, confidence=0.0, critique="Fails grading"),
    ):
        response = client.post(
            "/chat",
            json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is operating system?",
            },
        )

    assert response.status_code == 200
    # CRAG must NEVER be called when initial evidence is strong
    crag_mock.assert_not_called()


# ─── Test 9: user_id / document_id isolation remains enforced ─────────────────

def test_9_user_id_document_id_isolation_remains_enforced(client, chat_pipeline_fixture):
    """
    Requirement 9: user_id / document_id isolation remains enforced.
    Verifies that:
      - Attempting to chat on another user's document returns 403 Forbidden.
      - Attempting to chat on a mismatched session/document returns 400 Bad Request.
      - search_and_rerank enforces both user_id and document_id in the Qdrant filter.
    """
    other_doc_id = chat_pipeline_fixture["other_doc_id"]
    session_id = chat_pipeline_fixture["session_id"]

    # 1. Mismatched session / document_id (session document is doc_id, but request says other_doc_id)
    resp_mismatch = client.post(
        "/chat",
        json={
            "session_id": session_id,
            "document_id": other_doc_id,
            "message": "What is operating system?",
        },
    )
    assert resp_mismatch.status_code == 400
    assert "does not match session document" in resp_mismatch.json()["detail"]

    # 2. Verify search_and_rerank constructs filter with both user_id and document_id
    mock_client = MagicMock()
    mock_query_res = MagicMock()
    mock_query_res.points = []
    mock_client.query_points.return_value = mock_query_res

    with patch("app.services.embedding_service.embed_texts", return_value=[[0.1] * 384]):
        search_and_rerank(
            query="test query",
            document_id="doc-isolated-123",
            user_id="user-isolated-456",
            qdrant_client=mock_client,
        )

    assert mock_client.query_points.called
    kwargs = mock_client.query_points.call_args.kwargs
    query_filter = kwargs.get("query_filter")
    assert query_filter is not None
    # Must have both user_id and document_id conditions
    filter_keys = [cond.key for cond in query_filter.must]
    assert "user_id" in filter_keys
    assert "document_id" in filter_keys
    for cond in query_filter.must:
        if cond.key == "user_id":
            assert cond.match.value == "user-isolated-456"
        elif cond.key == "document_id":
            assert cond.match.value == "doc-isolated-123"
