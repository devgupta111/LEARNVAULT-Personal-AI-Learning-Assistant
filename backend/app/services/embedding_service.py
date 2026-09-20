"""
services/embedding_service.py

Lightweight embedding generation using FastEmbed (ONNX Runtime).
Replaces heavy PyTorch/SentenceTransformers to operate reliably within
Render Free's 512 MB RAM ceiling.

Model: sentence-transformers/all-MiniLM-L6-v2
  - 384-dimensional normalized output vectors (unit length)
  - 100% semantically compatible with existing Qdrant vectors and cosine similarity
  - Powered by ONNX Runtime instead of PyTorch (saves ~300+ MB RAM)
  - Zero PyTorch dependency, preventing OOM kills on Render Free

Design decisions:
  - Singleton model loading: the FastEmbed model is loaded once per process and
    reused for all subsequent calls.
  - Batch size 32: matches brain.md specification.
  - Returns plain Python lists of floats so output is JSON-serializable.
"""

import logging
from typing import List, Optional, Any

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
BATCH_SIZE = 32

_model: Optional[Any] = None


def _get_model():
    """
    Lazily load and return the FastEmbed TextEmbedding model singleton.
    Logs model initialization progress clearly for production diagnostics.
    """
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        logger.info("Embedding model initialization started: %s", EMBEDDING_MODEL_NAME)
        _model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
        logger.info(
            "Embedding model initialized. Vector dimension: %d",
            EMBEDDING_DIMENSION,
        )
    return _model


def get_embedding_model():
    """Return the underlying FastEmbed TextEmbedding model instance (loads on first call)."""
    return _get_model()


def get_embedding_dimension() -> int:
    """Return the vector dimension for the current model (384 for all-MiniLM-L6-v2)."""
    return EMBEDDING_DIMENSION


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Generate 384-d normalized embeddings for a list of text strings using FastEmbed (ONNX).

    Args:
        texts: List of non-empty strings to embed.

    Returns:
        List of float vectors, one per input text.
        Each vector has length equal to 384 (EMBEDDING_DIMENSION).

    Raises:
        ValueError: If texts is empty.
        RuntimeError: If embedding generation fails.
    """
    if not texts:
        raise ValueError("embed_texts received an empty list")

    model = _get_model()
    all_vectors: List[List[float]] = []

    try:
        # FastEmbed.embed returns a generator yielding numpy ndarrays (normalized)
        embeddings_iter = model.embed(texts, batch_size=BATCH_SIZE)
        for emb in embeddings_iter:
            all_vectors.append(emb.tolist())
    except Exception as exc:
        logger.error("FastEmbed embedding generation failed: %s", exc)
        raise RuntimeError(f"Embedding generation failed: {exc}") from exc

    return all_vectors


def embed_chunks(children: List[dict]) -> List[dict]:
    """
    Add an 'embedding' key to each child chunk dict.

    Args:
        children: List of child chunk dicts from chunking_service.generate_chunks().
                  Each must have a 'text' field.

    Returns:
        New list of child dicts with 'embedding' added. Input is not mutated.
        Chunks with empty text receive an empty list as their embedding.
    """
    if not children:
        return []

    valid_indices = [i for i, c in enumerate(children) if c.get("text", "").strip()]
    texts = [children[i]["text"] for i in valid_indices]

    logger.info(
        "Embedding started: %d child chunks (%d non-empty)",
        len(children),
        len(texts),
    )

    if not texts:
        return [dict(c, embedding=[]) for c in children]

    vectors = embed_texts(texts)
    vector_map = {valid_indices[i]: vectors[i] for i in range(len(valid_indices))}

    result = []
    for i, child in enumerate(children):
        new_child = dict(child)
        new_child["embedding"] = vector_map.get(i, [])
        result.append(new_child)

    logger.info(
        "Embedding completed: embedded %d chunks (dimension: %d)",
        len(result),
        EMBEDDING_DIMENSION,
    )

    return result
