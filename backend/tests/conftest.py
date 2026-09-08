"""
tests/conftest.py

Shared pytest fixtures.

Uses an in-memory SQLite database so tests don't need a running PostgreSQL.
Patches the background task's SessionLocal so it also uses SQLite.
Uses tmp_path to isolate uploads per test.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.documents as documents_module
from app.db.base import Base
from app.db.database import get_db
from app.main import app

TEST_DB_PATH = "test_temp.db"
SQLITE_URL = f"sqlite:///./{TEST_DB_PATH}"

test_engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """
    Provides a TestClient backed by SQLite with an isolated upload directory.

    What this fixture does:
    1. Redirects file uploads to pytest's tmp_path (cleaned up automatically)
    2. Patches the documents module's SessionLocal so the background task
       also uses SQLite (not the real PostgreSQL configured in .env)
    3. Overrides FastAPI's get_db dependency to use the same SQLite session
    4. Creates all tables before each test and drops them after
    """
    import app.config as cfg_module
    import app.main as main_module

    monkeypatch.setattr(cfg_module.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(documents_module, "SessionLocal", TestSessionLocal)

    Base.metadata.create_all(bind=test_engine)

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def cleanup_sqlite():
    """Remove the SQLite test database file after the full test session."""
    yield
    test_engine.dispose()
    db_path = Path(TEST_DB_PATH)
    if db_path.exists():
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def qdrant_test_client(monkeypatch):
    """
    Ensure tests run hermetically with an in-memory Qdrant instance
    if the external Qdrant container is not running, matching the
    SQLite pattern used for PostgreSQL.
    """
    import app.services.qdrant_service as q_svc
    from qdrant_client import QdrantClient

    if not q_svc.is_qdrant_available():
        memory_client = QdrantClient(":memory:")
        original_get_client = q_svc.get_qdrant_client

        def _mock_get_client(url=None, api_key=None):
            if url is not None and url != ":memory:" and "invalid" in url:
                return original_get_client(url=url, api_key=api_key)
            return memory_client

        monkeypatch.setattr(q_svc, "get_qdrant_client", _mock_get_client)

