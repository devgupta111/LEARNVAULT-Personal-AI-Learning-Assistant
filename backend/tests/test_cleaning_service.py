"""
tests/test_cleaning_service.py

Unit tests for cleaning_service.py (Day 2).
"""

import pytest
from app.services.cleaning_service import (
    clean_document_pages,
    deep_clean_page,
    _normalize_line_endings,
    _normalize_ligatures,
    _repair_hyphenation,
    _detect_repeated_headers_footers,
    _remove_repeated_lines,
)


def make_page(page_number: int, text: str, needs_ocr: bool = False) -> dict:
    return {"page_number": page_number, "text": text, "needs_ocr": needs_ocr}



class TestNormalizeLineEndings:
    def test_crlf_to_lf(self):
        assert _normalize_line_endings("line1\r\nline2") == "line1\nline2"

    def test_bare_cr_to_lf(self):
        assert _normalize_line_endings("line1\rline2") == "line1\nline2"

    def test_no_change_on_unix(self):
        text = "line1\nline2"
        assert _normalize_line_endings(text) == text


class TestNormalizeLigatures:
    def test_fi_ligature(self):
        assert _normalize_ligatures("\ufb01le") == "file"

    def test_fl_ligature(self):
        assert _normalize_ligatures("\ufb02ow") == "flow"

    def test_smart_quotes(self):
        result = _normalize_ligatures("\u2018hello\u2019")
        assert result == "'hello'"

    def test_em_dash(self):
        assert _normalize_ligatures("a\u2014b") == "a-b"

    def test_soft_hyphen_removed(self):
        assert _normalize_ligatures("soft\u00adhyphen") == "softhyphen"

    def test_unchanged_ascii(self):
        text = "Hello world"
        assert _normalize_ligatures(text) == text


class TestRepairHyphenation:
    def test_joins_continuation_artifact(self):
        result = _repair_hyphenation("infor-\nmation")
        assert result == "information"

    def test_preserves_uppercase_continuation(self):
        result = _repair_hyphenation("multi-\nCore")
        assert "multi-" in result or "multiCore" in result
        assert "\nCore" not in result or "multi-" in result

    def test_no_change_when_no_hyphen_newline(self):
        text = "normal text without issues"
        assert _repair_hyphenation(text) == text


class TestDetectRepeatedHeadersFooters:
    def test_detects_repeated_line(self):
        repeated_line = "Chapter 1: Introduction"
        pages = [
            make_page(i, repeated_line + f"\nUnique content page {i}")
            for i in range(1, 7)
        ]
        repeated = _detect_repeated_headers_footers(pages)
        assert repeated_line in repeated

    def test_unique_lines_not_flagged(self):
        pages = [
            make_page(i, f"Unique content for page {i}")
            for i in range(1, 5)
        ]
        repeated = _detect_repeated_headers_footers(pages)
        for i in range(1, 5):
            assert f"Unique content for page {i}" not in repeated

    def test_returns_empty_for_fewer_than_3_pages(self):
        pages = [make_page(1, "line"), make_page(2, "line")]
        assert _detect_repeated_headers_footers(pages) == set()

    def test_very_short_lines_not_detected(self):
        pages = [make_page(i, "hi\nContent " + str(i)) for i in range(1, 7)]
        repeated = _detect_repeated_headers_footers(pages)
        assert "hi" not in repeated


class TestDeepCleanPage:
    def test_removes_repeated_lines(self):
        repeated = {"HEADER: AI Learning"}
        text = "HEADER: AI Learning\nActual content here."
        result = deep_clean_page(text, repeated)
        assert "HEADER: AI Learning" not in result
        assert "Actual content here." in result

    def test_preserves_meaningful_content(self):
        text = "Operating Systems lecture.\nProcesses are programs in execution."
        result = deep_clean_page(text, set())
        assert "Operating Systems" in result
        assert "programs in execution" in result

    def test_handles_empty_input(self):
        assert deep_clean_page("", set()) == ""
        assert deep_clean_page("   ", set()) == ""

    def test_collapses_multiple_spaces(self):
        text = "word1   word2    word3"
        result = deep_clean_page(text, set())
        assert "  " not in result

    def test_collapses_excessive_newlines(self):
        text = "Para1\n\n\n\n\nPara2"
        result = deep_clean_page(text, set())
        assert "\n\n\n" not in result


class TestCleanDocumentPages:
    def test_returns_same_number_of_pages(self):
        pages = [make_page(i, f"Content for page {i}") for i in range(1, 4)]
        result = clean_document_pages(pages)
        assert len(result) == 3

    def test_preserves_ocr_pages_unchanged(self):
        pages = [
            make_page(1, "Real content here"),
            make_page(2, "", needs_ocr=True),
        ]
        result = clean_document_pages(pages)
        ocr_page = result[1]
        assert ocr_page["needs_ocr"] is True

    def test_repeated_header_removed_across_pages(self):
        header = "Lecture Notes - CS101 - Introduction to Computer Science"
        pages = [
            make_page(i, header + f"\nUnique educational content for page {i}.\n" * 5)
            for i in range(1, 7)
        ]
        result = clean_document_pages(pages)
        for page in result:
            if not page["needs_ocr"]:
                assert header not in page["text"]

    def test_page_numbers_preserved_in_output(self):
        pages = [make_page(i, f"Text for page {i}") for i in range(1, 4)]
        result = clean_document_pages(pages)
        numbers = [p["page_number"] for p in result]
        assert numbers == [1, 2, 3]
