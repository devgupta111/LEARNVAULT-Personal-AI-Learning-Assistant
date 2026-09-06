# Personal AI Learning Assistant

A full-stack RAG application that lets students upload lecture notes and PDFs,
ask natural-language questions about their own study material, and receive
grounded answers with page-level citations.

---

## Current Status — Day 1: Backend Foundation + PDF Upload + Extraction

What is implemented today:

- FastAPI backend with health endpoint
- PostgreSQL documents table
- PDF upload endpoint with validation
- Page-by-page text extraction using PyMuPDF
- Scanned-page detection
- Document processing status (PROCESSING → READY / FAILED)
- Document listing and status endpoints
- Tests for all of the above

What is NOT implemented yet (coming in later days):

- Text chunking
- Embeddings and Qdrant
- RAG question answering
- Agents
- Authentication
- Frontend

---

## Project Structure

```
personal-ai-learning-assistant/
├── frontend/                  Next.js app (Day 5+)
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI entry point
│   │   ├── config.py          Environment-variable settings
│   │   ├── api/
│   │   │   └── documents.py   Upload and status endpoints
│   │   ├── db/
│   │   │   ├── base.py        SQLAlchemy declarative base
│   │   │   └── database.py    Engine and session factory
│   │   ├── models/
│   │   │   └── document.py    Documents ORM model
│   │   ├── schemas/
│   │   │   └── document.py    Pydantic request/response schemas
│   │   └── services/
│   │       ├── pdf_service.py      PyMuPDF extraction + scan detection
│   │       └── document_service.py DB operations for documents
│   ├── tests/
│   │   ├── conftest.py         Pytest fixtures (SQLite, isolated uploads)
│   │   ├── test_pdf_service.py Unit tests for PDF extraction
│   │   └── test_documents.py   API integration tests
│   ├── requirements.txt
│   └── Dockerfile
├── data/
│   ├── uploads/               Uploaded PDFs (not committed)
│   └── test_documents/        Test PDFs for manual testing
├── .env                       Local secrets (not committed)
├── .env.example               Template — commit this, not .env
├── docker-compose.yml         PostgreSQL service
└── README.md
```

---

## Setup

### 1. Python environment

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Environment variables

Copy the example file and fill in your PostgreSQL credentials:

```powershell
copy .env.example .env
```

Edit `.env`:

```env
DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/ai_learning_db
UPLOAD_DIR=data/uploads
MAX_FILE_SIZE_MB=20
```

### 3. PostgreSQL

**Option A — Docker (recommended)**

```powershell
docker-compose up -d
```

This starts PostgreSQL 16 on port 5432 with:
- User: `postgres`
- Password: `postgres`
- Database: `ai_learning_db`

**Option B — Local PostgreSQL**

If you have PostgreSQL installed locally:

```sql
-- Run in psql
CREATE DATABASE ai_learning_db;
```

Update `DATABASE_URL` in `.env` with your credentials.

### 4. Start the backend

```powershell
# From the backend/ directory, with venv activated
uvicorn app.main:app --reload
```

The server will:
- Connect to PostgreSQL
- Create the `documents` table if it does not exist
- Start on http://127.0.0.1:8000

---

## Verify It Works

```
GET  http://127.0.0.1:8000/health
→   {"status": "ok"}

GET  http://127.0.0.1:8000/docs
→   Swagger UI showing all endpoints
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/documents/upload` | Upload a PDF |
| `GET` | `/documents/` | List all documents |
| `GET` | `/documents/{id}` | Get document status |

### Upload a PDF

```bash
curl -X POST http://127.0.0.1:8000/documents/upload \
  -F "file=@your_notes.pdf" \
  -F "subject=Operating Systems"
```

Response (HTTP 202):

```json
{
  "document_id": "3f7a1b2c-...",
  "status": "PROCESSING"
}
```

### Check status

```bash
curl http://127.0.0.1:8000/documents/3f7a1b2c-...
```

Response when ready:

```json
{
  "document_id": "3f7a1b2c-...",
  "filename": "your_notes.pdf",
  "subject": "Operating Systems",
  "status": "READY",
  "page_count": 12,
  "error_message": null,
  "created_at": "...",
  "updated_at": "..."
}
```

---

## Run Tests

```powershell
# From backend/ directory, with venv activated
pytest tests/ -v
```

Tests use SQLite — no PostgreSQL needed to run tests.

---

## Document Status Values

| Status | Meaning |
|--------|---------|
| `PROCESSING` | Upload accepted, extraction in progress |
| `READY` | Text extracted successfully |
| `FAILED` | Extraction failed (scanned PDF, corrupted file, etc.) |

---

## Notes

- `user_id` is currently a development placeholder (`"dev-user"`).
  JWT authentication will be added in a later phase.
- Uploaded PDFs are saved as `data/uploads/{document_id}.pdf`.
  The original filename is preserved in the database.
- Scanned pages (fewer than 50 extracted characters) are flagged with
  `needs_ocr: true`. OCR integration is a later phase.
