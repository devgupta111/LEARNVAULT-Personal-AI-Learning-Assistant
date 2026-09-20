"""
tests/test_day5_agents.py

Comprehensive test suite for Day 5:
  - Query Router & Rewriter Agent (Single structured LLM call)
  - CRAG (Corrective Retrieval-Augmented Generation) Agent
  - Integration with POST /chat pipeline
  - Verification of non-streaming, security filters, fallback rules, and retry limits.
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError

from app.config import settings
from app.models.document import Document
from app.models.session import Session as ChatSession
from app.models.message import Message
from app.schemas.chat_schemas import RouterOutput, CRAGOutput, GraderOutput
from app.services.query_router_service import (
    route_and_rewrite_query,
    SIMPLE_GREETINGS,
)
from app.services.crag_service import generate_crag_query
from app.services.llm_service import REFUSAL_MESSAGE


from tests.conftest import TestSessionLocal


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def chat_setup(client):
    """Create a ready document and an active session for dev-user."""
    db = TestSessionLocal()
    # Ensure idempotency
    db.query(ChatSession).filter(ChatSession.id == "sess-day5-test").delete()
    db.query(Document).filter(Document.id == "doc-day5-test").delete()
    db.commit()

    doc = Document(
        id="doc-day5-test",
        user_id="dev-user",
        filename="lecture5.pdf",
        file_path="/tmp/doc-day5-test.pdf",
        status="READY",
        page_count=10,
    )
    db.add(doc)
    db.commit()

    sess = ChatSession(
        id="sess-day5-test",
        user_id="dev-user",
        document_id="doc-day5-test",
    )
    db.add(sess)
    db.commit()
    db.close()

    yield {"doc_id": "doc-day5-test", "session_id": "sess-day5-test"}

    db = TestSessionLocal()
    db.query(ChatSession).filter(ChatSession.id == "sess-day5-test").delete()
    db.query(Document).filter(Document.id == "doc-day5-test").delete()
    db.commit()
    db.close()


# ─── A-F: Query Router & Rewriter Unit Tests ──────────────────────────────────

class TestQueryRouterAgent:
    """Tests covering Router/Rewriter requirements (A through F)."""

    def test_router_direct_chat_fastpath(self):
        """A: Simple conversational greeting fast-paths to direct_chat without LLM."""
        for greeting in ("Hello", "hi", "thanks!", "Good morning"):
            result = route_and_rewrite_query(query=greeting, history=[])
            assert result.route == "direct_chat"
            assert result.rewritten_query == greeting.strip()

    def test_router_direct_chat_via_llm(self):
        """A2: Conversational query not in fast-path routes to direct_chat via LLM."""
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "route": "direct_chat",
                "rewritten_query": "how are you today"
            })))
        ]
        with patch("app.services.query_router_service._get_router_client") as mock_client:
            mock_client.return_value = (MagicMock(chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=mock_resp)))), "test-model")
            result = route_and_rewrite_query(query="how are you today", history=[])
            assert result.route == "direct_chat"

    def test_router_rag_query(self):
        """B: Academic questions requiring study material route to rag_query with rewritten query."""
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "route": "rag_query",
                "rewritten_query": "database normalization 1NF 2NF"
            })))
        ]
        with patch("app.services.query_router_service._get_router_client") as mock_client:
            mock_client.return_value = (MagicMock(chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=mock_resp)))), "test-model")
            result = route_and_rewrite_query(query="explain normalization forms", history=[])
            assert result.route == "rag_query"
            assert result.rewritten_query == "database normalization 1NF 2NF"

    def test_router_quiz_mode(self):
        """C: Quiz request produces route = quiz_mode."""
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "route": "quiz_mode",
                "rewritten_query": "quiz on operating systems"
            })))
        ]
        with patch("app.services.query_router_service._get_router_client") as mock_client:
            mock_client.return_value = (MagicMock(chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=mock_resp)))), "test-model")
            result = route_and_rewrite_query(query="quiz me on operating systems", history=[])
            assert result.route == "quiz_mode"
            assert result.rewritten_query == "quiz on operating systems"

    def test_router_structured_output_validation(self):
        """D: RouterOutput strictly rejects invalid routes."""
        with pytest.raises(ValidationError):
            RouterOutput(route="unknown_route", rewritten_query="test")

        # Valid routes must succeed
        for valid in ("direct_chat", "rag_query", "quiz_mode"):
            out = RouterOutput(route=valid, rewritten_query="test")
            assert out.route == valid

    def test_router_failure_fallback_on_exception(self):
        """E: Router failure (API error/timeout) safely falls back to rag_query with original query."""
        with patch("app.services.query_router_service._get_router_client") as mock_client:
            mock_client.side_effect = RuntimeError("Groq API connection timeout")
            result = route_and_rewrite_query(query="Explain deadlocks in OS", history=[])
            assert result.route == "rag_query"
            assert result.rewritten_query == "Explain deadlocks in OS"

    def test_router_failure_fallback_on_malformed_json(self):
        """E2: Malformed JSON output safely falls back to rag_query with original query."""
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="INVALID_NOT_JSON"))]
        with patch("app.services.query_router_service._get_router_client") as mock_client:
            mock_client.return_value = (MagicMock(chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=mock_resp)))), "test-model")
            result = route_and_rewrite_query(query="What is indexing?", history=[])
            assert result.route == "rag_query"
            assert result.rewritten_query == "What is indexing?"

    def test_query_rewriting_with_history(self):
        """F: Router resolves follow-up pronoun/reference against recent chat history."""
        history = [
            {"role": "user", "content": "What is normalization?"},
            {"role": "assistant", "content": "Normalization organizes database columns and tables to reduce redundancy."},
        ]
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "route": "rag_query",
                "rewritten_query": "Explain second normal form 2NF in relational databases"
            })))
        ]
        with patch("app.services.query_router_service._get_router_client") as mock_client:
            mock_client.return_value = (MagicMock(chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=mock_resp)))), "test-model")
            result = route_and_rewrite_query(query="Explain the second form.", history=history)
            assert result.route == "rag_query"
            assert "second normal form" in result.rewritten_query.lower() or "2nf" in result.rewritten_query.lower()


# ─── G-M: CRAG Agent Unit Tests ───────────────────────────────────────────────

class TestCRAGAgent:
    """Tests covering CRAG Agent requirements (G through M)."""

    def test_crag_generates_one_alternative_query(self):
        """H: CRAG generates exactly one concise alternative query."""
        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "alternative_query": "relational schema decomposition Boyce-Codd normal form"
            })))
        ]
        with patch("app.services.crag_service._get_crag_client") as mock_client:
            mock_client.return_value = (MagicMock(chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=mock_resp)))), "test-crag-model")
            res = generate_crag_query(query="BCNF normalization")
            assert res is not None
            assert res.alternative_query == "relational schema decomposition Boyce-Codd normal form"

    def test_crag_alternative_query_length_validation(self):
        """I: CRAG rejects excessively long queries (> 300 chars) or empty queries."""
        # Empty query
        mock_resp_empty = MagicMock()
        mock_resp_empty.choices = [
            MagicMock(message=MagicMock(content=json.dumps({"alternative_query": "   "})))
        ]
        with patch("app.services.crag_service._get_crag_client") as mock_client:
            mock_client.return_value = (MagicMock(chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=mock_resp_empty)))), "model")
            assert generate_crag_query(query="test") is None

        # Excessively long query (> 300 characters)
        mock_resp_long = MagicMock()
        mock_resp_long.choices = [
            MagicMock(message=MagicMock(content=json.dumps({"alternative_query": "word " * 100})))
        ]
        with patch("app.services.crag_service._get_crag_client") as mock_client:
            mock_client.return_value = (MagicMock(chat=MagicMock(completions=MagicMock(create=MagicMock(return_value=mock_resp_long)))), "model")
            assert generate_crag_query(query="test") is None

    def test_crag_failure_returns_none(self):
        """M: CRAG returns None on API failure, timeout, or invalid JSON."""
        with patch("app.services.crag_service._get_crag_client") as mock_client:
            mock_client.side_effect = RuntimeError("CRAG API unavailable")
            assert generate_crag_query(query="test query") is None


# ─── N-Q: Chat Endpoint Integration Tests ─────────────────────────────────────

class TestChatPipelineDay5:
    """Full pipeline integration tests for Day 5 /chat endpoint."""

    def test_direct_chat_skips_retrieval(self, client, chat_setup):
        """N: direct_chat skips embedding, Qdrant, reranking, and CRAG."""
        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.generate_direct_chat_response") as mock_direct, \
             patch("app.api.chat.search_and_rerank") as mock_search:

            mock_router.return_value = RouterOutput(route="direct_chat", rewritten_query="hi")
            mock_direct.return_value = "Hello! How can I assist you with your studies?"

            resp = client.post(
                "/chat",
                json={
                    "session_id": chat_setup["session_id"],
                    "document_id": chat_setup["doc_id"],
                    "message": "Hi!",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["answer"] == "Hello! How can I assist you with your studies?"
            assert data["citations"] == []
            # Crucial check: search_and_rerank MUST NOT be called
            mock_search.assert_not_called()

    def test_quiz_mode_routing_stub(self, client, chat_setup):
        """C & Step 7: quiz_mode produces controlled stub without building quiz agent."""
        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search:

            mock_router.return_value = RouterOutput(route="quiz_mode", rewritten_query="quiz me")

            resp = client.post(
                "/chat",
                json={
                    "session_id": chat_setup["session_id"],
                    "document_id": chat_setup["doc_id"],
                    "message": "Give me a quiz on chapter 3",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert "quiz mode" in data["answer"].lower() or "day 6" in data["answer"].lower()
            assert data["citations"] == []
            mock_search.assert_not_called()

    def test_rag_query_uses_rewritten_query_for_retrieval(self, client, chat_setup):
        """O: RAG retrieval uses rewritten query, but original message is stored in PostgreSQL."""
        dummy_parent = [{
            "parent_chunk_id": "p-1",
            "document_id": chat_setup["doc_id"],
            "page_start": 2,
            "page_end": 2,
            "parent_text": "Indexing uses B-Trees.",
            "subject": "DB",
        }]

        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_rag_response") as mock_rag:

            mock_router.return_value = RouterOutput(
                route="rag_query",
                rewritten_query="B-Tree indexing algorithms in databases"
            )
            mock_search.return_value = (dummy_parent, False)  # Strong evidence
            mock_rag.return_value = "B-Trees are self-balancing search trees [Source 1]."

            resp = client.post(
                "/chat",
                json={
                    "session_id": chat_setup["session_id"],
                    "document_id": chat_setup["doc_id"],
                    "message": "tell me about that tree thing",
                },
            )

            assert resp.status_code == 200
            # Verify retrieval received the rewritten query
            mock_search.assert_called_once_with(
                query="B-Tree indexing algorithms in databases",
                document_id=chat_setup["doc_id"],
                user_id="dev-user",
                threshold=settings.RERANK_THRESHOLD,
                top_k=settings.RERANK_TOP_K,
            )

            # Verify PostgreSQL stored the ORIGINAL user message
            db = TestSessionLocal()
            try:
                user_msg = (
                    db.query(Message)
                    .filter(Message.session_id == chat_setup["session_id"], Message.sender == "user")
                    .order_by(Message.created_at.desc())
                    .first()
                )
                assert user_msg is not None
                assert user_msg.content == "tell me about that tree thing"
            finally:
                db.close()

    def test_crag_weak_evidence_triggers_single_retry_success(self, client, chat_setup):
        """G, J, K: Initial weak retrieval triggers CRAG -> retry succeeds with strong evidence."""
        strong_parent = [{
            "parent_chunk_id": "p-crag",
            "document_id": chat_setup["doc_id"],
            "page_start": 5,
            "page_end": 5,
            "parent_text": "Virtual memory paging tables.",
            "subject": "OS",
        }]

        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_crag_query") as mock_crag, \
             patch("app.api.chat.generate_rag_response") as mock_rag, \
             patch("app.api.chat.grade_answer") as mock_grader:

            mock_grader.return_value = GraderOutput(grounded=True, confidence=0.95, critique="")
            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="paging")
            # 1st retrieval weak, 2nd retrieval strong
            mock_search.side_effect = [
                ([], True),               # Initial retrieval is weak
                (strong_parent, False),   # Second retrieval is strong
            ]
            mock_crag.return_value = CRAGOutput(alternative_query="virtual memory page tables")
            mock_rag.return_value = "Page tables map virtual addresses [Source 1]."

            resp = client.post(
                "/chat",
                json={
                    "session_id": chat_setup["session_id"],
                    "document_id": chat_setup["doc_id"],
                    "message": "paging",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert "Page tables map virtual addresses" in data["answer"]
            assert len(data["citations"]) == 1

            # Assert exactly TWO search_and_rerank calls (1 initial + 1 CRAG retry)
            assert mock_search.call_count == 2
            # First search used original/rewritten query
            assert mock_search.call_args_list[0].kwargs["query"] == "paging"
            # Second search used CRAG alternative query
            assert mock_search.call_args_list[1].kwargs["query"] == "virtual memory page tables"

    def test_crag_weak_evidence_remains_weak_returns_refusal(self, client, chat_setup):
        """L: Initial weak retrieval triggers CRAG -> retry also weak -> returns refusal."""
        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_crag_query") as mock_crag:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="quantum physics")
            # Both attempts weak
            mock_search.side_effect = [
                ([], True),  # 1st attempt weak
                ([], True),  # 2nd attempt weak
            ]
            mock_crag.return_value = CRAGOutput(alternative_query="quantum mechanics wave functions")

            resp = client.post(
                "/chat",
                json={
                    "session_id": chat_setup["session_id"],
                    "document_id": chat_setup["doc_id"],
                    "message": "quantum physics",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["answer"] == REFUSAL_MESSAGE
            assert data["citations"] == []
            # Exactly two attempts, then refused
            assert mock_search.call_count == 2

    def test_crag_failure_immediately_returns_refusal(self, client, chat_setup):
        """M: If CRAG model call fails, immediately return Day-4 refusal without 2nd search."""
        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_crag_query") as mock_crag:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="something obscure")
            mock_search.return_value = ([], True)  # Weak
            mock_crag.return_value = None          # CRAG failed

            resp = client.post(
                "/chat",
                json={
                    "session_id": chat_setup["session_id"],
                    "document_id": chat_setup["doc_id"],
                    "message": "something obscure",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["answer"] == REFUSAL_MESSAGE
            assert data["citations"] == []
            # Search called only once since CRAG failed
            assert mock_search.call_count == 1

    def test_security_filters_strictly_enforced_in_crag_retry(self, client, chat_setup):
        """P: Both initial retrieval and CRAG retry strictly enforce user_id and document_id."""
        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.search_and_rerank") as mock_search, \
             patch("app.api.chat.generate_crag_query") as mock_crag:

            mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="q1")
            mock_search.side_effect = [([], True), ([], True)]
            mock_crag.return_value = CRAGOutput(alternative_query="q2")

            client.post(
                "/chat",
                json={
                    "session_id": chat_setup["session_id"],
                    "document_id": chat_setup["doc_id"],
                    "message": "q1",
                },
            )

            assert mock_search.call_count == 2
            for call in mock_search.call_args_list:
                assert call.kwargs["document_id"] == chat_setup["doc_id"]
                assert call.kwargs["user_id"] == "dev-user"

    def test_no_streaming_behavior(self, client, chat_setup):
        """Q: Verify POST /chat returns standard application/json, not text/event-stream."""
        with patch("app.api.chat.route_and_rewrite_query") as mock_router, \
             patch("app.api.chat.generate_direct_chat_response") as mock_direct:

            mock_router.return_value = RouterOutput(route="direct_chat", rewritten_query="hi")
            mock_direct.return_value = "Hello"

            resp = client.post(
                "/chat",
                json={
                    "session_id": chat_setup["session_id"],
                    "document_id": chat_setup["doc_id"],
                    "message": "hi",
                },
            )

            assert resp.headers["content-type"].startswith("application/json")
            assert "text/event-stream" not in resp.headers["content-type"]
