"""
backend/tests/test_document_edit.py

Automated integration tests for:
PATCH /documents/{document_id} — Document metadata editing (filename & subject).

Tests verify:
- Valid document edit succeeds (both fields, filename only, subject only)
- Filename exactly 60 characters succeeds
- Subject exactly 40 characters succeeds
- Filename over 60 characters fails (400)
- Subject over 40 characters fails (400)
- Blank filename fails (400)
- Blank subject fails (400)
- Whitespace-only values fail (400)
- Surrounding whitespace is trimmed
- Unauthorized user cannot edit another user's document (403)
- Unauthenticated request is rejected (401)
- Non-existent document returns 404
- Empty payload with neither field returns 400
- Preserves document_id, page_count, status, file_path, and Qdrant data
"""

import uuid
from datetime import datetime
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
from app.api.auth import create_access_token

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
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


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
def auth_headers():
    token = create_access_token("test-user-1")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_user_headers():
    token = create_access_token("test-user-2")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_document(db_session):
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        user_id="test-user-1",
        filename="Original Notes.pdf",
        subject="Computer Science",
        page_count=12,
        status="READY",
        file_path=f"documents/test-user-1/{doc_id}.pdf",
        created_at=datetime.utcnow(),
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


class TestDocumentEditEndpoint:
    """Test suite for PATCH /documents/{document_id}."""

    def test_valid_document_edit_both_fields(self, client, auth_headers, sample_document, db_session):
        payload = {
            "filename": "Updated Operating Systems.pdf",
            "subject": "Systems & OS",
        }
        res = client.patch(f"/documents/{sample_document.id}", json=payload, headers=auth_headers)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["document_id"] == sample_document.id
        assert data["filename"] == "Updated Operating Systems.pdf"
        assert data["subject"] == "Systems & OS"
        assert data["status"] == "READY"
        assert data["page_count"] == 12

        # Verify DB
        db_doc = db_session.query(Document).filter(Document.id == sample_document.id).first()
        assert db_doc.filename == "Updated Operating Systems.pdf"
        assert db_doc.subject == "Systems & OS"

    def test_valid_document_edit_filename_only(self, client, auth_headers, sample_document, db_session):
        payload = {"filename": "Only Filename Changed.pdf"}
        res = client.patch(f"/documents/{sample_document.id}", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["filename"] == "Only Filename Changed.pdf"
        assert data["subject"] == sample_document.subject  # Unchanged

    def test_valid_document_edit_subject_only(self, client, auth_headers, sample_document, db_session):
        payload = {"subject": "Distributed Systems"}
        res = client.patch(f"/documents/{sample_document.id}", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["subject"] == "Distributed Systems"
        assert data["filename"] == sample_document.filename  # Unchanged

    def test_filename_exactly_60_characters_succeeds(self, client, auth_headers, sample_document):
        exact_60 = "A" * 56 + ".pdf"  # 60 chars
        assert len(exact_60) == 60
        res = client.patch(f"/documents/{sample_document.id}", json={"filename": exact_60}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["filename"] == exact_60

    def test_subject_exactly_40_characters_succeeds(self, client, auth_headers, sample_document):
        exact_40 = "B" * 40
        assert len(exact_40) == 40
        res = client.patch(f"/documents/{sample_document.id}", json={"subject": exact_40}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["subject"] == exact_40

    def test_filename_over_60_characters_fails(self, client, auth_headers, sample_document):
        over_60 = "A" * 57 + ".pdf"  # 61 chars
        assert len(over_60) == 61
        res = client.patch(f"/documents/{sample_document.id}", json={"filename": over_60}, headers=auth_headers)
        assert res.status_code == 400
        assert "Filename cannot exceed 60 characters" in res.json()["detail"]

    def test_subject_over_40_characters_fails(self, client, auth_headers, sample_document):
        over_40 = "B" * 41
        assert len(over_40) == 41
        res = client.patch(f"/documents/{sample_document.id}", json={"subject": over_40}, headers=auth_headers)
        assert res.status_code == 400
        assert "Subject cannot exceed 40 characters" in res.json()["detail"]

    def test_blank_filename_fails(self, client, auth_headers, sample_document):
        res = client.patch(f"/documents/{sample_document.id}", json={"filename": ""}, headers=auth_headers)
        assert res.status_code == 400
        assert "Filename cannot be blank" in res.json()["detail"]

    def test_whitespace_only_filename_fails(self, client, auth_headers, sample_document):
        res = client.patch(f"/documents/{sample_document.id}", json={"filename": "   \t \n "}, headers=auth_headers)
        assert res.status_code == 400
        assert "Filename cannot be blank" in res.json()["detail"]

    def test_blank_subject_fails(self, client, auth_headers, sample_document):
        res = client.patch(f"/documents/{sample_document.id}", json={"subject": ""}, headers=auth_headers)
        assert res.status_code == 400
        assert "Subject cannot be blank" in res.json()["detail"]

    def test_whitespace_only_subject_fails(self, client, auth_headers, sample_document):
        res = client.patch(f"/documents/{sample_document.id}", json={"subject": "    "}, headers=auth_headers)
        assert res.status_code == 400
        assert "Subject cannot be blank" in res.json()["detail"]

    def test_surrounding_whitespace_is_trimmed(self, client, auth_headers, sample_document):
        payload = {
            "filename": "   Trimmed Notes.pdf   ",
            "subject": "   Machine Learning   ",
        }
        res = client.patch(f"/documents/{sample_document.id}", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["filename"] == "Trimmed Notes.pdf"
        assert data["subject"] == "Machine Learning"

    def test_empty_payload_fails(self, client, auth_headers, sample_document):
        res = client.patch(f"/documents/{sample_document.id}", json={}, headers=auth_headers)
        assert res.status_code == 400
        assert "At least one field" in res.json()["detail"]

    def test_unauthorized_user_cannot_edit(self, client, other_user_headers, sample_document):
        payload = {"filename": "Hacked Title.pdf"}
        res = client.patch(f"/documents/{sample_document.id}", json=payload, headers=other_user_headers)
        assert res.status_code == 403
        assert "permission" in res.json()["detail"].lower()

    def test_unauthenticated_request_fails(self, client, sample_document):
        payload = {"filename": "Anonymous Edit.pdf"}
        res = client.patch(f"/documents/{sample_document.id}", json=payload)
        assert res.status_code == 401

    def test_nonexistent_document_returns_404(self, client, auth_headers):
        missing_id = str(uuid.uuid4())
        res = client.patch(f"/documents/{missing_id}", json={"filename": "Missing.pdf"}, headers=auth_headers)
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_data_safety_and_preservation(self, client, auth_headers, sample_document, db_session):
        """Verify storage path, page_count, status, and ID are completely preserved, and no Qdrant/storage deletion occurs."""
        original_path = sample_document.file_path
        original_pages = sample_document.page_count
        original_status = sample_document.status
        original_id = sample_document.id

        with patch("app.api.documents.delete_document_vectors") as mock_qdrant, \
             patch("app.api.documents.delete_document_file") as mock_supabase:
            res = client.patch(
                f"/documents/{original_id}",
                json={"filename": "Safety Verified.pdf"},
                headers=auth_headers,
            )
            assert res.status_code == 200
            mock_qdrant.assert_not_called()
            mock_supabase.assert_not_called()

        db_doc = db_session.query(Document).filter(Document.id == original_id).first()
        assert db_doc.id == original_id
        assert db_doc.file_path == original_path
        assert db_doc.page_count == original_pages
        assert db_doc.status == original_status
        assert db_doc.filename == "Safety Verified.pdf"
