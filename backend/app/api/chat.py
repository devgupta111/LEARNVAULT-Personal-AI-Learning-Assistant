"""
api/chat.py

Day 5 — RAG Chat Endpoints with Query Router & Rewriter and CRAG Agent.

Endpoints:
    POST /sessions                          Create a new chat session
    GET  /sessions                          List sessions for current user
    GET  /sessions/{session_id}/messages    List messages in a session
    POST /chat                              Main chat endpoint (non-streaming JSON)
    GET  /chat/status                       Health/status check

POST /chat pipeline (Day 5):
    1. Authenticate user (dev-user stub; real JWT in Day 6)
    2. Validate session exists + belongs to authenticated user
    3. Validate document exists + belongs to authenticated user + is READY
    4. Load last 3-4 messages (chronological order)
    5. Query Router & Rewriter Agent (single structured LLM call):
         - direct_chat: Casual conversation -> direct LLM (skips retrieval)
         - quiz_mode:   Quiz request -> Day-6 reserved stub
         - rag_query:   Study material question -> rewritten query
    6. Initial Retrieval (Top-15 Qdrant -> Cross-encoder reranking)
    7. Evidence check:
         - Strong evidence -> grounded RAG generation -> citations -> persist & return
         - Weak evidence   -> CRAG Agent:
                               * Generates exactly 1 alternative query
                               * Retrieves and reranks exactly once again
                               * If strong -> grounded RAG generation -> persist & return
                               * If weak (or CRAG fails) -> Day-4 refusal
    8. Database persistence (PostgreSQL):
         * Original user message is stored (rewritten query is internal only)
         * Assistant answer + citation metadata stored

Security:
    - user_id ALWAYS derived from get_current_user() dependency.
    - Session ownership verified before any DB read.
    - Document ownership verified independently.
    - Qdrant filter always includes BOTH user_id AND document_id (both initial and CRAG retry).
    - API keys never returned to the frontend or logged.

No streaming (SSE) on Day 5. Streaming is deferred to Day 7.
No Grader / Quiz generation on Day 5. Deferred to Day 6.
"""

import datetime
import json
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.db.database import get_db
from app.models.document import Document
from app.models.session import Session as ChatSession
from app.models.message import Message
from app.schemas.chat_schemas import (
    ChatRequest,
    ChatResponse,
    CitationItem,
    CreateSessionRequest,
    MessageResponse,
    SessionResponse,
)
from app.services.reranker_service import search_and_rerank
from app.services.llm_service import (
    generate_rag_response,
    generate_direct_chat_response,
    get_citations,
    REFUSAL_MESSAGE,
)
from app.services.query_router_service import route_and_rewrite_query
from app.services.crag_service import generate_crag_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])

# ─── Auth dependency (dev stub — replaced by JWT in Day 6) ────────────────────

def get_current_user() -> str:
    """
    Returns the authenticated user_id.

    Day 4: Returns a hardcoded dev-user matching the document model default.
    Day 6 will replace this with a real JWT dependency that decodes the token
    and returns the actual user_id.

    NEVER trust a browser-supplied user_id. Always use this dependency.
    """
    return "dev-user"


# ─── Helper: load recent chat history ─────────────────────────────────────────

def _load_chat_history(
    session_id: str,
    db: DBSession,
    limit: int = 4,
) -> List[dict]:
    """
    Load the most recent `limit` messages for a session.

    Queries in descending order (newest first), then reverses the list
    so the returned history is chronological (oldest first).
    This matches the brain.md spec for history ordering.

    Returns a list of dicts with keys: role, content.
    """
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    # Reverse to chronological order
    rows = list(reversed(rows))
    history = []
    for row in rows:
        role = "user" if row.sender == "user" else "assistant"
        history.append({"role": role, "content": row.content})
    return history


# ─── Helper: save messages to DB ──────────────────────────────────────────────

def _save_message(
    session_id: str,
    sender: str,
    content: str,
    citations: List[dict],
    db: DBSession,
    created_at: Optional[datetime.datetime] = None,
) -> None:
    """
    Persist a single message (user question or assistant answer) to PostgreSQL.

    Citations are JSON-serialised for storage and deserialized on retrieval.
    An empty list is stored as None for user messages.
    """
    citations_json = json.dumps(citations) if citations else None
    msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        sender=sender,
        content=content,
        citations=citations_json,
        created_at=created_at or datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(msg)
    db.commit()


# ─── Session endpoints ────────────────────────────────────────────────────────

@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    request: CreateSessionRequest,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    POST /sessions — Create a new chat session.

    The document must belong to the authenticated user and be in READY status.
    Returns the new session_id.
    """
    # Verify document ownership
    document = db.query(Document).filter(Document.id == request.document_id).first()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{request.document_id}' not found.",
        )
    if document.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this document.",
        )
    if document.status != "READY":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Document is not ready for chat (status: {document.status}). "
                "Wait for processing to complete."
            ),
        )

    session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=current_user,
        document_id=request.document_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info(
        "Created session %s for user=%s document=%s",
        session.id,
        current_user,
        request.document_id,
    )

    return SessionResponse(
        session_id=session.id,
        document_id=session.document_id,
        created_at=session.created_at.isoformat() if session.created_at else "",
    )


@router.get("/sessions", response_model=List[SessionResponse])
def list_sessions(
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    GET /sessions — List all sessions for the current user.

    Returns sessions in descending creation order (newest first).
    A user can only see their own sessions.
    """
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user)
        .order_by(ChatSession.created_at.desc())
        .all()
    )
    return [
        SessionResponse(
            session_id=s.id,
            document_id=s.document_id,
            created_at=s.created_at.isoformat() if s.created_at else "",
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages", response_model=List[MessageResponse])
def list_messages(
    session_id: str,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    GET /sessions/{session_id}/messages — List messages in a session.

    Returns messages in chronological order (oldest first).
    Returns 404 if the session doesn't exist.
    Returns 403 if the session belongs to a different user.
    """
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    if session.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this session.",
        )

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    result = []
    for msg in messages:
        citations: List[CitationItem] = []
        if msg.citations:
            try:
                raw = json.loads(msg.citations)
                citations = [CitationItem(**c) for c in raw]
            except Exception:
                pass  # Malformed citations — return empty list
        result.append(
            MessageResponse(
                message_id=msg.id,
                session_id=msg.session_id,
                sender=msg.sender,
                content=msg.content,
                citations=citations,
                created_at=msg.created_at.isoformat() if msg.created_at else "",
            )
        )
    return result


# ─── Main chat endpoint ───────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    POST /chat — Day-5 RAG chat endpoint with Query Router/Rewriter and CRAG (non-streaming JSON).

    Day-5 Pipeline:
      1. Validate session ownership + document matching
      2. Validate document ownership + READY status
      3. Load last 3-4 chat messages (chronological order)
      4. Query Router & Rewriter Agent (single structured LLM call):
         - direct_chat: Casual conversation -> direct LLM (skips retrieval)
         - quiz_mode:   Quiz request -> Day-6 reserved stub
         - rag_query:   Study material question -> rewritten query for retrieval
      5. Initial Retrieval (Top-15 Qdrant -> Cross-encoder rerank)
      6. Evidence check:
         - Strong -> Grounded LLM generation -> Citations -> Persist & Return
         - Weak   -> CRAG Agent:
                     - Generates 1 alternative query
                     - Retrieves and reranks exactly once again
                     - If strong -> Grounded LLM generation -> Citations -> Persist & Return
                     - If weak (or CRAG failed) -> Standard Day-4 refusal
    """
    session_id = request.session_id
    document_id = request.document_id
    user_message = request.message

    # ── Step 1: Validate session ownership ───────────────────────────────────
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    if session.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this session.",
        )
    # Ensure the document_id in the request matches the session's document
    if session.document_id != document_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"document_id '{document_id}' does not match "
                f"session document '{session.document_id}'."
            ),
        )

    # ── Step 2: Validate document ownership + READY status ───────────────────
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )
    if document.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this document.",
        )
    if document.status != "READY":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Document is not ready for chat (status: {document.status}). "
                "Wait for processing to complete."
            ),
        )

    # ── Step 3: Load recent chat history (last 4 turns, chronological) ───────
    history = _load_chat_history(session_id=session_id, db=db, limit=4)
    logger.info(
        "Chat: session=%s, user=%s, doc=%s, history_turns=%d, query='%s...'",
        session_id,
        current_user,
        document_id,
        len(history),
        user_message[:60],
    )

    # ── Step 4: Query Router & Rewriter Agent ────────────────────────────────
    router_output = route_and_rewrite_query(query=user_message, history=history)
    selected_route = router_output.route
    logger.info(
        "Router: selected route='%s' for session=%s",
        selected_route,
        session_id,
    )

    # ── Path A: Direct Conversational Chat (no retrieval) ────────────────────
    if selected_route == "direct_chat":
        logger.info("Direct chat selected for session=%s. Skipping retrieval.", session_id)
        try:
            answer = generate_direct_chat_response(query=user_message, history=history)
        except RuntimeError as exc:
            logger.error("Direct chat generation failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chat service is temporarily unavailable. Please try again.",
            )
        except Exception as exc:
            logger.error("Unexpected direct chat error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="An error occurred during conversational response generation.",
            )

        # Persist user message + assistant answer
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            _save_message(session_id, "user", user_message, [], db, created_at=now)
            _save_message(
                session_id,
                "assistant",
                answer,
                [],
                db,
                created_at=now + datetime.timedelta(milliseconds=1),
            )
        except Exception as exc:
            logger.error("Failed to persist direct chat messages: %s", exc)

        return ChatResponse(
            session_id=session_id,
            answer=answer,
            citations=[],
        )

    # ── Path B: Quiz Mode Stub (Reserved for Day 6) ──────────────────────────
    if selected_route == "quiz_mode":
        logger.info("Quiz mode selected for session=%s. Returning Day-6 routing stub.", session_id)
        answer = (
            "Quiz mode detected. Interactive quiz generation and diagnostic testing "
            "are scheduled for Day 6. You can currently ask questions over your document "
            "in standard chat mode."
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            _save_message(session_id, "user", user_message, [], db, created_at=now)
            _save_message(
                session_id,
                "assistant",
                answer,
                [],
                db,
                created_at=now + datetime.timedelta(milliseconds=1),
            )
        except Exception as exc:
            logger.error("Failed to persist quiz stub messages: %s", exc)

        return ChatResponse(
            session_id=session_id,
            answer=answer,
            citations=[],
        )

    # ── Path C: RAG Query with Document Retrieval ────────────────────────────
    # The rewritten query replaces ONLY the query used for retrieval.
    # The original user message is preserved for database persistence and grounded context.
    retrieval_query = router_output.rewritten_query or user_message

    # Initial retrieval: Embed -> Qdrant Top-15 -> Cross-encoder rerank
    try:
        parent_results, is_weak = search_and_rerank(
            query=retrieval_query,
            document_id=document_id,
            user_id=current_user,
            threshold=settings.RERANK_THRESHOLD,
            top_k=settings.RERANK_TOP_K,
        )
    except RuntimeError as exc:
        logger.error("Retrieval pipeline failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Retrieval service is temporarily unavailable. Please try again.",
        )
    except Exception as exc:
        logger.error("Unexpected retrieval error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="An error occurred during document retrieval.",
        )

    # ── Step 5: Evidence Check & CRAG Corrective Retrieval ───────────────────
    if is_weak:
        logger.info(
            "Initial retrieval weak for session=%s (query='%s...'). Triggering CRAG Agent.",
            session_id,
            retrieval_query[:50],
        )

        crag_output = generate_crag_query(query=retrieval_query, history=history)

        if crag_output and crag_output.alternative_query:
            logger.info(
                "CRAG: Performing exactly one retry with alternative query='%s'",
                crag_output.alternative_query,
            )
            try:
                parent_results, is_weak = search_and_rerank(
                    query=crag_output.alternative_query,
                    document_id=document_id,
                    user_id=current_user,
                    threshold=settings.RERANK_THRESHOLD,
                    top_k=settings.RERANK_TOP_K,
                )
            except Exception as exc:
                logger.warning("CRAG retry retrieval failed: %s. Defaulting to weak.", exc)
                is_weak = True
        else:
            logger.info("CRAG: Alternative query generation failed or empty. Defaulting to refusal.")
            is_weak = True

    # If still weak after CRAG retry (or if CRAG failed) -> return Day-4 refusal
    if is_weak:
        logger.info(
            "Evidence remains weak after CRAG evaluation for session=%s → returning refusal",
            session_id,
        )
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            _save_message(session_id, "user", user_message, [], db, created_at=now)
            _save_message(
                session_id,
                "assistant",
                REFUSAL_MESSAGE,
                [],
                db,
                created_at=now + datetime.timedelta(milliseconds=1),
            )
        except Exception as exc:
            logger.error("Failed to persist refusal messages: %s", exc)

        return ChatResponse(
            session_id=session_id,
            answer=REFUSAL_MESSAGE,
            citations=[],
        )

    # ── Step 6: Grounded LLM Generation ──────────────────────────────────────
    logger.info(
        "Generating grounded answer from %d parent contexts for session=%s",
        len(parent_results),
        session_id,
    )
    try:
        answer = generate_rag_response(
            query=user_message,
            parent_results=parent_results,
            history=history,
        )
    except RuntimeError as exc:
        logger.error("LLM generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Answer generation is temporarily unavailable. Please try again.",
        )
    except Exception as exc:
        logger.error("Unexpected LLM error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="An error occurred during answer generation.",
        )

    # ── Step 7: Extract citation metadata ────────────────────────────────────
    raw_citations = get_citations(parent_results)
    citation_items = [CitationItem(**c) for c in raw_citations]

    # ── Step 8: Persist user message + assistant answer ───────────────────────
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        _save_message(session_id, "user", user_message, [], db, created_at=now)
        _save_message(
            session_id,
            "assistant",
            answer,
            raw_citations,
            db,
            created_at=now + datetime.timedelta(milliseconds=1),
        )
    except Exception as exc:
        logger.error("Failed to persist chat messages: %s", exc)

    logger.info(
        "Chat complete: session=%s, answer_len=%d, citations=%d",
        session_id,
        len(answer),
        len(citation_items),
    )

    return ChatResponse(
        session_id=session_id,
        answer=answer,
        citations=citation_items,
    )


# ─── Status endpoint ──────────────────────────────────────────────────────────

@router.get("/chat/status")
def chat_status():
    """Status check for the chat module."""
    return {
        "status": "active",
        "day": 5,
        "features": [
            "Core RAG pipeline",
            "Grounded answer generation",
            "Citations (source metadata)",
            "Weak-retrieval refusal",
            "Chat/session/message persistence (PostgreSQL)",
            "Session + document ownership checks",
            "Query Router & Rewriter Agent (direct_chat / rag_query / quiz_mode)",
            "CRAG corrective retrieval with single alternative-query retry",
        ],
        "deferred": [
            "Hallucination & Citation Grader (Day 6)",
            "Adaptive Quiz & Diagnostic Agent (Day 6)",
            "Production JWT authentication (Day 6)",
            "SSE streaming (Day 7)",
        ],
    }
