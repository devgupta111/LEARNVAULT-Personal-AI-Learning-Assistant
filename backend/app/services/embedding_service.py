"""
services/embedding_service.py

Local embedding generation using Sentence Transformers.

Model: all-MiniLM-L6-v2
  - 384-dimensional output vectors
  - Runs entirely locally, no API key required
  - Downloads model files from Hugging Face on first use (~90 MB, cached)
  - Well-maintained and benchmarked for semantic similarity tasks

Design decisions:
  - Singleton model loading: the model is loaded once per process and
    reused for all subsequent calls. This avoids the ~2-3 second startup
    cost per batch.
  - Batch size 32: matches brain.md specification. Processing in batches
    avoids loading all chunks into memory simultaneously.
  - Returns plain Python lists of floats so output is JSON-serializable.
  - The embedding model can be changed by updating EMBEDDING_MODEL_NAME
    without rewriting any calling code.
"""

import logging
from typing import List, Optional
import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 32

_model = None


def _get_model():
    """
    Lazily load and return the sentence-transformers model.

    The model is loaded on first call and cached for subsequent calls.
    This is safe for single-process use (FastAPI with a single worker or
    background tasks in the same process).
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        dim = _model.get_embedding_dimension()
        logger.info("Embedding model loaded. Vector dimension: %d", dim)
    return _model


def get_embedding_model():
    """Return the underlying SentenceTransformer model instance (loads on first call)."""
    return _get_model()


def get_embedding_dimension() -> int:
    """Return the vector dimension for the current model."""
    return _get_model().get_embedding_dimension()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a list of text strings.

    Args:
        texts: List of non-empty strings to embed.

    Returns:
        List of float vectors, one per input text.
        Each vector has length equal to get_embedding_dimension().

    Raises:
        ValueError: If texts is empty.
        RuntimeError: If embedding generation fails.
    """
    if not texts:
        raise ValueError("embed_texts received an empty list")

    model = _get_model()
    all_vectors = []

    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch = texts[batch_start : batch_start + BATCH_SIZE]
        try:
            vectors = model.encode(
                batch,
                convert_to_numpy=True,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            all_vectors.extend(vectors.tolist())
        except Exception as exc:
            logger.error(
                "Embedding batch %d-%d failed: %s",
                batch_start,
                batch_start + len(batch),
                exc,
            )
            raise RuntimeError(
                f"Embedding generation failed for batch starting at {batch_start}"
            ) from exc

    return all_vectors


def embed_chunks(children: List[dict]) -> List[dict]:
    """
    Add an 'embedding' key to each child chunk dict.

    Args:
        children: List of child chunk dicts from chunking_service.generate_chunks().
                  Each must have a non-empty 'text' field.

    Returns:
        New list of child dicts with 'embedding' added. Input is not mutated.
        Chunks with empty text receive an empty list as their embedding.
    """
    if not children:
        return []

    valid_indices = [i for i, c in enumerate(children) if c.get("text", "").strip()]
    texts = [children[i]["text"] for i in valid_indices]

    if not texts:
        return [dict(c, embedding=[]) for c in children]

    vectors = embed_texts(texts)
    vector_map = {valid_indices[i]: vectors[i] for i in range(len(valid_indices))}

    result = []
    for i, child in enumerate(children):
        new_child = dict(child)
        new_child["embedding"] = vector_map.get(i, [])
        result.append(new_child)

    return result
