"""
services/document_service.py

Database operations for documents.

Route handlers call these functions instead of using SQLAlchemy directly.
This keeps route handlers thin and makes the DB layer testable independently.
"""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.document import Document
from app.schemas.document import DocumentSummary, DocumentDetail

logger = logging.getLogger(__name__)


def get_document_by_id(db: Session, document_id: str) -> Optional[Document]:
    """Return a Document ORM object by ID, or None if not found."""
    return db.query(Document).filter(Document.id == document_id).first()


def get_all_documents(db: Session) -> List[Document]:
    """Return all documents, newest first."""
    return (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .all()
    )


def update_document_status(
    db: Session,
    document_id: str,
    status: str,
    page_count: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Update a document's processing status.

    Called by the background task after extraction completes or fails.
    Does not raise if the document is not found (logs a warning instead)
    so a crashed background task does not mask the original error.
    """
    doc = get_document_by_id(db, document_id)
    if doc is None:
        logger.warning(
            "update_document_status: document %s not found", document_id
        )
        return

    doc.status = status

    if page_count is not None:
        doc.page_count = page_count

    if error_message is not None:
        doc.error_message = error_message

    db.commit()
    logger.info("Document %s status → %s", document_id, status)


def document_to_summary(doc: Document) -> DocumentSummary:
    """Map a Document ORM object to a DocumentSummary schema."""
    return DocumentSummary(
        document_id=doc.id,
        filename=doc.filename,
        subject=doc.subject,
        status=doc.status,
        page_count=doc.page_count,
    )


def document_to_detail(doc: Document) -> DocumentDetail:
    """Map a Document ORM object to a DocumentDetail schema."""
    return DocumentDetail(
        document_id=doc.id,
        filename=doc.filename,
        subject=doc.subject,
        status=doc.status,
        page_count=doc.page_count,
        error_message=doc.error_message,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )
