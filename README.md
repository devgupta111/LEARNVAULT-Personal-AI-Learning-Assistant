# LEARNVAULT — Personal AI Learning Assistant

An agentic, full-stack learning assistant that enables students to upload lecture notes and textbooks, ask natural-language questions grounded strictly in their course material, receive factual answers with exact page-level citations, and master weak topics through adaptive auto-graded diagnostic quizzes.

---

## Architecture Overview

```
[ Student PDF Notes ]
         │
         ▼
[ PyMuPDF Extraction ] ──► [ Boundary-Aware Text Cleaning ]
                                     │
                                     ▼
                      [ Hierarchical Parent-Child Chunking ]
                        ├─ Parent: 2,800 chars (broad context)
                        └─ Child:    800 chars (dense semantic retrieval)
                                     │
                                     ▼
                      [ Local all-MiniLM-L6-v2 Embeddings ]
                                     │
                                     ▼
                      [ Qdrant Vector DB Ingestion ]
                                     │
┌────────────────────────────────────┴────────────────────────────────────┐
│                    FOUR BOUNDED AGENTS & CORE RAG                       │
│                                                                         │
│  1. Query Router & Rewriter Agent (LLM)                                │
│     └─ Fast-path greeting / direct chat OR multi-turn query rewriting   │
│                                                                         │
│  2. Corrective RAG (CRAG) Agent (LLM)                                  │
│     └─ Evaluates retrieval relevance (score < 0.35); max 1 query retry  │
│                                                                         │
│  3. Hallucination & Citation Grader (LLM)                              │
│     └─ Verifies answer grounding vs retrieved parent evidence          │
│     └─ Max 1 answer regeneration; safe refusal on double failure        │
│     └─ Streams only verified tokens via Server-Sent Events (SSE)        │
│                                                                         │
│  4. Adaptive Diagnostic Quiz Agent (LLM + Deterministic Engine)        │
│     └─ Generates 4-option MCQs grounded in student notes               │
│     └─ 100% deterministic grading (backend equality check)             │
│     └─ Weak topic detection: accuracy < 60% with targeted practice      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Core Features

- **Document Management**:
  - Drag-and-drop PDF upload with filename display, formatted file size, and file validation.
  - **Upload Limit**: Supports text-based PDF files up to **20 MB**.
  - Asynchronous extraction and processing pipeline (`PROCESSING` ➔ `READY` / `FAILED`).
  - Cascading deletion with an in-app confirmation dialog, permanently removing original PDF files, processed JSON files, temporary files, Qdrant vectors, chat history, and quizzes across all storage layers.

- **Grounded Conversational RAG**:
  - Top-15 Qdrant vector retrieval filtered by authenticated `user_id` and `document_id`.
  - FlashRank cross-encoder reranking (`ms-marco-TinyBERT-L-2-v2`) selecting top 4 parent contexts.
  - Strict grounding: answers exclusively from uploaded documents; refuses when evidence is insufficient.
  - Page-level citations displayed as clean clickable badges (`[Source N] <file> · Page X`).
  - Inline Chat Session Rename with persistent database updates and full message history retention.
  - **Quiz from Chat**: One-click transition from conversation to targeted quiz practice.

- **Adaptive Diagnostic Quizzes**:
  - Multiple-choice questions (4 options per question) generated from course notes.
  - **Deterministic Auto-Grading**: Exact string comparison (`submitted == correct`) calculated by backend code without LLM scoring bias.
  - **Score Bands & Diagnostics**:
    - **Strong**: 80%–100%
    - **Good**: 60%–79%
    - **Needs Practice / Weak**: `< 60%` (explicit rule: 59% is weak, 60% is not weak).
    - Context-aware Dashboard Weak Topics analysis displayed once actual quiz performance data exists.
  - Inline quiz topic rename in Quiz History table.
  - **Show Incorrect Answers Only**: Post-submission toggle filter for targeted revision without modifying scores or stored attempts.

- **Security & Data Isolation**:
  - Authentication via Google Identity Services (GIS) ("Continue with Google") and local/guest authentication.
  - Stateless Bearer tokens validating user identity across all endpoints.
  - Strict cross-user data isolation: users can only view, query, or delete their own documents, sessions, and quizzes.

- **Responsive Design & 3 Themes**:
  - Full-featured **Light ☀️**, **Dark 🌙**, and **Green 🌿** themes persisted across reloads without theme flash.
  - Fully responsive mobile experience with collapsible mobile navigation drawer.
  - Universal student-friendly **User Guide** modal accessible from Navbar, profile menu, and mobile drawer.
  - Unified theme-aware toast notification system.

---

## Technology Stack

| Layer | Technology | Description |
| :--- | :--- | :--- |
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4 | Responsive UI, SSE token streaming, theme engine |
| **Backend** | FastAPI, Python 3.10+, Pydantic v2, SQLAlchemy | Async REST APIs, SSE streaming, authentication |
| **Task Queue** | FastAPI `BackgroundTasks` | In-process asynchronous document ingestion (Redis & Celery are NOT wired into the active implementation) |
| **Vector DB** | Qdrant | 384-dimensional dense semantic search (Docker or local embedded) |
| **Database** | PostgreSQL / SQLite | User profiles, document metadata, chat history, quiz attempts |
| **Object Storage** | Supabase Storage (Private) | Persistent PDF storage in private bucket `learnvault-documents` (Render local filesystem is ephemeral/temporary) |
| **Embeddings** | `sentence-transformers` (`all-MiniLM-L6-v2`) | Runs 100% locally and offline (384-dim float vectors) |
| **Reranker** | FlashRank (`ms-marco-TinyBERT-L-2-v2`) | Local cross-encoder reranking without external API calls |
| **LLM Engine** | Groq API (`openai/gpt-oss-120b`, `llama-3.1-8b-instant`) | Fast inference for RAG generation and bounded agents |
| **PDF Engine** | PyMuPDF (`fitz`) | High-fidelity page extraction and scan detection |

---

## Local Setup Guide

### 1. Prerequisites
- **Python**: 3.10 or higher
- **Node.js**: 18 or higher (with npm)
- **Docker** *(optional)*: Docker Desktop for running PostgreSQL and Qdrant containers

> **Note on Zero-Configuration Local Fallbacks**:
> If PostgreSQL or Docker is not installed, the application automatically falls back to:
> - SQLite database at `data/ai_learning_local.db`
> - Embedded local Qdrant vector storage at `data/qdrant_local/`
> You can run and test the complete application without Docker or PostgreSQL.

---

### 2. Environment Configuration
Clone the repository and create your local `.env` file:

```powershell
# Copy the public example template to your private local .env
Copy-Item .env.example .env     # Windows PowerShell
cp .env.example .env            # macOS / Linux
```

Open `.env` and add your Groq API key:
```env
RAG_API_KEY=your_groq_api_key_here
```
*(Get a free API key at [console.groq.com](https://console.groq.com/keys). All 4 agents use `RAG_API_KEY` as a fallback if their dedicated keys are left blank.)*

---

### 3. Backend Setup

```powershell
# Navigate to backend directory
cd backend

# Create and activate Python virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1    # Windows
source .venv/bin/activate       # macOS / Linux

# Install backend dependencies
pip install -r requirements.txt

# Start the FastAPI server
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Backend will be available at: `http://127.0.0.1:8000` (API documentation at `http://127.0.0.1:8000/docs`).

---

### 4. Frontend Setup

In a separate terminal:
```powershell
# Navigate to frontend directory
cd frontend

# Install frontend dependencies
npm install

# Start the Next.js development server
npm run dev
```
Frontend will be available at: `http://localhost:3000`.

---

### 5. Docker Infrastructure *(Optional)*

To run PostgreSQL and Qdrant in Docker containers:
```powershell
# In the project root
docker compose up -d
```
- PostgreSQL: `localhost:5432` (`ai_learning_db`)
- Qdrant: `localhost:6333` / Web UI: `http://localhost:6333/dashboard`

---

## Quality Assurance & Verification

### Pre-Deployment Verification
All 259 automated regression and unit tests were executed with a 100% pass rate (245 passed, 14 skipped for optional local Docker services, 0 failures):
- PDF extraction and scanned-page detection
- Cleaning, chunking, and metadata validation
- Embeddings and Qdrant lifecycle
- Supabase Storage operations (persistent PDF upload, download, cascade deletion, guest purge)
- Core RAG, refusal, and conversational history
- Router & CRAG Agents
- Grader & Adaptive Quiz Agents
- Auth, SSE streaming, and cross-user data isolation
- Cascading deletion across all storage layers and session/topic rename

### Production Build & Type Check
```powershell
cd frontend
npm run build      # TypeScript validation + Next.js production build
```

---

## Bounded 4-Agent Architecture Specification

1. **Agent 1: Query Router & Rewriter (`query_router_service.py`)**:
   - Executes a single structured LLM classification.
   - Fast-path regex immediately routes social greetings to direct chat without LLM delay.
   - Rewrites follow-up questions to resolve pronouns against recent history before vector retrieval.
2. **Agent 2: Corrective RAG (CRAG) Agent (`crag_service.py`)**:
   - Triggered only when initial retrieval score is below `RERANK_THRESHOLD` (0.35).
   - Generates exactly **ONE** alternative search query.
   - If retry evidence remains weak, returns the unified refusal without looping.
3. **Agent 3: Hallucination & Citation Grader (`grader_service.py`)**:
   - Evaluates LLM draft answers against retrieved parent chunks.
   - Grader FAIL triggers exactly **ONE** answer regeneration using the **same context**.
   - If regeneration fails, safely returns the refusal message.
   - **Crucial Safety Rule**: Unverified answers are NEVER streamed token-by-token.
4. **Agent 4: Adaptive Quiz & Diagnostic Agent (`quiz_service.py`)**:
   - Generates grounded 4-option MCQs from student notes.
   - Identifies weak topics (`accuracy < 60%`) and offers targeted revision quizzes.
   - Auto-grading is 100% deterministic (`submitted == correct`) calculated in backend code.

---

## Security & Privacy Guidelines

- **No Secrets in Repository**: `.env` is ignored by `.gitignore`. Real API keys, passwords, and private tokens must never be committed.
- **Backend-Only Storage Credentials**: `SUPABASE_SECRET_KEY` is strictly server-side and never exposed to the frontend, logs, or repository. The storage bucket `learnvault-documents` is private.
- **Data Isolation**: All database queries and vector searches strictly enforce `user_id == authenticated_user`.
- **Read-Only Profile Fields**: User emails are immutable and read-only.
- **Client Identification**: Google Identity Services uses Web Client IDs (`GOOGLE_CLIENT_ID`) configured with authorized origins.

---

## License

This project is licensed under the MIT License — see the repository for details.
