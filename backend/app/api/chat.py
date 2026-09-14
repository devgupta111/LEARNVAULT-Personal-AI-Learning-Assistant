"""
api/chat.py

Day 6 — RAG Chat Endpoints with Query Router/Rewriter, CRAG Agent, and
Hallucination & Citation Grader.

Endpoints:
    POST /sessions                          Create a new chat session
    GET  /sessions                          List sessions for current user
    GET  /sessions/{session_id}/messages    List messages in a session
    POST /chat                              Main chat endpoint (non-streaming JSON)
    GET  /chat/status                       Health/status check

POST /chat pipeline (Day 6):
    1. Authenticate user (dev-user stub; real JWT in Day 7)
    2. Validate session exists + belongs to authenticated user
    3. Validate document exists + belongs to authenticated user + is READY
    4. Load last 3-4 messages (chronological order)
    5. Query Router & Rewriter Agent (single structured LLM call):
         - direct_chat: Casual conversation -> direct LLM (skips retrieval, skips grader)
         - quiz_mode:   Quiz request -> refer user to /quiz/generate endpoint
         - rag_query:   Study material question -> rewritten query
    6. Initial Retrieval (Top-15 Qdrant -> Cross-encoder reranking)
    7. Evidence check:
         - Strong evidence -> grounded RAG generation -> GRADE (Agent 3)
             PASS -> citations -> persist & return
             FAIL -> regenerate ONCE with SAME context -> GRADE again
                       PASS -> citations -> persist & return
                       FAIL -> unified refusal
         - Weak evidence   -> CRAG Agent:
                               * Generates exactly 1 alternative query
                               * Retrieves and reranks exactly once again
                               * If strong -> grounded RAG generation -> GRADE (same path)
                               * If weak (or CRAG fails) -> Day-4 refusal
    8. Database persistence (PostgreSQL):
         * Original user message is stored (rewritten query is internal only)
         * Assistant answer + citation metadata stored

Security:
    - user_id ALWAYS derived from get_current_user() dependency.
    - Session ownership verified before any DB read.
    - Document ownership verified independently.
    - Qdrant filter always includes BOTH user_id AND document_id.
    - API keys never returned to the frontend or logged.

No streaming (SSE) on Day 6. Streaming is deferred to Day 7.
No Grader / Quiz generation on Day 5. Grader + Quiz are now implemented in Day 6.
Grader does NOT trigger CRAG. Grader failure -> exactly one regeneration.
"""

import datetime
import json
import logging
import re
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
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
    RenameSessionRequest,
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
from app.services.grader_service import grade_answer  # Day 6
from app.api.auth import get_current_user  # Day 7 authenticated user dependency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])



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


# ─── Session endpoints ────────────────────────────────────────────────        

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
        title=session.title,
    )


@router.get("/sessions", response_model=List[SessionResponse])
def list_sessions(
    document_id: Optional[str] = Query(default=None, description="Filter sessions by document ID"),
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    GET /sessions — List all sessions for the current user.

    Returns sessions in descending creation order (newest first).
    A user can only see their own sessions. If document_id is specified,
    filters to sessions for that specific document.
    """
    query = db.query(ChatSession).filter(ChatSession.user_id == current_user)
    if document_id:
        query = query.filter(ChatSession.document_id == document_id)
    sessions = query.order_by(ChatSession.created_at.desc()).all()
    return [
        SessionResponse(
            session_id=s.id,
            document_id=s.document_id,
            created_at=s.created_at.isoformat() if s.created_at else "",
            title=s.title,
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


@router.delete("/sessions/{session_id}", status_code=200)
def delete_session(
    session_id: str,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict:
    """
    DELETE /sessions/{session_id} — Permanently delete a chat session.

    Deletion order (no ORM cascade configured on messages):
      1. Verify authenticated ownership.
      2. Delete all messages in the session.
      3. Delete the session row.

    Security:
      - user_id derived from get_current_user() — never trusted from the request.
      - Returns 403 if the session belongs to a different user.
      - Returns 404 if the session does not exist.
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
            detail="You do not have permission to delete this session.",
        )

    # Delete messages first (no ORM cascade configured)
    deleted_messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .delete(synchronize_session="fetch")
    )

    # Delete session row
    db.delete(session)
    db.commit()

    logger.info(
        "Session %s deleted by user %s (%d messages removed)",
        session_id,
        current_user,
        deleted_messages,
    )

    return {"deleted": True, "session_id": session_id}


@router.put("/chat/sessions/{session_id}", response_model=SessionResponse, status_code=status.HTTP_200_OK)
@router.put("/sessions/{session_id}", response_model=SessionResponse, status_code=status.HTTP_200_OK)
def rename_session(
    session_id: str,
    request: RenameSessionRequest,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    PUT /chat/sessions/{session_id} — Rename a chat session.

    Validation:
      - title must be non-empty after strip.
      - title max length: 255 characters.

    Security:
      - user_id derived from get_current_user() — never trusted from request.
      - Returns 403 if the session belongs to a different user.
      - Returns 404 if the session does not exist.
    """
    clean_title = request.title.strip()
    if not clean_title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Session title cannot be empty.",
        )
    if len(clean_title) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Session title is too long ({len(clean_title)} characters). Maximum is 255.",
        )

    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    if session.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to rename this session.",
        )

    old_title = session.title
    session.title = clean_title
    db.commit()
    db.refresh(session)

    logger.info(
        "Session %s renamed by user %s: '%s' -> '%s'",
        session_id,
        current_user,
        old_title,
        clean_title,
    )

    return SessionResponse(
        session_id=session.id,
        document_id=session.document_id,
        created_at=session.created_at.isoformat() if session.created_at else "",
        title=session.title,
    )


# ─── Verified RAG generation integrating Agents 1, 2, and 3 ────────────────────


def _generate_verified_answer(
    session_id: str,
    document_id: str,
    user_message: str,
    current_user: str,
    history: List[dict],
) -> tuple[str, List[dict]]:
    """
    Executes the full verified RAG pipeline integrating Agents 1, 2, and 3.

    Steps:
      1. Agent 1: Query Router & Rewriter (direct_chat / quiz_mode / rag_query)
      2. If rag_query: Qdrant retrieval + Cross-encoder rerank
      3. If weak evidence: Agent 2 (CRAG) executes exactly ONE retry
      4. If still weak: returns unified REFUSAL_MESSAGE
      5. Grounded RAG answer generation from parent contexts
      6. Agent 3: Hallucination & Citation Grader
         - PASS: return verified answer + citations
         - FAIL: regenerate ONCE using SAME parent contexts (no CRAG, no new retrieval)
           - PASS: return verified regenerated answer + citations
           - FAIL: return unified REFUSAL_MESSAGE + empty citations
    """
    # ── Step 1: Query Router & Rewriter Agent ────────────────────────────────
    router_output = route_and_rewrite_query(query=user_message, history=history)
    selected_route = router_output.route
    logger.info("Router: selected route='%s' for session=%s", selected_route, session_id)

    # Path A: Direct Conversational Chat (no retrieval)
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
        return answer, []

    # Path B: Quiz Mode
    if selected_route == "quiz_mode":
        logger.info("Quiz mode selected for session=%s. Routing to quiz API.", session_id)
        answer = (
            "Quiz mode detected. Use the dedicated Quiz interface or POST /quiz/generate "
            "endpoint to generate an adaptive quiz from your document. You can also ask study questions here."
        )
        return answer, []

    # Path C: RAG Query with Document Retrieval
    retrieval_query = router_output.rewritten_query or user_message

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

    # Evidence check & CRAG Corrective Retrieval
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

    if is_weak:
        logger.info("Evidence remains weak after CRAG for session=%s -> returning refusal", session_id)
        return REFUSAL_MESSAGE, []

    # Grounded LLM Generation
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

    # Agent 3: Hallucination & Citation Grader
    raw_citations = get_citations(parent_results)
    logger.info("Grader: evaluating initial answer for session=%s", session_id)
    grader_result = grade_answer(
        question=user_message,
        answer=answer,
        parent_results=parent_results,
        citations=raw_citations,
    )

    if not grader_result.grounded:
        logger.info(
            "Grader FAIL (confidence=%.2f): Regenerating once with SAME context for session=%s. Critique: '%s'",
            grader_result.confidence,
            session_id,
            grader_result.critique[:120] if grader_result.critique else "",
        )
        try:
            answer = generate_rag_response(
                query=user_message,
                parent_results=parent_results,  # SAME context — no re-retrieval, no CRAG
                history=history,
            )
        except Exception as exc:
            logger.error("Regeneration attempt failed for session=%s: %s", session_id, exc)
            answer = None

        if answer:
            raw_citations = get_citations(parent_results)
            regen_grader_result = grade_answer(
                question=user_message,
                answer=answer,
                parent_results=parent_results,
                citations=raw_citations,
            )
            if regen_grader_result.grounded:
                logger.info(
                    "Grader PASS after regeneration (confidence=%.2f) for session=%s",
                    regen_grader_result.confidence,
                    session_id,
                )
            else:
                logger.info(
                    "Grader FAIL after regeneration (confidence=%.2f) for session=%s. Returning refusal.",
                    regen_grader_result.confidence,
                    session_id,
                )
                answer = None

        if answer is None:
            return REFUSAL_MESSAGE, []
    else:
        logger.info("Grader PASS (confidence=%.2f) for session=%s", grader_result.confidence, session_id)

    return answer, raw_citations


# ─── Main chat endpoint (non-streaming JSON) ───────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    POST /chat — Day-6/Day-7 RAG chat endpoint with Router, CRAG, and Grader (non-streaming JSON).
    """
    session_id = request.session_id
    document_id = request.document_id
    user_message = request.message

    # Validate session ownership
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
    if session.document_id != document_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"document_id '{document_id}' does not match session document '{session.document_id}'.",
        )

    # Validate document ownership + READY status
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
            detail=f"Document is not ready for chat (status: {document.status}). Wait for processing to complete.",
        )

    history = _load_chat_history(session_id=session_id, db=db, limit=4)
    answer, raw_citations = _generate_verified_answer(
        session_id=session_id,
        document_id=document_id,
        user_message=user_message,
        current_user=current_user,
        history=history,
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    try:
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

    citation_items = [CitationItem(**c) for c in raw_citations]
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        citations=citation_items,
    )


# ─── Day 7: SSE Streaming chat endpoint ───────────────────────────────────────

@router.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    current_user: str = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    POST /chat/stream — Day-7 RAG chat endpoint with Server-Sent Events (SSE) streaming.

    Contract:
      data: {"token": "..."}\n\n
      data: {"done": true, "citations": [...]}\n\n

    Refusal:
      data: {"token": "I couldn't find sufficient information in your uploaded documents to answer that question."}\n\n
      data: {"done": true, "citations": []}\n\n

    CRITICAL RULE 15:
      Unverified answers are NEVER streamed.
      The LLM generates complete candidate answer -> Grader validates it -> only upon PASS
      are verified tokens streamed via SSE.
    """
    session_id = request.session_id
    document_id = request.document_id
    user_message = request.message

    # Validate session ownership
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
    if session.document_id != document_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"document_id '{document_id}' does not match session document '{session.document_id}'.",
        )

    # Validate document ownership + READY status
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
            detail=f"Document is not ready for chat (status: {document.status}). Wait for processing to complete.",
        )

    history = _load_chat_history(session_id=session_id, db=db, limit=4)

    def sse_event_stream():
        from app.db.database import SessionLocal
        stream_db = SessionLocal()
        try:
            # Complete answer is generated & graded BEFORE streaming any token (Rule 15)
            answer, raw_citations = _generate_verified_answer(
                session_id=session_id,
                document_id=document_id,
                user_message=user_message,
                current_user=current_user,
                history=history,
            )

            # Persist user message + verified answer to DB
            now = datetime.datetime.now(datetime.timezone.utc)
            _save_message(session_id, "user", user_message, [], stream_db, created_at=now)
            _save_message(
                session_id,
                "assistant",
                answer,
                raw_citations,
                stream_db,
                created_at=now + datetime.timedelta(milliseconds=1),
            )

            if answer == REFUSAL_MESSAGE:
                yield f"data: {json.dumps({'token': REFUSAL_MESSAGE})}\n\n"
                yield f"data: {json.dumps({'done': True, 'citations': []})}\n\n"
            else:
                # Stream verified tokens
                chunks = re.findall(r"\S+|\s+", answer)
                for chunk in chunks:
                    yield f"data: {json.dumps({'token': chunk})}\n\n"
                yield f"data: {json.dumps({'done': True, 'citations': raw_citations})}\n\n"

        except HTTPException as exc:
            yield f"data: {json.dumps({'error': exc.detail})}\n\n"
            yield f"data: {json.dumps({'done': True, 'citations': []})}\n\n"
        except Exception as exc:
            logger.exception("Error in SSE chat stream for session %s: %s", session_id, exc)
            yield f"data: {json.dumps({'error': 'An error occurred during chat streaming.'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'citations': []})}\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(
        sse_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Status endpoint ──────────────────────────────────────────────────────────

@router.get("/chat/status")
def chat_status():
    """Status check for the chat module."""
    return {
        "status": "active",
        "day": 7,
        "features": [
            "Core RAG pipeline",
            "Grounded answer generation",
            "Citations (source metadata)",
            "Weak-retrieval refusal",
            "Chat/session/message persistence (PostgreSQL)",
            "Session + document ownership checks",
            "Query Router & Rewriter Agent (direct_chat / rag_query / quiz_mode)",
            "CRAG corrective retrieval with single alternative-query retry",
            "Hallucination & Citation Grader (Agent 3) — grounding verification",
            "Exactly one answer regeneration on grader failure (same context)",
            "Unified refusal on second grader failure",
            "SSE streaming (POST /chat/stream)",
            "Frontend integration (Next.js)",
        ],
        "deferred": [],
    }

