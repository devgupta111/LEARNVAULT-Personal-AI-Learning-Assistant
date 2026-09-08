"""
services/pipeline_service.py

Day 2 ingestion pipeline orchestrator.

Runs the full pipeline from extracted PDF pages through to embedded chunks
saved as a local JSON file under data/processed/.

Pipeline steps:
  1. extract_text_from_pdf() [Day 1 - pdf_service]
  2. clean_document_pages()  [Day 2 - cleaning_service]
  3. generate_chunks()       [Day 2 - chunking_service]
  4. embed_chunks()          [Day 2 - embedding_service]
  5. save to data/processed/{document_id}.json

The output JSON structure is:
  {
    "document_id": "...",
    "user_id": "...",
    "subject": "...",
    "file_path": "...",
    "total_pages": ...,
    "parents": [ { chunk_id, document_id, user_id, subject,
                   page_start, page_end, text, chunk_index } ],
    "children": [ { chunk_id, document_id, user_id, subject,
                    page_start, page_end, parent_id, text,
                    chunk_index, embedding: [...] } ],
    "stats": {
      "total_parents": ...,
      "total_children": ...,
      "embedding_dimension": ...,
      "readable_pages": ...,
      "scanned_pages": ...
    }
  }

This file is the development inspection artifact. Qdrant integration
happens in Day 3/Phase 5.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any

from app.config import settings, PROJECT_ROOT
from app.services.pdf_service import extract_text_from_pdf, is_document_fully_scanned
from app.services.cleaning_service import clean_document_pages
from app.services.chunking_service import generate_chunks
from app.services.embedding_service import embed_chunks, get_embedding_dimension
from app.services.qdrant_service import upsert_document_chunks

logger = logging.getLogger(__name__)

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def _get_processed_path(document_id: str) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    return PROCESSED_DIR / f"{document_id}.json"


def run_ingestion_pipeline(
    document_id: str,
    file_path: str,
    subject: str = "General",
    user_id: str = "dev-user",
    qdrant_client: Optional[Any] = None,
    skip_qdrant: bool = False,
) -> Dict:
    """
    Run the complete ingestion pipeline for a single document.

    Pipeline sequence:
      1. Extract text page-by-page (pdf_service)
      2. Detect scanned pages & apply deep cleaning (cleaning_service)
      3. Generate hierarchical parent and child chunks (chunking_service)
      4. Generate 384-d embeddings for child chunks (embedding_service)
      5. Upsert points into Qdrant vector database (qdrant_service)
      6. Save processed output JSON to data/processed/{document_id}.json

    Args:
        document_id:   Unique identifier for the document.
        file_path:     Absolute path to the PDF file.
        subject:       Document subject label.
        user_id:       User identifier (dev placeholder until auth is added).
        qdrant_client: Optional QdrantClient instance (e.g. for testing with :memory:).
        skip_qdrant:   Set True only to bypass vector storage.

    Returns:
        A summary dict with keys: status, total_parents, total_children,
        embedding_dimension, readable_pages, scanned_pages, output_path,
        qdrant_points_indexed, qdrant_collection.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        ValueError:        If the PDF is corrupted or fully scanned.
        RuntimeError:      If embedding generation or Qdrant upsert fails.
    """
    logger.info("Pipeline START for document %s", document_id)

    pages = extract_text_from_pdf(file_path)
    logger.info("Extracted %d pages from %s", len(pages), file_path)

    if is_document_fully_scanned(pages):
        raise ValueError(
            "Document is fully scanned (image-only). Cannot generate text chunks."
        )

    readable_pages = [p for p in pages if not p["needs_ocr"]]
    scanned_pages = [p for p in pages if p["needs_ocr"]]
    logger.info(
        "Readable pages: %d, scanned pages: %d",
        len(readable_pages),
        len(scanned_pages),
    )

    cleaned_pages = clean_document_pages(pages)
    logger.info("Cleaning complete")

    parents, children = generate_chunks(
        cleaned_pages,
        document_id=document_id,
        user_id=user_id,
        subject=subject,
    )
    logger.info(
        "Generated %d parent chunks and %d child chunks",
        len(parents),
        len(children),
    )

    if not children:
        raise ValueError(
            "No child chunks were generated. The document may have too little text."
        )

    children_with_embeddings = embed_chunks(children)
    embedding_dim = get_embedding_dimension()
    logger.info(
        "Embedded %d child chunks (dimension: %d)",
        len(children_with_embeddings),
        embedding_dim,
    )

    # Day 3 — Qdrant vector database upsert
    qdrant_points_indexed = 0
    qdrant_collection = None
    if not skip_qdrant:
        logger.info("Upserting %d child chunks into Qdrant", len(children_with_embeddings))
        qdrant_result = upsert_document_chunks(
            parents=parents,
            children=children_with_embeddings,
            client=qdrant_client,
        )
        qdrant_points_indexed = qdrant_result.get("points_indexed", 0)
        qdrant_collection = qdrant_result.get("collection_name")
        logger.info("Qdrant upsert complete: %d points indexed", qdrant_points_indexed)

    output = {
        "document_id": document_id,
        "user_id": user_id,
        "subject": subject,
        "file_path": file_path,
        "total_pages": len(pages),
        "parents": parents,
        "children": children_with_embeddings,
        "stats": {
            "total_parents": len(parents),
            "total_children": len(children_with_embeddings),
            "embedding_dimension": embedding_dim,
            "readable_pages": len(readable_pages),
            "scanned_pages": len(scanned_pages),
            "qdrant_points_indexed": qdrant_points_indexed,
            "qdrant_collection": qdrant_collection,
        },
    }

    output_path = _get_processed_path(document_id)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("Saved processed output to %s", output_path)

    logger.info("Pipeline COMPLETE for document %s", document_id)
    return {
        "status": "success",
        "total_parents": len(parents),
        "total_children": len(children_with_embeddings),
        "embedding_dimension": embedding_dim,
        "readable_pages": len(readable_pages),
        "scanned_pages": len(scanned_pages),
        "qdrant_points_indexed": qdrant_points_indexed,
        "qdrant_collection": qdrant_collection,
        "output_path": str(output_path),
    }

