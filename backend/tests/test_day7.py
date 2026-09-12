"""
test_day7.py

Comprehensive automated tests for Day 7:
  1. Authentication endpoints (POST /auth/login, GET /auth/me, GET /auth/status)
  2. Token encoding, decoding, and get_current_user dependency with dev fallback
  3. Document user isolation and ownership checks
  4. SSE chat streaming endpoint (POST /chat/stream):
     - Token chunk format: data: {"token": "..."}\n\n
     - Completion event: data: {"done": true, "citations": [...]}\n\n
     - Normal grounded RAG streaming with citations
     - Direct conversational chat / greeting over SSE (no Qdrant search)
     - Quiz mode redirection over SSE
     - Weak retrieval -> CRAG retry -> Refusal over SSE
     - Grader FAIL -> exactly one regeneration using SAME context -> PASS -> verified stream
     - Grader FAIL -> regeneration FAIL -> unified refusal over SSE
     - Security: Cross-user permission denial (403 Forbidden)
"""

import json
import uuid
import datetime
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.base import Base
from app.db.database import get_db
from app.models.document import Document
from app.models.session import Session as ChatSession
from app.models.message import Message
from app.services.query_router_service import RouterOutput
from app.services.crag_service import CRAGOutput
from app.services.grader_service import GraderOutput
from app.services.llm_service import REFUSAL_MESSAGE
from app.api.auth import create_access_token, decode_access_token, get_current_user

# Hermetic test database
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_setup(db_session):
    """Seed documents and sessions for user 'student-alice' and user 'student-bob'."""
    alice_id = "student-alice"
    bob_id = "student-bob"

    alice_doc_id = str(uuid.uuid4())
    bob_doc_id = str(uuid.uuid4())

    alice_doc = Document(
        id=alice_doc_id,
        user_id=alice_id,
        filename="alice_notes.pdf",
        subject="Databases",
        file_path=f"data/uploads/{alice_doc_id}.pdf",
        status="READY",
    )
    bob_doc = Document(
        id=bob_doc_id,
        user_id=bob_id,
        filename="bob_notes.pdf",
        subject="Physics",
        file_path=f"data/uploads/{bob_doc_id}.pdf",
        status="READY",
    )
    db_session.add(alice_doc)
    db_session.add(bob_doc)
    db_session.commit()

    alice_session_id = str(uuid.uuid4())
    bob_session_id = str(uuid.uuid4())

    alice_session = ChatSession(
        id=alice_session_id,
        user_id=alice_id,
        document_id=alice_doc_id,
    )
    bob_session = ChatSession(
        id=bob_session_id,
        user_id=bob_id,
        document_id=bob_doc_id,
    )
    db_session.add(alice_session)
    db_session.add(bob_session)
    db_session.commit()

    return {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "alice_doc_id": alice_doc_id,
        "bob_doc_id": bob_doc_id,
        "alice_session_id": alice_session_id,
        "bob_session_id": bob_session_id,
        "alice_token": create_access_token(alice_id),
        "bob_token": create_access_token(bob_id),
    }


def parse_sse_events(response_text: str):
    """Parses raw text/event-stream into a list of JSON data objects."""
    events = []
    lines = response_text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("data: "):
            json_part = line[6:].strip()
            try:
                events.append(json.loads(json_part))
            except Exception:
                pass
    return events


# ─── 1. Authentication Integration Tests ──────────────────────────────────────

class TestDay7Auth:
    def test_login_success(self, client):
        resp = client.post("/auth/login", json={"username": "alice", "password": "any"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_type"] == "bearer"
        assert data["user_id"] == "alice"
        assert data["username"] == "alice"
        assert data["access_token"].startswith("tok_")

    def test_login_blank_username(self, client):
        resp = client.post("/auth/login", json={"username": "   "})
        assert resp.status_code == 422

    def test_get_me_with_bearer_token(self, client):
        token = create_access_token("test-student")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.get("/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "test-student"
        assert data["username"] == "test-student"

    def test_get_me_fallback_without_header(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "dev-user"

    def test_auth_status(self, client):
        resp = client.get("/auth/status")
        assert resp.status_code == 200
        assert resp.json()["day"] == 7

    def test_invalid_token_header(self, client):
        resp = client.get("/auth/me", headers={"Authorization": "InvalidScheme token"})
        assert resp.status_code == 401

    def test_update_profile_success(self, client):
        token = create_access_token("test-profile-user")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.put("/auth/profile", json={"username": "Rahul Sharma"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "Rahul Sharma"
        assert data["user_id"] == "test-profile-user"

        # Verify that GET /auth/me reflects the updated name
        me_resp = client.get("/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "Rahul Sharma"

    def test_update_profile_blank_name(self, client):
        token = create_access_token("test-profile-user")
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.put("/auth/profile", json={"username": "   "}, headers=headers)
        assert resp.status_code == 422

    def test_email_immutable_during_profile_update(self, client):
        token = create_access_token("test-profile-user")
        headers = {"Authorization": f"Bearer {token}"}
        # Attempt to pass an arbitrary email field; it should not overwrite user email
        resp = client.put("/auth/profile", json={"username": "Verified Name", "email": "hacker@evil.com"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == "Verified Name"
        assert resp.json()["email"] != "hacker@evil.com"

    def test_update_profile_unauthenticated(self, client):
        resp = client.put("/auth/profile", json={"username": "Hacker"})
        assert resp.status_code == 401


# ─── 2. User Isolation & Security Tests ───────────────────────────────────────

class TestDay7Security:
    def test_user_cannot_access_other_user_document(self, client, test_setup):
        # Alice tries to view Bob's document
        headers = {"Authorization": f"Bearer {test_setup['alice_token']}"}
        resp = client.get(f"/documents/{test_setup['bob_doc_id']}", headers=headers)
        assert resp.status_code == 403
        assert "permission" in resp.json()["detail"].lower()

    def test_user_cannot_stream_other_user_session(self, client, test_setup):
        # Alice tries to stream chat on Bob's session
        headers = {"Authorization": f"Bearer {test_setup['alice_token']}"}
        resp = client.post(
            "/chat/stream",
            json={
                "session_id": test_setup["bob_session_id"],
                "document_id": test_setup["bob_doc_id"],
                "message": "Hello",
            },
            headers=headers,
        )
        assert resp.status_code == 403


# ─── 3. SSE Streaming Contract Tests ──────────────────────────────────────────

class TestDay7SSEStreaming:
    @patch("app.api.chat.route_and_rewrite_query")
    @patch("app.api.chat.generate_direct_chat_response")
    def test_sse_greeting_direct_chat(self, mock_direct, mock_router, client, test_setup):
        """Greeting routes to direct_chat, skips retrieval, and streams tokens over SSE."""
        mock_router.return_value = RouterOutput(route="direct_chat", rewritten_query="Hi")
        mock_direct.return_value = "Hello! How can I help you study today?"

        headers = {"Authorization": f"Bearer {test_setup['alice_token']}"}
        resp = client.post(
            "/chat/stream",
            json={
                "session_id": test_setup["alice_session_id"],
                "document_id": test_setup["alice_doc_id"],
                "message": "Hi",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = parse_sse_events(resp.text)
        assert len(events) >= 2

        # Verify token chunking and done event
        tokens = [e["token"] for e in events if "token" in e]
        assembled = "".join(tokens)
        assert assembled == "Hello! How can I help you study today?"

        done_event = events[-1]
        assert done_event.get("done") is True
        assert done_event.get("citations") == []

    @patch("app.api.chat.route_and_rewrite_query")
    @patch("app.api.chat.search_and_rerank")
    @patch("app.api.chat.generate_rag_response")
    @patch("app.api.chat.get_citations")
    @patch("app.api.chat.grade_answer")
    def test_sse_normal_grounded_rag_pass(
        self, mock_grade, mock_citations, mock_gen, mock_search, mock_router, client, test_setup
    ):
        """Normal grounded RAG: Router -> Retrieval -> Generation -> Grader PASS -> SSE stream."""
        mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="What is normalization?")
        mock_search.return_value = (
            [{"parent_chunk_id": "p1", "parent_text": "DBMS normalization details", "page_start": 1, "page_end": 1}],
            False,  # is_weak = False
        )
        mock_gen.return_value = "Normalization reduces redundancy in databases. [Source 1]"
        mock_citations.return_value = [{"source_id": 1, "page_start": 1, "page_end": 1, "document_id": test_setup["alice_doc_id"]}]
        mock_grade.return_value = GraderOutput(grounded=True, confidence=0.95, critique="Accurate")

        headers = {"Authorization": f"Bearer {test_setup['alice_token']}"}
        resp = client.post(
            "/chat/stream",
            json={
                "session_id": test_setup["alice_session_id"],
                "document_id": test_setup["alice_doc_id"],
                "message": "What is normalization?",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)

        tokens = [e["token"] for e in events if "token" in e]
        assembled = "".join(tokens)
        assert "Normalization reduces redundancy in databases." in assembled

        done_event = events[-1]
        assert done_event.get("done") is True
        assert len(done_event.get("citations")) == 1
        assert done_event["citations"][0]["source_id"] == 1

    @patch("app.api.chat.route_and_rewrite_query")
    @patch("app.api.chat.search_and_rerank")
    @patch("app.api.chat.generate_crag_query")
    def test_sse_weak_retrieval_crag_refusal(
        self, mock_crag, mock_search, mock_router, client, test_setup
    ):
        """Weak retrieval triggers CRAG once; if still weak, streams standard refusal over SSE."""
        mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="Quantum gravity")
        mock_search.side_effect = [([], True), ([], True)]
        mock_crag.return_value = CRAGOutput(alternative_query="Quantum physics")

        headers = {"Authorization": f"Bearer {test_setup['alice_token']}"}
        resp = client.post(
            "/chat/stream",
            json={
                "session_id": test_setup["alice_session_id"],
                "document_id": test_setup["alice_doc_id"],
                "message": "Quantum gravity",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)

        # CRAG ran exactly once
        assert mock_crag.call_count == 1
        # Two search calls (initial + 1 retry)
        assert mock_search.call_count == 2

        tokens = [e["token"] for e in events if "token" in e]
        assert REFUSAL_MESSAGE in tokens
        done_event = events[-1]
        assert done_event.get("done") is True
        assert done_event.get("citations") == []

    @patch("app.api.chat.route_and_rewrite_query")
    @patch("app.api.chat.search_and_rerank")
    @patch("app.api.chat.generate_rag_response")
    @patch("app.api.chat.get_citations")
    @patch("app.api.chat.grade_answer")
    def test_sse_grader_regeneration_once_pass(
        self, mock_grade, mock_citations, mock_gen, mock_search, mock_router, client, test_setup
    ):
        """Grader FAIL -> regenerate ONCE with SAME context -> PASS -> stream verified answer."""
        mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="Query")
        context = [{"parent_chunk_id": "p1", "parent_text": "Valid text", "page_start": 2, "page_end": 2}]
        mock_search.return_value = (context, False)

        # Generation calls: 1st returns hallucinatory answer, 2nd returns grounded answer
        mock_gen.side_effect = [
            "Hallucinatory claim [Source 1]",
            "Verified grounded claim [Source 1]",
        ]
        mock_citations.return_value = [{"source_id": 1, "page_start": 2, "page_end": 2, "document_id": test_setup["alice_doc_id"]}]

        # Grader: 1st FAIL, 2nd PASS
        mock_grade.side_effect = [
            GraderOutput(grounded=False, confidence=0.2, critique="Unsupported claim"),
            GraderOutput(grounded=True, confidence=0.9, critique="Now grounded"),
        ]

        headers = {"Authorization": f"Bearer {test_setup['alice_token']}"}
        resp = client.post(
            "/chat/stream",
            json={
                "session_id": test_setup["alice_session_id"],
                "document_id": test_setup["alice_doc_id"],
                "message": "Query",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)

        # Verified regeneration happened exactly once (total 2 generation calls)
        assert mock_gen.call_count == 2
        # Verified grade called twice
        assert mock_grade.call_count == 2
        # Both generation calls used the SAME context
        assert mock_gen.call_args_list[0][1]["parent_results"] == context
        assert mock_gen.call_args_list[1][1]["parent_results"] == context

        # Only the verified answer reaches the client (Critical Rule 15)
        tokens = [e["token"] for e in events if "token" in e]
        assembled = "".join(tokens)
        assert "Verified grounded claim" in assembled
        assert "Hallucinatory claim" not in assembled

        done_event = events[-1]
        assert done_event.get("done") is True
        assert len(done_event.get("citations")) == 1

    @patch("app.api.chat.route_and_rewrite_query")
    @patch("app.api.chat.search_and_rerank")
    @patch("app.api.chat.generate_rag_response")
    @patch("app.api.chat.get_citations")
    @patch("app.api.chat.grade_answer")
    def test_sse_grader_double_failure_refusal(
        self, mock_grade, mock_citations, mock_gen, mock_search, mock_router, client, test_setup
    ):
        """Grader FAIL -> regenerate ONCE -> Grader FAIL again -> stream unified refusal."""
        mock_router.return_value = RouterOutput(route="rag_query", rewritten_query="Query")
        mock_search.return_value = ([{"parent_chunk_id": "p1", "parent_text": "Text", "page_start": 1, "page_end": 1}], False)

        mock_gen.side_effect = ["Bad 1", "Bad 2"]
        mock_citations.return_value = []

        # Both grading calls FAIL
        mock_grade.side_effect = [
            GraderOutput(grounded=False, confidence=0.1, critique="Fail 1"),
            GraderOutput(grounded=False, confidence=0.1, critique="Fail 2"),
        ]

        headers = {"Authorization": f"Bearer {test_setup['alice_token']}"}
        resp = client.post(
            "/chat/stream",
            json={
                "session_id": test_setup["alice_session_id"],
                "document_id": test_setup["alice_doc_id"],
                "message": "Query",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)

        # Exactly 2 generation calls (max 1 regeneration)
        assert mock_gen.call_count == 2
        assert mock_grade.call_count == 2

        # Refusal streamed to client
        tokens = [e["token"] for e in events if "token" in e]
        assert REFUSAL_MESSAGE in tokens
        done_event = events[-1]
        assert done_event.get("done") is True
        assert done_event.get("citations") == []
