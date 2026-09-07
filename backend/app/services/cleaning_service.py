"""
services/cleaning_service.py

Deep text cleaning for extracted PDF pages.

This service runs AFTER pdf_service.extract_text_from_pdf() and applies
additional cleaning that is safe for academic text but was intentionally
left out of the Day 1 minimal cleaner.

What Day 1 cleaning already does (in pdf_service.clean_page_text):
  - Remove ASCII control characters (keep newline, tab)
  - Normalize tabs to spaces
  - Collapse runs of 2+ spaces to one space
  - Collapse 3+ consecutive blank lines to two blank lines
  - Strip leading/trailing whitespace

What this module adds:
  - Detect and remove repeated page headers/footers
  - Repair soft-hyphen line-break artifacts
  - Normalize common ligature/encoding artifacts
  - Normalize Windows line endings to Unix
"""

import re
from collections import Counter
from typing import List, Dict, Set


LIGATURE_MAP = {
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb00": "ff",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "ft",
    "\ufb06": "st",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u00ad": "",
}


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_ligatures(text: str) -> str:
    for src, dst in LIGATURE_MAP.items():
        text = text.replace(src, dst)
    return text


def _repair_hyphenation(text: str) -> str:
    return re.sub(r"([a-zA-Z])-\n([a-z])", r"\1\2", text)


def _detect_repeated_headers_footers(pages: List[Dict]) -> Set[str]:
    """
    Detect repeated header/footer lines that appear on multiple pages.

    Headers and footers by definition only appear at the top or bottom of pages.
    Only inspects the first 2 and last 2 non-empty lines of each page to prevent
    treating body paragraphs or repeated educational content as headers/footers.
    """
    if len(pages) < 3:
        return set()
    line_counts: Counter = Counter()
    for page in pages:
        seen_in_page: Set[str] = set()
        lines = [line.strip() for line in page["text"].split("\n") if line.strip()]
        if not lines:
            continue
        # Headers/footers only occur at page boundaries (top 2 or bottom 2 lines)
        candidates = set(lines[:2] + lines[-2:]) if len(lines) > 4 else set(lines[:1] + lines[-1:])
        for stripped in candidates:
            if 5 <= len(stripped) <= 120 and stripped not in seen_in_page:
                line_counts[stripped] += 1
                seen_in_page.add(stripped)
    threshold = max(3, len(pages) // 2)
    return {line for line, count in line_counts.items() if count >= threshold}


def _remove_repeated_lines(text: str, repeated: Set[str]) -> str:
    """
    Remove detected repeated header/footer lines from the page text.

    Only removes matching lines from the start (header zone) or end (footer zone)
    of the page, preserving any identical phrasing that occurs in the body text.
    """
    if not repeated:
        return text
    raw_lines = text.split("\n")
    non_empty = [i for i, l in enumerate(raw_lines) if l.strip()]
    if not non_empty:
        return text

    # Header zone: first 2 non-empty lines; footer zone: last 2 non-empty lines
    header_indices = set(non_empty[:2])
    footer_indices = set(non_empty[-2:])
    boundary_indices = header_indices | footer_indices

    result_lines = []
    for i, line in enumerate(raw_lines):
        if i in boundary_indices and line.strip() in repeated:
            continue
        result_lines.append(line)
    return "\n".join(result_lines)


def deep_clean_page(text: str, repeated_lines: Set[str]) -> str:
    if not text or not text.strip():
        return ""
    text = _normalize_line_endings(text)
    text = _normalize_ligatures(text)
    text = _repair_hyphenation(text)
    text = _remove_repeated_lines(text, repeated_lines)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_document_pages(pages: List[Dict]) -> List[Dict]:
    """
    Apply deep cleaning to every page in a document.

    Takes output of pdf_service.extract_text_from_pdf() and returns
    a new list with more thoroughly cleaned text.

    Args:
        pages: List of page dicts with keys: page_number, text, needs_ocr.

    Returns:
        New list of page dicts with cleaned text. Input is not mutated.
    """
    readable_pages = [p for p in pages if not p["needs_ocr"]]
    repeated_lines = _detect_repeated_headers_footers(readable_pages)
    result = []
    for page in pages:
        if page["needs_ocr"]:
            result.append(dict(page))
            continue
        cleaned = deep_clean_page(page["text"], repeated_lines)
        result.append({
            "page_number": page["page_number"],
            "text": cleaned,
            "needs_ocr": page["needs_ocr"],
        })
    return result
