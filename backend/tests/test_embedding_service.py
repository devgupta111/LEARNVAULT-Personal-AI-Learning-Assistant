"""
tests/test_embedding_service.py

Unit tests for embedding_service.py (Day 2).

These tests actually load the sentence-transformers model.
First run will download the model (~90 MB). Subsequent runs use cache.
"""

import math
import pytest
from app.services.embedding_service import (
    embed_texts,
    embed_chunks,
    get_embedding_dimension,
    EMBEDDING_MODEL_NAME,
)


class TestGetEmbeddingDimension:
    def test_returns_positive_integer(self):
        dim = get_embedding_dimension()
        assert isinstance(dim, int)
        assert dim > 0

    def test_returns_384_for_minilm(self):
        if "MiniLM" in EMBEDDING_MODEL_NAME or "minilm" in EMBEDDING_MODEL_NAME.lower():
            assert get_embedding_dimension() == 384


class TestEmbedTexts:
    def test_single_text_returns_one_vector(self):
        vectors = embed_texts(["The operating system manages hardware resources."])
        assert len(vectors) == 1

    def test_multiple_texts_return_correct_count(self):
        texts = [
            "Process scheduling is a core OS function.",
            "Memory management allocates RAM to processes.",
            "File systems organize data on storage devices.",
        ]
        vectors = embed_texts(texts)
        assert len(vectors) == 3

    def test_empty_list_raises_value_error(self):
        with pytest.raises(ValueError):
            embed_texts([])

    def test_all_vectors_have_same_dimension(self):
        texts = [
            "Short text.",
            "A much longer sentence describing a concept in detail with many words.",
        ]
        vectors = embed_texts(texts)
        dim = get_embedding_dimension()
        for v in vectors:
            assert len(v) == dim

    def test_vectors_are_lists_of_floats(self):
        vectors = embed_texts(["Test embedding output type check."])
        assert isinstance(vectors[0], list)
        for val in vectors[0]:
            assert isinstance(val, float)

    def test_no_nan_values(self):
        vectors = embed_texts(["Normalization reduces redundancy in databases."])
        for val in vectors[0]:
            assert not math.isnan(val)

    def test_no_inf_values(self):
        vectors = embed_texts(["CPU scheduling determines process execution order."])
        for val in vectors[0]:
            assert not math.isinf(val)

    def test_normalized_embeddings_have_unit_length(self):
        vectors = embed_texts(["Embeddings are normalized unit vectors."])
        magnitude = sum(v * v for v in vectors[0]) ** 0.5
        assert abs(magnitude - 1.0) < 0.01

    def test_different_texts_produce_different_vectors(self):
        v1 = embed_texts(["The sky is blue."])[0]
        v2 = embed_texts(["Database normalization removes redundancy."])[0]
        assert v1 != v2

    def test_same_text_produces_same_vector(self):
        text = "Deterministic embedding check for reproducibility."
        v1 = embed_texts([text])[0]
        v2 = embed_texts([text])[0]
        assert v1 == v2


class TestEmbedChunks:
    def make_child(self, chunk_id: str, text: str) -> dict:
        return {
            "chunk_id": chunk_id,
            "document_id": "doc-001",
            "user_id": "dev-user",
            "subject": "OS",
            "page_start": 1,
            "page_end": 1,
            "parent_id": "parent-001",
            "text": text,
        }

    def test_empty_list_returns_empty(self):
        assert embed_chunks([]) == []

    def test_adds_embedding_key_to_each_chunk(self):
        chunks = [
            self.make_child("c-001", "Process scheduling algorithms manage CPU time."),
            self.make_child("c-002", "Memory paging divides address space into pages."),
        ]
        result = embed_chunks(chunks)
        for chunk in result:
            assert "embedding" in chunk

    def test_original_keys_preserved(self):
        chunk = self.make_child("c-001", "Virtual memory extends physical RAM capacity.")
        result = embed_chunks([chunk])
        original_keys = set(chunk.keys())
        result_keys = set(result[0].keys())
        assert original_keys.issubset(result_keys)

    def test_embedding_dimension_consistent(self):
        chunks = [
            self.make_child(f"c-{i}", f"Educational content about topic {i} in computer science.")
            for i in range(5)
        ]
        result = embed_chunks(chunks)
        dim = get_embedding_dimension()
        for chunk in result:
            assert len(chunk["embedding"]) == dim

    def test_does_not_mutate_input(self):
        chunk = self.make_child("c-001", "Immutability test for embedding service.")
        original_keys = set(chunk.keys())
        embed_chunks([chunk])
        assert set(chunk.keys()) == original_keys
        assert "embedding" not in chunk

    def test_empty_text_chunk_gets_empty_embedding(self):
        chunks = [self.make_child("c-001", "")]
        result = embed_chunks(chunks)
        assert result[0]["embedding"] == []
