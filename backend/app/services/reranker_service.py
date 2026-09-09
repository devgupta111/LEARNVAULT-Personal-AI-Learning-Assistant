"""
services/reranker_service.py

Cross-encoder reranking of Qdrant retrieval results using FlashRank.

FlashRank runs entirely locally (no API key, no network call after first download).
It downloads a small cross-encoder model (~30 MB) on first use and caches it.

Responsibilities:
  - Accept a query string and a list of Qdrant ScoredPoint results (Top 15).
  - Rerank query/candidate pairs using the cross-encoder.
  - Apply a configurable relevance threshold to determine if evidence is strong.
  - Return the top-K parent context chunks with deduplication.
  - Signal whether retrieval is "weak" (all scores below threshold) so CRAG is triggered.

Design notes:
  - Threshold (RERANK_THRESHOLD = 0.35) is a starting point, not a universal law.
    Tune based on your actual PDFs and query distribution.
  - Parent deduplication preserves rank order (best child score wins for each parent).
  - The reranker model is loaded lazily and cached (singleton pattern).
"""

import logging
from typing import List, Dict, Tuple, Optional, Any

logger = logging.getLogger(__name__)

_ranker = None


def _get_ranker():
    """Lazily load and cache the FlashRank ranker (singleton)."""
    global _ranker
    if _ranker is None:
        try:
            from flashrank import Ranker
            logger.info("Loading FlashRank cross-encoder model...")
            _ranker = Ranker()
            logger.info("FlashRank model loaded successfully")
        except Exception as exc:
            logger.error("Failed to load FlashRank model: %s", exc)
            raise RuntimeError(
                f"FlashRank could not be loaded. Ensure 'flashrank' is installed: {exc}"
            ) from exc
    return _ranker


def rerank_results(
    query: str,
    scored_points: List[Any],
    threshold: float = 0.35,
    top_k: int = 4,
) -> Tuple[List[Dict], bool]:
    """
    Rerank Qdrant ScoredPoint results using the FlashRank cross-encoder.

    Args:
        query:         The search query string.
        scored_points: List of Qdrant ScoredPoint objects from vector search.
        threshold:     Minimum reranker score for evidence to be considered strong.
        top_k:         Maximum number of unique parent contexts to return.

    Returns:
        A tuple of:
          - List of payload dicts for the top-K unique parent chunks (deduplicated).
            Each dict has keys from Qdrant payload: parent_chunk_id, parent_text,
            document_id, user_id, subject, page_start, page_end, child_id, text.
            Additionally includes 'rerank_score'.
          - bool: True if evidence is weak (all top scores below threshold), False if strong.

    Notes:
        - If scored_points is empty, returns ([], True) — weak by definition.
        - If FlashRank fails, falls back to Qdrant's raw cosine scores and logs a warning.
    """
    if not scored_points:
        logger.info("Reranker: no results to rerank → weak evidence")
        return [], True

    # Build passage list for FlashRank
    passages = []
    for point in scored_points:
        payload = point.payload or {}
        # Use child text for reranking (precise match), parent text for generation context
        candidate_text = payload.get("text") or payload.get("parent_text", "")
        passages.append({"id": str(point.id), "text": candidate_text, "meta": payload})

    try:
        from flashrank import RerankRequest
        ranker = _get_ranker()
        rerank_request = RerankRequest(query=query, passages=passages)
        reranked = ranker.rerank(rerank_request)
    except Exception as exc:
        logger.warning(
            "FlashRank reranking failed: %s. Falling back to Qdrant cosine scores.", exc
        )
        # Fallback: use Qdrant vector scores directly, no cross-encoder
        reranked = [
            {"id": str(p.id), "score": p.score, "meta": (p.payload or {})}
            for p in scored_points
        ]

    if not reranked:
        return [], True

    # Determine if top evidence is weak
    top_score = reranked[0].get("score", 0.0)
    is_weak = top_score < threshold
    logger.info(
        "Reranker: top score=%.4f, threshold=%.4f, weak=%s",
        top_score,
        threshold,
        is_weak,
    )

    # Deduplicate by parent_chunk_id (preserve rank order, best child score wins)
    seen_parents: set = set()
    unique_parent_results: List[Dict] = []

    for item in reranked:
        meta = item.get("meta", {})
        parent_id = meta.get("parent_chunk_id", "")
        if parent_id in seen_parents:
            continue
        seen_parents.add(parent_id)

        result = dict(meta)
        result["rerank_score"] = item.get("score", 0.0)
        unique_parent_results.append(result)

        if len(unique_parent_results) >= top_k:
            break

    logger.info(
        "Reranker: returning %d unique parent contexts (is_weak=%s)",
        len(unique_parent_results),
        is_weak,
    )
    return unique_parent_results, is_weak


def search_and_rerank(
    query: str,
    document_id: str,
    user_id: str,
    qdrant_client=None,
    collection_name: Optional[str] = None,
    top_n: int = 15,
    threshold: float = 0.35,
    top_k: int = 4,
) -> Tuple[List[Dict], bool]:
    """
    Convenience function: embed query → Qdrant search → rerank.

    Combines embedding, filtered Qdrant search (user_id + document_id), and
    cross-encoder reranking into one call. This is the standard retrieval path
    used by both the initial RAG query and CRAG retry.

    Args:
        query:           Text to embed and search.
        document_id:     Must match authenticated document (security filter).
        user_id:         Must match authenticated user (security filter).
        qdrant_client:   Optional QdrantClient (uses singleton if None).
        collection_name: Optional collection name override.
        top_n:           Number of candidates to retrieve from Qdrant (default 15).
        threshold:       Reranker score threshold for strong evidence.
        top_k:           Max unique parent results to return.

    Returns:
        Tuple of (unique_parent_results, is_weak).
    """
    from app.services.embedding_service import embed_texts
    from app.services.qdrant_service import get_qdrant_client
    from app.config import settings
    from qdrant_client.http import models as qdrant_models

    # --- Embed query using the same model as ingestion ---
    try:
        query_vector = embed_texts([query])[0]
    except Exception as exc:
        logger.error("Query embedding failed: %s", exc)
        raise RuntimeError(f"Failed to embed query: {exc}") from exc

    # --- Qdrant filtered search (security: must filter by both user_id and document_id) ---
    client = qdrant_client or get_qdrant_client()
    col = collection_name or settings.QDRANT_COLLECTION_NAME

    search_filter = qdrant_models.Filter(
        must=[
            qdrant_models.FieldCondition(
                key="user_id",
                match=qdrant_models.MatchValue(value=user_id),
            ),
            qdrant_models.FieldCondition(
                key="document_id",
                match=qdrant_models.MatchValue(value=document_id),
            ),
        ]
    )

    try:
        if hasattr(client, "query_points"):
            query_res = client.query_points(
                collection_name=col,
                query=query_vector,
                query_filter=search_filter,
                limit=top_n,
                with_payload=True,
            )
            scored_points = query_res.points
        else:
            scored_points = client.search(
                collection_name=col,
                query_vector=query_vector,
                query_filter=search_filter,
                limit=top_n,
                with_payload=True,
            )
    except Exception as exc:
        logger.error("Qdrant search failed: %s", exc)
        raise RuntimeError(f"Qdrant search failed: {exc}") from exc

    logger.info(
        "Qdrant search returned %d results for query='%s...'",
        len(scored_points),
        query[:60],
    )

    return rerank_results(
        query=query,
        scored_points=scored_points,
        threshold=threshold,
        top_k=top_k,
    )
