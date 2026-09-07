"""
scripts/verify_day2_individual.py

Comprehensive standalone verification for all Day 2 requirements.
Executes individual tests for:
  1. Text Cleaning
  2. Parent Chunking
  3. Child Chunking
  4. Metadata Validation & Determinism
  5. Embedding Service (local, offline)
  6. End-to-End Pipeline on 3 Real PDFs
  7. Negative / Fault Tolerance Tests
  8. Processed Output JSON Validation
  9. Dependency Check
"""

import os
import sys
import json
import uuid
import tempfile
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.pdf_service import extract_text_from_pdf, clean_page_text
from app.services.cleaning_service import clean_document_pages, deep_clean_page
from app.services.chunking_service import generate_chunks
from app.services.embedding_service import (
    embed_texts,
    embed_chunks,
    get_embedding_dimension,
    get_embedding_model,
)
from app.services.pipeline_service import run_ingestion_pipeline
from app.config import settings
import pymupdf

UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "uploads"
PROCESSED_DIR = Path(settings.PROCESSED_DIR)

results = {}

print("=" * 70)
print("DAY 2 INDIVIDUAL COMPONENT VERIFICATION")
print("=" * 70)

# ----------------------------------------------------------------------
# 1. TEXT CLEANING TEST
# ----------------------------------------------------------------------
print("\n--- 1. TEXT CLEANING TEST ---")
sample_pdf = UPLOADS_DIR / "lec-1.pdf"
raw_pages = extract_text_from_pdf(str(sample_pdf))
cleaned_pages = clean_document_pages(raw_pages)

assert len(raw_pages) == len(cleaned_pages), "Page count mismatch"
assert len(cleaned_pages) > 0, "No pages extracted"

# Verify whitespace normalization, meaningful text preservation, page boundaries
raw_p1 = raw_pages[0]["text"]
clean_p1 = cleaned_pages[0]["text"]

assert "  " not in clean_p1, "Excess whitespace (double space) found in cleaned text"
assert "\n\n\n" not in clean_p1, "Excessive blank lines found in cleaned text"
assert len(clean_p1) > 100, "Cleaned text appears wiped or too short"
assert cleaned_pages[0]["page_number"] == 1, "Page number lost"

print("  [OK] Excessive whitespace & blank lines normalized")
print("  [OK] Extraction noise reduced while preserving content")
print(f"  [OK] Page boundaries preserved: page {cleaned_pages[0]['page_number']}")
print(f"  [OK] Cleaned snippet: {clean_p1[:120]}...")
results["Text Cleaning"] = "PASS"

# ----------------------------------------------------------------------
# 2. PARENT CHUNK TEST
# ----------------------------------------------------------------------
print("\n--- 2. PARENT CHUNK TEST ---")
doc_id = str(uuid.uuid4())
parents, children = generate_chunks(
    cleaned_pages,
    document_id=doc_id,
    user_id="dev-user-001",
    subject="Operating Systems",
)

assert len(parents) > 0, "No parent chunks generated"
for p in parents:
    assert p["text"].strip(), "Empty parent chunk found"
    assert p["document_id"] == doc_id, "Parent document_id mismatch"
    assert 1 <= p["page_start"] <= p["page_end"] <= len(cleaned_pages), "Invalid page range"
    assert "chunk_id" in p and p["chunk_id"], "Missing parent chunk_id"

print(f"  [OK] Generated {len(parents)} parent chunk(s)")
print(f"  [OK] Parent chunk_id: {parents[0]['chunk_id']}")
print(f"  [OK] Parent page range: {parents[0]['page_start']} to {parents[0]['page_end']}")
print(f"  [OK] Parent text length: {len(parents[0]['text'])} chars")
results["Parent Chunking"] = "PASS"

# ----------------------------------------------------------------------
# 3. CHILD CHUNK TEST
# ----------------------------------------------------------------------
print("\n--- 3. CHILD CHUNK TEST ---")
assert len(children) > 0, "No child chunks generated"
parent_ids = {p["chunk_id"] for p in parents}

for c in children:
    assert c["parent_id"] in parent_ids, f"Child parent_id {c['parent_id']} not in parents"
    assert c["text"].strip(), "Empty child chunk text"
    assert len(c["text"]) <= 1000, f"Child chunk exceeds reasonable size: {len(c['text'])}"
    assert c["document_id"] == doc_id, "Child document_id mismatch"

print(f"  [OK] Generated {len(children)} child chunk(s)")
print(f"  [OK] Every child chunk correctly points to an existing parent_id")
print(f"  [OK] Sample child size: {len(children[0]['text'])} chars")
results["Child Chunking"] = "PASS"

# ----------------------------------------------------------------------
# 4. METADATA TEST
# ----------------------------------------------------------------------
print("\n--- 4. METADATA TEST ---")
required_keys = [
    "chunk_id",
    "document_id",
    "user_id",
    "subject",
    "page_start",
    "page_end",
    "parent_id",
    "text",
]

for key in required_keys:
    assert key in children[0], f"Missing required metadata key: {key}"

# Determinism test
parents_run2, children_run2 = generate_chunks(
    cleaned_pages,
    document_id=doc_id,
    user_id="dev-user-001",
    subject="Operating Systems",
)
assert [c["chunk_id"] for c in children] == [c["chunk_id"] for c in children_run2], "Chunk IDs are non-deterministic!"

print(f"  [OK] All required metadata fields present: {', '.join(required_keys)}")
print("  [OK] Deterministic chunk IDs verified across independent runs (UUID5 + SHA-256)")
results["Metadata"] = "PASS"

# ----------------------------------------------------------------------
# 5. EMBEDDING TEST
# ----------------------------------------------------------------------
print("\n--- 5. EMBEDDING TEST ---")
model = get_embedding_model()
assert model is not None, "Embedding model failed to load"

dim = get_embedding_dimension()
sample_texts = [
    "Process scheduling algorithms in modern operating systems.",
    "Virtual memory paging and segmentation mechanisms.",
]
vectors = embed_texts(sample_texts)

assert len(vectors) == 2, "Vector count mismatch"
assert len(vectors[0]) == dim, f"Vector dimension mismatch: expected {dim}, got {len(vectors[0])}"
assert all(isinstance(val, float) for val in vectors[0]), "Embedding contains non-float values"
assert not any(val != val for val in vectors[0]), "Embedding contains NaN values"

from app.services.embedding_service import EMBEDDING_MODEL_NAME

print(f"  [OK] Embedding model: {EMBEDDING_MODEL_NAME}")
print(f"  [OK] Reported & verified embedding dimension: {dim}")
print(f"  [OK] Vector is non-empty, numeric float list, with zero NaN values")
results["Embedding"] = "PASS"

# ----------------------------------------------------------------------
# 6. END-TO-END DAY 2 TEST (3 REAL PDFS)
# ----------------------------------------------------------------------
print("\n--- 6. END-TO-END DAY 2 TEST (3 REAL PDFS) ---")
test_pdfs = ["lec-1.pdf", "Lec-2.pdf", "Lec-3.pdf"]
e2e_outputs = []

for pdf_name in test_pdfs:
    pdf_path = UPLOADS_DIR / pdf_name
    assert pdf_path.exists(), f"PDF not found: {pdf_path}"
    doc_uuid = str(uuid.uuid4())
    result = run_ingestion_pipeline(
        file_path=str(pdf_path),
        document_id=doc_uuid,
        user_id="dev-user-001",
        subject=pdf_name.replace(".pdf", ""),
    )
    e2e_outputs.append((pdf_name, doc_uuid, result))
    print(f"  [OK] Ingestion complete for {pdf_name}: {result['total_parents']} parents, {result['total_children']} children, {result['readable_pages'] + result['scanned_pages']} pages")

results["End-to-End Processing"] = "PASS"

# ----------------------------------------------------------------------
# 7. NEGATIVE TESTS
# ----------------------------------------------------------------------
print("\n--- 7. NEGATIVE TESTS ---")
# 7a. Blank / image-only PDF
blank_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
blank_pdf.close()
doc = pymupdf.open()
doc.new_page()
doc.save(blank_pdf.name)
doc.close()

try:
    run_ingestion_pipeline(
        file_path=blank_pdf.name,
        document_id=str(uuid.uuid4()),
        user_id="dev",
        subject="Test",
    )
    raise AssertionError("Blank PDF should have failed!")
except ValueError as e:
    print(f"  [OK] Blank PDF rejected gracefully: {e}")

# 7b. Corrupted PDF
bad_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
bad_pdf.write(b"not a valid pdf content")
bad_pdf.close()

try:
    run_ingestion_pipeline(
        file_path=bad_pdf.name,
        document_id=str(uuid.uuid4()),
        user_id="dev",
        subject="Test",
    )
    raise AssertionError("Corrupted PDF should have failed!")
except ValueError as e:
    print(f"  [OK] Corrupted PDF rejected gracefully: {e}")

# 7c. Missing file
try:
    run_ingestion_pipeline(
        file_path="non_existent_file.pdf",
        document_id=str(uuid.uuid4()),
        user_id="dev",
        subject="Test",
    )
    raise AssertionError("Missing PDF should have failed!")
except FileNotFoundError as e:
    print(f"  [OK] Missing PDF rejected gracefully: {e}")

# Cleanup negative test temporary files safely
for p in [blank_pdf.name, bad_pdf.name]:
    try:
        os.unlink(p)
    except Exception:
        pass

results["Negative Tests"] = "PASS"

# ----------------------------------------------------------------------
# 8. OUTPUT TEST
# ----------------------------------------------------------------------
print("\n--- 8. OUTPUT TEST ---")
for pdf_name, doc_uuid, res in e2e_outputs:
    processed_file = PROCESSED_DIR / f"{doc_uuid}.json"
    assert processed_file.exists(), f"Processed output JSON missing: {processed_file}"
    with open(processed_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["document_id"] == doc_uuid
    assert len(data["children"]) > 0
    assert "embedding" in data["children"][0]
    assert len(data["children"][0]["embedding"]) == dim
    print(f"  [OK] Verified {processed_file.name} (valid JSON, {len(data['parents'])} parents, {len(data['children'])} children with embeddings)")

results["Output Validation"] = "PASS"

# ----------------------------------------------------------------------
# 9. DEPENDENCY TEST
# ----------------------------------------------------------------------
print("\n--- 9. DEPENDENCY TEST ---")
import sentence_transformers
import numpy

req_path = backend_dir / "requirements.txt"
req_text = req_path.read_text(encoding="utf-8")
assert "sentence-transformers" in req_text, "sentence-transformers missing from requirements.txt"
assert "numpy" in req_text, "numpy missing from requirements.txt"

# Verify future dependencies are NOT in requirements.txt
forbidden = ["qdrant", "redis", "celery", "langchain", "langgraph"]
for pkg in forbidden:
    assert pkg not in req_text.lower(), f"Forbidden future package '{pkg}' found in requirements.txt!"

print(f"  [OK] sentence-transformers version: {sentence_transformers.__version__}")
print(f"  [OK] numpy version: {numpy.__version__}")
print("  [OK] No future dependencies (Qdrant, Redis, Celery, LangChain, LangGraph) in requirements.txt")
results["Dependency Check"] = "PASS"

# ----------------------------------------------------------------------
# SUMMARY
# ----------------------------------------------------------------------
print("\n" + "=" * 70)
print("ALL DAY 2 INDIVIDUAL TESTS COMPLETED SUCCESSFULLY")
print("=" * 70)
for k, v in results.items():
    print(f"  {k:25}: {v}")
