"""
db/database.py

Creates the SQLAlchemy engine and session factory.
Provides the get_db() FastAPI dependency for route handlers.
"""

import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.config import settings, PROJECT_ROOT

logger = logging.getLogger(__name__)


def _create_app_engine():
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgresql"):
        try:
            test_engine = create_engine(db_url, pool_pre_ping=True)
            with test_engine.connect():
                pass
            logger.info("Connected successfully to PostgreSQL database")
            return test_engine
        except Exception as exc:
            sqlite_path = PROJECT_ROOT / "data" / "ai_learning_local.db"
            sqlite_url = f"sqlite:///{sqlite_path}"
            logger.warning(
                "Could not connect to PostgreSQL: %s. "
                "Falling back to local SQLite database: %s",
                exc,
                sqlite_url,
            )
            return create_engine(
                sqlite_url,
                connect_args={"check_same_thread": False},
            )
    else:
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        return create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)


engine = _create_app_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session per request.
    The session is closed automatically after the response is sent.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
