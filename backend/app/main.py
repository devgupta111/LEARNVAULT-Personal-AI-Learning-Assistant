"""
main.py

FastAPI application entry point.

On startup, creates all database tables that don't already exist.
Tables are never dropped on startup to protect existing data.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.base import Base
from app.db.database import engine
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router
# Import all models so Base.metadata.create_all() creates every table
from app.models import Document, Session, Message  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — creating database tables if needed")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready")

    # Day 3: Ensure Qdrant collection and payload indexes exist
    try:
        from app.services.qdrant_service import ensure_collection, is_qdrant_available
        if is_qdrant_available():
            ensure_collection()
            logger.info("Qdrant collection and payload indexes ready")
        else:
            logger.warning(
                "Qdrant is not currently reachable; collection will be initialized when reachable"
            )
    except Exception as exc:
        logger.warning("Could not initialize Qdrant on startup: %s", exc)

    yield
    logger.info("Shutting down")



app = FastAPI(
    title="Personal AI Learning Assistant",
    description="Backend API for the RAG-based study assistant.",
    version="1.0.0-day4",
    lifespan=lifespan,
)

app.include_router(documents_router)
app.include_router(chat_router)  # includes /chat, /sessions, /sessions/{id}/messages


@app.get("/health", tags=["Health"])
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/", tags=["Health"])
def root():
    """Root endpoint."""
    return {
        "message": "Personal AI Learning Assistant API",
        "version": "1.0.0-day4",
        "docs": "/docs",
    }
