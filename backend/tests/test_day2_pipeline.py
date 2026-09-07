"""
tests/test_day2_pipeline.py

End-to-end integration tests for the complete Day 2 ingestion pipeline.

These tests run against the real PDFs in data/uploads/ when available.
They test the full pipeline: PDF -> extract -> clean -> chunk -> embed -> JSON output.
"""

import json
import math
import pytest
from pathlib import Path

from app.services.pdf_service import extract_text_from_pdf
from app.services.cleaning_service import clean_document_pages
from app.services.chunking_service import generate_chunks
from app.services.embedding_service import embed_chunks, get_embedding_dimension
from app.services.pipeline_service import run_ingestion_pipeline

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOADS_DIR = PROJECT_ROOT / "data" / "uploads"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

TEST_PDF_FILES = [
    UPLOADS_DIR / "lec-1.pdf",
    UPLOADS_DIR / "Lec-2.pdf",
    UPLOADS_DIR / "Lec-3.pdf",
]

EXISTING_PDFS = [f for f in TEST_PDF_FILES if f.exists()]


class TestExtractThenClean:
    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_extract_and_clean_produces_text(self, pdf_path):
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        assert len(cleaned) == len(pages)
        readable = [p for p in cleaned if not p["needs_ocr"]]
        assert len(readable) > 0

    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_cleaning_preserves_page_numbers(self, pdf_path):
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        original_numbers = [p["page_number"] for p in pages]
        cleaned_numbers = [p["page_number"] for p in cleaned]
        assert original_numbers == cleaned_numbers

    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_cleaned_text_is_not_empty_for_readable_pages(self, pdf_path):
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        for page in cleaned:
            if not page["needs_ocr"]:
                assert page["text"].strip() != ""


class TestChunkingOnRealPDFs:
    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_generates_parents_and_children(self, pdf_path):
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        doc_id = pdf_path.stem
        parents, children = generate_chunks(cleaned, doc_id, "dev-user", "Test")
        assert len(parents) >= 1
        assert len(children) >= 1

    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_all_children_reference_valid_parents(self, pdf_path):
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        doc_id = pdf_path.stem
        parents, children = generate_chunks(cleaned, doc_id, "dev-user", "Test")
        parent_ids = {p["chunk_id"] for p in parents}
        for child in children:
            assert child["parent_id"] in parent_ids, (
                f"Child {child['chunk_id']} references unknown parent {child['parent_id']}"
            )

    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_all_required_metadata_present_in_children(self, pdf_path):
        required_keys = {
            "chunk_id", "document_id", "user_id", "subject",
            "page_start", "page_end", "parent_id", "text"
        }
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        doc_id = pdf_path.stem
        _, children = generate_chunks(cleaned, doc_id, "dev-user", "Test")
        for child in children:
            missing = required_keys - set(child.keys())
            assert not missing, f"Child missing keys: {missing}"


class TestEmbeddingOnRealChunks:
    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_embedding_produces_correct_dimension(self, pdf_path):
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        doc_id = pdf_path.stem
        _, children = generate_chunks(cleaned, doc_id, "dev-user", "Test")
        embedded = embed_chunks(children)
        dim = get_embedding_dimension()
        for chunk in embedded:
            if chunk["text"].strip():
                assert len(chunk["embedding"]) == dim

    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_no_nan_in_any_embedding(self, pdf_path):
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        doc_id = pdf_path.stem
        _, children = generate_chunks(cleaned, doc_id, "dev-user", "Test")
        embedded = embed_chunks(children)
        for chunk in embedded:
            for val in chunk["embedding"]:
                assert not math.isnan(val)

    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_all_embeddings_non_empty(self, pdf_path):
        pages = extract_text_from_pdf(str(pdf_path))
        cleaned = clean_document_pages(pages)
        doc_id = pdf_path.stem
        _, children = generate_chunks(cleaned, doc_id, "dev-user", "Test")
        embedded = embed_chunks(children)
        for chunk in embedded:
            if chunk["text"].strip():
                assert chunk["embedding"] != []


class TestFullPipeline:
    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_pipeline_runs_and_saves_json(self, pdf_path, tmp_path, monkeypatch):
        import app.services.pipeline_service as psvc
        monkeypatch.setattr(psvc, "PROCESSED_DIR", tmp_path)

        result = run_ingestion_pipeline(
            document_id=pdf_path.stem,
            file_path=str(pdf_path),
            subject="Test Subject",
            user_id="dev-user",
        )
        assert result["status"] == "success"

    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_pipeline_output_json_structure(self, pdf_path, tmp_path, monkeypatch):
        import app.services.pipeline_service as psvc
        monkeypatch.setattr(psvc, "PROCESSED_DIR", tmp_path)

        result = run_ingestion_pipeline(
            document_id=pdf_path.stem,
            file_path=str(pdf_path),
            subject="Test Subject",
            user_id="dev-user",
        )
        output_file = tmp_path / f"{pdf_path.stem}.json"
        assert output_file.exists(), f"Expected output at {output_file}"

        with open(output_file, encoding="utf-8") as f:
            data = json.load(f)

        assert "document_id" in data
        assert "parents" in data
        assert "children" in data
        assert "stats" in data
        assert data["stats"]["total_parents"] > 0
        assert data["stats"]["total_children"] > 0
        assert data["stats"]["embedding_dimension"] > 0

    @pytest.mark.parametrize("pdf_path", EXISTING_PDFS)
    def test_pipeline_children_have_embeddings_in_json(self, pdf_path, tmp_path, monkeypatch):
        import app.services.pipeline_service as psvc
        monkeypatch.setattr(psvc, "PROCESSED_DIR", tmp_path)

        run_ingestion_pipeline(
            document_id=pdf_path.stem,
            file_path=str(pdf_path),
            subject="Test Subject",
            user_id="dev-user",
        )
        output_file = tmp_path / f"{pdf_path.stem}.json"
        with open(output_file, encoding="utf-8") as f:
            data = json.load(f)

        dim = data["stats"]["embedding_dimension"]
        for child in data["children"]:
            assert "embedding" in child
            if child["text"].strip():
                assert len(child["embedding"]) == dim
