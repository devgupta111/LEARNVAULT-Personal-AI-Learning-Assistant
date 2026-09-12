"""
api/documents.py

Document upload and status endpoints.

Endpoints:
    POST /documents/upload     Upload a PDF and start background extraction
    GET  /documents            List all documents (dev: all users)
    GET  /documents/{id}       Get status and metadata for one document
"""

import uuid
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db, SessionLocal
from app.models.document import Document
from app.schemas.document import DocumentUploadResponse, DocumentSummary, DocumentDetail
from app.services.pdf_service import extract_text_from_pdf, is_document_fully_scanned
from app.services.pipeline_service import run_ingestion_pipeline
from app.services.document_service import (
    get_document_by_id,
    get_all_documents,
    get_documents_by_user,
    update_document_status,
    document_to_summary,
    document_to_detail,
)
from app.api.auth import get_current_user

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_MIME_TYPES = {"application/pdf"}


def process_document_background(
    document_id: str,
    file_path: str,
    subject: str = "General",
    user_id: str = "dev-user",
) -> None:
    """
    Background task: run the full Day 2 ingestion pipeline.

    Calls run_ingestion_pipeline() which handles:
      - PDF extraction (Day 1 pdf_service)
      - Deep text cleaning (Day 2 cleaning_service)
      - Parent + child chunking (Day 2 chunking_service)
      - Embedding generation (Day 2 embedding_service)
      - Local JSON output to data/processed/

    This function creates its own database session because FastAPI background
    tasks run after the HTTP response is sent.
    SessionLocal is a module-level variable so tests can patch it.
    """
    db = SessionLocal()
    try:
        result = run_ingestion_pipeline(
            document_id=document_id,
            file_path=file_path,
            subject=subject,
            user_id=user_id,
        )
        update_document_status(
            db,
            document_id,
            status="READY",
            page_count=result["readable_pages"] + result["scanned_pages"],
        )
        logger.info(
            "Document %s -> READY (%d parents, %d children, dim=%d)",
            document_id,
            result["total_parents"],
            result["total_children"],
            result["embedding_dimension"],
        )

    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.error("Pipeline error for document %s: %s", document_id, exc)
        update_document_status(
            db,
            document_id,
            status="FAILED",
            error_message=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected pipeline error for document %s", document_id)
        update_document_status(
            db,
            document_id,
            status="FAILED",
            error_message="An unexpected error occurred during processing.",
        )
    finally:
        db.close()


@router.post("/upload", status_code=202, response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    subject: str = Form(default="General"),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a PDF document.

    Validates the file, saves it to disk, creates a database record with
    status PROCESSING, and starts background text extraction.

    Returns HTTP 202 immediately so the client does not wait for extraction.
    Derives user_id strictly from the authenticated token/dependency.
    """
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{suffix}'. Only PDF files are accepted.",
        )

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid content type. File must be a PDF (application/pdf).",
        )

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File is too large. "
                f"Maximum allowed size is {settings.MAX_FILE_SIZE_MB} MB."
            ),
        )

    document_id = str(uuid.uuid4())

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{document_id}.pdf"

    try:
        file_path.write_bytes(content)
    except OSError as exc:
        logger.error("Failed to save uploaded file: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save the uploaded file.")

    doc = Document(
        id=document_id,
        user_id=current_user,
        filename=file.filename,
        subject=subject,
        file_path=str(file_path),
        status="PROCESSING",
    )

    try:
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception as exc:
        file_path.unlink(missing_ok=True)
        logger.error("Database error saving document: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create document record.")

    background_tasks.add_task(
        process_document_background,
        document_id,
        str(file_path),
        subject,
        current_user,
    )

    return DocumentUploadResponse(document_id=document_id, status="PROCESSING")


@router.get("/", response_model=List[DocumentSummary])
def list_documents(
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[DocumentSummary]:
    """
    List uploaded documents for the authenticated user.
    """
    documents = get_documents_by_user(db, current_user)
    return [document_to_summary(doc) for doc in documents]


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetail:
    """Get status and metadata for a specific document with user ownership check."""
    doc = get_document_by_id(db, document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_id}' not found.",
        )
    if doc.user_id != current_user:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this document.",
        )
    return document_to_detail(doc)

