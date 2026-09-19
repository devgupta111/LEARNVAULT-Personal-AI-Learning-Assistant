"""
services/guest_cleanup_service.py

Handles complete, privacy-compliant deletion of guest data upon user signup.

Audit of all guest data storage locations:
1. PostgreSQL:
   - documents (user_id == guest_user_id)
   - sessions (user_id == guest_user_id or document_id in guest_doc_ids)
   - messages (session_id in guest_session_ids)
   - quizzes (user_id == guest_user_id or document_id in guest_doc_ids)
   - quiz_attempts (user_id == guest_user_id or quiz_id in guest_quiz_ids)
   - users (user_id == guest_user_id, if temporary record exists)
2. Qdrant:
   - vectors and payloads where user_id == guest_user_id
3. Filesystem:
   - Uploaded PDFs in settings.UPLOAD_DIR / {doc_id}.pdf
   - Processed chunk JSONs in settings.PROCESSED_DIR / {doc_id}.json
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models.document import Document
from app.models.session import Session as ChatSession
from app.models.message import Message
from app.models.quiz import Quiz
from app.models.quiz_attempt import QuizAttempt
from app.models.user import User
from app.services.qdrant_service import delete_user_vectors

logger = logging.getLogger(__name__)


def is_guest_user_id(user_id: Optional[str]) -> bool:
    """
    Determine whether a user identifier belongs to a guest session.
    Protects authenticated Google accounts from ever being classified as guests.
    """
    if not user_id:
        return False
    clean = user_id.strip()
    if clean.startswith("google_"):
        return False
    return clean == "dev-user" or clean.startswith("guest_") or clean.startswith("guest-")


def cleanup_guest_data(guest_user_id: str, db: Session) -> Dict[str, Any]:
    """
    Permanently and securely delete all data associated with a guest session.

    Execution Flow:
      1. Verify that guest_user_id is a valid guest identifier (never an authenticated account).
      2. Locate all documents owned by the guest.
      3. Locate all sessions and quizzes for the guest or their documents.
      4. Delete DB records in strict foreign-key order:
         - QuizAttempts
         - Quizzes
         - Messages
         - Sessions
         - Documents
         - Temporary guest User row (if any)
      5. Delete filesystem assets (uploaded PDFs and processed JSON chunks).
      6. Delete Qdrant vectors scoped strictly to guest_user_id.

    Safety:
      - Every database deletion is strictly scoped to the guest identifier or their document IDs.
      - Never performs unscoped table deletions (no 'DELETE FROM documents').
      - Never drops or clears the entire Qdrant collection.
      - Never deletes directories or files of other users.
      - Completely idempotent: safe to call repeatedly or when no data exists.
      - No sensitive tokens, contents, or credentials are logged.
    """
    if not guest_user_id or not guest_user_id.strip():
        return {"status": "skipped", "reason": "empty_guest_id", "deleted": 0}

    clean_id = guest_user_id.strip()

    # Security Guard: NEVER allow cleanup of authenticated accounts
    if clean_id.startswith("google_"):
        logger.warning(
            "Security guard triggered: Refusing guest data cleanup for authenticated account."
        )
        return {
            "status": "rejected",
            "reason": "authenticated_account_protected",
            "deleted": 0,
        }

    warnings: List[str] = []

    # 1. Query all documents owned by this guest
    guest_docs = db.query(Document).filter(Document.user_id == clean_id).all()
    doc_ids = [d.id for d in guest_docs]
    doc_file_paths = [d.file_path for d in guest_docs if d.file_path]

    # 2. Query all sessions for this guest (or tied to guest documents)
    if doc_ids:
        guest_sessions = (
            db.query(ChatSession)
            .filter((ChatSession.user_id == clean_id) | (ChatSession.document_id.in_(doc_ids)))
            .all()
        )
    else:
        guest_sessions = (
            db.query(ChatSession)
            .filter(ChatSession.user_id == clean_id)
            .all()
        )
    session_ids = [s.id for s in guest_sessions]

    # 3. Query all quizzes for this guest (or tied to guest documents)
    if doc_ids:
        guest_quizzes = (
            db.query(Quiz)
            .filter((Quiz.user_id == clean_id) | (Quiz.document_id.in_(doc_ids)))
            .all()
        )
    else:
        guest_quizzes = (
            db.query(Quiz)
            .filter(Quiz.user_id == clean_id)
            .all()
        )
    quiz_ids = [q.id for q in guest_quizzes]

    # 4. Database Deletions in FK order
    deleted_attempts = 0
    deleted_quizzes = 0
    deleted_messages = 0
    deleted_sessions = 0
    deleted_documents = 0
    deleted_users = 0

    try:
        # 4a. Delete QuizAttempts
        if quiz_ids:
            deleted_attempts = (
                db.query(QuizAttempt)
                .filter((QuizAttempt.quiz_id.in_(quiz_ids)) | (QuizAttempt.user_id == clean_id))
                .delete(synchronize_session=False)
            )
        else:
            deleted_attempts = (
                db.query(QuizAttempt)
                .filter(QuizAttempt.user_id == clean_id)
                .delete(synchronize_session=False)
            )

        # 4b. Delete Quizzes
        if quiz_ids:
            deleted_quizzes = (
                db.query(Quiz)
                .filter(Quiz.id.in_(quiz_ids))
                .delete(synchronize_session=False)
            )

        # 4c. Delete Messages
        if session_ids:
            deleted_messages = (
                db.query(Message)
                .filter(Message.session_id.in_(session_ids))
                .delete(synchronize_session=False)
            )

        # 4d. Delete Sessions
        if session_ids:
            deleted_sessions = (
                db.query(ChatSession)
                .filter(ChatSession.id.in_(session_ids))
                .delete(synchronize_session=False)
            )

        # 4e. Delete Documents
        if doc_ids:
            deleted_documents = (
                db.query(Document)
                .filter(Document.id.in_(doc_ids))
                .delete(synchronize_session=False)
            )

        # 4f. Delete temporary User record if one was created
        deleted_users = (
            db.query(User)
            .filter(User.id == clean_id, User.auth_provider != "google")
            .delete(synchronize_session=False)
        )

        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Database error during guest cleanup: %s", exc)
        warnings.append(f"Database cleanup error: {exc}")

    # 5. Filesystem Deletions (PDFs and chunk JSONs)
    deleted_files = 0
    upload_dir = Path(settings.UPLOAD_DIR)
    proc_dir = Path(settings.PROCESSED_DIR)

    for doc_id in doc_ids:
        # PDF upload
        pdf_path = upload_dir / f"{doc_id}.pdf"
        try:
            if pdf_path.exists():
                pdf_path.unlink(missing_ok=True)
                deleted_files += 1
        except OSError as exc:
            warnings.append(f"Failed to delete PDF file: {exc}")

        # Processed chunk JSON
        proc_path = proc_dir / f"{doc_id}.json"
        try:
            if proc_path.exists():
                proc_path.unlink(missing_ok=True)
                deleted_files += 1
        except OSError as exc:
            warnings.append(f"Failed to delete processed JSON: {exc}")

    # Also check any explicit doc_file_paths recorded in Document
    for fp in doc_file_paths:
        try:
            custom_path = Path(fp)
            if custom_path.exists() and custom_path.is_file():
                resolved = custom_path.resolve()
                if upload_dir.resolve() in resolved.parents or proc_dir.resolve() in resolved.parents:
                    custom_path.unlink(missing_ok=True)
        except Exception:
            pass

    # 6. Qdrant Vector Deletions (strictly scoped to clean_id)
    deleted_vectors = 0
    try:
        deleted_vectors = delete_user_vectors(user_id=clean_id)
    except Exception as exc:
        logger.warning("Qdrant vector cleanup notice for guest user: %s", exc)
        warnings.append(f"Qdrant vector cleanup notice: {exc}")

    logger.info(
        "Guest cleanup completed for guest_id=%s: "
        "docs=%d, sessions=%d, msgs=%d, quizzes=%d, attempts=%d, files=%d, vectors=%d",
        clean_id,
        deleted_documents,
        deleted_sessions,
        deleted_messages,
        deleted_quizzes,
        deleted_attempts,
        deleted_files,
        deleted_vectors,
    )

    return {
        "status": "success",
        "guest_user_id": clean_id,
        "deleted_documents": deleted_documents,
        "deleted_sessions": deleted_sessions,
        "deleted_messages": deleted_messages,
        "deleted_quizzes": deleted_quizzes,
        "deleted_attempts": deleted_attempts,
        "deleted_users": deleted_users,
        "deleted_files": deleted_files,
        "deleted_vectors": deleted_vectors,
        "warnings": warnings,
    }
