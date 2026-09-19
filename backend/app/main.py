"""
main.py

FastAPI application entry point.

On startup, creates all database tables that don't already exist.
Tables are never dropped on startup to protect existing data.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.base import Base
from app.db.database import engine
from app.api.auth import router as auth_router  # Day 7
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router
from app.api.quiz import router as quiz_router  # Day 6
# Import all models so Base.metadata.create_all() creates every table
from app.models import Document, Session, Message, Quiz, QuizAttempt, User  # noqa: F401


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — creating database tables if needed")
    Base.metadata.create_all(bind=engine)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title VARCHAR(255);"))
            conn.commit()
    except Exception as exc:
        logger.warning("Could not run title column migration: %s", exc)
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
    title="LearnVault API",
    description="Backend API for LearnVault — Personal AI Learning Assistant.",
    version="1.0.0",
    lifespan=lifespan,
)


def get_allowed_origins() -> list[str]:
    """
    Construct the list of allowed CORS origins from settings.
    Ensures local development hosts are always permitted, while production
    origins (such as Vercel) can be supplied via CORS_ORIGINS or FRONTEND_URL.
    """
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    if settings.CORS_ORIGINS:
        for item in settings.CORS_ORIGINS.split(","):
            cleaned = item.strip()
            if cleaned and cleaned not in origins:
                origins.append(cleaned)
    if settings.FRONTEND_URL:
        cleaned_frontend = settings.FRONTEND_URL.strip()
        if cleaned_frontend and cleaned_frontend not in origins:
            origins.append(cleaned_frontend)
    return origins


# Enable safe CORS for Next.js frontend (never wildcard with credentials in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)       # Day 7: /auth/login, /auth/me, /auth/status
app.include_router(documents_router)
app.include_router(chat_router)       # includes /chat, /chat/stream, /sessions, /sessions/{id}/messages
app.include_router(quiz_router)       # Day 6: /quiz/generate, /quiz/{id}, /quiz/{id}/submit, /quiz/history



@app.get("/health", tags=["Health"])
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/", tags=["Health"])
def root():
    """Root endpoint."""
    return {
        "message": "Personal AI Learning Assistant API",
        "version": "1.0.0-day6",
        "docs": "/docs",
    }
