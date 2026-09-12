/**
 * types/index.ts
 *
 * Unified TypeScript type definitions for Personal AI Learning Assistant.
 */

export interface User {
  user_id: string;
  username?: string | null;
  email?: string | null;
  picture?: string | null;
  auth_provider?: string | null;
  role?: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  username?: string | null;
  email?: string | null;
  picture?: string | null;
  auth_provider?: string | null;
}

export interface DocumentSummary {
  document_id: string;
  id?: string;
  filename: string;
  subject?: string | null;
  status: "PROCESSING" | "READY" | "FAILED";
  page_count?: number | null;
  created_at?: string;
}

export interface DocumentDetail extends DocumentSummary {
  file_path?: string;
  error_message?: string | null;
  updated_at?: string;
}

export interface DocumentUploadResponse {
  document_id: string;
  status: string;
}

export interface CitationItem {
  source_id: number;
  document_id: string;
  page_start: number;
  page_end: number;
  parent_chunk_id?: string | null;
  subject?: string | null;
}

export interface ChatSession {
  session_id: string;
  id?: string;
  user_id?: string;
  document_id: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  message_id?: string;
  session_id: string;
  sender: "user" | "assistant";
  content: string;
  citations: CitationItem[];
  created_at: string;
}


export interface QuizQuestion {
  question: string;
  options: string[];
  correct_answer?: string;
  topic?: string;
  explanation?: string;
}

export interface QuizDetail {
  quiz_id: string;
  id?: string;
  document_id: string;
  topic: string;
  questions: QuizQuestion[];
  created_at: string;
}

export interface QuestionResult {
  question: string;
  submitted_answer: string;
  correct_answer: string;
  is_correct: boolean;
  explanation?: string;
}

export interface QuizSubmissionResult {
  quiz_id: string;
  attempt_id: string;
  score: number;
  total: number;
  percentage: number;
  results: QuestionResult[];
}

export interface QuizHistoryItem {
  quiz_id: string;
  document_id: string;
  topic: string;
  num_questions: number;
  created_at: string;
  latest_attempt_id?: string | null;
  latest_score?: number | null;
  latest_percentage?: number | null;
  latest_attempt_at?: string | null;
}

