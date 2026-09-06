"""
services/pdf_service.py

PDF text extraction using PyMuPDF.

Responsibilities:
- Open a PDF file page by page
- Apply basic text cleaning (control chars, whitespace)
- Detect scanned/image-only pages
- Return a structured list of page dicts

Does NOT chunk, embed, or send text to any LLM (those belong to later days).
"""

import re
from pathlib import Path
from typing import List, Dict

import pymupdf

SCANNED_PAGE_THRESHOLD = 50


def clean_page_text(text: str) -> str:
    """
    Apply minimal cleaning to raw extracted page text.

    What this does:
    - Remove null bytes and most ASCII control characters
      (keeps \\n, \\r, \\t which carry structural meaning)
    - Normalize tab characters to a single space
    - Collapse runs of 2+ spaces to a single space
    - Collapse runs of 3+ blank lines to two blank lines
    - Strip leading/trailing whitespace

    What this deliberately does NOT do:
    - Remove newlines (they separate bullet points, numbered lists, etc.)
    - Remove any Unicode characters
    - Remove page numbers, headers, or footers
      (header/footer removal is a Day 2 task)
    """
    if not text:
        return ""

    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    text = text.replace("\t", " ")

    text = re.sub(r" {2,}", " ", text)

    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def extract_text_from_pdf(file_path: str) -> List[Dict]:
    """
    Extract text from a PDF file, page by page.

    Args:
        file_path: Absolute or relative path to the PDF file.

    Returns:
        A list of page dicts, one per page:
        [
            {
                "page_number": 1,
                "text": "cleaned extracted text",
                "needs_ocr": False
            },
            {
                "page_number": 2,
                "text": "",
                "needs_ocr": True
            },
            ...
        ]

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If PyMuPDF cannot open the file (corrupted, encrypted, etc.).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise ValueError(f"Could not open PDF file: {exc}") from exc

    pages: List[Dict] = []

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            raw_text = page.get_text()
            cleaned = clean_page_text(raw_text)
            needs_ocr = len(cleaned) < SCANNED_PAGE_THRESHOLD

            pages.append(
                {
                    "page_number": page_index + 1,
                    "text": cleaned,
                    "needs_ocr": needs_ocr,
                }
            )
    finally:
        doc.close()

    return pages


def is_document_fully_scanned(pages: List[Dict]) -> bool:
    """
    Return True if every page in the document needs OCR.

    A document is considered fully scanned only when ALL pages produce
    fewer than SCANNED_PAGE_THRESHOLD characters. A single readable page
    is enough to consider the document searchable.

    An empty page list is treated as fully scanned.
    """
    if not pages:
        return True
    return all(page["needs_ocr"] for page in pages)
