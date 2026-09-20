"""
backend/tests/test_deletion_and_rename.py

Automated integration tests for:
1. DELETE /documents/{document_id} — document deletion with cascade to sessions, messages,
   quizzes, quiz_attempts, files, and Qdrant vectors.
2. DELETE /sessions/{session_id} — chat session deletion with cascade to messages.
3. PATCH /quiz/{quiz_id}/rename — quiz topic rename with validation.
"""

import json
import uuid
from pathlib import Path
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
from app.models.quiz import Quiz
from app.models.quiz_attempt import QuizAttempt
from app.api.auth import create_access_token
from app.config import settings
from qdrant_client import QdrantClient
from qdrant_client.http import models
import app.services.qdrant_service as qdrant_service

# In-memory hermetic SQLite
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
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
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ─── Test Document Deletion ───────────────────────────────────────────────────


class TestDeleteDocument:
    def test_delete_document_success(self, client, db, tmp_path, monkeypatch):
        alice_id = "alice-user"
        token = create_access_token(alice_id)
        headers = {"Authorization": f"Bearer {token}"}

        # Override UPLOAD_DIR to tmp_path
        monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

        # Create document
        doc_id = str(uuid.uuid4())
        fake_pdf = tmp_path / f"{doc_id}.pdf"
        fake_pdf.write_bytes(b"%PDF-test-content")

        doc = Document(
            id=doc_id,
            user_id=alice_id,
            filename="alice_paper.pdf",
            subject="OS",
            file_path=str(fake_pdf),
            status="READY",
        )
        db.add(doc)

        # Create session + messages
        sess_id = str(uuid.uuid4())
        session = ChatSession(id=sess_id, user_id=alice_id, document_id=doc_id)
        db.add(session)
        msg = Message(
            id=str(uuid.uuid4()),
            session_id=sess_id,
            sender="user",
            content="Hello",
        )
        db.add(msg)

        # Create quiz + attempt
        quiz_id = str(uuid.uuid4())
        quiz = Quiz(
            id=quiz_id,
            user_id=alice_id,
            document_id=doc_id,
            topic="Deadlocks",
            questions=json.dumps([{"id": 1, "question": "Q1", "options": ["A", "B"], "correct_index": 0}]),
        )
        db.add(quiz)
        attempt = QuizAttempt(
            id=str(uuid.uuid4()),
            quiz_id=quiz_id,
            user_id=alice_id,
            score=1,
            percentage=100.0,
            answers=json.dumps({"1": 0}),
        )
        db.add(attempt)
        db.commit()

        # Mock delete_document_vectors to avoid external Qdrant call
        with patch("app.api.documents.delete_document_vectors") as mock_qdrant_delete:
            mock_qdrant_delete.return_value = 5
            res = client.delete(f"/documents/{doc_id}", headers=headers)

        assert res.status_code == 200
        data = res.json()
        assert data["deleted"] is True
        assert data["document_id"] == doc_id
        mock_qdrant_delete.assert_called_once_with(document_id=doc_id, user_id=alice_id)

        # Verify DB rows were deleted
        assert db.query(Document).filter(Document.id == doc_id).first() is None
        assert db.query(ChatSession).filter(ChatSession.id == sess_id).first() is None
        assert db.query(Message).filter(Message.session_id == sess_id).first() is None
        assert db.query(Quiz).filter(Quiz.id == quiz_id).first() is None
        assert db.query(QuizAttempt).filter(QuizAttempt.quiz_id == quiz_id).first() is None

        # Verify file deleted
        assert not fake_pdf.exists()

    def test_delete_document_complete_data_cleanup(self, client, db, tmp_path, monkeypatch):
        """
        Verify complete data cleanup when a document is deleted:
        - original uploaded PDF removed from UPLOAD_DIR
        - processed JSON chunks removed from PROCESSED_DIR
        - temporary extraction/working files removed
        - database records removed (Document, Session, Message, Quiz, QuizAttempt)
        - Qdrant vectors removed for this document
        - other users' documents, files, and vectors remain 100% intact.
        """
        upload_dir = tmp_path / "uploads"
        processed_dir = tmp_path / "processed"
        upload_dir.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_dir))
        monkeypatch.setattr(settings, "PROCESSED_DIR", str(processed_dir))

        # Use hermetic in-memory Qdrant client
        memory_qdrant = QdrantClient(":memory:")
        monkeypatch.setattr(qdrant_service, "get_qdrant_client", lambda *args, **kwargs: memory_qdrant)
        qdrant_service.ensure_collection(client=memory_qdrant)

        alice_id = "alice-student-1"
        bob_id = "bob-student-2"

        alice_token = create_access_token(alice_id)
        alice_headers = {"Authorization": f"Bearer {alice_token}"}

        # 1. Create Alice's document, files, sessions, quizzes, vectors
        alice_doc_id = str(uuid.uuid4())
        alice_pdf = upload_dir / f"{alice_doc_id}.pdf"
        alice_pdf.write_bytes(b"%PDF-1.4 Alice's private notes")

        alice_json = processed_dir / f"{alice_doc_id}.json"
        alice_json.write_text(json.dumps({"document_id": alice_doc_id, "chunks": ["chunk1", "chunk2"]}))

        alice_tmp = upload_dir / f"{alice_doc_id}.extracted.tmp"
        alice_tmp.write_text("temporary extraction data")

        alice_doc = Document(
            id=alice_doc_id,
            user_id=alice_id,
            filename="alice_notes.pdf",
            subject="Algorithms",
            file_path=str(alice_pdf),
            status="READY",
        )
        db.add(alice_doc)

        alice_session = ChatSession(id=str(uuid.uuid4()), user_id=alice_id, document_id=alice_doc_id, title="Alice Chat")
        alice_session_id = alice_session.id
        db.add(alice_session)
        alice_msg = Message(id=str(uuid.uuid4()), session_id=alice_session_id, sender="user", content="Graph traversal?")
        db.add(alice_msg)

        alice_quiz = Quiz(id=str(uuid.uuid4()), user_id=alice_id, document_id=alice_doc_id, topic="Graphs", questions="[]")
        alice_quiz_id = alice_quiz.id
        db.add(alice_quiz)
        alice_attempt = QuizAttempt(id=str(uuid.uuid4()), quiz_id=alice_quiz_id, user_id=alice_id, score=1, answers="[]")
        db.add(alice_attempt)

        # Alice's Qdrant vector
        memory_qdrant.upsert(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=[0.1] * 384,
                    payload={"document_id": alice_doc_id, "user_id": alice_id, "text": "Alice chunk text"},
                )
            ],
        )

        # 2. Create Bob's document, files, sessions, quizzes, vectors (must remain untouched!)
        bob_doc_id = str(uuid.uuid4())
        bob_pdf = upload_dir / f"{bob_doc_id}.pdf"
        bob_pdf.write_bytes(b"%PDF-1.4 Bob's private notes")

        bob_json = processed_dir / f"{bob_doc_id}.json"
        bob_json.write_text(json.dumps({"document_id": bob_doc_id, "chunks": ["bob_chunk"]}))

        bob_doc = Document(
            id=bob_doc_id,
            user_id=bob_id,
            filename="bob_notes.pdf",
            subject="Networks",
            file_path=str(bob_pdf),
            status="READY",
        )
        db.add(bob_doc)

        bob_session = ChatSession(id=str(uuid.uuid4()), user_id=bob_id, document_id=bob_doc_id)
        db.add(bob_session)

        # Bob's Qdrant vector
        memory_qdrant.upsert(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=[0.2] * 384,
                    payload={"document_id": bob_doc_id, "user_id": bob_id, "text": "Bob chunk text"},
                )
            ],
        )

        db.commit()

        # Verify initial presence
        assert alice_pdf.exists()
        assert alice_json.exists()
        assert alice_tmp.exists()
        assert bob_pdf.exists()
        assert bob_json.exists()

        alice_pts_before, _ = memory_qdrant.scroll(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=alice_doc_id))]
            ),
        )
        assert len(alice_pts_before) == 1

        # 3. Delete Alice's document
        res = client.delete(f"/documents/{alice_doc_id}", headers=alice_headers)
        assert res.status_code == 200
        assert res.json()["deleted"] is True

        # 4. Verify Alice's filesystem files are gone
        assert not alice_pdf.exists(), "Alice's PDF was not deleted!"
        assert not alice_json.exists(), "Alice's processed JSON was not deleted!"
        assert not alice_tmp.exists(), "Alice's temporary file was not deleted!"

        # 5. Verify Alice's database records are gone
        assert db.query(Document).filter(Document.id == alice_doc_id).first() is None
        assert db.query(ChatSession).filter(ChatSession.document_id == alice_doc_id).first() is None
        assert db.query(Message).filter(Message.session_id == alice_session_id).first() is None
        assert db.query(Quiz).filter(Quiz.document_id == alice_doc_id).first() is None
        assert db.query(QuizAttempt).filter(QuizAttempt.quiz_id == alice_quiz_id).first() is None

        # 6. Verify Alice's Qdrant vectors are gone
        alice_pts_after, _ = memory_qdrant.scroll(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=alice_doc_id))]
            ),
        )
        assert len(alice_pts_after) == 0, "Alice's Qdrant vectors were not deleted!"

        # 7. Verify Bob's data is 100% UNTOUCHED
        assert bob_pdf.exists(), "Bob's PDF must not be deleted!"
        assert bob_json.exists(), "Bob's processed JSON must not be deleted!"
        assert db.query(Document).filter(Document.id == bob_doc_id).first() is not None
        assert db.query(ChatSession).filter(ChatSession.id == bob_session.id).first() is not None

        bob_pts, _ = memory_qdrant.scroll(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=bob_doc_id))]
            ),
        )
        assert len(bob_pts) == 1, "Bob's Qdrant vectors must remain intact!"

    def test_delete_document_not_found(self, client):
        token = create_access_token("alice-user")
        headers = {"Authorization": f"Bearer {token}"}
        res = client.delete(f"/documents/{uuid.uuid4()}", headers=headers)
        assert res.status_code == 404

    def test_delete_document_wrong_user(self, client, db):
        alice_id = "alice-user"
        bob_id = "bob-user"
        doc_id = str(uuid.uuid4())

        doc = Document(
            id=doc_id,
            user_id=alice_id,
            filename="alice.pdf",
            subject="OS",
            file_path=f"data/uploads/{doc_id}.pdf",
            status="READY",
        )
        db.add(doc)
        db.commit()

        # Bob attempts to delete Alice's doc
        bob_token = create_access_token(bob_id)
        res = client.delete(f"/documents/{doc_id}", headers={"Authorization": f"Bearer {bob_token}"})
        assert res.status_code == 403


# ─── Test Session Deletion ────────────────────────────────────────────────────


class TestDeleteSession:
    def test_delete_session_success(self, client, db):
        user_id = "charlie-user"
        token = create_access_token(user_id)
        headers = {"Authorization": f"Bearer {token}"}

        doc_id = str(uuid.uuid4())
        doc = Document(
            id=doc_id,
            user_id=user_id,
            filename="notes.pdf",
            file_path="f.pdf",
            status="READY",
        )
        db.add(doc)

        sess_id = str(uuid.uuid4())
        session = ChatSession(id=sess_id, user_id=user_id, document_id=doc_id)
        db.add(session)

        msg1 = Message(id=str(uuid.uuid4()), session_id=sess_id, sender="user", content="Hi")
        msg2 = Message(id=str(uuid.uuid4()), session_id=sess_id, sender="assistant", content="Hello!")
        db.add_all([msg1, msg2])
        db.commit()

        res = client.delete(f"/sessions/{sess_id}", headers=headers)
        assert res.status_code == 200
        assert res.json() == {"deleted": True, "session_id": sess_id}

        # Check session & messages gone
        assert db.query(ChatSession).filter(ChatSession.id == sess_id).first() is None
        assert db.query(Message).filter(Message.session_id == sess_id).count() == 0

        # Document still exists
        assert db.query(Document).filter(Document.id == doc_id).first() is not None

    def test_delete_session_not_found(self, client):
        token = create_access_token("charlie-user")
        res = client.delete(f"/sessions/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 404

    def test_delete_session_wrong_user(self, client, db):
        owner_id = "owner-user"
        other_id = "other-user"

        sess_id = str(uuid.uuid4())
        session = ChatSession(id=sess_id, user_id=owner_id, document_id=str(uuid.uuid4()))
        db.add(session)
        db.commit()

        other_token = create_access_token(other_id)
        res = client.delete(f"/sessions/{sess_id}", headers={"Authorization": f"Bearer {other_token}"})
        assert res.status_code == 403


# ─── Test Quiz Topic Rename ───────────────────────────────────────────────────


class TestRenameQuizTopic:
    def test_rename_quiz_success(self, client, db):
        user_id = "dave-user"
        token = create_access_token(user_id)
        headers = {"Authorization": f"Bearer {token}"}

        quiz_id = str(uuid.uuid4())
        quiz = Quiz(
            id=quiz_id,
            user_id=user_id,
            document_id=str(uuid.uuid4()),
            topic="Old Topic Name",
            questions=json.dumps([]),
        )
        db.add(quiz)
        db.commit()

        res = client.patch(
            f"/quiz/{quiz_id}/rename",
            json={"topic": "New Renamed Topic"},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["renamed"] is True
        assert data["topic"] == "New Renamed Topic"
        assert data["quiz_id"] == quiz_id

        # Verify DB
        db.refresh(quiz)
        assert quiz.topic == "New Renamed Topic"

    def test_rename_quiz_empty_topic(self, client, db):
        user_id = "dave-user"
        token = create_access_token(user_id)
        headers = {"Authorization": f"Bearer {token}"}

        quiz_id = str(uuid.uuid4())
        quiz = Quiz(
            id=quiz_id,
            user_id=user_id,
            document_id=str(uuid.uuid4()),
            topic="Topic",
            questions=json.dumps([]),
        )
        db.add(quiz)
        db.commit()

        res = client.patch(
            f"/quiz/{quiz_id}/rename",
            json={"topic": "   "},
            headers=headers,
        )
        assert res.status_code == 422

    def test_rename_quiz_too_long(self, client, db):
        user_id = "dave-user"
        token = create_access_token(user_id)
        headers = {"Authorization": f"Bearer {token}"}

        quiz_id = str(uuid.uuid4())
        quiz = Quiz(
            id=quiz_id,
            user_id=user_id,
            document_id=str(uuid.uuid4()),
            topic="Topic",
            questions=json.dumps([]),
        )
        db.add(quiz)
        db.commit()

        res = client.patch(
            f"/quiz/{quiz_id}/rename",
            json={"topic": "A" * 256},
            headers=headers,
        )
        assert res.status_code == 422

    def test_rename_quiz_not_found(self, client):
        token = create_access_token("dave-user")
        res = client.patch(
            f"/quiz/{uuid.uuid4()}/rename",
            json={"topic": "New Topic"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 404

    def test_rename_quiz_wrong_user(self, client, db):
        owner_id = "owner-dave"
        other_id = "intruder-eve"

        quiz_id = str(uuid.uuid4())
        quiz = Quiz(
            id=quiz_id,
            user_id=owner_id,
            document_id=str(uuid.uuid4()),
            topic="Dave's Private Quiz",
            questions=json.dumps([]),
        )
        db.add(quiz)
        db.commit()

        eve_token = create_access_token(other_id)
        res = client.patch(
            f"/quiz/{quiz_id}/rename",
            json={"topic": "Hacked Topic"},
            headers={"Authorization": f"Bearer {eve_token}"},
        )
        assert res.status_code == 403


# ─── Test Chat Session Rename ─────────────────────────────────────────────────


class TestRenameChatSession:
    def test_rename_session_success(self, client, db):
        user_id = "frank-user"
        token = create_access_token(user_id)
        headers = {"Authorization": f"Bearer {token}"}

        sess_id = str(uuid.uuid4())
        session = ChatSession(
            id=sess_id,
            user_id=user_id,
            document_id=str(uuid.uuid4()),
            title="Old Session Name",
        )
        db.add(session)
        db.commit()

        res = client.put(
            f"/chat/sessions/{sess_id}",
            json={"title": "Operating Systems - Processes & Threads"},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["session_id"] == sess_id
        assert data["title"] == "Operating Systems - Processes & Threads"

        # Verify DB persistence
        db.expire_all()
        refreshed = db.query(ChatSession).filter(ChatSession.id == sess_id).first()
        assert refreshed.title == "Operating Systems - Processes & Threads"

    def test_rename_session_empty_title(self, client, db):
        user_id = "frank-user"
        token = create_access_token(user_id)
        sess_id = str(uuid.uuid4())
        session = ChatSession(
            id=sess_id,
            user_id=user_id,
            document_id=str(uuid.uuid4()),
        )
        db.add(session)
        db.commit()

        # Empty string
        res = client.put(
            f"/chat/sessions/{sess_id}",
            json={"title": "   "},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 422

    def test_rename_session_too_long(self, client, db):
        user_id = "frank-user"
        token = create_access_token(user_id)
        sess_id = str(uuid.uuid4())
        session = ChatSession(
            id=sess_id,
            user_id=user_id,
            document_id=str(uuid.uuid4()),
        )
        db.add(session)
        db.commit()

        res = client.put(
            f"/chat/sessions/{sess_id}",
            json={"title": "A" * 256},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 422

    def test_rename_session_not_found(self, client):
        token = create_access_token("frank-user")
        res = client.put(
            f"/chat/sessions/{uuid.uuid4()}",
            json={"title": "Valid Name"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 404

    def test_rename_session_wrong_user(self, client, db):
        owner_id = "owner-frank"
        other_id = "intruder-eve"

        sess_id = str(uuid.uuid4())
        session = ChatSession(
            id=sess_id,
            user_id=owner_id,
            document_id=str(uuid.uuid4()),
            title="Private Chat",
        )
        db.add(session)
        db.commit()

        eve_token = create_access_token(other_id)
        res = client.put(
            f"/chat/sessions/{sess_id}",
            json={"title": "Hijacked Chat"},
            headers={"Authorization": f"Bearer {eve_token}"},
        )
        assert res.status_code == 403

        # Confirm title untouched
        db.expire_all()
        refreshed = db.query(ChatSession).filter(ChatSession.id == sess_id).first()
        assert refreshed.title == "Private Chat"

    def test_rename_session_preserves_messages(self, client, db):
        user_id = "frank-user"
        token = create_access_token(user_id)

        sess_id = str(uuid.uuid4())
        session = ChatSession(
            id=sess_id,
            user_id=user_id,
            document_id=str(uuid.uuid4()),
        )
        db.add(session)
        db.flush()

        # Add 3 messages
        for i in range(3):
            msg = Message(
                id=str(uuid.uuid4()),
                session_id=sess_id,
                sender="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
            )
            db.add(msg)
        db.commit()

        res = client.put(
            f"/chat/sessions/{sess_id}",
            json={"title": "New Title"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

        # Check messages untouched
        messages = db.query(Message).filter(Message.session_id == sess_id).all()
        assert len(messages) == 3
