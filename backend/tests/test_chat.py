"""
tests/test_chat.py

Day-4 chat API tests.

Coverage:
    - POST /sessions: create session, document not found, wrong user, not READY
    - GET  /sessions: list user sessions
    - POST /chat: valid request flow (mocked LLM + retrieval)
    - POST /chat: empty message validation
    - POST /chat: invalid session (not found, wrong user, wrong document)
    - POST /chat: invalid document (not found, wrong user, not READY)
    - POST /chat: weak retrieval → refusal
    - GET  /sessions/{id}/messages: list messages with correct ordering
    - GET  /sessions/{id}/messages: session not found → 404
    - GET  /sessions/{id}/messages: wrong user → 403
    - GET  /chat/status: 200

All tests use:
    - In-memory SQLite (from conftest.py)
    - Mocked search_and_rerank (no real Qdrant/embeddings needed)
    - Mocked generate_rag_response (no real LLM needed)

Note on DetachedInstanceError:
    All helper functions return plain string IDs (not ORM objects) because
    the SQLAlchemy session is closed before the test body runs. Accessing
    ORM object attributes after session close raises DetachedInstanceError.
"""

import json
import uuid
from typing import Tuple
from unittest.mock import patch

import pytest

from app.models.document import Document
from app.models.session import Session as ChatSession
from app.models.message import Message


# ─── Helpers — return plain string IDs, never detached ORM objects ────────────

def _make_ready_document(db, user_id: str = "dev-user") -> str:
    """Insert a READY document and return its id (str)."""
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        user_id=user_id,
        filename="test.pdf",
        subject="Test Subject",
        file_path=f"/tmp/{doc_id}.pdf",
        status="READY",
    )
    db.add(doc)
    db.commit()
    return doc_id


def _make_processing_document(db, user_id: str = "dev-user") -> str:
    """Insert a PROCESSING document and return its id (str)."""
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        user_id=user_id,
        filename="pending.pdf",
        subject="Pending",
        file_path=f"/tmp/{doc_id}.pdf",
        status="PROCESSING",
    )
    db.add(doc)
    db.commit()
    return doc_id


def _make_session(db, document_id: str, user_id: str = "dev-user") -> str:
    """Insert a chat session and return its id (str)."""
    session_id = str(uuid.uuid4())
    session = ChatSession(
        id=session_id,
        user_id=user_id,
        document_id=document_id,
    )
    db.add(session)
    db.commit()
    return session_id


def _setup_doc_and_session(db, user_id: str = "dev-user") -> Tuple[str, str]:
    """Create a READY document + session, return (doc_id, session_id)."""
    doc_id = _make_ready_document(db, user_id=user_id)
    session_id = _make_session(db, doc_id, user_id=user_id)
    return doc_id, session_id


# Fake parent results returned by the mocked retrieval pipeline
_FAKE_PARENT_RESULTS = [
    {
        "parent_chunk_id": "parent-uuid-1",
        "parent_text": "Machine learning is a subset of artificial intelligence.",
        "document_id": "doc-1",
        "user_id": "dev-user",
        "subject": "AI",
        "page_start": 1,
        "page_end": 2,
        "text": "Machine learning is a subset of AI.",
    }
]

_FAKE_ANSWER = "Machine learning is a subset of AI [Source 1]."


# ─── POST /sessions ───────────────────────────────────────────────────────────

class TestCreateSession:
    def test_create_session_success(self, client):
        """Creates a session for a READY document owned by dev-user."""
        from tests.conftest import TestSessionLocal
        db = TestSessionLocal()
        doc_id = _make_ready_document(db)
        db.close()

        resp = client.post("/sessions", json={"document_id": doc_id})
        assert resp.status_code == 201
        data = resp.json()
        assert "session_id" in data
        assert data["document_id"] == doc_id

    def test_create_session_document_not_found(self, client):
        resp = client.post("/sessions", json={"document_id": "nonexistent-doc"})
        assert resp.status_code == 404

    def test_create_session_document_not_ready(self, client):
        from tests.conftest import TestSessionLocal
        db = TestSessionLocal()
        doc_id = _make_processing_document(db)
        db.close()

        resp = client.post("/sessions", json={"document_id": doc_id})
        assert resp.status_code == 422

    def test_create_session_empty_document_id(self, client):
        resp = client.post("/sessions", json={"document_id": "   "})
        assert resp.status_code == 422

    def test_create_session_wrong_user_owns_document(self, client):
        """A document belonging to another user must not be accessible."""
        from tests.conftest import TestSessionLocal
        db = TestSessionLocal()
        doc_id = _make_ready_document(db, user_id="other-user")
        db.close()

        resp = client.post("/sessions", json={"document_id": doc_id})
        assert resp.status_code == 403


# ─── GET /sessions ────────────────────────────────────────────────────────────

class TestListSessions:
    def test_list_sessions_empty(self, client):
        resp = client.get("/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_sessions_returns_own_sessions(self, client):
        from tests.conftest import TestSessionLocal
        db = TestSessionLocal()
        doc_id = _make_ready_document(db)
        _make_session(db, doc_id)
        _make_session(db, doc_id)
        db.close()

        resp = client.get("/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        for item in data:
            assert "session_id" in item
            assert "document_id" in item


# ─── GET /sessions/{session_id}/messages ─────────────────────────────────────

class TestListMessages:
    def test_list_messages_empty_session(self, client):
        from tests.conftest import TestSessionLocal
        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        resp = client.get(f"/sessions/{session_id}/messages")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_messages_not_found(self, client):
        resp = client.get("/sessions/nonexistent-session/messages")
        assert resp.status_code == 404

    def test_list_messages_wrong_user(self, client):
        """A session belonging to another user must not be accessible."""
        from tests.conftest import TestSessionLocal
        db = TestSessionLocal()
        doc_id = _make_ready_document(db, user_id="other-user")
        session_id = _make_session(db, doc_id, user_id="other-user")
        db.close()

        resp = client.get(f"/sessions/{session_id}/messages")
        assert resp.status_code == 403

    def test_list_messages_chronological_order(self, client):
        """Messages must be returned in ascending (chronological) order."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)

        msg1 = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            sender="user",
            content="First question",
            citations=None,
        )
        db.add(msg1)
        db.commit()

        msg2 = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            sender="assistant",
            content="First answer",
            citations=None,
        )
        db.add(msg2)
        db.commit()
        db.close()

        resp = client.get(f"/sessions/{session_id}/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["sender"] == "user"
        assert data[0]["content"] == "First question"
        assert data[1]["sender"] == "assistant"
        assert data[1]["content"] == "First answer"

    def test_list_messages_includes_citations(self, client):
        """Citations stored with assistant messages should be returned."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)

        citations_data = [
            {
                "source_id": "Source 1",
                "document_id": doc_id,
                "page_start": 1,
                "page_end": 2,
                "parent_chunk_id": "chunk-1",
                "subject": "AI",
            }
        ]
        msg = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            sender="assistant",
            content="Some answer [Source 1].",
            citations=json.dumps(citations_data),
        )
        db.add(msg)
        db.commit()
        db.close()

        resp = client.get(f"/sessions/{session_id}/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        citations = data[0]["citations"]
        assert len(citations) == 1
        assert citations[0]["source_id"] == "Source 1"
        assert citations[0]["page_start"] == 1


# ─── POST /chat ───────────────────────────────────────────────────────────────

class TestChat:
    def test_chat_weak_retrieval_returns_refusal(self, client):
        """When retrieval is weak, the endpoint returns the refusal message."""
        from tests.conftest import TestSessionLocal
        from app.services.llm_service import REFUSAL_MESSAGE

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        with patch(
            "app.api.chat.search_and_rerank",
            return_value=([], True),  # empty results, is_weak=True
        ):
            resp = client.post("/chat", json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is quantum entanglement?",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == REFUSAL_MESSAGE
        assert data["citations"] == []
        assert data["session_id"] == session_id

    def test_chat_strong_retrieval_returns_answer(self, client):
        """When retrieval is strong, the endpoint returns the LLM answer with citations."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        with patch(
            "app.api.chat.search_and_rerank",
            return_value=(_FAKE_PARENT_RESULTS, False),
        ), patch(
            "app.api.chat.generate_rag_response",
            return_value=_FAKE_ANSWER,
        ):
            resp = client.post("/chat", json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is machine learning?",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == _FAKE_ANSWER
        assert data["session_id"] == session_id
        assert len(data["citations"]) == 1
        assert data["citations"][0]["source_id"] == "Source 1"

    def test_chat_persists_messages(self, client):
        """After a successful chat, messages are stored in the DB."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        with patch(
            "app.api.chat.search_and_rerank",
            return_value=(_FAKE_PARENT_RESULTS, False),
        ), patch(
            "app.api.chat.generate_rag_response",
            return_value=_FAKE_ANSWER,
        ):
            client.post("/chat", json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is machine learning?",
            })

        # Verify messages were persisted
        resp = client.get(f"/sessions/{session_id}/messages")
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 2
        assert messages[0]["sender"] == "user"
        assert messages[0]["content"] == "What is machine learning?"
        assert messages[1]["sender"] == "assistant"
        assert messages[1]["content"] == _FAKE_ANSWER

    def test_chat_refusal_persists_messages(self, client):
        """After a refusal, both the user question and refusal are stored."""
        from tests.conftest import TestSessionLocal
        from app.services.llm_service import REFUSAL_MESSAGE

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        with patch(
            "app.api.chat.search_and_rerank",
            return_value=([], True),
        ):
            client.post("/chat", json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "Tell me about aliens.",
            })

        resp = client.get(f"/sessions/{session_id}/messages")
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 2
        assert messages[0]["sender"] == "user"
        assert messages[1]["sender"] == "assistant"
        assert messages[1]["content"] == REFUSAL_MESSAGE

    def test_chat_empty_message_rejected(self, client):
        """An empty message should return HTTP 422."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        resp = client.post("/chat", json={
            "session_id": session_id,
            "document_id": doc_id,
            "message": "   ",
        })
        assert resp.status_code == 422

    def test_chat_session_not_found(self, client):
        resp = client.post("/chat", json={
            "session_id": "nonexistent-session",
            "document_id": "some-doc",
            "message": "What is ML?",
        })
        assert resp.status_code == 404

    def test_chat_session_wrong_user(self, client):
        """Session belonging to another user must return 403."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id = _make_ready_document(db, user_id="other-user")
        session_id = _make_session(db, doc_id, user_id="other-user")
        db.close()

        resp = client.post("/chat", json={
            "session_id": session_id,
            "document_id": doc_id,
            "message": "What is ML?",
        })
        assert resp.status_code == 403

    def test_chat_document_mismatch(self, client):
        """Requesting with a document_id that doesn't match the session's document must fail."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        other_doc_id = _make_ready_document(db)
        db.close()

        resp = client.post("/chat", json={
            "session_id": session_id,
            "document_id": other_doc_id,  # Wrong document for this session
            "message": "What is ML?",
        })
        assert resp.status_code == 400

    def test_chat_document_not_ready(self, client):
        """A session with a PROCESSING document should be rejected."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id = _make_processing_document(db)
        session_id = _make_session(db, doc_id)
        db.close()

        resp = client.post("/chat", json={
            "session_id": session_id,
            "document_id": doc_id,
            "message": "What is ML?",
        })
        assert resp.status_code == 422

    def test_chat_document_not_found(self, client):
        """A session referencing a deleted document should return 404 on chat."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        # Create session with a document_id that doesn't exist in DB
        ghost_doc_id = str(uuid.uuid4())
        session_id = _make_session(db, ghost_doc_id)
        db.close()

        resp = client.post("/chat", json={
            "session_id": session_id,
            "document_id": ghost_doc_id,
            "message": "What is ML?",
        })
        assert resp.status_code == 404

    def test_chat_retrieval_error_returns_503(self, client):
        """If the retrieval pipeline throws, the endpoint should return 503."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        with patch(
            "app.api.chat.search_and_rerank",
            side_effect=RuntimeError("Qdrant is down"),
        ):
            resp = client.post("/chat", json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is ML?",
            })

        assert resp.status_code == 503

    def test_chat_llm_error_returns_503(self, client):
        """If LLM generation throws, the endpoint should return 503."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        with patch(
            "app.api.chat.search_and_rerank",
            return_value=(_FAKE_PARENT_RESULTS, False),
        ), patch(
            "app.api.chat.generate_rag_response",
            side_effect=RuntimeError("LLM timeout"),
        ):
            resp = client.post("/chat", json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "What is ML?",
            })

        assert resp.status_code == 503

    def test_chat_history_used_in_next_turn(self, client):
        """After one exchange, the second turn should see non-empty history."""
        from tests.conftest import TestSessionLocal

        db = TestSessionLocal()
        doc_id, session_id = _setup_doc_and_session(db)
        db.close()

        from app.schemas.chat_schemas import RouterOutput

        # First turn
        with patch(
            "app.api.chat.route_and_rewrite_query",
            return_value=RouterOutput(route="rag_query", rewritten_query="First question"),
        ), patch(
            "app.api.chat.search_and_rerank",
            return_value=(_FAKE_PARENT_RESULTS, False),
        ), patch(
            "app.api.chat.generate_rag_response",
            return_value=_FAKE_ANSWER,
        ):
            client.post("/chat", json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "First question",
            })

        # Second turn — capture history passed to generate_rag_response
        captured_history = []

        def fake_generate(query, parent_results, history=None):
            captured_history.extend(history or [])
            return "Second answer"

        with patch(
            "app.api.chat.route_and_rewrite_query",
            return_value=RouterOutput(route="rag_query", rewritten_query="Second question"),
        ), patch(
            "app.api.chat.search_and_rerank",
            return_value=(_FAKE_PARENT_RESULTS, False),
        ), patch(
            "app.api.chat.generate_rag_response",
            side_effect=fake_generate,
        ):
            resp = client.post("/chat", json={
                "session_id": session_id,
                "document_id": doc_id,
                "message": "Second question",
            })

        assert resp.status_code == 200
        # History should contain at least the first turn (user + assistant)
        assert len(captured_history) >= 2
        assert captured_history[0]["role"] == "user"
        assert captured_history[0]["content"] == "First question"


# ─── GET /chat/status ─────────────────────────────────────────────────────────

class TestChatStatus:
    def test_chat_status_200(self, client):
        resp = client.get("/chat/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["day"] in (5, 6)
        assert "Core RAG pipeline" in data["features"]
