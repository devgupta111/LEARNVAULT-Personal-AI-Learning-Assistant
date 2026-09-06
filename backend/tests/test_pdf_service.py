"""
tests/test_pdf_service.py

Unit tests for pdf_service.py.

These tests are pure unit tests — no database, no HTTP, no filesystem mocks.
They create real temporary PDF files using PyMuPDF and test extraction behavior.
"""

import io
import os
import tempfile

import pymupdf
import pytest

from app.services.pdf_service import (
    SCANNED_PAGE_THRESHOLD,
    clean_page_text,
    extract_text_from_pdf,
    is_document_fully_scanned,
)


def make_searchable_pdf(text: str, num_pages: int = 1) -> str:
    """
    Create a temporary searchable PDF containing the given text.
    Returns the file path. Caller is responsible for deleting the file.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = pymupdf.open()
    for _ in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    doc.save(tmp.name)
    doc.close()
    return tmp.name


def make_blank_pdf(num_pages: int = 1) -> str:
    """
    Create a temporary blank PDF (no text) to simulate a scanned document.
    Returns the file path. Caller is responsible for deleting the file.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = pymupdf.open()
    for _ in range(num_pages):
        doc.new_page()
    doc.save(tmp.name)
    doc.close()
    return tmp.name


class TestCleanPageText:
    def test_returns_empty_string_for_empty_input(self):
        assert clean_page_text("") == ""

    def test_returns_empty_string_for_none(self):
        assert clean_page_text(None) == ""

    def test_removes_null_bytes(self):
        result = clean_page_text("Hello\x00World")
        assert "\x00" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_control_characters(self):
        result = clean_page_text("Text\x01\x02\x03More")
        assert "\x01" not in result
        assert "\x02" not in result

    def test_preserves_newlines(self):
        text = "Line 1\nLine 2\nLine 3"
        result = clean_page_text(text)
        assert "Line 1" in result
        assert "Line 2" in result

    def test_normalizes_tabs_to_space(self):
        result = clean_page_text("Col1\tCol2\tCol3")
        assert "\t" not in result
        assert "Col1" in result

    def test_collapses_multiple_spaces(self):
        result = clean_page_text("Word1   Word2    Word3")
        assert "  " not in result

    def test_collapses_excessive_blank_lines(self):
        text = "Para1\n\n\n\n\nPara2"
        result = clean_page_text(text)
        assert "\n\n\n" not in result

    def test_strips_leading_trailing_whitespace(self):
        result = clean_page_text("  Hello World  ")
        assert result == "Hello World"

    def test_preserves_meaningful_content(self):
        text = "Operating Systems: Process Scheduling and Memory Management"
        result = clean_page_text(text)
        assert "Operating Systems" in result
        assert "Process Scheduling" in result


class TestExtractTextFromPdf:
    def test_raises_file_not_found_for_missing_file(self):
        with pytest.raises(FileNotFoundError):
            extract_text_from_pdf("/nonexistent/path/file.pdf")

    def test_raises_value_error_for_invalid_file(self, tmp_path):
        fake_pdf = tmp_path / "not_a_real.pdf"
        fake_pdf.write_bytes(b"this is not a pdf")
        with pytest.raises(ValueError):
            extract_text_from_pdf(str(fake_pdf))

    def test_single_page_extraction(self):
        path = make_searchable_pdf("Database Management Systems lecture notes with relational algebra and schema normalization details.")
        try:
            pages = extract_text_from_pdf(path)
            assert len(pages) == 1
            assert pages[0]["page_number"] == 1
            assert "Database Management" in pages[0]["text"]
            assert pages[0]["needs_ocr"] is False
        finally:
            os.unlink(path)

    def test_multi_page_extraction(self):
        path = make_searchable_pdf(
            "This is a lecture note page with sufficient content for extraction.",
            num_pages=3,
        )
        try:
            pages = extract_text_from_pdf(path)
            assert len(pages) == 3
            assert pages[0]["page_number"] == 1
            assert pages[1]["page_number"] == 2
            assert pages[2]["page_number"] == 3
        finally:
            os.unlink(path)

    def test_page_numbers_are_one_indexed(self):
        path = make_searchable_pdf("Content", num_pages=4)
        try:
            pages = extract_text_from_pdf(path)
            page_numbers = [p["page_number"] for p in pages]
            assert page_numbers == [1, 2, 3, 4]
        finally:
            os.unlink(path)

    def test_each_page_has_required_keys(self):
        path = make_searchable_pdf("Test content here for key check.")
        try:
            pages = extract_text_from_pdf(path)
            for page in pages:
                assert "page_number" in page
                assert "text" in page
                assert "needs_ocr" in page
        finally:
            os.unlink(path)

    def test_scanned_page_detected(self):
        path = make_blank_pdf(num_pages=1)
        try:
            pages = extract_text_from_pdf(path)
            assert len(pages) == 1
            assert pages[0]["needs_ocr"] is True
        finally:
            os.unlink(path)

    def test_mixed_pages_detected_correctly(self):
        doc = pymupdf.open()
        readable = doc.new_page()
        readable.insert_text((72, 72), "Readable content for testing purposes here with extensive text exceeding the threshold.", fontsize=11)
        doc.new_page()

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        doc.save(tmp.name)
        doc.close()

        try:
            pages = extract_text_from_pdf(tmp.name)
            assert len(pages) == 2
            assert pages[0]["needs_ocr"] is False
            assert pages[1]["needs_ocr"] is True
        finally:
            os.unlink(tmp.name)

    def test_text_is_cleaned(self):
        path = make_searchable_pdf("Clean   text   with  spaces")
        try:
            pages = extract_text_from_pdf(path)
            assert "  " not in pages[0]["text"]
        finally:
            os.unlink(path)


class TestIsDocumentFullyScanned:
    def test_empty_page_list_is_fully_scanned(self):
        assert is_document_fully_scanned([]) is True

    def test_all_scanned_returns_true(self):
        pages = [
            {"page_number": 1, "text": "", "needs_ocr": True},
            {"page_number": 2, "text": "hi", "needs_ocr": True},
        ]
        assert is_document_fully_scanned(pages) is True

    def test_all_readable_returns_false(self):
        pages = [
            {"page_number": 1, "text": "Long text content", "needs_ocr": False},
            {"page_number": 2, "text": "More content here", "needs_ocr": False},
        ]
        assert is_document_fully_scanned(pages) is False

    def test_one_readable_page_returns_false(self):
        pages = [
            {"page_number": 1, "text": "", "needs_ocr": True},
            {"page_number": 2, "text": "Long readable page content here", "needs_ocr": False},
            {"page_number": 3, "text": "", "needs_ocr": True},
        ]
        assert is_document_fully_scanned(pages) is False
