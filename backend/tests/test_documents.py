"""
tests/test_documents.py

Integration tests for the document API endpoints.

Uses the client fixture from conftest.py (SQLite + isolated upload dir).
Background tasks run synchronously inside TestClient, so by the time
the test reads the status, processing is already complete.
"""

import io
import time

import pymupdf
import pytest


def make_pdf_bytes(
    text: str = "Lecture notes with sufficient content for testing and verification purposes.",
    num_pages: int = 1,
) -> bytes:
    """Create a valid in-memory PDF with readable text."""
    doc = pymupdf.open()
    for _ in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def make_blank_pdf_bytes(num_pages: int = 1) -> bytes:
    """Create a blank PDF (no text) to simulate a fully scanned document."""
    doc = pymupdf.open()
    for _ in range(num_pages):
        doc.new_page()
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_root_returns_message(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "message" in response.json()


class TestUploadValidation:
    def test_rejects_non_pdf_extension(self, client):
        response = client.post(
            "/documents/upload",
            data={"subject": "Test"},
            files={"file": ("notes.txt", b"some text", "application/pdf")},
        )
        assert response.status_code == 400
        assert "PDF" in response.json()["detail"]

    def test_rejects_wrong_mime_type(self, client):
        response = client.post(
            "/documents/upload",
            data={"subject": "Test"},
            files={"file": ("notes.pdf", b"%PDF-fake", "text/plain")},
        )
        assert response.status_code == 400

    def test_rejects_empty_file(self, client):
        response = client.post(
            "/documents/upload",
            data={"subject": "Test"},
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert response.status_code == 400

    def test_rejects_oversized_file(self, client):
        large_content = b"x" * (21 * 1024 * 1024)
        response = client.post(
            "/documents/upload",
            data={"subject": "Test"},
            files={"file": ("large.pdf", large_content, "application/pdf")},
        )
        assert response.status_code == 400
        assert "large" in response.json()["detail"].lower()

    def test_rejects_corrupted_pdf(self, client):
        response = client.post(
            "/documents/upload",
            data={"subject": "Test"},
            files={"file": ("bad.pdf", b"not a real pdf content", "application/pdf")},
        )
        assert response.status_code == 202
        data = response.json()
        doc_id = data["document_id"]

        status_response = client.get(f"/documents/{doc_id}")
        assert status_response.status_code == 200
        detail = status_response.json()
        assert detail["status"] == "FAILED"


class TestSuccessfulUpload:
    def test_returns_202_with_document_id(self, client):
        pdf = make_pdf_bytes("Operating Systems lecture notes page content.")
        response = client.post(
            "/documents/upload",
            data={"subject": "OS"},
            files={"file": ("os_notes.pdf", pdf, "application/pdf")},
        )
        assert response.status_code == 202
        data = response.json()
        assert "document_id" in data
        assert data["status"] == "PROCESSING"
        assert len(data["document_id"]) == 36

    def test_document_becomes_ready_after_processing(self, client):
        pdf = make_pdf_bytes("DBMS lecture notes covering relational normalization and database design principles.")
        response = client.post(
            "/documents/upload",
            data={"subject": "DBMS"},
            files={"file": ("dbms.pdf", pdf, "application/pdf")},
        )
        doc_id = response.json()["document_id"]

        status = client.get(f"/documents/{doc_id}")
        assert status.status_code == 200
        detail = status.json()
        assert detail["status"] == "READY"
        assert detail["page_count"] == 1
        assert detail["filename"] == "dbms.pdf"
        assert detail["subject"] == "DBMS"

    def test_multi_page_pdf(self, client):
        pdf = make_pdf_bytes(
            "Algorithm Design lecture content covering dynamic programming and divide and conquer strategies.",
            num_pages=5,
        )
        response = client.post(
            "/documents/upload",
            data={"subject": "DAA"},
            files={"file": ("daa_notes.pdf", pdf, "application/pdf")},
        )
        doc_id = response.json()["document_id"]

        status = client.get(f"/documents/{doc_id}")
        detail = status.json()
        assert detail["status"] == "READY"
        assert detail["page_count"] == 5

    def test_default_subject_is_general(self, client):
        pdf = make_pdf_bytes("Some detailed content here for the default subject test with ample characters.")
        response = client.post(
            "/documents/upload",
            files={"file": ("notes.pdf", pdf, "application/pdf")},
        )
        doc_id = response.json()["document_id"]
        detail = client.get(f"/documents/{doc_id}").json()
        assert detail["subject"] == "General"


class TestScannedDocument:
    def test_fully_scanned_pdf_becomes_failed(self, client):
        pdf = make_blank_pdf_bytes(num_pages=3)
        response = client.post(
            "/documents/upload",
            data={"subject": "Scanned"},
            files={"file": ("scanned.pdf", pdf, "application/pdf")},
        )
        doc_id = response.json()["document_id"]

        status = client.get(f"/documents/{doc_id}")
        detail = status.json()
        assert detail["status"] == "FAILED"
        assert "scanned" in detail["error_message"].lower()


class TestStatusEndpoint:
    def test_returns_404_for_unknown_id(self, client):
        response = client.get("/documents/nonexistent-uuid-here")
        assert response.status_code == 404

    def test_detail_has_all_required_fields(self, client):
        pdf = make_pdf_bytes("Content for field completeness test.")
        upload = client.post(
            "/documents/upload",
            data={"subject": "Math"},
            files={"file": ("math.pdf", pdf, "application/pdf")},
        )
        doc_id = upload.json()["document_id"]
        detail = client.get(f"/documents/{doc_id}").json()

        required_fields = [
            "document_id", "filename", "subject", "status",
            "page_count", "error_message", "created_at", "updated_at",
        ]
        for field in required_fields:
            assert field in detail, f"Missing field: {field}"


class TestListEndpoint:
    def test_list_returns_array(self, client):
        response = client.get("/documents/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_uploaded_document_appears_in_list(self, client):
        pdf = make_pdf_bytes("List endpoint test content.")
        client.post(
            "/documents/upload",
            data={"subject": "CS"},
            files={"file": ("cs.pdf", pdf, "application/pdf")},
        )
        docs = client.get("/documents/").json()
        assert len(docs) >= 1
        filenames = [d["filename"] for d in docs]
        assert "cs.pdf" in filenames

    def test_list_item_has_required_fields(self, client):
        pdf = make_pdf_bytes("Content for list field test.")
        client.post(
            "/documents/upload",
            data={"subject": "Physics"},
            files={"file": ("physics.pdf", pdf, "application/pdf")},
        )
        docs = client.get("/documents/").json()
        doc = next(d for d in docs if d["filename"] == "physics.pdf")
        for field in ["document_id", "filename", "subject", "status", "page_count"]:
            assert field in doc
