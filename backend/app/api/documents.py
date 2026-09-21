"""
api/documents.py

Document upload and status endpoints.

Endpoints:
    POST /documents/upload     Upload a PDF and start background extraction
    GET  /documents            List all documents (dev: all users)
    GET  /documents/{id}       Get status and metadata for one document
    DELETE /documents/{id}     Delete a document and all associated data
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
from app.models.session import Session as ChatSession
from app.models.message import Message
from app.models.quiz import Quiz
from app.models.quiz_attempt import QuizAttempt
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentSummary,
    DocumentDetail,
    UpdateDocumentRequest,
)
from app.services.pipeline_service import run_ingestion_pipeline
from app.services.document_service import (
    get_document_by_id,
    get_all_documents,
    get_documents_by_user,
    update_document_status,
    document_to_summary,
    document_to_detail,
)
from app.services.qdrant_service import delete_document_vectors
from app.api.auth import get_current_user, require_authenticated_user
from app.services.supabase_storage_service import (
    is_supabase_configured,
    upload_document_file,
    download_document_file,
    delete_document_file,
)

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

    If the local temporary PDF is missing (e.g. cold container / server restart),
    it is downloaded from private Supabase Storage on-demand.
    Upon successful extraction, temporary local PDFs are cleaned up to prevent
    ephemeral disk bloat in production.
    """
    db = SessionLocal()
    local_path = Path(file_path)

    try:
        # If local file does not exist, fetch from Supabase Storage
        if not local_path.exists():
            doc = get_document_by_id(db, document_id)
            if (
                doc
                and doc.file_path
                and doc.file_path.startswith("documents/")
                and is_supabase_configured()
            ):
                logger.info(
                    "Local processing file missing; downloading from Supabase Storage: %s",
                    doc.file_path,
                )
                pdf_bytes = download_document_file(doc.file_path)
                upload_dir = Path(settings.UPLOAD_DIR)
                upload_dir.mkdir(parents=True, exist_ok=True)
                local_path = upload_dir / f"{document_id}.pdf"
                local_path.write_bytes(pdf_bytes)
            else:
                raise FileNotFoundError(
                    f"PDF file not found locally or in storage: {file_path}"
                )

        result = run_ingestion_pipeline(
            document_id=document_id,
            file_path=str(local_path),
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
        if is_supabase_configured():
            doc = get_document_by_id(db, document_id)
            if doc and doc.file_path and doc.file_path.startswith("documents/"):
                try:
                    delete_document_file(doc.file_path)
                    logger.info("Cleaned up Supabase storage object for failed document %s", document_id)
                except Exception as cleanup_exc:
                    logger.warning("Notice cleaning Supabase object on failure: %s", cleanup_exc)
    except Exception as exc:
        logger.exception("Unexpected pipeline error for document %s", document_id)
        update_document_status(
            db,
            document_id,
            status="FAILED",
            error_message="An unexpected error occurred during processing.",
        )
        if is_supabase_configured():
            doc = get_document_by_id(db, document_id)
            if doc and doc.file_path and doc.file_path.startswith("documents/"):
                try:
                    delete_document_file(doc.file_path)
                    logger.info("Cleaned up Supabase storage object for failed document %s", document_id)
                except Exception as cleanup_exc:
                    logger.warning("Notice cleaning Supabase object on failure: %s", cleanup_exc)
    finally:
        # Clean up temporary local PDF cache when Supabase Storage is active
        if is_supabase_configured() and local_path.exists():
            try:
                local_path.unlink(missing_ok=True)
                logger.info("Cleaned up temporary local PDF cache: %s", local_path)
            except OSError as exc:
                logger.warning("Notice cleaning temporary local PDF %s: %s", local_path, exc)
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

    Validates the file, uploads it persistently to Supabase Storage (if configured),
    caches it to temporary disk for background extraction, creates a database record
    with status PROCESSING, and starts background extraction.

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
    temp_file_path = upload_dir / f"{document_id}.pdf"

    # Save to local temporary processing path
    try:
        temp_file_path.write_bytes(content)
    except OSError as exc:
        logger.error("Failed to save temporary uploaded file: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save the uploaded file.")

    # Upload to Supabase Storage if configured
    storage_path = None
    if is_supabase_configured():
        try:
            storage_path = upload_document_file(
                user_id=current_user,
                document_id=document_id,
                content=content,
            )
        except Exception as exc:
            temp_file_path.unlink(missing_ok=True)
            logger.error("Failed to upload document to Supabase Storage: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Failed to upload document to persistent storage.",
            )

    doc_file_path = storage_path if storage_path else str(temp_file_path)

    doc = Document(
        id=document_id,
        user_id=current_user,
        filename=file.filename,
        subject=subject,
        file_path=doc_file_path,
        status="PROCESSING",
    )

    try:
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception as exc:
        temp_file_path.unlink(missing_ok=True)
        if storage_path and is_supabase_configured():
            try:
                delete_document_file(storage_path)
            except Exception:
                pass
        logger.error("Database error saving document: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create document record.")

    background_tasks.add_task(
        process_document_background,
        document_id,
        str(temp_file_path),
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


@router.delete("/{document_id}", status_code=200)
def delete_document(
    document_id: str,
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    DELETE /documents/{document_id} — Permanently delete a document.

    Deletion order (respecting FK dependencies, no ORM cascade configured):
      1. Verify authenticated ownership.
      2. Delete quiz_attempts for quizzes belonging to this document.
      3. Delete quizzes belonging to this document.
      4. Delete messages for sessions belonging to this document.
      5. Delete sessions belonging to this document.
      6. Delete uploaded PDF file from data/uploads/.
      7. Delete Qdrant vectors for this document (filtered by document_id AND user_id).
      8. Delete document row from PostgreSQL.

    External resource cleanup (file + Qdrant) is performed before the DB row is
    deleted. If either fails, a warning is logged and deletion continues so we do
    not leave an orphaned DB row. The error is included in the response.

    Security:
      - user_id is derived from get_current_user() — never trusted from the request.
      - Returns 403 if the document belongs to a different user.
    """
    # Step 1: Verify ownership
    doc = get_document_by_id(db, document_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_id}' not found.",
        )
    if doc.user_id != current_user:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete this document.",
        )

    cleanup_warnings: List[str] = []

    # Step 2: Delete quiz_attempts for this document's quizzes
    quiz_ids = [
        q.id for q in db.query(Quiz.id).filter(Quiz.document_id == document_id).all()
    ]
    if quiz_ids:
        deleted_attempts = (
            db.query(QuizAttempt)
            .filter(QuizAttempt.quiz_id.in_(quiz_ids))
            .delete(synchronize_session="fetch")
        )
        logger.info(
            "Deleted %d quiz_attempt(s) for document %s",
            deleted_attempts,
            document_id,
        )

    # Step 3: Delete quizzes
    deleted_quizzes = (
        db.query(Quiz)
        .filter(Quiz.document_id == document_id)
        .delete(synchronize_session="fetch")
    )
    logger.info("Deleted %d quiz(es) for document %s", deleted_quizzes, document_id)

    # Step 4: Delete messages for this document's sessions
    session_ids = [
        s.id
        for s in db.query(ChatSession.id).filter(ChatSession.document_id == document_id).all()
    ]
    if session_ids:
        deleted_messages = (
            db.query(Message)
            .filter(Message.session_id.in_(session_ids))
            .delete(synchronize_session="fetch")
        )
        logger.info(
            "Deleted %d message(s) for document %s",
            deleted_messages,
            document_id,
        )

    # Step 5: Delete sessions
    deleted_sessions = (
        db.query(ChatSession)
        .filter(ChatSession.document_id == document_id)
        .delete(synchronize_session="fetch")
    )
    logger.info("Deleted %d session(s) for document %s", deleted_sessions, document_id)

    db.commit()

    # Step 6: Delete from Supabase Storage if configured
    if doc.file_path and doc.file_path.startswith("documents/") and is_supabase_configured():
        try:
            delete_document_file(doc.file_path)
            logger.info("Deleted document from Supabase Storage: %s", doc.file_path)
        except Exception as exc:
            msg = f"Supabase storage cleanup notice: {exc}"
            logger.warning(msg)
            cleanup_warnings.append(msg)

    # Step 6b: Delete uploaded PDF, processed JSON, and document temporary files from disk
    upload_dir = Path(settings.UPLOAD_DIR)
    proc_dir = Path(settings.PROCESSED_DIR)

    paths_to_clean = {
        upload_dir / f"{document_id}.pdf",
        proc_dir / f"{document_id}.json",
    }
    if doc.file_path and not doc.file_path.startswith("documents/"):
        paths_to_clean.add(Path(doc.file_path))

    # Clean up any temporary files matching {document_id}* in upload_dir or proc_dir
    if upload_dir.exists():
        for temp_f in upload_dir.glob(f"{document_id}*"):
            paths_to_clean.add(temp_f)
    if proc_dir.exists():
        for temp_f in proc_dir.glob(f"{document_id}*"):
            paths_to_clean.add(temp_f)

    for p in paths_to_clean:
        try:
            if p.exists() and p.is_file():
                # Safety check: only delete files residing within upload_dir or proc_dir
                res_p = p.resolve()
                if upload_dir.resolve() in res_p.parents or proc_dir.resolve() in res_p.parents:
                    p.unlink(missing_ok=True)
                    logger.info("Deleted document file: %s", p)
        except OSError as exc:
            msg = f"Failed to delete document file '{p}': {exc}"
            logger.error(msg)
            cleanup_warnings.append(msg)

    # Step 7: Delete Qdrant vectors (filtered by document_id AND user_id for safety)
    try:
        delete_document_vectors(document_id=document_id, user_id=current_user)
    except RuntimeError as exc:
        msg = f"Qdrant vector cleanup warning: {exc}"
        logger.error(msg)
        cleanup_warnings.append(msg)

    # Step 8: Delete document row
    db.delete(doc)
    db.commit()

    logger.info(
        "Document %s deleted by user %s. Warnings: %s",
        document_id,
        current_user,
        cleanup_warnings or "none",
    )

    response: dict = {"deleted": True, "document_id": document_id}
    if cleanup_warnings:
        response["warnings"] = cleanup_warnings
    return response


@router.patch("/{document_id}", response_model=DocumentSummary)
async def update_document(
    document_id: str,
    payload: UpdateDocumentRequest,
    current_user: str = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> DocumentSummary:
    """
    PATCH /documents/{document_id} — Update document metadata (filename, subject).

    Requirements:
      - Authenticated user required.
      - Ownership verification required (403 if document belongs to a different user).
      - Rejects blank values (empty or whitespace only).
      - Trims surrounding whitespace.
      - Filename max length: 60 characters.
      - Subject max length: 40 characters.
      - Updates only filename and subject.
      - Strictly preserves document_id, page_count, status, file_path, and Qdrant data.
    """
    doc = get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.user_id != current_user:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to edit this document.",
        )

    if payload.filename is None and payload.subject is None:
        raise HTTPException(
            status_code=400,
            detail="At least one field (filename or subject) must be provided.",
        )

    if payload.filename is not None:
        clean_filename = payload.filename.strip()
        if not clean_filename:
            raise HTTPException(
                status_code=400,
                detail="Filename cannot be blank.",
            )
        if len(clean_filename) > 60:
            raise HTTPException(
                status_code=400,
                detail="Filename cannot exceed 60 characters.",
            )
        doc.filename = clean_filename

    if payload.subject is not None:
        clean_subject = payload.subject.strip()
        if not clean_subject:
            raise HTTPException(
                status_code=400,
                detail="Subject cannot be blank.",
            )
        if len(clean_subject) > 40:
            raise HTTPException(
                status_code=400,
                detail="Subject cannot exceed 40 characters.",
            )
        doc.subject = clean_subject

    db.commit()
    db.refresh(doc)

    logger.info(
        "Document %s updated by user %s: filename='%s', subject='%s'",
        document_id,
        current_user,
        doc.filename,
        doc.subject,
    )

    return document_to_summary(doc)


