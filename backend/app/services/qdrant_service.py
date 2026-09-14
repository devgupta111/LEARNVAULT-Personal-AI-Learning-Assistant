"""
services/qdrant_service.py

Qdrant vector database integration for the Personal AI Learning Assistant.

Responsibilities:
- Client initialization with environment-based configuration.
- Safe, idempotent collection lifecycle management (dimension: 384, distance: Cosine).
- Keyword payload index creation for user_id and document_id.
- Transforming Day 2 parent/child chunks into Qdrant PointStruct objects.
- Batched vector upserts using deterministic UUID5 child IDs as point IDs.
- Safe error handling and connection health checks.

Model: all-MiniLM-L6-v2 (vector dimension 384)
Distance metric: Cosine
"""

import logging
from typing import List, Dict, Optional, Tuple, Any

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import settings, PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_VECTOR_SIZE = 384
DEFAULT_DISTANCE = models.Distance.COSINE
LOCAL_QDRANT_PATH = PROJECT_ROOT / "data" / "qdrant_local"

_active_client: Optional[QdrantClient] = None


def reset_qdrant_client() -> None:
    """Close and reset any cached Qdrant client (useful in test teardown)."""
    global _active_client
    if _active_client is not None:
        try:
            _active_client.close()
        except Exception:
            pass
        _active_client = None


def get_qdrant_client(
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    force_new: bool = False,
) -> QdrantClient:
    """
    Return an initialized QdrantClient instance.

    - If url is ':memory:', returns a new in-memory client (used for isolated tests).
    - If a custom url (different from settings.QDRANT_URL) is specified, returns a client
      pointing directly to that custom URL.
    - Otherwise, attempts to connect to settings.QDRANT_URL (e.g. Docker container).
      If the remote connection is refused or fails, automatically falls back
      to an embedded local disk Qdrant database under data/qdrant_local, matching
      the PostgreSQL -> SQLite fallback design.
    """
    global _active_client

    if url == ":memory:":
        return QdrantClient(":memory:")

    # If an explicit custom URL (other than settings.QDRANT_URL) is passed, return direct client
    if url is not None and url != settings.QDRANT_URL:
        return QdrantClient(
            url=url,
            api_key=api_key if api_key is not None else settings.QDRANT_API_KEY,
            timeout=5.0,
        )

    if not force_new and _active_client is not None:
        return _active_client

    target_url = url or settings.QDRANT_URL
    target_key = api_key if api_key is not None else settings.QDRANT_API_KEY

    # Try connecting to remote Qdrant server first
    try:
        remote_client = QdrantClient(
            url=target_url,
            api_key=target_key,
            timeout=1.5,
        )
        # Fast health check to see if remote server is up
        remote_client.get_collections()
        logger.info("Connected successfully to Qdrant vector database at %s", target_url)
        _active_client = remote_client
        return _active_client
    except Exception as exc:
        LOCAL_QDRANT_PATH.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "Could not connect to Qdrant server at %s: %s. "
            "Falling back to local embedded Qdrant storage at %s",
            target_url,
            exc,
            LOCAL_QDRANT_PATH,
        )
        _active_client = QdrantClient(path=str(LOCAL_QDRANT_PATH))
        return _active_client


def is_qdrant_available(client: Optional[QdrantClient] = None) -> bool:
    """
    Check whether Qdrant is currently reachable.
    Does not throw exceptions; returns False on connection failure.
    """
    try:
        client_instance = client or get_qdrant_client()
        client_instance.get_collections()
        return True
    except Exception as exc:
        logger.warning("Qdrant health check failed: %s", exc)
        return False


def ensure_collection(
    client: Optional[QdrantClient] = None,
    collection_name: Optional[str] = None,
    vector_size: int = DEFAULT_VECTOR_SIZE,
) -> bool:
    """
    Ensure the target Qdrant collection and payload indexes exist.

    - If the collection exists, it is preserved (never recreated or dropped).
    - If it does not exist, it is created with vector_size (384) and Cosine distance.
    - Ensures payload keyword indexes for 'user_id' and 'document_id' exist.

    Args:
        client: QdrantClient instance (creates one from settings if None).
        collection_name: Name of the collection (uses settings.QDRANT_COLLECTION_NAME if None).
        vector_size: Vector dimension (defaults to 384).

    Returns:
        True if the collection exists or was successfully created.

    Raises:
        RuntimeError: If Qdrant is unreachable or creation fails.
    """
    target_client = client or get_qdrant_client()
    target_collection = collection_name or settings.QDRANT_COLLECTION_NAME

    try:
        collections = target_client.get_collections().collections
        exists = any(c.name == target_collection for c in collections)

        if not exists:
            logger.info(
                "Creating Qdrant collection '%s' (dimension=%d, distance=Cosine)",
                target_collection,
                vector_size,
            )
            target_client.create_collection(
                collection_name=target_collection,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=DEFAULT_DISTANCE,
                ),
            )
            logger.info("Collection '%s' created successfully", target_collection)
        else:
            logger.info("Qdrant collection '%s' already exists", target_collection)

        # Ensure payload indexes for filtering exist
        create_payload_indexes(target_client, target_collection)
        return True

    except Exception as exc:
        logger.error(
            "Failed to ensure Qdrant collection '%s': %s",
            target_collection,
            exc,
        )
        raise RuntimeError(
            f"Failed to connect to or configure Qdrant collection '{target_collection}': {exc}"
        ) from exc


def create_payload_indexes(client: QdrantClient, collection_name: str) -> None:
    """
    Create keyword payload indexes for user_id and document_id if they don't already exist.
    """
    indexed_fields = ["user_id", "document_id"]
    for field in indexed_fields:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            logger.debug("Ensured payload index on '%s' for '%s'", field, collection_name)
        except Exception as exc:
            # Qdrant may return an error if index already exists; log as debug
            logger.debug(
                "Payload index creation for '%s' returned: %s",
                field,
                exc,
            )


def build_points(
    parents: List[Dict],
    children: List[Dict],
    expected_dim: int = DEFAULT_VECTOR_SIZE,
) -> List[models.PointStruct]:
    """
    Convert Day 2 parent chunks and embedded child chunks into Qdrant PointStructs.

    Requirements:
    - Uses deterministic child chunk ID (UUID string) as the point ID.
    - Payload contains:
        child_id, parent_chunk_id, parent_text, document_id, user_id,
        subject, page_start, page_end, text.
    - Validates that each embedding is present and has length == expected_dim.

    Raises:
        ValueError: If a vector is missing or has incorrect dimension.
    """
    if not children:
        return []

    # Map parent_id -> parent_text for fast context lookup
    parent_text_map: Dict[str, str] = {
        p.get("chunk_id", ""): p.get("text", "")
        for p in parents
    }

    points: List[models.PointStruct] = []
    for idx, child in enumerate(children):
        vector = child.get("embedding")
        if not vector or not isinstance(vector, list):
            raise ValueError(
                f"Child chunk at index {idx} (id={child.get('chunk_id')}) is missing an embedding vector."
            )

        if len(vector) != expected_dim:
            raise ValueError(
                f"Child chunk {child.get('chunk_id')} has vector dimension {len(vector)}, expected {expected_dim}."
            )

        point_id = child.get("chunk_id")
        if not point_id:
            raise ValueError(f"Child chunk at index {idx} is missing 'chunk_id'.")

        parent_id = child.get("parent_id", "")
        parent_text = parent_text_map.get(parent_id, "")

        payload: Dict[str, Any] = {
            "child_id": point_id,
            "parent_chunk_id": parent_id,
            "parent_text": parent_text,
            "document_id": child.get("document_id", ""),
            "user_id": child.get("user_id", ""),
            "subject": child.get("subject", ""),
            "page_start": child.get("page_start", 1),
            "page_end": child.get("page_end", 1),
            "text": child.get("text", ""),
            "chunk_index": child.get("chunk_index", idx),
        }

        points.append(
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        )

    return points


def upsert_document_chunks(
    parents: List[Dict],
    children: List[Dict],
    client: Optional[QdrantClient] = None,
    collection_name: Optional[str] = None,
    batch_size: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Upsert document chunks and embeddings into Qdrant.

    Args:
        parents: List of parent chunk dicts from Day 2.
        children: List of embedded child chunk dicts from Day 2.
        client: Optional QdrantClient instance.
        collection_name: Optional collection name override.
        batch_size: Batch size for upserting points.

    Returns:
        Dict summarizing: status, points_indexed, collection_name.

    Raises:
        ValueError: If chunks/embeddings are invalid or dimension mismatch.
        RuntimeError: If Qdrant is unavailable or upsert fails.
    """
    target_client = client or get_qdrant_client()
    target_collection = collection_name or settings.QDRANT_COLLECTION_NAME
    target_batch_size = batch_size or settings.QDRANT_BATCH_SIZE

    # Ensure collection exists before upserting
    ensure_collection(
        client=target_client,
        collection_name=target_collection,
        vector_size=DEFAULT_VECTOR_SIZE,
    )

    points = build_points(parents, children, expected_dim=DEFAULT_VECTOR_SIZE)
    if not points:
        return {
            "status": "success",
            "points_indexed": 0,
            "collection_name": target_collection,
        }

    total_points = len(points)
    logger.info(
        "Upserting %d points into Qdrant collection '%s' (batch size=%d)",
        total_points,
        target_collection,
        target_batch_size,
    )

    try:
        for i in range(0, total_points, target_batch_size):
            batch = points[i : i + target_batch_size]
            target_client.upsert(
                collection_name=target_collection,
                points=batch,
                wait=True,
            )
        logger.info(
            "Successfully upserted %d points into collection '%s'",
            total_points,
            target_collection,
        )
        return {
            "status": "success",
            "points_indexed": total_points,
            "collection_name": target_collection,
        }
    except Exception as exc:
        logger.error(
            "Failed to upsert points into Qdrant collection '%s': %s",
            target_collection,
            exc,
        )
        raise RuntimeError(
            f"Failed to upsert vectors into Qdrant collection '{target_collection}': {exc}"
        ) from exc


def delete_document_vectors(
    document_id: str,
    user_id: str,
    client: Optional[QdrantClient] = None,
    collection_name: Optional[str] = None,
) -> int:
    """
    Delete all Qdrant vectors for a given document owned by the authenticated user.

    Filters by both document_id AND user_id payload to prevent cross-user deletion.

    This MUST be called explicitly when deleting a document — PostgreSQL ON DELETE CASCADE
    does NOT propagate to Qdrant.

    Args:
        document_id: The document whose vectors should be removed.
        user_id: The authenticated owner — used as an additional safety filter.
        client: Optional QdrantClient instance.
        collection_name: Optional collection name override.

    Returns:
        Number of points deleted (may be 0 if no vectors existed).

    Raises:
        RuntimeError: If Qdrant is unavailable or deletion fails.
    """
    target_client = client or get_qdrant_client()
    target_collection = collection_name or settings.QDRANT_COLLECTION_NAME

    # Safety: only delete points matching BOTH document_id and user_id
    delete_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=document_id),
            ),
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=user_id),
            ),
        ]
    )

    try:
        result = target_client.delete(
            collection_name=target_collection,
            points_selector=models.FilterSelector(filter=delete_filter),
            wait=True,
        )
        # result.status is an OperationStatus enum; check for failure
        status_val = str(result.status) if result.status else "unknown"
        logger.info(
            "Deleted Qdrant vectors for document_id=%s user_id=%s status=%s",
            document_id,
            user_id,
            status_val,
        )
        # Return estimated deleted count; Qdrant doesn't always return exact count
        return getattr(result, "result", 0) or 0
    except Exception as exc:
        logger.error(
            "Failed to delete Qdrant vectors for document_id=%s user_id=%s: %s",
            document_id,
            user_id,
            exc,
        )
        raise RuntimeError(
            f"Failed to delete Qdrant vectors for document '{document_id}': {exc}"
        ) from exc


def get_collection_info(
    client: Optional[QdrantClient] = None,
    collection_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Return metadata and stats for the collection, or None if it doesn't exist.
    """
    target_client = client or get_qdrant_client()
    target_collection = collection_name or settings.QDRANT_COLLECTION_NAME
    try:
        info = target_client.get_collection(collection_name=target_collection)
        vectors_config = info.config.params.vectors
        vector_size = getattr(vectors_config, "size", None)
        distance = getattr(vectors_config, "distance", None)
        return {
            "name": target_collection,
            "status": info.status.name if hasattr(info.status, "name") else str(info.status),
            "points_count": info.points_count,
            "vector_size": vector_size,
            "distance": str(distance) if distance else None,
        }
    except Exception as exc:
        logger.debug("Could not fetch collection info for '%s': %s", target_collection, exc)
        return None
