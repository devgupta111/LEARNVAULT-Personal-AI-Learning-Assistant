"""
tests/test_chunking_service.py

Unit tests for chunking_service.py (Day 2).
"""

import pytest
from app.services.chunking_service import (
    generate_chunks,
    _split_text_into_chunks,
    _make_parent_id,
    _make_child_id,
    PARENT_CHUNK_SIZE,
    CHILD_CHUNK_SIZE,
)


def make_page(page_number: int, text: str, needs_ocr: bool = False) -> dict:
    return {"page_number": page_number, "text": text, "needs_ocr": needs_ocr}


def make_long_text(num_chars: int = 5000) -> str:
    sentence = "The operating system manages processes, memory, and hardware resources. "
    return (sentence * (num_chars // len(sentence) + 1))[:num_chars]


class TestSplitTextIntoChunks:
    def test_empty_text_returns_empty(self):
        assert _split_text_into_chunks("", 800, 120) == []

    def test_short_text_returns_single_chunk(self):
        text = "Short academic content."
        spans = _split_text_into_chunks(text, 800, 120)
        assert len(spans) == 1
        start, end = spans[0]
        assert text[start:end].strip() == text.strip()

    def test_long_text_creates_multiple_chunks(self):
        text = make_long_text(5000)
        spans = _split_text_into_chunks(text, 800, 120)
        assert len(spans) > 1

    def test_chunks_cover_all_content(self):
        text = make_long_text(4000)
        spans = _split_text_into_chunks(text, 800, 120)
        covered = set()
        for start, end in spans:
            for i in range(start, end):
                covered.add(i)
        total_non_whitespace = len(text.strip())
        assert len(covered) >= total_non_whitespace * 0.95

    def test_overlap_exists_between_consecutive_chunks(self):
        text = make_long_text(4000)
        spans = _split_text_into_chunks(text, 800, 120)
        if len(spans) < 2:
            return
        first_end = spans[0][1]
        second_start = spans[1][0]
        assert second_start < first_end


class TestDeterministicIDs:
    def test_same_input_same_parent_id(self):
        id1 = _make_parent_id("doc-001", 0, "Some text content")
        id2 = _make_parent_id("doc-001", 0, "Some text content")
        assert id1 == id2

    def test_different_text_different_parent_id(self):
        id1 = _make_parent_id("doc-001", 0, "Text content A")
        id2 = _make_parent_id("doc-001", 0, "Text content B")
        assert id1 != id2

    def test_different_document_different_parent_id(self):
        id1 = _make_parent_id("doc-001", 0, "Same text")
        id2 = _make_parent_id("doc-002", 0, "Same text")
        assert id1 != id2

    def test_same_input_same_child_id(self):
        pid = _make_parent_id("doc-001", 0, "Parent text")
        id1 = _make_child_id(pid, 0, "Child text")
        id2 = _make_child_id(pid, 0, "Child text")
        assert id1 == id2

    def test_parent_id_is_valid_uuid(self):
        import uuid
        pid = _make_parent_id("doc-001", 0, "Some text")
        uuid.UUID(pid)

    def test_child_id_is_valid_uuid(self):
        import uuid
        pid = _make_parent_id("doc-001", 0, "Parent text")
        cid = _make_child_id(pid, 0, "Child text")
        uuid.UUID(cid)


class TestGenerateChunks:
    def test_returns_empty_for_all_ocr_pages(self):
        pages = [make_page(1, "", needs_ocr=True)]
        parents, children = generate_chunks(pages, "doc-001", "dev-user", "CS")
        assert parents == []
        assert children == []

    def test_single_short_page_creates_at_least_one_parent(self):
        pages = [make_page(1, make_long_text(500))]
        parents, children = generate_chunks(pages, "doc-001", "dev-user", "CS")
        assert len(parents) >= 1
        assert len(children) >= 1

    def test_multiple_pages_creates_chunks(self):
        pages = [
            make_page(i, make_long_text(2000))
            for i in range(1, 4)
        ]
        parents, children = generate_chunks(pages, "doc-001", "dev-user", "CS")
        assert len(parents) >= 1
        assert len(children) >= len(parents)

    def test_child_parent_id_references_existing_parent(self):
        pages = [make_page(1, make_long_text(3000))]
        parents, children = generate_chunks(pages, "doc-001", "dev-user", "CS")
        parent_ids = {p["chunk_id"] for p in parents}
        for child in children:
            assert child["parent_id"] in parent_ids

    def test_all_children_have_required_metadata_keys(self):
        required_keys = {
            "chunk_id", "document_id", "user_id", "subject",
            "page_start", "page_end", "parent_id", "text"
        }
        pages = [make_page(1, make_long_text(2000))]
        _, children = generate_chunks(pages, "doc-001", "dev-user", "OS")
        for child in children:
            assert required_keys.issubset(set(child.keys())), (
                f"Missing keys: {required_keys - set(child.keys())}"
            )

    def test_document_id_propagated_to_all_chunks(self):
        pages = [make_page(1, make_long_text(2000))]
        parents, children = generate_chunks(pages, "doc-xyz", "dev-user", "Math")
        for p in parents:
            assert p["document_id"] == "doc-xyz"
        for c in children:
            assert c["document_id"] == "doc-xyz"

    def test_subject_propagated_to_children(self):
        pages = [make_page(1, make_long_text(2000))]
        _, children = generate_chunks(pages, "doc-001", "dev-user", "Database Systems")
        for c in children:
            assert c["subject"] == "Database Systems"

    def test_page_numbers_are_valid(self):
        pages = [
            make_page(1, make_long_text(1000)),
            make_page(2, make_long_text(1000)),
        ]
        parents, children = generate_chunks(pages, "doc-001", "dev-user", "CS")
        all_pages = {1, 2}
        for c in children:
            assert c["page_start"] in all_pages or c["page_end"] in all_pages
            assert c["page_start"] <= c["page_end"]

    def test_child_text_is_not_empty(self):
        pages = [make_page(1, make_long_text(2000))]
        _, children = generate_chunks(pages, "doc-001", "dev-user", "CS")
        for c in children:
            assert c["text"].strip() != ""

    def test_child_text_size_reasonable(self):
        pages = [make_page(1, make_long_text(8000))]
        _, children = generate_chunks(pages, "doc-001", "dev-user", "CS")
        for c in children:
            assert len(c["text"]) <= CHILD_CHUNK_SIZE * 2

    def test_deterministic_ids_on_same_input(self):
        pages = [make_page(1, make_long_text(2000))]
        parents1, children1 = generate_chunks(pages, "doc-001", "dev-user", "CS")
        parents2, children2 = generate_chunks(pages, "doc-001", "dev-user", "CS")
        assert [p["chunk_id"] for p in parents1] == [p["chunk_id"] for p in parents2]
        assert [c["chunk_id"] for c in children1] == [c["chunk_id"] for c in children2]
