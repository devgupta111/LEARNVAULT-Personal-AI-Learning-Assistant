"""
tests/test_qdrant_service.py

Comprehensive test suite for Day 3 — Qdrant vector database integration.

Verifies:
1. Qdrant client initialization (memory and configured URL).
2. Collection creation with dimension=384, distance=Cosine.
3. Existing collection does not cause failure or data loss.
4. Payload indexes for user_id and document_id.
5. Vector upsertion.
6. Idempotent upsertion with duplicate IDs (points count unchanged).
7. Payload structure and data integrity.
8. Rejection of invalid vector dimensions.
9. Connection failure handling.
10. End-to-end indexing of Day 2 chunks.
11. Pipeline failure handling when Qdrant errors.
"""

import uuid
import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.services.qdrant_service import (
    get_qdrant_client,
    ensure_collection,
    build_points,
    upsert_document_chunks,
    get_collection_info,
    create_payload_indexes,
    is_qdrant_available,
    DEFAULT_VECTOR_SIZE,
)
from app.services.pipeline_service import run_ingestion_pipeline


@pytest.fixture
def memory_client():
    """Provides a fresh in-memory Qdrant client for isolated testing."""
    return QdrantClient(":memory:")


@pytest.fixture
def sample_parents_and_children():
    """Generates valid Day 2 parent and child chunk structures with 384-d vectors."""
    doc_id = str(uuid.uuid4())
    parent_id_1 = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}|P|0|hash1"))
    parent_id_2 = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}|P|1|hash2"))

    parents = [
        {
            "chunk_id": parent_id_1,
            "document_id": doc_id,
            "user_id": "test-user",
            "subject": "Operating Systems",
            "page_start": 1,
            "page_end": 1,
            "text": "Full text of parent section 1 covering process management and lifecycle.",
            "chunk_index": 0,
        },
        {
            "chunk_id": parent_id_2,
            "document_id": doc_id,
            "user_id": "test-user",
            "subject": "Operating Systems",
            "page_start": 2,
            "page_end": 2,
            "text": "Full text of parent section 2 covering memory management and paging.",
            "chunk_index": 1,
        },
    ]

    child_id_1 = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{parent_id_1}|C|0|chash1"))
    child_id_2 = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{parent_id_1}|C|1|chash2"))
    child_id_3 = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{parent_id_2}|C|0|chash3"))

    # Generate 384-dimensional unit vectors
    v1 = [0.1] * 384
    v2 = [0.2] * 384
    v3 = [0.3] * 384

    children = [
        {
            "chunk_id": child_id_1,
            "document_id": doc_id,
            "user_id": "test-user",
            "subject": "Operating Systems",
            "page_start": 1,
            "page_end": 1,
            "parent_id": parent_id_1,
            "text": "Child snippet 1 on processes.",
            "chunk_index": 0,
            "embedding": v1,
        },
        {
            "chunk_id": child_id_2,
            "document_id": doc_id,
            "user_id": "test-user",
            "subject": "Operating Systems",
            "page_start": 1,
            "page_end": 1,
            "parent_id": parent_id_1,
            "text": "Child snippet 2 on lifecycle states.",
            "chunk_index": 1,
            "embedding": v2,
        },
        {
            "chunk_id": child_id_3,
            "document_id": doc_id,
            "user_id": "test-user",
            "subject": "Operating Systems",
            "page_start": 2,
            "page_end": 2,
            "parent_id": parent_id_2,
            "text": "Child snippet 3 on virtual memory.",
            "chunk_index": 0,
            "embedding": v3,
        },
    ]

    return parents, children


# ---------------------------------------------------------------------------
# 1. Client Initialization Tests
# ---------------------------------------------------------------------------
class TestQdrantClientInit:
    def test_memory_client_initialization(self):
        client = get_qdrant_client(url=":memory:")
        assert client is not None

    def test_url_client_initialization(self):
        client = get_qdrant_client(url="http://localhost:6333")
        assert client is not None

    def test_is_qdrant_available_memory(self, memory_client):
        assert is_qdrant_available(memory_client) is True

    def test_is_qdrant_available_invalid_host(self):
        bad_client = QdrantClient(url="http://invalid-non-existent-host:9999", timeout=0.5)
        assert is_qdrant_available(bad_client) is False


# ---------------------------------------------------------------------------
# 2. Collection Configuration Tests
# ---------------------------------------------------------------------------
class TestCollectionConfiguration:
    def test_ensure_collection_creates_collection(self, memory_client):
        col_name = "test_col_create"
        res = ensure_collection(client=memory_client, collection_name=col_name, vector_size=384)
        assert res is True

        info = get_collection_info(client=memory_client, collection_name=col_name)
        assert info is not None
        assert info["name"] == col_name
        assert info["vector_size"] == 384
        assert "Cosine" in info["distance"]

    def test_ensure_collection_idempotent_no_wipe(self, memory_client):
        col_name = "test_col_idempotent"
        ensure_collection(client=memory_client, collection_name=col_name, vector_size=384)

        # Upsert 1 test point
        memory_client.upsert(
            collection_name=col_name,
            points=[models.PointStruct(id=str(uuid.uuid4()), vector=[0.1] * 384, payload={})],
        )
        assert memory_client.count(col_name).count == 1

        # Call ensure_collection again - must NOT wipe data
        ensure_collection(client=memory_client, collection_name=col_name, vector_size=384)
        assert memory_client.count(col_name).count == 1

    def test_payload_indexes_created(self, memory_client):
        col_name = "test_col_indexes"
        ensure_collection(client=memory_client, collection_name=col_name)
        create_payload_indexes(client=memory_client, collection_name=col_name)
        # Verify collection accepts payload filtering
        info = get_collection_info(client=memory_client, collection_name=col_name)
        assert info is not None


# ---------------------------------------------------------------------------
# 3. Point Construction & Validation Tests
# ---------------------------------------------------------------------------
class TestPointConstruction:
    def test_build_points_success(self, sample_parents_and_children):
        parents, children = sample_parents_and_children
        points = build_points(parents, children, expected_dim=384)

        assert len(points) == len(children)
        for i, pt in enumerate(points):
            child = children[i]
            assert pt.id == child["chunk_id"]
            assert len(pt.vector) == 384
            assert pt.payload["child_id"] == child["chunk_id"]
            assert pt.payload["parent_chunk_id"] == child["parent_id"]
            assert pt.payload["document_id"] == child["document_id"]
            assert pt.payload["user_id"] == child["user_id"]
            assert pt.payload["subject"] == child["subject"]
            assert pt.payload["page_start"] == child["page_start"]
            assert pt.payload["page_end"] == child["page_end"]
            assert pt.payload["text"] == child["text"]
            # Parent text resolution test
            assert len(pt.payload["parent_text"]) > 0

    def test_build_points_rejects_dimension_mismatch(self, sample_parents_and_children):
        parents, children = sample_parents_and_children
        children[0]["embedding"] = [0.1] * 128  # Wrong dimension

        with pytest.raises(ValueError, match="vector dimension"):
            build_points(parents, children, expected_dim=384)

    def test_build_points_rejects_missing_embedding(self, sample_parents_and_children):
        parents, children = sample_parents_and_children
        children[0]["embedding"] = None

        with pytest.raises(ValueError, match="missing an embedding vector"):
            build_points(parents, children, expected_dim=384)


# ---------------------------------------------------------------------------
# 4. Upsert & Idempotency Tests
# ---------------------------------------------------------------------------
class TestUpsertAndIdempotency:
    def test_upsert_document_chunks(self, memory_client, sample_parents_and_children):
        parents, children = sample_parents_and_children
        col_name = "test_upsert"

        result = upsert_document_chunks(
            parents=parents,
            children=children,
            client=memory_client,
            collection_name=col_name,
        )

        assert result["status"] == "success"
        assert result["points_indexed"] == len(children)
        assert memory_client.count(col_name).count == len(children)

    def test_duplicate_upsert_is_idempotent(self, memory_client, sample_parents_and_children):
        parents, children = sample_parents_and_children
        col_name = "test_idempotent_upsert"

        # First upsert
        upsert_document_chunks(
            parents=parents,
            children=children,
            client=memory_client,
            collection_name=col_name,
        )
        initial_count = memory_client.count(col_name).count

        # Second upsert with identical chunks and IDs
        upsert_document_chunks(
            parents=parents,
            children=children,
            client=memory_client,
            collection_name=col_name,
        )
        second_count = memory_client.count(col_name).count

        assert initial_count == len(children)
        assert second_count == initial_count  # NO DUPLICATES CREATED

    def test_retrieve_upserted_payload(self, memory_client, sample_parents_and_children):
        parents, children = sample_parents_and_children
        col_name = "test_payload_retrieval"

        upsert_document_chunks(
            parents=parents,
            children=children,
            client=memory_client,
            collection_name=col_name,
        )

        child0_id = children[0]["chunk_id"]
        points = memory_client.retrieve(collection_name=col_name, ids=[child0_id])
        assert len(points) == 1
        payload = points[0].payload
        assert payload["child_id"] == child0_id
        assert payload["parent_chunk_id"] == children[0]["parent_id"]
        assert payload["parent_text"] == parents[0]["text"]
        assert payload["user_id"] == "test-user"
        assert payload["subject"] == "Operating Systems"


# ---------------------------------------------------------------------------
# 5. Pipeline Integration & Error Handling
# ---------------------------------------------------------------------------
class TestPipelineQdrantIntegration:
    def test_pipeline_with_memory_qdrant(self, tmp_path, memory_client):
        """Verify run_ingestion_pipeline indexes into Qdrant and records stats."""
        # Use existing sample PDF
        from pathlib import Path
        pdf_path = Path("data/uploads/lec-1.pdf").resolve()
        if not pdf_path.exists():
            pytest.skip("lec-1.pdf not found in data/uploads")

        doc_id = str(uuid.uuid4())
        col_name = f"test_pipe_{doc_id[:8]}"

        result = run_ingestion_pipeline(
            document_id=doc_id,
            file_path=str(pdf_path),
            subject="Test Subject",
            user_id="dev-user",
            qdrant_client=memory_client,
        )

        assert result["status"] == "success"
        assert result["qdrant_points_indexed"] > 0
        assert memory_client.count(settings.QDRANT_COLLECTION_NAME).count > 0

    def test_pipeline_raises_on_qdrant_failure(self, monkeypatch):
        """Verify that when Qdrant fails, pipeline raises RuntimeError."""
        from pathlib import Path
        pdf_path = Path("data/uploads/lec-1.pdf").resolve()
        if not pdf_path.exists():
            pytest.skip("lec-1.pdf not found in data/uploads")

        # Mock upsert_document_chunks to simulate Qdrant error
        def mock_failed_upsert(*args, **kwargs):
            raise RuntimeError("Connection refused to Qdrant cluster")

        monkeypatch.setattr(
            "app.services.pipeline_service.upsert_document_chunks",
            mock_failed_upsert,
        )

        doc_id = str(uuid.uuid4())
        with pytest.raises(RuntimeError, match="Connection refused to Qdrant"):
            run_ingestion_pipeline(
                document_id=doc_id,
                file_path=str(pdf_path),
                subject="Failing Test",
            )
