"""
services/chunking_service.py

Hierarchical parent-child chunking for extracted PDF text.

Design decisions (per brain.md specification):
  Parent chunks: 600-800 tokens, ~50 token overlap
  Child chunks:  150-250 tokens, ~30 token overlap

  We measure in characters, not tokens, to avoid a tokenizer dependency:
    1 English token ~= 4 characters
    Parent: 2400-3200 chars, overlap ~200 chars
    Child:  600-1000 chars, overlap ~120 chars

  These values balance two needs:
    - Parents large enough to give the LLM full context paragraphs
    - Children small enough for precise vector similarity search

Deterministic IDs:
  We use UUID5 seeded by SHA-256 of stable text content.
  UUID5 takes a namespace UUID and a string name; we derive the
  namespace by hashing (document_id + chunk_index + text) with SHA-256.
  This makes chunk IDs reproducible across retries without requiring
  a database sequence.

  parent_id = uuid5(NAMESPACE_DNS, document_id + "|P|" + str(idx) + "|" + sha256(text))
  child_id  = uuid5(NAMESPACE_DNS, parent_id + "|C|" + str(idx) + "|" + sha256(text))
"""

import hashlib
import uuid
from typing import List, Dict, Tuple

PARENT_CHUNK_SIZE = 2800
PARENT_CHUNK_OVERLAP = 200

CHILD_CHUNK_SIZE = 800
CHILD_CHUNK_OVERLAP = 120

_NAMESPACE = uuid.NAMESPACE_DNS


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_parent_id(document_id: str, index: int, text: str) -> str:
    name = f"{document_id}|P|{index}|{_sha256_hex(text)}"
    return str(uuid.uuid5(_NAMESPACE, name))


def _make_child_id(parent_id: str, index: int, text: str) -> str:
    name = f"{parent_id}|C|{index}|{_sha256_hex(text)}"
    return str(uuid.uuid5(_NAMESPACE, name))


def _split_text_into_chunks(text: str, chunk_size: int, overlap: int) -> List[Tuple[int, int]]:
    """
    Return list of (start, end) character index pairs for sliding window chunks.

    Attempts to break at paragraph or sentence boundaries near the target
    chunk end to avoid splitting sentences in the middle.
    Paragraph break (double newline) is preferred over sentence break.
    """
    if not text:
        return []

    spans = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            para_break = text.rfind("\n\n", start, end)
            if para_break != -1 and para_break > start + chunk_size // 3:
                end = para_break + 2
            else:
                sentence_end = -1
                for punct in (".", "!", "?"):
                    pos = text.rfind(punct + " ", start, end)
                    if pos != -1 and pos > sentence_end:
                        sentence_end = pos + 1
                if sentence_end != -1 and sentence_end > start + chunk_size // 3:
                    end = sentence_end + 1

        span_text = text[start:end].strip()
        if span_text:
            spans.append((start, end))

        next_start = end - overlap
        if next_start <= start:
            next_start = start + max(1, chunk_size - overlap)
        start = next_start

    return spans


def _pages_for_span(
    pages: List[Dict],
    char_start: int,
    char_end: int,
    page_offsets: List[Tuple[int, int, int]],
) -> Tuple[int, int]:
    """
    Return (page_start, page_end) for a character span in the concatenated
    document text.

    page_offsets is a list of (page_number, offset_start, offset_end) tuples
    built once from the concatenated text.
    """
    page_start = None
    page_end = None
    for page_number, offset_start, offset_end in page_offsets:
        if offset_start <= char_end and offset_end >= char_start:
            if page_start is None:
                page_start = page_number
            page_end = page_number
    if page_start is None:
        page_start = page_offsets[0][0]
        page_end = page_offsets[-1][0]
    return page_start, page_end


def _build_page_offsets(pages: List[Dict]) -> Tuple[str, List[Tuple[int, int, int]]]:
    """
    Concatenate all readable page texts with a separator and record
    the character offsets for each page so we can map chunk positions
    back to page numbers.

    Returns:
        full_text:    Concatenated string of all page texts.
        page_offsets: List of (page_number, start_offset, end_offset).
    """
    separator = "\n\n"
    segments = []
    page_offsets = []
    cursor = 0

    for page in pages:
        if page["needs_ocr"] or not page["text"].strip():
            continue
        page_text = page["text"]
        start = cursor
        end = cursor + len(page_text)
        page_offsets.append((page["page_number"], start, end))
        segments.append(page_text)
        cursor = end + len(separator)

    full_text = separator.join(segments)
    return full_text, page_offsets


def generate_chunks(
    pages: List[Dict],
    document_id: str,
    user_id: str,
    subject: str,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Generate hierarchical parent and child chunks from extracted PDF pages.

    Args:
        pages:       Output of cleaning_service.clean_document_pages() or
                     pdf_service.extract_text_from_pdf().
        document_id: Document UUID string.
        user_id:     User identifier (currently a dev placeholder).
        subject:     Document subject label.

    Returns:
        (parents, children):
          parents  — list of parent chunk dicts
          children — list of child chunk dicts, each referencing a parent_id
    """
    full_text, page_offsets = _build_page_offsets(pages)

    if not full_text.strip():
        return [], []

    parent_spans = _split_text_into_chunks(
        full_text, PARENT_CHUNK_SIZE, PARENT_CHUNK_OVERLAP
    )

    parents: List[Dict] = []
    children: List[Dict] = []

    for p_index, (p_start, p_end) in enumerate(parent_spans):
        parent_text = full_text[p_start:p_end].strip()
        if not parent_text:
            continue

        p_page_start, p_page_end = _pages_for_span(
            pages, p_start, p_end, page_offsets
        )
        parent_id = _make_parent_id(document_id, p_index, parent_text)

        parent_chunk = {
            "chunk_id": parent_id,
            "document_id": document_id,
            "user_id": user_id,
            "subject": subject,
            "page_start": p_page_start,
            "page_end": p_page_end,
            "text": parent_text,
            "chunk_index": p_index,
        }
        parents.append(parent_chunk)

        child_spans = _split_text_into_chunks(
            parent_text, CHILD_CHUNK_SIZE, CHILD_CHUNK_OVERLAP
        )

        for c_index, (c_start, c_end) in enumerate(child_spans):
            child_text = parent_text[c_start:c_end].strip()
            if not child_text:
                continue

            c_page_start, c_page_end = _pages_for_span(
                pages,
                p_start + c_start,
                p_start + c_end,
                page_offsets,
            )
            child_id = _make_child_id(parent_id, c_index, child_text)

            child_chunk = {
                "chunk_id": child_id,
                "document_id": document_id,
                "user_id": user_id,
                "subject": subject,
                "page_start": c_page_start,
                "page_end": c_page_end,
                "parent_id": parent_id,
                "text": child_text,
                "chunk_index": c_index,
            }
            children.append(child_chunk)

    return parents, children
