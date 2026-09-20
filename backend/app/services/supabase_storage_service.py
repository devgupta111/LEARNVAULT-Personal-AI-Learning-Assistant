"""
services/supabase_storage_service.py

Persistent storage backend using Supabase Storage (private bucket).
Used in production on Render where the container filesystem is ephemeral.

Security & Architecture:
- Bucket: learnvault-documents (PRIVATE)
- Keys: SUPABASE_URL + SUPABASE_SECRET_KEY (backend-only, never exposed to client)
- Never logs secret keys or sensitive tokens.
- Deterministic path: documents/{user_id}/{document_id}.pdf
- Local filesystem (data/uploads) acts purely as an ephemeral processing cache.
"""

import logging
from typing import Optional, List, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)

# Cached Supabase client instance
_supabase_client = None


def is_supabase_configured() -> bool:
    """Check whether Supabase Storage credentials are configured."""
    return bool(
        settings.SUPABASE_URL
        and settings.SUPABASE_URL.strip()
        and settings.SUPABASE_SECRET_KEY
        and settings.SUPABASE_SECRET_KEY.strip()
    )


def get_storage_client():
    """
    Return a cached Supabase Client instance initialized with SUPABASE_SECRET_KEY.
    Raises RuntimeError if Supabase credentials are missing.
    """
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    if not is_supabase_configured():
        raise RuntimeError(
            "Supabase Storage is not configured. SUPABASE_URL and SUPABASE_SECRET_KEY are required."
        )

    try:
        from supabase import create_client, Client
        _supabase_client = create_client(
            settings.SUPABASE_URL.strip(),
            settings.SUPABASE_SECRET_KEY.strip(),
        )
        return _supabase_client
    except Exception as exc:
        logger.error("Failed to initialize Supabase client: %s", exc)
        raise RuntimeError(f"Could not initialize Supabase Storage client: {exc}") from exc


def reset_storage_client() -> None:
    """Reset the cached client instance (primarily for unit tests)."""
    global _supabase_client
    _supabase_client = None


def build_storage_path(user_id: str, document_id: str) -> str:
    """
    Generate a deterministic object path within the private bucket:
    documents/{user_id}/{document_id}.pdf
    """
    clean_user = user_id.strip().replace(" ", "_")
    clean_doc = document_id.strip()
    return f"documents/{clean_user}/{clean_doc}.pdf"


def upload_document_file(user_id: str, document_id: str, content: bytes) -> str:
    """
    Upload a PDF document to the private Supabase Storage bucket.

    Args:
        user_id: Authenticated user identifier (never trusted from browser).
        document_id: UUID4 identifier of the document.
        content: Raw binary content of the PDF file.

    Returns:
        storage_path: The relative object path in the bucket (e.g. documents/user123/doc456.pdf).

    Raises:
        RuntimeError: If upload fails.
    """
    storage_path = build_storage_path(user_id, document_id)
    bucket_name = settings.SUPABASE_BUCKET_NAME

    client = get_storage_client()
    try:
        logger.info(
            "Uploading document to Supabase Storage: bucket=%s, path=%s, size=%d bytes",
            bucket_name,
            storage_path,
            len(content),
        )
        # Using upsert=true allows re-uploading if retried
        client.storage.from_(bucket_name).upload(
            path=storage_path,
            file=content,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        logger.info("Successfully uploaded %s to Supabase Storage", storage_path)
        return storage_path
    except Exception as exc:
        logger.error("Failed to upload document to Supabase Storage (%s): %s", storage_path, exc)
        raise RuntimeError(f"Supabase Storage upload failed: {exc}") from exc


def download_document_file(storage_path: str) -> bytes:
    """
    Download a PDF document from the private Supabase Storage bucket.

    Args:
        storage_path: The relative object path in the bucket.

    Returns:
        Raw bytes of the document.

    Raises:
        RuntimeError: If download fails.
    """
    bucket_name = settings.SUPABASE_BUCKET_NAME
    client = get_storage_client()
    try:
        logger.info("Downloading document from Supabase Storage: bucket=%s, path=%s", bucket_name, storage_path)
        data = client.storage.from_(bucket_name).download(storage_path)
        return data
    except Exception as exc:
        logger.error("Failed to download document from Supabase Storage (%s): %s", storage_path, exc)
        raise RuntimeError(f"Supabase Storage download failed: {exc}") from exc


def delete_document_file(storage_path: str) -> bool:
    """
    Delete a specific PDF object from the private Supabase Storage bucket.

    Args:
        storage_path: The relative object path in the bucket.

    Returns:
        True if successfully deleted or not found; raises on unexpected error.
    """
    if not storage_path or not storage_path.strip():
        return False

    clean_path = storage_path.strip()
    bucket_name = settings.SUPABASE_BUCKET_NAME
    client = get_storage_client()
    try:
        logger.info("Deleting document from Supabase Storage: bucket=%s, path=%s", bucket_name, clean_path)
        client.storage.from_(bucket_name).remove([clean_path])
        logger.info("Successfully removed %s from Supabase Storage", clean_path)
        return True
    except Exception as exc:
        logger.warning("Supabase Storage deletion notice for %s: %s", clean_path, exc)
        return False


def delete_user_storage_files(user_id: str) -> int:
    """
    Delete all stored PDF files belonging to a specific user (used in guest cleanup).

    Args:
        user_id: User identifier whose objects should be purged.

    Returns:
        Number of objects removed.
    """
    if not user_id or not user_id.strip():
        return 0

    clean_user = user_id.strip().replace(" ", "_")
    folder_prefix = f"documents/{clean_user}"
    bucket_name = settings.SUPABASE_BUCKET_NAME
    client = get_storage_client()

    try:
        logger.info("Listing objects in Supabase Storage prefix: %s", folder_prefix)
        items = client.storage.from_(bucket_name).list(folder_prefix)
        if not items:
            return 0

        paths_to_delete = []
        for item in items:
            name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
            if name:
                paths_to_delete.append(f"{folder_prefix}/{name}")

        if paths_to_delete:
            logger.info("Purging %d Supabase Storage objects for user %s", len(paths_to_delete), clean_user)
            client.storage.from_(bucket_name).remove(paths_to_delete)
            return len(paths_to_delete)
        return 0
    except Exception as exc:
        logger.warning("Supabase Storage user files cleanup notice for %s: %s", clean_user, exc)
        return 0
