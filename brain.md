# Personal AI Learning Assistant --- Project Brain (V4)

## 0. Project Goal

Build a full-stack RAG-based Personal AI Learning Assistant where a
student can upload lecture notes, PDFs, and textbooks, ask
natural-language questions over their own study material, receive
grounded answers with page citations, and generate quizzes with
deterministic MCQ auto-grading.

This is a resume project. Priorities are: **working \> complex,
explainable \> fancy, reliable \> feature-heavy**.

The architecture is locked. Do not add new frameworks, databases,
agents, queues, or autonomous loops unless a real implementation
requirement appears.

------------------------------------------------------------------------

# 1. Locked V4 Architecture

## Core features

-   JWT authentication
-   PDF upload and validation
-   PostgreSQL document tracking
-   Asynchronous processing with Celery + Redis
-   PyMuPDF page-by-page extraction
-   Optional OCR for scanned pages
-   Text cleaning and normalization
-   Hierarchical parent-child chunking
-   Deterministic UUID5 chunk IDs using stable SHA-256 text hashes
-   Batch embeddings with retry/backoff
-   Qdrant vector storage with user/document payload filters
-   Conversational query rewriting
-   Top-15 vector retrieval
-   Cross-encoder reranking
-   Relevance threshold
-   CRAG corrective retrieval with exactly one retry
-   Parent-context deduplication
-   Grounded LLM generation
-   Hallucination/citation grading
-   Exactly one answer regeneration after grader failure
-   Unified refusal path
-   SSE streaming
-   PostgreSQL chat history
-   Adaptive quiz generation
-   Deterministic MCQ auto-grading
-   Basic testing, logging, security, Docker/deployment

## Exactly four agentic components

1.  Query Router & Rewriter Agent
2.  CRAG Agent
3.  Hallucination & Citation Grader
4.  Adaptive Quiz & Diagnostic Agent

Deterministic services such as PDF extraction, chunking, embeddings,
Qdrant search, database operations, SSE, and MCQ score calculation are
NOT agents.

------------------------------------------------------------------------

# 2. High-Level System

``` text
                         PERSONAL AI LEARNING ASSISTANT
                                      |
                   +------------------+------------------+
                   |                                     |
                   v                                     v
          DOCUMENT PIPELINE                        QUERY PIPELINE
                   |                                     |
              PDF Upload                            User Question
                   |                                     |
              FastAPI API                          JWT Authentication
                   |                                     |
           PostgreSQL Tracking                    Chat History
                   |                                     |
            Celery + Redis                    Query Router/Rewriter Agent
                   |                              /       |        \\
             PyMuPDF                            /        |          \\
                   |                       direct_chat  RAG       quiz_mode
             Optional OCR                        |        |          |
                   |                         Direct LLM  |     Quiz Agent
             Text Cleaning                                  |
                   |                                      Embedding
           Parent Chunking                                     |
                   |                                  Qdrant Filtered Search
            Child Chunking                                     |
                   |                                  Cross-Encoder Rerank
            UUID5 IDs                                          |
                   |                                       Evidence Gate
            Embeddings                                      /          \\
                   |                                      YES           NO
                 Qdrant                                     |             |
                   |                                  Parent Context    CRAG
              READY status                                   |             |
                                                        Grounded LLM   Retry once
                                                             |             |
                                                    Hallucination Grader   |
                                                       /       \\\          |
                                                     PASS      FAIL        |
                                                       |        |          |
                                                      SSE   Regenerate     |
                                                               once         |
                                                                |          |
                                                          Grade again       |
                                                          /       \\\       |
                                                       PASS       FAIL     |
                                                        |           |       |
                                                       SSE        Refusal <-+
```

------------------------------------------------------------------------

# 3. Document Ingestion Pipeline

``` text
Next.js Upload
  -> FastAPI /documents/upload
  -> JWT validation + MIME/size validation
  -> PostgreSQL document row (PROCESSING)
  -> save data/uploads/{document_id}.pdf
  -> Celery + Redis
  -> PyMuPDF page extraction
  -> scanned-page detection
  -> optional OCR for flagged pages
  -> clean/normalize text
  -> parent chunks (600–800 tokens, ~50 overlap)
  -> child chunks (150–250 tokens, ~30 overlap)
  -> deterministic UUID5 IDs
  -> batch embeddings
  -> Qdrant upsert
  -> PostgreSQL status READY
```

## Upload

Next.js submits `multipart/form-data` containing the PDF and subject to
FastAPI.

FastAPI must: - require authentication - validate MIME type - enforce
configurable file-size limit - generate document UUID4 - create
PostgreSQL tracking row - save file - dispatch worker - return HTTP 202

Response:

``` json
{"document_id":"<uuid4>","status":"PROCESSING"}
```

Never trust a browser-supplied user_id for authorization. Derive the
user from the authenticated JWT.

## Database document status

``` text
PROCESSING -> READY
PROCESSING -> FAILED
```

`documents` fields:

``` text
id, user_id, filename, subject, status,
error_reason, created_at, processed_at
```

## Async processing

Use Celery + Redis for the target implementation. A simple background
task is acceptable temporarily during local development, but expensive
extraction/embedding work should not block the upload HTTP request.

## Extraction and OCR

Use PyMuPDF (`fitz`) page by page and preserve page numbers.

For each page, if extracted text is below an initial configurable
threshold such as 50 characters, mark it as a possible
scanned/image-only page.

If OCR is enabled, OCR only those flagged pages and merge their text
back into the page sequence.

If every page is image-only and OCR is unavailable/fails, mark the
document FAILED with a useful error message. A few bad pages must not
invalidate an otherwise searchable document.

OCR is optional for the MVP; searchable PDFs should work first.

## Cleaning

-   remove null/control characters
-   normalize spaces and tabs
-   reduce excessive line breaks
-   remove repeated headers/footers only when confidently detected
-   fix extraction artifacts without deleting meaningful academic
    content
-   preserve page boundaries

## Hierarchical chunks

Parent: - 600--800 tokens - about 50-token overlap

Child: - 150--250 tokens - about 30-token overlap

Relationship:

``` text
Parent 1 -> Child 1, Child 2, Child 3
Parent 2 -> Child 4, Child 5, Child 6
```

Child metadata:

``` text
child_id
parent_chunk_id
document_id
user_id
subject
page_start/page_end
child_text
```

## Deterministic IDs

Document ID = UUID4.

Chunk IDs = UUID5 based on stable identifiers and SHA-256 text hashes.

Conceptually:

``` text
parent_chunk_id = UUID5(namespace, document_id + parent_index + SHA256(parent_text))
child_id = UUID5(namespace, parent_chunk_id + child_index + SHA256(child_text))
```

Purpose: retries are idempotent and worker retries do not create
duplicate Qdrant vectors.

## Embeddings

Use one consistent embedding model for both document chunks and user
queries. Batch size can start at 32.

Use exponential backoff with jitter for transient 429/5xx errors. Where
practical, isolate malformed chunks so one bad chunk does not fail the
whole document.

## Qdrant

Store child vectors. Payload should include:

``` json
{
  "child_id":"...",
  "parent_chunk_id":"...",
  "parent_text":"...",
  "document_id":"...",
  "user_id":"...",
  "subject":"...",
  "page_start":4,
  "page_end":5
}
```

Keep parent_text in the child payload for the first production version
so query-time parent context does not require another database read.

Create payload indexes once for `user_id` and `document_id`.

------------------------------------------------------------------------

# 4. Query & RAG Pipeline

``` text
User question
 -> JWT authentication
 -> last 3–4 chat turns from PostgreSQL
 -> Query Router & Rewriter Agent
 -> route
    direct_chat -> direct LLM -> SSE
    quiz_mode   -> Quiz Agent
    rag_query   -> query embedding
                 -> Qdrant filter(user_id + document_id), Top 15
                 -> cross-encoder reranking
                 -> evidence threshold
                    PASS -> parent dedup -> grounded LLM
                         -> buffer answer
                         -> Hallucination/Citation Grader
                            PASS -> SSE
                            FAIL -> regenerate once -> grade again
                                     PASS -> SSE
                                     FAIL -> refusal
                    FAIL -> CRAG Agent
                         -> alternative query
                         -> embedding -> Qdrant -> rerank
                         -> pass -> normal RAG
                         -> fail -> refusal
```

## Chat history

Fetch only the last 3--4 turns. Query in descending timestamp order and
reverse the returned records before giving them to the model so history
is chronological.

## Query Router & Rewriter Agent

One structured LLM call, not two agents.

Input: - raw user message - recent history

Output:

``` json
{
  "route":"direct_chat | rag_query | quiz_mode",
  "rewritten_query":"standalone search query"
}
```

If the request is a RAG question, use `rewritten_query` for embedding.
If rewriting fails, fall back to the raw user message instead of
crashing the request.

A lightweight shortcut for obvious greetings/pleasantries is allowed,
but do not create a separate intent-routing system.

## Query embedding

Embed using exactly the same model/dimension used during ingestion.
Retry transient failures.

## Qdrant retrieval

Use authenticated user identity and selected document:

``` text
user_id = authenticated user
AND
document_id = selected document
```

Retrieve Top 15.

This filter is a security requirement, not merely a performance
optimization.

## Cross-encoder reranking

Rerank query/candidate pairs using BGE reranker or FlashRank.

Use a configurable relevance threshold. An initial example may be 0.35,
but treat it as a tunable threshold calibrated against real project
queries rather than as a universal probability.

## CRAG Agent

Trigger only when the top reranked evidence is below threshold.

``` text
weak retrieval
 -> CRAG Agent
 -> one alternative query
 -> embedding
 -> Qdrant
 -> rerank
```

Maximum exactly one retry. If the retry fails, use the unified refusal.
No recursive CRAG loops.

## Parent context

Take the strongest 3--4 child results. Deduplicate `parent_chunk_id`
while preserving rank order.

``` python
seen = set()
unique_parents = []
for chunk in top_chunks:
    pid = chunk.payload["parent_chunk_id"]
    if pid not in seen:
        seen.add(pid)
        unique_parents.append(chunk.payload)
```

Use the stored parent text and page metadata.

## Grounded generation

Prompt must explicitly say: - answer only from supplied context - do not
use outside knowledge - if evidence is insufficient, use the refusal
statement - cite factual statements using `[Source X]`

Context format:

``` text
[Source 1 | Page 4]
...

[Source 2 | Page 12]
...
```

## Hallucination & Citation Grader

The complete answer is generated and buffered server-side before the
user receives it.

The grader checks: - claims are supported by retrieved context -
citations correspond to supporting sources - response follows grounding
instructions

Structured output example:

``` json
{"grounded":true,"confidence":0.94}
```

LOCKED failure path:

``` text
Generation
 -> Grade
 -> PASS: stream
 -> FAIL: regenerate once with the same retrieved context
          -> Grade again
          -> PASS: stream
          -> FAIL: refusal
```

Do not trigger CRAG from the grader. Do not regenerate indefinitely. Do
not stream the unverified first answer.

## Unified refusal

Both retrieval failure and final grounding failure use the same response
path.

Example:

``` text
I couldn't find sufficient information in your uploaded documents to answer that question.
```

Store the user query and refusal in PostgreSQL.

## SSE

Use FastAPI `StreamingResponse` / SSE to Next.js.

Conceptually:

``` text
data: {"token":"..."}

data: {"token":"..."}

data: {"done":true,"citations":[...]}
```

Only the approved buffered answer is released after grading.

------------------------------------------------------------------------

# 5. Quiz / Auto-Grading Pipeline

Quiz is intentionally separate from normal chat RAG.

``` text
Quiz request
 -> Quiz/Diagnostic Agent
 -> previous quiz attempts
 -> weak-topic detection
 -> Qdrant relevant chunks
 -> LLM quiz generation
 -> structured JSON
 -> Pydantic validation
 -> PostgreSQL quizzes
 -> Quiz UI
 -> student submits answers
 -> deterministic MCQ auto-grading
 -> score + feedback
 -> quiz_attempts
```

## Adaptive behavior

Start with a simple weak-topic rule such as accuracy below 60%.

Example:

``` text
Normalization 85%
Transactions 90%
Indexing      55%  <- weak
Deadlock      70%
```

The next quiz can prioritize Indexing.

Do not build a complicated mastery/knowledge model.

## Quiz generation

Retrieve a small amount of relevant document context, for example up to
3 relevant chunks per weak topic.

Generate structured MCQs. Validate them with Pydantic before saving.

## Auto-grading

MCQ grading is deterministic:

``` text
submitted_answer == correct_answer
```

Do not call an LLM to decide whether an MCQ answer is correct.

The LLM can provide a short explanation/feedback, but score calculation
must remain deterministic.

------------------------------------------------------------------------

# 6. PostgreSQL Schema

## users

``` text
id
email
created_at
```

## documents

``` text
id
user_id
filename
subject
status
error_reason
created_at
processed_at
```

## sessions

``` text
id
user_id
document_id
created_at
```

## messages

``` text
id
session_id
sender
content
citations
created_at
```

## quizzes

``` text
id
user_id
document_id
title
questions
created_at
```

## quiz_attempts

``` text
id
quiz_id
user_id
answers
score
created_at
```

Keep the schema simple.

------------------------------------------------------------------------

# 7. Security

-   JWT authentication
-   derive user identity from authenticated token
-   never trust browser user_id for authorization
-   filter Qdrant by authenticated user_id and selected document_id
-   enforce document/session/message/quiz ownership in backend
-   validate PDF type and size
-   keep secrets in `.env`
-   `.env` must be in `.gitignore`
-   never expose API keys to Next.js/browser
-   use HTTPS in production

------------------------------------------------------------------------

# 8. Technology Stack

Frontend: - Next.js - React - TypeScript - Tailwind CSS

Backend: - FastAPI - Python - Pydantic

RAG: - Sentence Transformers or embedding API - Qdrant - BGE reranker or
FlashRank - Gemini, Groq, or OpenAI LLM

Documents: - PyMuPDF - Tesseract/OCRmyPDF optional

Infrastructure: - PostgreSQL - Redis - Celery - Docker

Streaming: - Server-Sent Events

------------------------------------------------------------------------

# 9. Suggested Project Structure

``` text
personal-ai-learning-assistant/
├── frontend/
│   ├── app/
│   │   ├── login/
│   │   ├── dashboard/
│   │   ├── documents/
│   │   ├── chat/
│   │   └── quiz/
│   ├── components/
│   ├── hooks/
│   ├── lib/
│   ├── types/
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── auth.py
│   │   │   ├── documents.py
│   │   │   ├── chat.py
│   │   │   └── quiz.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── pdf_service.py
│   │   │   ├── ocr_service.py
│   │   │   ├── chunking_service.py
│   │   │   ├── embedding_service.py
│   │   │   ├── qdrant_service.py
│   │   │   ├── reranker_service.py
│   │   │   ├── llm_service.py
│   │   │   └── quiz_service.py
│   │   ├── agents/
│   │   │   ├── query_router.py
│   │   │   ├── crag_agent.py
│   │   │   ├── grounding_grader.py
│   │   │   └── quiz_agent.py
│   │   ├── workers/
│   │   │   └── document_worker.py
│   │   ├── db/
│   │   └── utils/
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
│
├── data/
│   └── uploads/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── brain.md
```

Agents stay separate from deterministic services.

------------------------------------------------------------------------

# 10. Implementation Phases

## PHASE 1 --- Foundation ✅ COMPLETE (2026-09-06)

### Build

-   Next.js frontend
-   FastAPI backend
-   PostgreSQL connection configured via env vars
-   `.env` / `.env.example`
-   health endpoint
-   base folders

### API

`GET /health` ✅

### What was built

-   `backend/app/main.py` — FastAPI entry point, CORS, all routers registered
-   `backend/app/config.py` — pydantic-settings loading all env vars
-   `backend/app/api/auth.py` — placeholder (Phase 2)
-   `backend/app/api/documents.py` — placeholder (Phase 3)
-   `backend/app/api/chat.py` — placeholder (Phase 6)
-   `backend/app/api/quiz.py` — placeholder (Phase 8)
-   `backend/app/models/`, `schemas/`, `services/`, `agents/`, `workers/`, `db/`, `utils/` — all scaffolded
-   `backend/tests/` — scaffolded
-   `backend/requirements.txt` — phase-organized, Phase 1 packages uncommented
-   `backend/.env` — local dev values (not committed)
-   `.env.example` — all keys documented at root
-   `.gitignore` — root-level, covers .env, .venv, PDFs, node_modules
-   `frontend/src/app/login/`, `dashboard/`, `documents/`, `chat/`, `quiz/` — page stubs
-   `frontend/components/`, `hooks/`, `lib/`, `types/` — scaffolded
-   Old Day 1 files (`core/config.py`, `extraction_service.py`) deprecated in place

### LLM model

`LLM_MODEL=openai/gpt-oss-120b` configured in `.env` and `.env.example`.
`LLM_API_KEY` will be provided by user when Phase 5–6 is reached.

### Startup commands (Phase 1)

Backend:
```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
# Verify: GET http://127.0.0.1:8000/health
```

Frontend:
```powershell
cd frontend
npm run dev
# Verify: http://localhost:3000
```

### Antigravity prompt

> Implement Phase 1 of the Personal AI Learning Assistant from brain.md.
> Create a clean monorepo with frontend/ using Next.js + TypeScript and
> backend/ using FastAPI + Python. Configure PostgreSQL through
> environment variables. Add GET /health. Create .env.example with
> DATABASE_URL, QDRANT_URL, QDRANT_API_KEY, REDIS_URL, LLM_API_KEY, and
> EMBEDDING_API_KEY placeholders. Never hardcode secrets. Create the
> folder structure defined in brain.md. Do not implement RAG, agents,
> OCR, quiz generation, or complex authentication yet. Verify frontend
> and backend run independently and document startup commands.

## PHASE 2 --- Authentication + Database

### Build

-   user model
-   JWT authentication
-   password hashing
-   users/documents/sessions/messages models
-   ownership dependency

### APIs

`POST /auth/register` `POST /auth/login` `GET /auth/me`

### Antigravity prompt

> Implement Phase 2. Add PostgreSQL models/migrations for users,
> documents, sessions, and messages. Implement JWT authentication with
> secure password hashing. Create POST /auth/register, POST /auth/login,
> and GET /auth/me. Add a reusable FastAPI dependency that obtains the
> authenticated user from JWT. Never trust a frontend user_id for
> authorization. Keep the implementation conventional and simple. Add
> tests for registration, login, invalid credentials, protected
> endpoints, and ownership checks. Do not implement RAG, agents, OCR, or
> quiz logic yet.

## PHASE 3 --- PDF Upload + Async Worker

### Build

-   Next.js upload UI
-   FastAPI multipart endpoint
-   PDF MIME validation
-   configurable size limit
-   UUID4 document ID
-   save PDF to `data/uploads/{document_id}.pdf`
-   PostgreSQL PROCESSING record
-   Celery + Redis dispatch
-   document status APIs

### APIs

`POST /documents/upload` `GET /documents` `GET /documents/{document_id}`

### Antigravity prompt

> Implement Phase 3. Build the end-to-end PDF upload flow. Next.js
> submits multipart/form-data with the PDF and subject to FastAPI.
> Require JWT authentication, validate PDF MIME/type and file size,
> generate UUID4 document_id, create a PostgreSQL document record with
> PROCESSING status, save the file at data/uploads/{document_id}.pdf,
> dispatch a Celery + Redis worker, and return HTTP 202 with document_id
> and status. Add document list and detail endpoints restricted to the
> authenticated user. The worker may initially be a placeholder that
> updates status. Do not implement embeddings, Qdrant, RAG, or agents
> yet. Add upload/status UI and ownership tests.

## PHASE 4 --- Extraction + OCR Hook + Chunking

### Build

-   PyMuPDF page extraction
-   page numbers
-   scanned-page threshold
-   optional OCR service
-   text cleaning
-   parent/child chunking
-   UUID5 IDs

### Antigravity prompt

> Implement Phase 4. Replace the placeholder worker with real PyMuPDF
> page-by-page extraction while preserving page numbers. Flag pages with
> fewer than a configurable initial 50-character threshold as possible
> scanned pages. Add an OCR service interface using Tesseract/OCRmyPDF
> when enabled; OCR only flagged pages and merge results into page
> order. If every page is image-only and OCR is unavailable/fails, mark
> the document FAILED with a clear error_reason. Implement cleaning for
> control characters, whitespace, tabs, excessive line breaks, and safe
> repeated headers/footers. Implement parent chunks of 600--800 tokens
> with about 50 overlap and child chunks of 150--250 tokens with about
> 30 overlap. Add deterministic UUID5 IDs based on stable SHA-256 text
> hashes. Preserve document/user/subject/page metadata. Do not add
> embeddings, Qdrant, or agents. Add unit tests for extraction, scanned
> pages, chunk relationships, page metadata, and deterministic IDs.

## PHASE 5 --- Embeddings + Qdrant

### Build

-   embedding service
-   batch size around 32
-   retries/backoff
-   chunk isolation
-   Qdrant collection
-   payload indexes
-   vector upsert
-   READY/FAILED status

### Antigravity prompt

> Implement Phase 5. Add an embedding service using one consistent model
> for ingestion and future query embeddings. Batch child chunks,
> initially 32 per batch. Add exponential backoff with jitter for
> transient 429/5xx errors and isolate malformed chunks where practical.
> Create the Qdrant collection and one-time keyword payload indexes for
> user_id and document_id. Upsert child vectors with child_id,
> parent_chunk_id, parent_text, document_id, user_id, subject, and page
> metadata. Use deterministic child IDs as Qdrant point IDs. Mark
> PostgreSQL documents READY only after successful indexing and FAILED
> with useful error_reason on failure. Add tests for batching, retry
> behavior, payloads, and Qdrant filtering fields. Do not add agents
> yet.

## PHASE 6 --- Basic RAG Chat (No Agents Yet)

### Build

-   sessions
-   messages
-   last 3--4 history turns
-   raw query embedding
-   Qdrant user/document filter
-   Top 15 retrieval
-   cross-encoder reranking
-   Top 3--4 parent context
-   grounded prompt
-   relevance refusal
-   citations
-   SSE

### APIs

`POST /chat` `GET /sessions` `GET /sessions/{session_id}/messages`

### Antigravity prompt

> Implement Phase 6. Build the first complete RAG chat pipeline WITHOUT
> agentic components. POST /chat requires JWT and receives session_id,
> document_id, and message. Fetch only the last 3--4 messages and
> reverse them into chronological order. Use the raw message directly as
> the search query for this phase. Embed it using the same model as
> ingestion. Search Qdrant using both authenticated user_id and selected
> document_id, retrieving Top 15. Rerank with the cross-encoder. Take
> the strongest 3--4 child results, deduplicate parent_chunk_id while
> preserving rank order, and use parent_text/page metadata as context.
> Use a strict prompt that answers only from context, refuses when
> evidence is insufficient, and cites \[Source X\]. Add configurable
> relevance threshold, SSE streaming, and PostgreSQL message/citation
> persistence. Do not implement Query Router, CRAG, or Hallucination
> Grader yet. The goal is a stable end-to-end RAG baseline.

## PHASE 7 --- RAG Agents + Reliability

### Build

-   Query Router & Rewriter Agent
-   CRAG Agent
-   Hallucination & Citation Grader
-   one regeneration
-   unified refusal

### Antigravity prompt

> Implement Phase 7. Add exactly the three RAG-side agentic components
> defined in brain.md. First add the Query Router & Rewriter as one
> structured LLM call accepting raw message + recent history and
> returning route = direct_chat \| rag_query \| quiz_mode plus
> rewritten_query. Do not create separate router and rewriter agents. If
> rewriting fails, fall back to the raw message. For rag_query, use
> rewritten_query for embedding. For direct_chat, provide a direct
> response. For quiz_mode, route to the quiz branch but do not implement
> the full quiz feature in this phase. Next add CRAG after cross-encoder
> reranking only when the top score is below the configured threshold.
> CRAG generates one alternative query and reruns embedding -\> Qdrant
> -\> rerank exactly once. If still weak, use unified refusal. Finally
> add the Hallucination & Citation Grader after complete LLM generation.
> Buffer the answer before SSE. Grade groundedness and citation support
> using structured output. If it passes, stream it. If it fails,
> regenerate exactly once using the SAME retrieved context, grade again,
> then stream if it passes or refuse if it fails. Never trigger CRAG
> from the grader and never allow loops. Keep all state transitions
> explicit. Add tests for every branch.

## PHASE 8 --- Quiz + Auto-Grading Agent

### Build

-   quiz tables
-   quiz APIs
-   Quiz/Diagnostic Agent
-   weak-topic detection
-   Qdrant retrieval
-   structured quiz JSON
-   Pydantic validation
-   quiz UI
-   deterministic MCQ grading
-   attempts/score/feedback

### APIs

`POST /quiz/generate` `GET /quiz/{quiz_id}`
`POST /quiz/{quiz_id}/submit` `GET /quiz/history`

### Antigravity prompt

> Implement Phase 8. Build the separate Quiz/Diagnostic Agent branch.
> Add quizzes and quiz_attempts tables and the quiz APIs. The agent
> should read previous attempts, identify weak topics with a simple
> initial rule such as accuracy below 60%, retrieve a small number of
> relevant Qdrant chunks using authenticated user/document filters, and
> generate MCQs as strict structured JSON. Validate generated data with
> Pydantic before saving. Build the Next.js quiz UI. On submission,
> grade MCQs deterministically by comparing submitted_answer with the
> stored correct_answer. Save attempts, score, topic, and timestamp.
> Show score and concise feedback. Do not use an LLM to determine
> whether an MCQ answer is correct. Do not route quiz requests through
> the normal chat answer pipeline.

## PHASE 9 --- Security + Evaluation + Observability

### Build

-   ownership/security tests
-   RAG evaluation set
-   retrieval tests
-   groundedness tests
-   citation tests
-   refusal tests
-   CRAG recovery tests
-   agent branch tests
-   quiz tests
-   latency/error logs

### Antigravity prompt

> Implement Phase 9 without changing the architecture. Add tests proving
> users cannot access another user's documents, vectors, sessions,
> messages, quizzes, or attempts. Create a small RAG evaluation set
> covering answerable, unanswerable, conversational follow-up, weak
> retrieval, successful CRAG recovery, unsuccessful CRAG, grounded
> answer, unsupported answer, and citation correctness. Test Query
> Router routes, fallback behavior, grader pass/fail/regeneration, and
> quiz validation/grading. Add structured logs for document processing,
> embedding, retrieval, reranking, generation, CRAG, grading, and quiz
> operations. Record useful latency measurements. Do not build a
> separate analytics platform.

## PHASE 10 --- UI Polish + Docker + Deployment + Resume

### Build

-   dashboard
-   document list/status
-   polished chat UI
-   streaming states
-   citations/page display
-   refusal state
-   quiz UI
-   score/feedback
-   Docker
-   deployment configuration
-   README
-   final architecture diagram

### Antigravity prompt

> Implement Phase 10 without changing the core architecture. Polish the
> Next.js dashboard, document upload/status UI, chat UI, streaming
> states, page/source citations, refusal state, quiz UI, score and
> feedback. Add loading, error, empty, and processing states. Dockerize
> the application and prepare production configuration using environment
> variables only. Never expose API keys in browser code. Update README
> with overview, architecture, pipeline, technology stack, local setup,
> environment variables, API overview, RAG flow, agent flow, quiz flow,
> security, testing, and deployment. Add the final V4 architecture
> diagram. Do not introduce new agents, databases, queues, frameworks,
> or complexity.

------------------------------------------------------------------------

# 11. Critical Build Order

``` text
Phase 1  Foundation
   ↓
Phase 2  Auth + DB
   ↓
Phase 3  PDF Upload + Worker
   ↓
Phase 4  Extraction + Chunking
   ↓
Phase 5  Embeddings + Qdrant
   ↓
Phase 6  Basic RAG
   ↓
Phase 7  RAG Agents
   ↓
Phase 8  Quiz Agent
   ↓
Phase 9  Testing + Security
   ↓
Phase 10 Polish + Deployment
```

Do NOT build agents before the basic RAG pipeline works. This is
deliberate: it makes the system easier to debug and gives a stable
baseline before adding agentic decisions.

Do NOT build quiz before the core RAG system is working.

------------------------------------------------------------------------

# 12. What Not To Add

Unless a real requirement appears, do not add:

-   Kubernetes
-   Kafka
-   multiple vector databases
-   Neo4j
-   LangGraph solely for the label
-   agent-to-agent messaging
-   infinite loops
-   complex memory systems
-   web search for document answers
-   external knowledge retrieval
-   knowledge graphs
-   microservices
-   complicated mastery models
-   LLM-based MCQ grading
-   extra agents

------------------------------------------------------------------------

# 13. Recruiter Explanation

> I built a full-stack AI learning assistant that lets students upload
> their lecture notes and textbooks and ask questions over their own
> study material. Documents are processed asynchronously with Celery,
> extracted page-by-page with PyMuPDF, hierarchically chunked, embedded,
> and stored in Qdrant. For conversational queries, the system rewrites
> the question when needed, performs user/document-filtered retrieval
> and cross-encoder reranking, and uses corrective retrieval when
> evidence is weak. The generated answer is grounded in the retrieved
> context and verified by a hallucination and citation grader before
> being streamed with page-level citations. I also added an adaptive
> quiz system that identifies weak topics and generates targeted MCQs
> with deterministic auto-grading.

The agentic design is intentionally bounded: four agentic components,
explicit branches, one CRAG retry, and one answer regeneration.
Deterministic components remain normal services.

------------------------------------------------------------------------

# 14. Final Design Principle

``` text
WORKING > COMPLEX
EXPLAINABLE > FANCY
RELIABLE > MANY FEATURES
```

This is the locked V4 project brain. Do not expand the architecture
unless implementation evidence requires it.

------------------------------------------------------------------------

# 15. Implementation Progress & Current Status

## Current Status: DAY 7 COMPLETED & FULLY VERIFIED (240/240 Tests Passing)

### IMPLEMENTED (Tested & Verified)

#### Day 1 — Backend Foundation & PDF Extraction
- **FastAPI Core**: Application lifecycle, CORS, health endpoint (`/health`), upload endpoint (`/documents/upload`), document status endpoint (`/documents/{document_id}`), and document list endpoint (`/documents`).
- **Database Tracking**: Document model tracking status (`PROCESSING`, `READY`, `FAILED`), page count, filename, upload path, and timestamps (configured for PostgreSQL with SQLite fallback for local development).
- **PDF Upload & Storage**: Validates PDF file signature, size limit (50 MB), and saves to `data/uploads/{document_id}.pdf`.
- **PyMuPDF Extraction (`pdf_service.py`)**: Page-by-page extraction preserving 1-indexed page boundaries, detects scanned/image-only pages (<50 characters), and provides minimal whitespace and control character normalization.

#### Day 2 — Text Cleaning, Parent-Child Chunking, Metadata & Local Embeddings
- **Deep Text Cleaning (`cleaning_service.py`)**:
  - Boundary-aware header/footer detection: analyzes only page boundaries (top 2 and bottom 2 non-empty lines) across >= 3 pages to detect running headers/footers without stripping body paragraphs or educational content.
  - Normalizes line endings (`\r\n` / `\r` -> `\n`).
  - Normalizes common typographical ligatures and quotes (`fi`, `fl`, `ff`, smart quotes, em-dashes).
  - Repairs hyphenation line-break artifacts (`infor-\nmation` -> `information`).
  - Collapses excessive internal whitespace while preserving paragraph and sentence structures.
- **Hierarchical Parent-Child Chunking (`chunking_service.py`)**:
  - **Parent Chunks**: 2,800 characters (~700 tokens), 200 character overlap. Captures broad contextual sections and maintains global page boundaries (`page_start`, `page_end`).
  - **Child Chunks**: 800 characters (~200 tokens), 120 character overlap. Derived from parent text, sized for precise dense semantic retrieval.
  - **Boundary Sensitivity**: Splits on paragraph breaks (`\n\n`) preferentially, falling back to sentence terminators (`.`, `!`, `?`) to preserve meaning.
  - **Deterministic IDs**: Chunk IDs are stable across processes and runs using UUID5 on `NAMESPACE_DNS` seeded with SHA-256 hashes of chunk text:
    - Parent ID: `uuid5(NAMESPACE_DNS, f"{document_id}|P|{index}|{sha256(text)}")`
    - Child ID: `uuid5(NAMESPACE_DNS, f"{parent_id}|C|{index}|{sha256(text)}")`
- **Chunk Metadata**:
  Every child chunk carries:
  ```json
  {
    "child_id": "<uuid5>",
    "document_id": "<uuid4>",
    "user_id": "dev-user-001",
    "subject": "<subject_name>",
    "page_start": 1,
    "page_end": 1,
    "parent_id": "<parent_uuid5>",
    "text": "..."
  }
  ```
- **Local Embedding Service (`embedding_service.py`)**:
  - **Model**: `all-MiniLM-L6-v2` via `sentence-transformers` (runs 100% locally and offline; no API key, no account, no cost).
  - **Embedding Dimension**: 384-dimensional fixed float vectors.
  - **Performance Optimization**: Singleton lazy loading (loads once per process, cached in memory), batch processing with `BATCH_SIZE = 32`.
  - **Clean Public Interface**: `embed_texts()`, `embed_chunks()`, `get_embedding_dimension()`, and `get_embedding_model()`.
- **Pipeline Orchestration (`pipeline_service.py`)**:
  - Full automated sequence: `extract_text_from_pdf` -> `clean_document_pages` -> `generate_chunks` -> `embed_chunks` -> `upsert_document_chunks` -> saves JSON to `data/processed/{document_id}.json`.
  - Integrated into FastAPI background task on upload.
- **Local Processed Output (`data/processed/`)**:
  - Structured JSON format containing document metadata, parent chunks, embedded child chunks, and pipeline execution statistics.

#### Day 3 — Vector Database Integration (Qdrant)
- **Qdrant Client & Service (`qdrant_service.py`)**:
  - Environment-based configuration via `Settings` (`QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_NAME`, `QDRANT_BATCH_SIZE`).
  - Automatic embedded disk storage fallback (`data/qdrant_local/`) when Docker Qdrant is unavailable, matching the PostgreSQL -> SQLite fallback pattern for seamless offline development.
  - Supports `:memory:` client for hermetic offline testing and automated integration testing.
  - Idempotent collection lifecycle (`ensure_collection`): dimension 384, distance `Cosine`. Never drops or overwrites collections on startup.
- **Payload & Indexing**:
  - Keyword payload indexes created once for `user_id` and `document_id`.
  - Rich payload stored per child point: `child_id`, `parent_chunk_id`, `parent_text`, `document_id`, `user_id`, `subject`, `page_start`, `page_end`, `text`, `chunk_index`.
- **Deterministic Point IDs & Idempotency**:
  - Uses UUID5 child chunk ID as Qdrant point ID.
  - Repeated upserts with identical document/chunk data overwrite points rather than creating duplicates.
- **Batched Upsert Pipeline**:
  - Batched point ingestion (`QDRANT_BATCH_SIZE = 64`) with vector validation.
  - Seamlessly integrated into `run_ingestion_pipeline` and FastAPI background upload handler.
  - Terminal failure during vector ingestion properly marks document status `FAILED`.
- **Docker Compose Setup**:
  - Added `qdrant` service (`qdrant/qdrant:latest`, ports `6333:6333`, `6334:6334`) and persistent volume `qdrant_data`.
- **Testing & Verification**:
  - 15 automated tests in `backend/tests/test_qdrant_service.py` (100% passing).
  - Full backend test suite passing (156/156 tests passing).
  - End-to-end verified with real lecture PDF (`lec-1.pdf`) and live manual API testing via Swagger UI (`/docs`).

#### Day 4 — Core RAG Pipeline, Retrieval, Reranking, Refusal & Chat Persistence
- **Core RAG Pipeline (`app/api/chat.py`, `app/services/llm_service.py`, `app/services/reranker_service.py`)**:
  - Clean non-streaming baseline without premature agents or SSE streaming.
  - Full pipeline: auth dependency -> validate session & document ownership -> validate document `READY` -> load chronological history -> embed query with `all-MiniLM-L6-v2` -> Qdrant Top-15 search (`user_id` + `document_id` payload filters) -> FlashRank cross-encoder reranking -> weak-evidence threshold check (`RERANK_THRESHOLD = 0.35`) -> refusal on weak evidence -> parent-context reconstruction (`RERANK_TOP_K = 4`) on strong evidence -> grounded LLM generation -> citation extraction -> database message persistence -> JSON response.
- **Qdrant Top-15 Vector Retrieval**:
  - Employs `QdrantClient.query_points` (with legacy `.search` fallback) to retrieve top 15 candidate child vectors strictly filtered by both `user_id` and `document_id`.
- **Cross-Encoder Reranking (`reranker_service.py`)**:
  - Uses local FlashRank (`ms-marco-TinyBERT-L-2-v2`, runs locally without external API keys).
  - Evaluates query against candidate child passages and ranks by relevance score.
  - Parent deduplication: selects top unique parent contexts up to `RERANK_TOP_K = 4`, preserving rank order with highest child score.
- **Weak-Evidence Refusal**:
  - Configurable threshold (`RERANK_THRESHOLD = 0.35`).
  - If top reranker score is below threshold, immediately returns standard unified refusal: `"I couldn't find sufficient information in your uploaded documents to answer that question."`
  - Refusal is persisted to chat history and returned without hallucinating from outside knowledge.
- **Parent-Context Reconstruction**:
  - Strong evidence chunks swap child chunk text for their complete parent context (`parent_text`), preserving `page_start`, `page_end`, and `document_id` metadata for rich LLM context.
- **Non-Streaming LLM Generation (`llm_service.py`)**:
  - Model configured to `openai/gpt-oss-120b` via Groq API.
  - Server-side environment key handling via `RAG_API_KEY` and `RAG_MODEL`.
  - Strict grounding prompt: enforces answering exclusively from provided parent contexts, cites numbered sources, and prohibits external knowledge.
- **Citation Metadata**:
  - Extracts structured citations (`source_id`, `document_id`, `page_start`, `page_end`, `parent_chunk_id`, `subject`) aligned with `[Source N]` tags.
- **PostgreSQL / SQLite Chat Persistence (`models/session.py`, `models/message.py`)**:
  - `Session` model: `id`, `user_id`, `document_id`, `created_at`.
  - `Message` model: `id`, `session_id`, `sender` ("user" | "assistant"), `content`, `citations` (JSON text), `created_at`.
  - Deterministic millisecond timestamp offset ensures strict chronological ordering across turns.
- **Authorization & Ownership Checks**:
  - FastAPI auth dependency `get_current_user()` returns authenticated user (`dev-user`).
  - Session ownership verified: 403 on mismatched user, 404 on missing session.
  - Document ownership verified: 403 on mismatched user, 404 on missing document, 422 on not `READY`.
  - Request document ID validated against session document ID: 400 on mismatch.
- **API Endpoints**:
  - `POST /sessions`: Create new conversation session for a document.
  - `GET /sessions`: List user's sessions (newest first).
  - `GET /sessions/{session_id}/messages`: List session messages (chronological order).
  - `POST /chat`: Main RAG chat endpoint (non-streaming JSON).
  - `GET /chat/status`: Status and feature manifest.
- **Testing & Verification**:
  - Automated tests: 26/26 tests passing in `backend/tests/test_chat.py`.
  - Full test suite: 180/180 tests passing (2 skipped for live docker integration).
  - Manual end-to-end verification (A-J) against live FastAPI server with real study materials and `openai/gpt-oss-120b`.

#### Day 5 — Query Router/Rewriter Agent & CRAG Agent (DAY 5 = COMPLETED AND VERIFIED)
- **Status**: COMPLETED AND VERIFIED (100% test pass rate, all manual verification checks A-I passing against live server).
- **Agent 1: Query Router & Rewriter Agent (`app/services/query_router_service.py`)**:
  - Implemented as a bounded service executing **ONE structured LLM call** (not two agents).
  - Strict Pydantic schema `RouterOutput` validating `route: Literal["direct_chat", "rag_query", "quiz_mode"]` and `rewritten_query: str`.
  - Fast-path heuristic: simple conversational greetings immediately route to `direct_chat` without LLM latency.
  - Route behavior:
    - `direct_chat`: Greetings, pleasantries, small talk. Skips retrieval completely and uses `generate_direct_chat_response` without inventiveness.
    - `rag_query`: Study questions requiring document retrieval. Resolves pronouns/references against recent chronological history into a standalone search query.
    - `quiz_mode`: Quiz generation requests. Cleanly routed to a Day-6 reserved stub response (no quiz questions or tables created).
  - Safe fallback: On any LLM timeout, malformed JSON, or API exception, safely defaults to `route="rag_query"` with `rewritten_query=original_user_query`.
  - Retrieval rule enforced: Rewritten query replaces ONLY the query used for retrieval; original user message is preserved in PostgreSQL and LLM context.
- **Agent 2: CRAG Agent (`app/services/crag_service.py`)**:
  - Implemented as a separate bounded service executing a structured LLM call.
  - Strict Pydantic schema `CRAGOutput` validating `alternative_query: str`.
  - Triggered **ONLY** when initial retrieval yields weak evidence (`score < RERANK_THRESHOLD`). Never called for direct_chat, quiz_mode, or strong retrieval.
  - Generates exactly **ONE** concise alternative search query (target <= 60 tokens / under 300 characters) using synonyms, entity expansion, and clearer phrasing.
  - Enforces exactly **ONE** retrieval retry:
    - If retry evidence is strong -> proceeds to Day-4 grounded RAG generation.
    - If retry evidence is still weak -> returns standard Day-4 refusal: `"I couldn't find sufficient information in your uploaded documents to answer that question."`
  - Safe fallback: On CRAG model failure, timeout, or invalid output, immediately returns the standard Day-4 refusal. Never loops or retries more than once.
  - Centralized retrieval reuse: CRAG retry reuses the identical `search_and_rerank` pipeline with authenticated `user_id` and `document_id` security filters strictly enforced.
- **Configuration & Provider Isolation (`app/config.py`, `.env.example`)**:
  - Dedicated configuration settings added: `ROUTER_API_KEY`, `ROUTER_MODEL` (default: `llama-3.1-8b-instant`), `CRAG_API_KEY`, `CRAG_MODEL` (default: `llama-3.1-8b-instant`).
  - Seamless fallback to `RAG_API_KEY` when dedicated router/CRAG keys are not specified.
  - Never hardcodes or logs API keys.
- **Chat Endpoint Integration (`app/api/chat.py`)**:
  - Updated `POST /chat` to integrate Router and CRAG seamlessly into the Day-4 pipeline.
  - Strictly non-streaming JSON responses maintained (no SSE, no `StreamingResponse`).
  - Updated `GET /chat/status` feature manifest (`query_router`, `crag_agent`, `day=5`).
- **Testing & Verification**:
  - Dedicated Day-5 tests: 19/19 passing in `backend/tests/test_day5_agents.py` covering requirements A through Q.
  - Full backend test suite: 199/199 passing (2 skipped for live docker integration).
  - Manual end-to-end verification (A-I) against live FastAPI application:
    - Check A: Simple Greeting ("Hello") -> `direct_chat`, fastpath, no Qdrant retrieval, no CRAG, normal JSON (PASS).
    - Check B: Normal RAG Question -> `rag_query`, rewritten query used internally, Qdrant retrieval, citations returned (PASS).
    - Check C: Follow-up Question -> History context resolved, rewritten query generated, retrieval performed (PASS).
    - Check D & F: Out-of-domain / Weak retrieval -> Initial retrieval weak -> CRAG triggered -> Exactly one retry performed -> Evidence still weak -> Standard Day-4 refusal returned (PASS).
    - Check G: Quiz request -> `quiz_mode` routing stub returned cleanly without creating quiz questions/tables (PASS).
    - Check H: Security -> Session ownership and document ownership strictly verified (404/400/403) (PASS).
    - Check I: Non-streaming verification -> Standard `application/json` response, no SSE, no `data: {"token": ...}` (PASS).
- **Deferred Boundaries Strictly Respected**:
  - No Hallucination/Citation Grader (Day 6).
  - No Quiz Agent generation or grading (Day 6).
  - No SSE streaming (Day 7).
  - No frontend / Next.js work (Day 7).
  - No new external frameworks (LangGraph, CrewAI, AutoGen) introduced.

---

#### Day 6 — Hallucination & Citation Grader + Adaptive Quiz Agent (DAY 6 = IMPLEMENTED AND VERIFIED)

- **Status**: IMPLEMENTED AND VERIFIED (100% test pass rate across 26 dedicated Day-6 tests, full suite 225/225 passing, and manual API verification passed).

##### Agent 3: Hallucination & Citation Grader (`app/services/grader_service.py`)
- Verified as a bounded service executing ONE structured LLM call (evaluates answer vs already-retrieved parent context).
- Evaluates grounding, citation correctness, and unsupported claims against supplied evidence.
- Does NOT perform retrieval, does NOT call CRAG, does NOT generate quizzes.
- Strict Pydantic schema `GraderOutput` validating `grounded: bool`, `confidence: float`, `critique: str`.
- Locked grader failure flow verified in `app/api/chat.py`:
  - Grader PASS -> verified answer returned immediately with citations.
  - Grader FAIL -> exactly one regeneration using the SAME retrieved context (no re-retrieval, no CRAG).
  - Regenerated answer PASS -> verified regenerated answer returned with citations.
  - Regenerated answer FAIL -> unified refusal returned (`REFUSAL_MESSAGE`), citations=[].
  - Maximum regeneration attempts = 1. No second regeneration, no infinite loop.
  - Grader failure NEVER triggers CRAG.

##### Agent 4: Adaptive Quiz & Diagnostic Agent (`app/services/quiz_service.py`)
- Verified as a separate pipeline from normal chat RAG.
- Weak-topic detection verified: simple locked rule `accuracy < 60%`.
- Topic retrieval verified: approximately 3 parent chunks retrieved from Qdrant with `user_id` AND `document_id` security filters strictly enforced.
- MCQ generation verified: grounded in study material, 4 options each, validated by `QuizQuestion` Pydantic schema.
- Malformed LLM output handling verified: invalid questions filtered or rejected safely.
- Deterministic auto-grading verified: `submitted_answer == correct_answer` (exact string comparison). Score and percentage calculated strictly by backend application code — LLM never determines correctness.

##### Quiz API Endpoints & Persistence (`app/api/quiz.py`)
- `POST /quiz/generate`: Verified (document ownership check, weak-topic detection, Qdrant retrieval, MCQ generation, DB persistence, returns 201).
- `GET  /quiz/{quiz_id}`: Verified (ownership check, deserialization, returns 200; 403 on other user's quiz, 404 on invalid ID).
- `POST /quiz/{quiz_id}/submit`: Verified (ownership check, deterministic grading, `quiz_attempts` persistence, returns 200; 422 on empty answers).
- `GET  /quiz/history`: Verified (user-isolated quiz history with latest attempt statistics).
- `GET  /quiz/status`: Verified (Day 6 feature manifest; path ordering fixed to prevent shadowing).

##### Authentication, Ownership & Security
- Authenticated identity strictly derived from `get_current_user()` dependency (never trusted from request body).
- Cross-user access strictly rejected with 403 Forbidden for generation, retrieval, submission, and history.
- Every Qdrant retrieval strictly enforces `user_id == authenticated_user` AND `document_id == selected_document`.

##### Verification & Test Results
- Dedicated Day-6 tests: 26/26 passing in `backend/tests/test_day6.py` covering all required verification points 1–26.
- Full regression suite: 225/225 passing (2 skipped for live Qdrant container) across all test files.
- Manual API verification: Passed for all endpoints (`POST /quiz/generate`, `GET /quiz/{quiz_id}`, `POST /quiz/{quiz_id}/submit`, `GET /quiz/history`, `GET /quiz/status`).

##### Day 6 Boundaries Respected
- Preserved locked agent count at exactly four (Router, CRAG, Grader, Quiz).
- Deterministic auto-grading cleanly decoupled from LLM chat generation.

---

#### Day 7 — Next.js Frontend + SSE Streaming + Auth Integration + Full Integration & Testing (DAY 7 = COMPLETED AND VERIFIED)

- **Status**: COMPLETED AND FULLY VERIFIED (100% test pass rate across 240/240 backend regression tests, 14/14 manual E2E test scenarios A–N passing, and Next.js frontend production build passing with 0 errors).

##### Authentication & Authorization Integration
- **JWT & Bearer Tokens**: Implemented `POST /auth/login`, `GET /auth/me`, and `GET /auth/status`.
- **Reusable Server-Side Dependency (`get_current_user`)**:
  - Verifies token integrity and extracts subject user ID.
  - Development fallback: seamlessly falls back to `"dev-user"` when no Authorization header is provided.
  - **Never trusts client-supplied `user_id`**: Backend derives authenticated identity exclusively from the token dependency.
- **Cross-User Isolation**:
  - Enforced across document upload, document viewing, chat sessions, message streaming, and quiz generation/submission/history.
  - Mismatched user accesses return HTTP 403 Forbidden.
  - Qdrant queries enforce payload filters: `user_id == authenticated_user` AND `document_id == selected_document`.

##### Server-Sent Events (SSE) Streaming (`POST /chat/stream`)
- **FastAPI `StreamingResponse`**: Uses `media_type="text/event-stream"`.
- **CRITICAL RULE 15 ENFORCED — No Unverified Answers Streamed**:
  - Unverified RAG answers are NEVER streamed token-by-token.
  - Full RAG response is generated internally, buffered, and passed to Agent 3 (Hallucination & Citation Grader).
  - **Grader PASS**: Verified answer streamed to frontend as SSE events (`data: {"token": "..."}\n\n`), ending with `data: {"done": true, "citations": [...]}\n\n`.
  - **Grader FAIL**: Regenerates answer ONCE using the **SAME retrieved context** (no re-retrieval, no CRAG). Grader re-evaluates.
  - **Regenerated PASS**: Streamed as verified answer with citations.
  - **Regenerated FAIL**: Streams standard refusal message (`REFUSAL_MESSAGE`), then `data: {"done": true, "citations": []}\n\n`.
  - **Maximum regeneration attempts**: Exactly 1. No infinite loops.
- **Direct Chat & Greetings**: Handled via fast-path / Agent 1 direct chat, streamed without Qdrant vector retrieval.

##### Next.js 16.3.4 Frontend (`frontend/`)
- Built with TypeScript, React 19, and Tailwind CSS.
- **Pages**:
  - `/login`: Clean functional login page supporting custom credentials and one-click Quick Dev Login (`dev-user`).
  - `/dashboard`: Document metrics cards, processing status badges (`PROCESSING`, `READY`, `FAILED`), and quick-action navigation.
  - `/documents`: PDF upload form (`multipart/form-data`) + subject, live 3-second auto-polling for documents undergoing background processing.
  - `/chat`: Document selector, session list/creation, chronological message history, real-time SSE token streaming, citation badges (`[Source N] Page X`), refusal UI, and concurrent request locking.
  - `/quiz`: Topic input, adaptive quiz generation via Agent 4, multiple choice question options, deterministic auto-grading result display, and quiz attempt history with weak-topic diagnostics (`accuracy < 60%`).
- **Components & Lib**:
  - `Navbar.tsx`: Sticky responsive header with branding, 4-agent status, navigation, and user authentication state.
  - `lib/api.ts`: Centralized API client handling JWT bearer headers, error normalization, and SSE streaming via `ReadableStreamDefaultReader`.
  - `types/index.ts`: Strict TypeScript interfaces for User, Documents, Sessions, Messages, Citations, and Quizzes.

##### Four Bounded Agents Verification
- **Agent 1: Query Router & Rewriter** (`app/services/query_router_service.py`)
- **Agent 2: CRAG Agent** (`app/services/crag_service.py`)
- **Agent 3: Hallucination & Citation Grader** (`app/services/grader_service.py`)
- **Agent 4: Adaptive Quiz & Diagnostic Agent** (`app/services/quiz_service.py`)
- **Strictly No 5th Agent**: No extra agents, planners, or memory agents were created.

##### Testing & Security Verification
- **Automated Tests**: 240 passed, 0 failed in `backend/tests/` (including 13 dedicated Day 7 tests in `backend/tests/test_day7.py`).
- **Manual E2E Test Suite (`verify_day7_e2e.py`)**: All 14 scenarios (Tests A through N) passed:
  - Test A: Login (PASS)
  - Test B: Document Upload (PASS)
  - Test C: Document List (PASS)
  - Test D: Normal RAG SSE (PASS)
  - Test E: Follow-up Pronoun Rewrite (PASS)
  - Test F: Greeting / Direct Chat (PASS)
  - Test G: Weak Retrieval + CRAG Refusal (PASS)
  - Test H: Grader Regeneration Fail -> Pass (PASS)
  - Test I: Grader Double Failure -> Refusal (PASS)
  - Test J: Quiz Generation (PASS)
  - Test K: Deterministic Quiz Grading (PASS)
  - Test L: Quiz History & Weak Topics (PASS)
  - Test M: Security & Cross-User Isolation (PASS)
  - Test N: SSE Protocol Integrity (PASS)
##### Day 7 Final Authentication, Weak Topic & UI Enhancements
- **Google Sign-In with Google Identity Services (GIS)**:
  - Frontend loads official GIS script and renders official button with `Continue with Google`.
  - Backend verifies ID token cryptographically via `verify_google_token` (`POST /auth/google`).
  - Derives stable `user_id = f"google_{sub}"` (Google `sub` claim — never email as primary ID).
  - Persists `User` entity to PostgreSQL `users` table and issues application Bearer token.
  - Client-side route protection via `useAuth(true)` redirects unauthenticated users to `/login`.
  - Navbar dynamically reflects authenticated user profile and provides "Sign Out".
- **React Key Warning Elimination**:
  - Identified root cause in `src/app/chat/page.tsx`: backend `MessageResponse` returned `message_id`, causing `msg.id` to be undefined and falling back to non-unique index keys.
  - Normalized `id` in `getSessionMessages` and updated `ChatMessage` type with `message_id`.
  - Deduplicated `sessions` and `documents` to guarantee unique IDs.
  - Applied stable `parent_chunk_id` for citation elements.
- **Clean Citation Presentation**:
  - Normalized citations in `src/app/chat/page.tsx` to display `[Source N] <filename> · Page <page_num>` without redundant `"Source"` prefixes (preventing `[Source Source 1]`).
- **Complete Actionable Weak Topic Behavior**:
  - Diagnostic threshold: `< 60% = Weak`, `>= 60% = Mastered / Not Weak`.
  - Updated `detect_weak_topics` to evaluate latest attempt result per topic.
  - Quiz completion card displays actionable diagnostic alert and `[Practice Weak Topic]` button when accuracy `< 60%`.
  - Quiz History table includes actionable `[Practice Weak Topic]` button for all weak topics.
  - Targeted weak-topic practice routes directly to existing Agent 4 with user + document filtering.
- **Dashboard Weak Topics Section**:
  - Added dedicated "Weak Topics" section to `/dashboard` displaying weak topics, accuracy percentage, and a `[Practice]` button linking to the targeted quiz.
  - Displays `"No weak topics detected."` when all topics are $\ge 60\%$.
- **Document Date Display**:
  - Added `created_at` field to `DocumentSummary` Pydantic schema and `document_to_summary` mapping function so existing database upload timestamps are properly serialized and rendered instead of `—`.
- **Architecture Integrity**:
  - Maintained exactly 4 bounded agents (Router, CRAG, Grader, Quiz).
  - Preserved all locked RAG rules and deterministic grading logic.

---

## Day 7 — Final UX / Auth / Theme Polish (implemented 2026-09-12)

### Root Causes Fixed

- **"Rendering…" indefinite spinner** — `useAuth` called `setLoading(false)` only when a token existed, but not in the `requireAuth && !token` redirect path. Pages that consumed `loading` were therefore stuck. Fix: `useAuth` now uses a `checked` ref to run the check exactly once and always resolves `loading` to `false` in non-redirect paths. Also added an explicit 8-second GIS timeout on the login page so "Loading Google Sign-In…" never hangs forever.
- **React key warning in Chat** — `<button key={sess.id}>` used `sess.id` but the `ChatSession` object has `session_id`. Fixed to use `sess.session_id || sess.id`.
- **Data fetch racing auth redirect** — Dashboard, Documents, Chat, and Quiz pages all started API calls on mount regardless of auth state. If `useAuth` was redirecting the user to `/login`, the API calls still fired (returning 401). Fixed by gating all initial data fetches with `if (authLoading) return` in `useEffect`.
- **Hydration mismatch on Navbar** — Auth state and theme are localStorage-based (client-only), but Navbar rendered on server with no auth. Fixed with a `mounted` state gate so the auth section renders only after client mount.
- **Theme flash on hard reload** — No theme was applied before React hydrated. Fixed by injecting an inline `<script>` in `layout.tsx` that reads localStorage and applies `data-theme` + `.dark` class synchronously, before the first paint.

### Files Changed

| File | Change |
|---|---|
| `frontend/hooks/useAuth.ts` | Fixed indefinite loading; uses `checked` ref; all paths resolve `loading=false` |
| `frontend/hooks/useTheme.ts` | **New** — Light/Dark/Green theme hook with localStorage persistence |
| `frontend/src/app/globals.css` | **Rewritten** — Full CSS custom property system for all 3 themes |
| `frontend/src/app/layout.tsx` | Added inline theme-init script; `suppressHydrationWarning`; removed hardcoded Tailwind bg/text classes |
| `frontend/components/Navbar.tsx` | **Rewritten** — removed "4 Agents" pill, removed "Student" role label, added Light/Dark/Green theme picker dropdown, hydration-safe auth state, clean display name |
| `frontend/src/app/page.tsx` | **Rewritten** — removed "Day 7 — Locked 4-Agent Architecture" badge; removed "Agent 1/2/3/4" labels |
| `frontend/src/app/login/page.tsx` | **Rewritten** — 8-second GIS timeout; renamed dev button to "Continue as Guest"; `router.replace` instead of `router.push` |
| `frontend/src/app/dashboard/page.tsx` | Auth-gated fetch; full-page loading spinner; CSS vars throughout; removed internal pipeline description |
| `frontend/src/app/documents/page.tsx` | Auth-gated fetch; auth spinner; CSS vars; clean description text |
| `frontend/src/app/chat/page.tsx` | Fixed React key (session_id); auth-gated fetch; removed "4-Agent verified answers" subtitle; CSS vars |
| `frontend/src/app/quiz/page.tsx` | Removed "Agent 4 retrieves…" subtitle; auth-gated fetch; auth spinner; CSS vars |
| `frontend/next.config.ts` | Disabled `devIndicators` overlay (`devIndicators: false`) |

### Theme System

- 3 themes: `light`, `dark`, `green`
- Stored in `localStorage` under key `app-theme`
- Applied via `data-theme` attribute on `<html>` element
- Tailwind `dark:` utilities active when `data-theme="dark"` or `data-theme="green"` (`.dark` class added)
- Inline script in `layout.tsx` prevents theme flash on hard reload
- Theme persists across tabs and page reloads

---

## Final — Production Polish: Auth + Profile + Theme + Navigation + Full Regression Testing (VERIFIED 2026-09-12)

- **Status**: COMPLETE & FULLY VERIFIED (Full pytest regression suite 205 passed, 14 skipped hermetically, 0 failed across 219 test cases; dedicated Day 7 suite 17/17 passed; Next.js production build passing with 0 errors across all 8 static routes; E2E automated test suite 9/9 passed).

### 1. Dynamic Logo Navigation (Personal AI Assistant)
- **Contract Enforced**:
  - **Unauthenticated User**: Clicking `Personal AI Assistant` navigates to `/` (public landing page).
  - **Authenticated User**: Clicking `Personal AI Assistant` navigates directly to `/dashboard`. Authenticated users never unexpectedly return to the public landing page via logo clicks.
  - **Direct URL Access**: If an authenticated user manually browses to `/`, client-side effect immediately redirects them to `/dashboard` without redirect loops.

### 2. Unified Public & Authenticated Theme System
- **Single System**: One centralized theme engine (`frontend/hooks/useTheme.ts` + `frontend/src/app/globals.css`).
- **Logged-Out Users**:
  - Navbar renders `[ Theme ▼ ] [ Sign In ]`.
  - Logged-out users can change theme freely (`Light`, `Dark`, `Green`) before logging in.
  - Theme applies immediately, requires no login or backend call, and persists via `localStorage` under `app-theme`.
- **Logged-In Users**:
  - Standalone Theme button is removed from the navbar.
  - Theme control lives inside the Profile dropdown as an interactive submenu (`Theme › [Light, Dark, Green]`).
  - Active theme displays a clear checkmark indicator.
  - Theme selected before login remains active after login and survives hard reloads without flashing wrong colors (injected synchronous `<head>` script).

### 3. Authenticated Navbar & Profile Dropdown
- **Clean Navbar**: Renders `[AI] Personal AI Assistant`, links (`Dashboard`, `Documents`, `RAG Chat`, `Quiz`), and user control `[Avatar] [User Name ▼]`.
- **Strict Username Display**:
  - Displays ONLY the user's actual provided name or verified Google account name (e.g. `Dev Kumar`).
  - NEVER derives names from email, `email.split('@')[0]`, `user_id`, or database UUIDs.
  - NEVER hardcodes `Student`, `User`, or `Dev`.
  - If no name was provided (e.g. guest session), renders a clean neutral avatar control without inventing a name.
  - Email is strictly forbidden from the navbar and dropdown header.
- **Avatar**:
  - Displays verified profile image if present.
  - Generates initials only from actual user-provided names.
  - Falls back to a clean neutral SVG avatar icon.
- **Profile Dropdown**:
  - Header: Avatar + actual display name only.
  - Menu Items: Profile (`/profile`), Theme submenu (`Light`, `Dark`, `Green`), Sign Out.
  - Closes automatically on outside click, Escape key, or route navigation.

### 4. Profile Management & Read-Only Email
- **Profile Page (`/profile`)**:
  - Displays actual Name, Email, Profile Picture, and Authentication Provider.
  - "Edit Profile" allows the user to update their display name.
  - **Email Immutability**: Email is strictly read-only (`[ READ ONLY ]` badge, HTML disabled attribute). Backend `PUT /auth/profile` accepts only `username` and ignores/rejects any attempt to alter email.
- **Real-Time State Synchronization**:
  - Updating name in `/profile` calls `PUT /auth/profile` with Bearer token authentication.
  - Dispatches `"user-updated"` event to synchronize the navbar immediately without requiring a full page reload.
  - Blank names are rejected with HTTP 422 Unprocessable Entity.
  - Unauthenticated requests to `PUT /auth/profile` are strictly rejected with HTTP 401 Unauthorized via `require_authenticated_user`.

### 5. Sign Out (Public Landing Page UX)
- Located inside the Profile dropdown (and on `/profile`).
- **Required Behavior**:
  1. Clears application authentication token (`token`) and user object (`user`) from `localStorage`.
  2. Dispatches `"user-updated"` event to synchronize all mounted components instantly.
  3. Clears authenticated user state from frontend memory (`currentUser = null`).
  4. Closes profile dropdown and submenu.
  5. Implements double-click guard (`loggingOutRef`) to prevent duplicate logout requests or navigation collisions.
  6. Preserves global user preferences strictly (active theme such as `Green` or `Dark` is retained in `localStorage` under `app-theme`).
  7. Updates navbar immediately to logged-out state: `Personal AI Assistant` (links to `/`), main links, and `[ Theme ▼ ] [ Sign In ]`.
  8. Redirects immediately to `/` (Public Landing Page) via `router.replace("/")` (does NOT redirect to `/login`).
  9. The user can then explicitly click `Sign In` whenever they choose to authenticate again.

### 6. Loading & Performance Eliminating "Rendering..." Hang
- Replaced all indefinite "Rendering..." spinners with explicit state labels: "Signing in...", "Checking session...", "Connecting to Google...".
- Fixed `useAuth`: Guaranteed to resolve `loading` state to `false` in all lifecycle paths (SUCCESS → redirect; FAILURE → error notification).
- Gated all data-fetching effects on protected pages with `if (authLoading) return` to eliminate request races and 401 storms.
- Added 6-second timeout to Google Identity Services initialization to notify users gracefully rather than hanging forever.

### 7. Route Protection
- Protected routes: `/dashboard`, `/documents`, `/chat`, `/quiz`, `/profile`.
- Unauthenticated access redirects immediately to `/login`.
- Authenticated access to `/login` redirects immediately to `/dashboard`.

### 8. Development UI Cleanup
- Search across all pages removed engineering labels:
  - Removed "Day 1-7" and "Locked 4-Agent Architecture" badges.
  - Removed internal test counts ("240/240 Tests Passing").
  - Replaced "dev-user" button with user-friendly "Continue as Guest".
  - Hero CTA buttons given unified styling (`.hero-cta-btn`).

### 9. Preserved 4-Agent RAG & Quiz Architecture
- Exactly four agents remain:
  1. Query Router & Rewriter
  2. CRAG Agent (max 1 retry, refusal on failure)
  3. Hallucination & Citation Grader (max 1 regeneration with SAME context, no unverified streaming)
  4. Adaptive Quiz Agent (deterministic auto-grading `submitted_answer == correct_answer`, weak topic detection `< 60%`)
- No additional agents or pipelines were created.

### 10. Verification Summary
- **Backend Full Pytest Suite**: 205 passed, 14 skipped (live docker qdrant), 0 failed across 219 items (ran hermetically in 5m34s).
- **Backend Dedicated Day 7 Suite**: 17 passed, 0 failed (`pytest tests/test_day7.py -v` in 4.64s).
- **E2E Automated Script (`scratch/verify_final_e2e.py`)**: 9/9 passed:
  1. `/auth/status` (PASS)
  2. `/auth/login` (PASS)
  3. `/auth/me` with Bearer token (PASS)
  4. `PUT /auth/profile` update name (PASS)
  5. Profile name persistence (PASS)
  6. Email immutability during profile update (PASS)
  7. Blank name rejection 422 (PASS)
  8. Unauthenticated profile update rejection 401 (PASS)
  9. Frontend served on port 3000 (PASS)
- **Frontend Production Build**: `npm run build` completed with 0 errors across all 8 static pages in 2.4s.
- **Live Google Sign-In**: Confirmed live in server logs (`POST /auth/google` returned 200, authenticating `google_110853262066131569014`).

