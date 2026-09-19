"""
tests/test_guest_cleanup.py

Privacy & Guest Data Lifecycle End-to-End Tests.

Verifies:
1. Guest upload -> Google signup -> Complete pre-signup guest data cleanup.
2. Verified deletion across:
   - PostgreSQL: documents, sessions, messages, quizzes, quiz_attempts, temporary user rows.
   - Qdrant: vector points with user_id payload.
   - Filesystem: uploaded PDFs in settings.UPLOAD_DIR, processed JSON chunks in settings.PROCESSED_DIR.
3. Clean account state: Authenticated user starts with 0 documents (no migration).
4. Strict data isolation: Another user's data remains 100% intact and untouched.
5. Multiple guest uploads cleanup.
6. Failure safety:
   - Account creation failure leaves guest data intact.
   - Safe idempotency when guest has 0 items or items are already deleted.
7. Security guard: Authenticated Google accounts cannot be wiped as guest data.
"""

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.main import app
from app.config import settings
from app.db.base import Base
from app.db.database import get_db
from app.models.document import Document
from app.models.session import Session as ChatSession
from app.models.message import Message
from app.models.quiz import Quiz
from app.models.quiz_attempt import QuizAttempt
from app.models.user import User
from app.services.guest_cleanup_service import cleanup_guest_data, is_guest_user_id
import app.services.qdrant_service as qdrant_service

# Isolated SQLite test database
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    """
    Sets up isolated directories, in-memory DB tables, and in-memory Qdrant client.
    """
    Base.metadata.create_all(bind=test_engine)

    upload_dir = tmp_path / "uploads"
    processed_dir = tmp_path / "processed"
    upload_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(settings, "PROCESSED_DIR", str(processed_dir))

    # Use in-memory Qdrant client
    memory_qdrant = QdrantClient(":memory:")
    monkeypatch.setattr(qdrant_service, "get_qdrant_client", lambda *args, **kwargs: memory_qdrant)

    # Initialize collection
    qdrant_service.ensure_collection(client=memory_qdrant)

    yield {
        "upload_dir": upload_dir,
        "processed_dir": processed_dir,
        "qdrant": memory_qdrant,
    }

    Base.metadata.drop_all(bind=test_engine)


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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_is_guest_user_id():
    """Verify guest identification rules and security boundaries."""
    assert is_guest_user_id("dev-user") is True
    assert is_guest_user_id("guest_abc123") is True
    assert is_guest_user_id("guest-999") is True
    assert is_guest_user_id("google_1092837465") is False
    assert is_guest_user_id("google_sub_id") is False
    assert is_guest_user_id("") is False
    assert is_guest_user_id(None) is False


def test_guest_upload_and_signup_cleanup_single_doc(client, db, setup_test_environment):
    """
    Full Lifecycle Privacy Test:
    1. Guest uploads PDF & uses assistant (PDF, chunks, DB records, Qdrant vectors created).
    2. Another user has their own data.
    3. Guest signs up via Google OAuth.
    4. Verify ALL guest data is deleted across PostgreSQL, Qdrant, and filesystem.
    5. Verify authenticated user has clean account state (0 documents).
    6. Verify other user's data is 100% untouched.
    """
    upload_dir = setup_test_environment["upload_dir"]
    proc_dir = setup_test_environment["processed_dir"]
    qdrant = setup_test_environment["qdrant"]

    guest_id = "dev-user"
    other_user_id = "google_other_student_999"

    # Step 1: Create Guest document, files, DB rows, and vectors
    guest_doc_id = str(uuid.uuid4())
    guest_pdf_file = upload_dir / f"{guest_doc_id}.pdf"
    guest_pdf_file.write_bytes(b"%PDF-1.4 Guest sensitive lecture notes")

    guest_proc_file = proc_dir / f"{guest_doc_id}.json"
    guest_proc_file.write_text(json.dumps({"document_id": guest_doc_id, "chunks": ["chunk1"]}))

    guest_doc = Document(
        id=guest_doc_id,
        user_id=guest_id,
        filename="guest_notes.pdf",
        file_path=str(guest_pdf_file),
        status="READY",
    )
    db.add(guest_doc)

    guest_session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=guest_id,
        document_id=guest_doc_id,
        title="Guest Study Session",
    )
    guest_session_id = guest_session.id
    db.add(guest_session)

    guest_msg = Message(
        id=str(uuid.uuid4()),
        session_id=guest_session_id,
        sender="user",
        content="What is normal distribution?",
    )
    db.add(guest_msg)

    guest_quiz = Quiz(
        id=str(uuid.uuid4()),
        user_id=guest_id,
        document_id=guest_doc_id,
        topic="Statistics",
        questions=json.dumps([{"question": "Q1", "options": ["A", "B"], "correct": "A"}]),
    )
    db.add(guest_quiz)

    guest_attempt = QuizAttempt(
        id=str(uuid.uuid4()),
        quiz_id=guest_quiz.id,
        user_id=guest_id,
        answers=json.dumps(["A"]),
        score=1,
        percentage=100.0,
    )
    db.add(guest_attempt)

    # Insert vector into Qdrant for guest
    qdrant.upsert(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=[0.1] * 384,
                payload={
                    "user_id": guest_id,
                    "document_id": guest_doc_id,
                    "text": "Guest chunk text",
                },
            )
        ],
    )

    # Step 2: Create Other User data (must remain untouched)
    other_doc_id = str(uuid.uuid4())
    other_pdf_file = upload_dir / f"{other_doc_id}.pdf"
    other_pdf_file.write_bytes(b"%PDF-1.4 Other user private textbook")

    other_proc_file = proc_dir / f"{other_doc_id}.json"
    other_proc_file.write_text(json.dumps({"document_id": other_doc_id, "chunks": ["chunk_other"]}))

    other_doc = Document(
        id=other_doc_id,
        user_id=other_user_id,
        filename="other_textbook.pdf",
        file_path=str(other_pdf_file),
        status="READY",
    )
    db.add(other_doc)

    other_session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=other_user_id,
        document_id=other_doc_id,
        title="Other User Session",
    )
    db.add(other_session)

    other_quiz = Quiz(
        id=str(uuid.uuid4()),
        user_id=other_user_id,
        document_id=other_doc_id,
        topic="Biology",
        questions=json.dumps([{"question": "Bio Q", "options": ["X", "Y"], "correct": "X"}]),
    )
    db.add(other_quiz)

    db.commit()

    # Insert vector into Qdrant for other user
    other_point_id = str(uuid.uuid4())
    qdrant.upsert(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=other_point_id,
                vector=[0.2] * 384,
                payload={
                    "user_id": other_user_id,
                    "document_id": other_doc_id,
                    "text": "Other user chunk text",
                },
            )
        ],
    )

    # Verify initial state: both exist
    assert guest_pdf_file.exists()
    assert guest_proc_file.exists()
    assert other_pdf_file.exists()
    assert other_proc_file.exists()

    guest_points, _ = qdrant.scroll(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=guest_id))]
        ),
    )
    assert len(guest_points) == 1

    # Step 3: Guest signs up with Google OAuth
    new_google_sub = "1234567890_new_user"
    mock_idinfo = {
        "sub": new_google_sub,
        "name": "Jane Student",
        "email": "jane@university.edu",
        "picture": "https://example.com/jane.jpg",
    }

    with patch("app.api.auth.verify_google_token", return_value=mock_idinfo):
        resp = client.post(
            "/auth/google",
            json={
                "credential": "mock_valid_credential",
                "guest_user_id": guest_id,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == f"google_{new_google_sub}"
        auth_token = data["access_token"]

    # Step 4: Verify PostgreSQL: ALL guest data is deleted
    assert db.query(Document).filter(Document.user_id == guest_id).count() == 0
    assert db.query(ChatSession).filter(ChatSession.user_id == guest_id).count() == 0
    assert db.query(Message).filter(Message.session_id == guest_session_id).count() == 0
    assert db.query(Quiz).filter(Quiz.user_id == guest_id).count() == 0
    assert db.query(QuizAttempt).filter(QuizAttempt.user_id == guest_id).count() == 0

    # Step 5: Verify Filesystem: Guest files are deleted
    assert not guest_pdf_file.exists(), "Guest PDF was not deleted!"
    assert not guest_proc_file.exists(), "Guest processed JSON was not deleted!"

    # Step 6: Verify Qdrant: Guest vectors are deleted
    guest_points_after, _ = qdrant.scroll(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=guest_id))]
        ),
    )
    assert len(guest_points_after) == 0, "Guest vectors were not removed from Qdrant!"

    # Step 7: Verify Clean Account State: New user has 0 documents (NO migrated data)
    docs_resp = client.get(
        "/documents/",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert docs_resp.status_code == 200
    assert docs_resp.json() == [], "Authenticated account must start with 0 documents!"

    # Step 8: Verify Other User's Data is 100% Untouched
    assert db.query(Document).filter(Document.user_id == other_user_id).count() == 1
    assert db.query(ChatSession).filter(ChatSession.user_id == other_user_id).count() == 1
    assert db.query(Quiz).filter(Quiz.user_id == other_user_id).count() == 1
    assert other_pdf_file.exists(), "Other user's PDF must not be deleted!"
    assert other_proc_file.exists(), "Other user's processed JSON must not be deleted!"

    other_points, _ = qdrant.scroll(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=other_user_id))]
        ),
    )
    assert len(other_points) == 1, "Other user's vectors must remain untouched!"


def test_multiple_guest_uploads_cleanup(client, db, setup_test_environment):
    """
    Verify cleanup when a guest uploaded multiple documents before signing up.
    All documents, files, chunks, sessions, quizzes, and vectors must be wiped.
    """
    upload_dir = setup_test_environment["upload_dir"]
    proc_dir = setup_test_environment["processed_dir"]
    qdrant = setup_test_environment["qdrant"]
    guest_id = "dev-user"

    pdf_files = []
    proc_files = []

    # Guest uploads 3 distinct PDFs
    for i in range(3):
        doc_id = str(uuid.uuid4())
        pdf_path = upload_dir / f"{doc_id}.pdf"
        pdf_path.write_bytes(f"%PDF-1.4 Guest document {i}".encode())
        pdf_files.append(pdf_path)

        proc_path = proc_dir / f"{doc_id}.json"
        proc_path.write_text(json.dumps({"document_id": doc_id, "index": i}))
        proc_files.append(proc_path)

        doc = Document(
            id=doc_id,
            user_id=guest_id,
            filename=f"doc_{i}.pdf",
            file_path=str(pdf_path),
            status="READY",
        )
        db.add(doc)

        sess = ChatSession(id=str(uuid.uuid4()), user_id=guest_id, document_id=doc_id)
        db.add(sess)
        db.add(Message(id=str(uuid.uuid4()), session_id=sess.id, sender="user", content=f"Q for doc {i}"))

        qz = Quiz(id=str(uuid.uuid4()), user_id=guest_id, document_id=doc_id, questions="[]")
        db.add(qz)

        qdrant.upsert(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=[0.1] * 384,
                    payload={"user_id": guest_id, "document_id": doc_id},
                )
            ],
        )

    db.commit()

    assert db.query(Document).filter(Document.user_id == guest_id).count() == 3
    for p in pdf_files:
        assert p.exists()
    for p in proc_files:
        assert p.exists()

    # User signs up
    mock_idinfo = {
        "sub": "user_multidoc_99",
        "name": "MultiDoc User",
        "email": "multi@example.com",
    }
    with patch("app.api.auth.verify_google_token", return_value=mock_idinfo):
        resp = client.post(
            "/auth/google",
            json={"credential": "mock_token", "guest_user_id": guest_id},
        )
        assert resp.status_code == 200

    # Verify all 3 documents and files were purged
    assert db.query(Document).filter(Document.user_id == guest_id).count() == 0
    assert db.query(ChatSession).filter(ChatSession.user_id == guest_id).count() == 0
    assert db.query(Quiz).filter(Quiz.user_id == guest_id).count() == 0

    for p in pdf_files:
        assert not p.exists()
    for p in proc_files:
        assert not p.exists()

    points, _ = qdrant.scroll(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=guest_id))]
        ),
    )
    assert len(points) == 0


def test_failure_safety_account_creation_failure_leaves_guest_data(client, db, setup_test_environment):
    """
    Failure Safety Case B:
    If account creation fails (e.g. invalid Google token / 401),
    guest data MUST NOT be deleted.
    """
    upload_dir = setup_test_environment["upload_dir"]
    guest_id = "dev-user"

    doc_id = str(uuid.uuid4())
    pdf_path = upload_dir / f"{doc_id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 Important test notes")

    doc = Document(id=doc_id, user_id=guest_id, filename="important.pdf", file_path=str(pdf_path))
    db.add(doc)
    db.commit()

    from fastapi import HTTPException

    with patch("app.api.auth.verify_google_token", side_effect=HTTPException(status_code=401, detail="Expired token")):
        resp = client.post(
            "/auth/google",
            json={"credential": "bad_token", "guest_user_id": guest_id},
        )
        assert resp.status_code == 401

    # Guest document and file must STILL exist
    assert db.query(Document).filter(Document.user_id == guest_id).count() == 1
    assert pdf_path.exists()


def test_idempotency_empty_guest_and_double_cleanup(db):
    """
    Failure Safety Cases C & D:
    - Guest has no stored data: completes safely with 0 deletions.
    - Double cleanup: second call is safe and idempotent.
    """
    # Case C: No stored data
    res1 = cleanup_guest_data("guest_new_empty", db)
    assert res1["status"] == "success"
    assert res1["deleted_documents"] == 0

    # Case D: Double cleanup on dev-user
    res2 = cleanup_guest_data("dev-user", db)
    assert res2["status"] == "success"

    res3 = cleanup_guest_data("dev-user", db)
    assert res3["status"] == "success"
    assert res3["deleted_documents"] == 0


def test_security_protects_authenticated_accounts(db):
    """
    Security Rule (Section 16):
    Guest cleanup must NEVER be executed against authenticated accounts.
    """
    res = cleanup_guest_data("google_1092837465928172", db)
    assert res["status"] == "rejected"
    assert res["reason"] == "authenticated_account_protected"
