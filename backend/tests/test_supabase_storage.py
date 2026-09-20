"""
tests/test_supabase_storage.py

Automated tests for Supabase Storage persistent PDF integration:
- Configuration checks
- Deterministic path generation
- Upload, download, and delete operations
- Failure handling and orphaned file prevention
- Document upload integration with Supabase Storage
- Document cascading deletion with Supabase Storage
- Guest lifecycle cleanup with Supabase Storage
"""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.db.database import get_db, SessionLocal
from app.models.document import Document
from app.models.user import User
from app.services.supabase_storage_service import (
    is_supabase_configured,
    build_storage_path,
    upload_document_file,
    download_document_file,
    delete_document_file,
    delete_user_storage_files,
    reset_storage_client,
)
from app.services.guest_cleanup_service import cleanup_guest_data


@pytest.fixture(autouse=True)
def reset_client():
    reset_storage_client()
    yield
    reset_storage_client()


class TestSupabaseStorageServiceUnit:
    """Unit tests for Supabase storage service helpers and functions."""

    def test_build_storage_path(self):
        path = build_storage_path("user_123", "doc_456")
        assert path == "documents/user_123/doc_456.pdf"

        # Check sanitization of spaces
        path_with_spaces = build_storage_path("dev user", "doc_abc")
        assert path_with_spaces == "documents/dev_user/doc_abc.pdf"

    def test_is_supabase_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "secret_key_123")
        assert is_supabase_configured() is True

        monkeypatch.setattr(settings, "SUPABASE_URL", None)
        assert is_supabase_configured() is False

        monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "")
        assert is_supabase_configured() is False

    @patch("supabase.create_client")
    def test_upload_document_file_success(self, mock_create_client, monkeypatch):
        monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "secret_key_123")
        monkeypatch.setattr(settings, "SUPABASE_BUCKET_NAME", "learnvault-documents")

        mock_client = MagicMock()
        mock_storage = MagicMock()
        mock_bucket = MagicMock()
        mock_client.storage = mock_storage
        mock_storage.from_.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        content = b"%PDF-1.4 test content"
        path = upload_document_file("alice", "doc-1", content)

        assert path == "documents/alice/doc-1.pdf"
        mock_storage.from_.assert_called_with("learnvault-documents")
        mock_bucket.upload.assert_called_once_with(
            path="documents/alice/doc-1.pdf",
            file=content,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )

    @patch("supabase.create_client")
    def test_upload_document_file_failure(self, mock_create_client, monkeypatch):
        monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "secret_key_123")

        mock_client = MagicMock()
        mock_storage = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.upload.side_effect = Exception("Network timeout")
        mock_client.storage = mock_storage
        mock_storage.from_.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        with pytest.raises(RuntimeError, match="Supabase Storage upload failed"):
            upload_document_file("alice", "doc-1", b"data")

    @patch("supabase.create_client")
    def test_download_document_file_success(self, mock_create_client, monkeypatch):
        monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "secret_key_123")
        monkeypatch.setattr(settings, "SUPABASE_BUCKET_NAME", "learnvault-documents")

        mock_client = MagicMock()
        mock_storage = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.download.return_value = b"%PDF-1.4 downloaded data"
        mock_client.storage = mock_storage
        mock_storage.from_.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        data = download_document_file("documents/alice/doc-1.pdf")
        assert data == b"%PDF-1.4 downloaded data"
        mock_bucket.download.assert_called_once_with("documents/alice/doc-1.pdf")

    @patch("supabase.create_client")
    def test_delete_document_file_success(self, mock_create_client, monkeypatch):
        monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "secret_key_123")
        monkeypatch.setattr(settings, "SUPABASE_BUCKET_NAME", "learnvault-documents")

        mock_client = MagicMock()
        mock_storage = MagicMock()
        mock_bucket = MagicMock()
        mock_client.storage = mock_storage
        mock_storage.from_.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        res = delete_document_file("documents/alice/doc-1.pdf")
        assert res is True
        mock_bucket.remove.assert_called_once_with(["documents/alice/doc-1.pdf"])

    @patch("supabase.create_client")
    def test_delete_user_storage_files(self, mock_create_client, monkeypatch):
        monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "secret_key_123")
        monkeypatch.setattr(settings, "SUPABASE_BUCKET_NAME", "learnvault-documents")

        mock_client = MagicMock()
        mock_storage = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.list.return_value = [
            {"name": "doc-1.pdf"},
            {"name": "doc-2.pdf"},
        ]
        mock_client.storage = mock_storage
        mock_storage.from_.return_value = mock_bucket
        mock_create_client.return_value = mock_client

        count = delete_user_storage_files("guest_abc")
        assert count == 2
        mock_bucket.list.assert_called_once_with("documents/guest_abc")
        mock_bucket.remove.assert_called_once_with([
            "documents/guest_abc/doc-1.pdf",
            "documents/guest_abc/doc-2.pdf",
        ])


class TestSupabaseStorageIntegration:
    """Integration tests with FastAPI routes using mocked Supabase client."""

    @patch("app.api.documents.upload_document_file")
    @patch("app.api.documents.is_supabase_configured", return_value=True)
    def test_upload_stores_supabase_path(self, mock_is_configured, mock_upload):
        mock_upload.return_value = "documents/dev-user/test-doc-id.pdf"
        client = TestClient(app)

        pdf_bytes = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF"
        )

        response = client.post(
            "/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"subject": "Biology"},
        )

        assert response.status_code == 202
        doc_id = response.json()["document_id"]

        with SessionLocal() as db:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            assert doc is not None
            assert doc.file_path == "documents/dev-user/test-doc-id.pdf"

            # Clean up
            db.delete(doc)
            db.commit()

    @patch("app.api.documents.delete_document_file")
    @patch("app.api.documents.is_supabase_configured", return_value=True)
    def test_delete_document_calls_supabase(self, mock_is_configured, mock_delete):
        client = TestClient(app)
        doc_id = "test-supa-delete-123"

        with SessionLocal() as db:
            doc = Document(
                id=doc_id,
                user_id="dev-user",
                filename="test.pdf",
                subject="Math",
                file_path=f"documents/dev-user/{doc_id}.pdf",
                status="READY",
            )
            db.add(doc)
            db.commit()

        response = client.delete(f"/documents/{doc_id}")
        assert response.status_code == 200
        assert response.json()["deleted"] is True

        mock_delete.assert_called_once_with(f"documents/dev-user/{doc_id}.pdf")

    @patch("app.services.guest_cleanup_service.delete_document_file")
    @patch("app.services.guest_cleanup_service.delete_user_storage_files")
    @patch("app.services.guest_cleanup_service.is_supabase_configured", return_value=True)
    def test_guest_cleanup_calls_supabase(self, mock_is_configured, mock_delete_user_files, mock_delete_file):
        guest_id = "guest_test_supa_99"
        doc_id = "guest_doc_supa_99"

        with SessionLocal() as db:
            doc = Document(
                id=doc_id,
                user_id=guest_id,
                filename="guest_notes.pdf",
                subject="Physics",
                file_path=f"documents/{guest_id}/{doc_id}.pdf",
                status="READY",
            )
            db.add(doc)
            db.commit()

            summary = cleanup_guest_data(guest_id, db)

        assert summary["status"] == "success"
        mock_delete_file.assert_called_once_with(f"documents/{guest_id}/{doc_id}.pdf")
        mock_delete_user_files.assert_called_once_with(guest_id)

    @patch("app.api.documents.delete_document_file")
    @patch("app.api.documents.is_supabase_configured", return_value=True)
    def test_delete_document_ownership_protection(self, mock_is_configured, mock_delete):
        """Test that a user cannot delete another user's document and Supabase delete is NOT called."""
        client = TestClient(app)
        doc_id = "other-user-doc-99"

        with SessionLocal() as db:
            doc = Document(
                id=doc_id,
                user_id="different-user",
                filename="secret.pdf",
                subject="Math",
                file_path=f"documents/different-user/{doc_id}.pdf",
                status="READY",
            )
            db.add(doc)
            db.commit()

        # Request comes from dev-user (mocked current_user)
        response = client.delete(f"/documents/{doc_id}")
        assert response.status_code == 403
        mock_delete.assert_not_called()

        # Clean up test doc
        with SessionLocal() as db:
            db.query(Document).filter(Document.id == doc_id).delete()
            db.commit()

    @patch("app.api.documents.upload_document_file", side_effect=RuntimeError("Storage quota exceeded"))
    @patch("app.api.documents.is_supabase_configured", return_value=True)
    def test_upload_failure_cleans_up_and_returns_500(self, mock_is_configured, mock_upload):
        """Test that if Supabase upload fails, returns 500 and no DB record is left."""
        client = TestClient(app)
        pdf_bytes = b"%PDF-1.4 sample content for failure test"

        response = client.post(
            "/documents/upload",
            files={"file": ("fail_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"subject": "Chemistry"},
        )

        assert response.status_code == 500
        assert "Failed to upload document to persistent storage" in response.json()["detail"]

    @patch("app.api.documents.download_document_file", return_value=b"%PDF-1.4 downloaded bytes")
    @patch("app.api.documents.run_ingestion_pipeline")
    @patch("app.api.documents.is_supabase_configured", return_value=True)
    def test_process_document_background_downloads_and_cleans_temp_file(
        self, mock_is_configured, mock_pipeline, mock_download, tmp_path
    ):
        """Test that background processing downloads from Supabase when local file missing and cleans up afterward."""
        from app.api.documents import process_document_background

        doc_id = "test-bg-download-123"
        storage_path = f"documents/dev-user/{doc_id}.pdf"
        non_existent_local_path = str(tmp_path / f"{doc_id}.pdf")

        mock_pipeline.return_value = {
            "readable_pages": 3,
            "scanned_pages": 0,
            "total_parents": 2,
            "total_children": 5,
            "embedding_dimension": 384,
        }

        with SessionLocal() as db:
            doc = Document(
                id=doc_id,
                user_id="dev-user",
                filename="download_test.pdf",
                subject="Physics",
                file_path=storage_path,
                status="PROCESSING",
            )
            db.add(doc)
            db.commit()

        # Run the background task
        process_document_background(
            document_id=doc_id,
            file_path=non_existent_local_path,
            subject="Physics",
            user_id="dev-user",
        )

        mock_download.assert_called_once_with(storage_path)
        mock_pipeline.assert_called_once()

        # Verify document status updated to READY
        with SessionLocal() as db:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            assert doc is not None
            assert doc.status == "READY"
            assert doc.page_count == 3

            # Clean up
            db.delete(doc)
            db.commit()

    @patch("app.api.documents.download_document_file", return_value=b"%PDF-1.4 bad pdf")
    @patch("app.api.documents.delete_document_file")
    @patch("app.api.documents.run_ingestion_pipeline", side_effect=RuntimeError("Corrupt PDF content"))
    @patch("app.api.documents.is_supabase_configured", return_value=True)
    def test_process_document_failure_cleans_supabase_and_sets_failed(
        self, mock_is_configured, mock_pipeline, mock_delete, mock_download, tmp_path
    ):
        """Test that when processing fails, Supabase object is deleted and doc status is FAILED."""
        from app.api.documents import process_document_background

        doc_id = "test-bg-fail-cleanup"
        storage_path = f"documents/dev-user/{doc_id}.pdf"
        local_path = str(tmp_path / f"{doc_id}.pdf")

        with SessionLocal() as db:
            doc = Document(
                id=doc_id,
                user_id="dev-user",
                filename="corrupt.pdf",
                subject="Chemistry",
                file_path=storage_path,
                status="PROCESSING",
            )
            db.add(doc)
            db.commit()

        process_document_background(
            document_id=doc_id,
            file_path=local_path,
            subject="Chemistry",
            user_id="dev-user",
        )

        mock_delete.assert_called_once_with(storage_path)

        with SessionLocal() as db:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            assert doc is not None
            assert doc.status == "FAILED"

            # Clean up
            db.delete(doc)
            db.commit()

    @patch("app.services.guest_cleanup_service.delete_document_file")
    @patch("app.services.guest_cleanup_service.is_supabase_configured", return_value=True)
    def test_guest_cleanup_rejects_authenticated_account(self, mock_is_configured, mock_delete):
        """Test that authenticated Google accounts are never cleaned up by guest lifecycle."""
        auth_user_id = "google_10987654321"

        with SessionLocal() as db:
            summary = cleanup_guest_data(auth_user_id, db)

        assert summary["status"] == "rejected"
        assert summary["reason"] == "authenticated_account_protected"
        mock_delete.assert_not_called()

