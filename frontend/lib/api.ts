/**
 * lib/api.ts
 *
 * Backend API client for Personal AI Learning Assistant.
 * Handles authentication, documents, sessions, chat SSE streaming, and quizzes.
 */

import {
  AuthResponse,
  ChatMessage,
  ChatSession,
  CitationItem,
  DocumentDetail,
  DocumentSummary,
  DocumentUploadResponse,
  QuizHistoryItem,
  QuizDetail,
  QuizSubmissionResult,
  User,
} from "../types";


export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Token and User Helpers ──────────────────────────────────────────────────

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("token", token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("token");
  localStorage.removeItem("user");
  // Notify all listening components (Navbar, pages) to clear user state immediately
  window.dispatchEvent(new Event("user-updated"));
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("user");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function setUser(user: User): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("user", JSON.stringify(user));
  window.dispatchEvent(new Event("user-updated"));
}

// ─── Authenticated Fetch Wrapper ─────────────────────────────────────────────

async function authFetch(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  return response;
}

export const GOOGLE_CLIENT_ID =
  process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ||
  "345444138884-bbigs9vt771fii89o3kf0ncs1snl01fu.apps.googleusercontent.com";

// ─── Authentication API ──────────────────────────────────────────────────────

export async function loginUser(
  username: string,
  password?: string
): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(errorData.detail || `Login failed with status ${res.status}`);
  }

  const data: AuthResponse = await res.json();
  setToken(data.access_token);
  setUser({
    user_id: data.user_id,
    username: data.username || null,
    email: data.email || null,
    picture: data.picture || null,
    auth_provider: data.auth_provider || (data.user_id === "dev-user" ? "guest" : "local"),
    role: "student",
  });
  return data;
}

export async function loginWithGoogle(
  credential: string,
  guestUserId?: string
): Promise<AuthResponse> {
  const body: Record<string, string> = { credential };
  if (guestUserId) {
    body["guest_user_id"] = guestUserId;
  }

  // Clear any existing token and guest user before establishing authenticated session
  clearToken();

  const res = await fetch(`${API_BASE_URL}/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: "Google Sign-In failed" }));
    throw new Error(errorData.detail || `Google login failed with status ${res.status}`);
  }

  const data: AuthResponse = await res.json();
  setToken(data.access_token);
  setUser({
    user_id: data.user_id,
    username: data.username || null,
    email: data.email || null,
    picture: data.picture || null,
    auth_provider: data.auth_provider || "google",
    role: "student",
  });
  return data;
}

export async function cleanupGuestData(guestUserId: string = "dev-user"): Promise<void> {
  await fetch(`${API_BASE_URL}/auth/guest/cleanup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ guest_user_id: guestUserId }),
  }).catch((err) => {
    console.warn("Guest data cleanup request notice:", err);
  });
}

export async function getMe(): Promise<User> {
  const res = await authFetch("/auth/me");
  if (!res.ok) {
    throw new Error("Failed to load user profile");
  }
  const profile: User = await res.json();
  setUser(profile);
  return profile;
}

export async function updateProfile(username: string): Promise<User> {
  const res = await authFetch("/auth/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to update profile" }));
    throw new Error(err.detail || "Failed to update profile");
  }

  const profile: User = await res.json();
  setUser(profile);
  return profile;
}


// ─── Documents API ───────────────────────────────────────────────────────────

export async function getDocuments(): Promise<DocumentSummary[]> {
  const res = await authFetch("/documents/");
  if (!res.ok) {
    throw new Error("Failed to fetch documents");
  }
  return res.json();
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  const res = await authFetch(`/documents/${id}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch document: ${res.statusText}`);
  }
  return res.json();
}

export async function uploadDocument(
  file: File,
  subject: string = "General"
): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("subject", subject);

  const res = await authFetch("/documents/upload", {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "Document upload failed");
  }

  return res.json();
}

export async function deleteDocument(documentId: string): Promise<void> {
  const res = await authFetch(`/documents/${documentId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to delete document" }));
    throw new Error(err.detail || `Failed to delete document (${res.status})`);
  }
}

// ─── Sessions and Chat API ───────────────────────────────────────────────────


export async function getSessions(documentId?: string): Promise<ChatSession[]> {
  const url = documentId
    ? `/sessions?document_id=${encodeURIComponent(documentId)}`
    : "/sessions";
  const res = await authFetch(url);
  if (!res.ok) {
    throw new Error("Failed to fetch chat sessions");
  }
  return res.json();
}

export async function createSession(documentId: string): Promise<ChatSession> {
  const res = await authFetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create session" }));
    throw new Error(err.detail || "Failed to create session");
  }

  return res.json();
}

export async function getSessionMessages(
  sessionId: string
): Promise<ChatMessage[]> {
  const res = await authFetch(`/sessions/${sessionId}/messages`);
  if (!res.ok) {
    throw new Error("Failed to fetch session messages");
  }
  const data = await res.json();
  return (data || []).map((m: Record<string, unknown>) => ({
    ...m,
    id: (m.message_id as string) || (m.id as string) || `msg-${Math.random()}`,
    message_id: (m.message_id as string) || (m.id as string),
  })) as ChatMessage[];
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await authFetch(`/sessions/${sessionId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to delete session" }));
    throw new Error(err.detail || `Failed to delete session (${res.status})`);
  }
}

export async function renameSession(sessionId: string, title: string): Promise<ChatSession> {
  const res = await authFetch(`/chat/sessions/${sessionId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to rename session" }));
    throw new Error(err.detail || `Failed to rename session (${res.status})`);
  }
  return res.json();
}


/**
 * Consumes the SSE stream from POST /chat/stream.
 *
 * Calls:
 *   onToken(token: string) - as verified tokens arrive
 *   onDone(citations: CitationItem[]) - when stream finishes
 *   onError(error: string) - on connection or parsing failure
 */
export async function streamChat(
  sessionId: string,
  documentId: string,
  message: string,
  onToken: (token: string) => void,
  onDone: (citations: CitationItem[]) => void,
  onError: (error: string) => void
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        session_id: sessionId,
        document_id: documentId,
        message,
      }),
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Network error";
    onError(`Network error connecting to chat stream: ${message}`);
    return;
  }

  if (!response.ok) {
    const errData = await response.json().catch(() => ({ detail: response.statusText }));
    onError(errData.detail || `Chat request failed with status ${response.status}`);
    return;
  }

  if (!response.body) {
    onError("Response body is not readable");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // Keep unfinished last line in buffer
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith("data:")) {
          const jsonStr = trimmed.slice(5).trim();
          if (!jsonStr) continue;

          try {
            const eventData = JSON.parse(jsonStr);

            if (eventData.error) {
              onError(eventData.error);
            }

            if (eventData.token) {
              onToken(eventData.token);
            }

            if (eventData.done) {
              onDone(eventData.citations || []);
            }
          } catch {
            // Ignore non-JSON or partial lines
          }
        }
      }
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Stream read error";
    onError(`Stream read error: ${message}`);
  } finally {
    reader.releaseLock();
  }
}

// ─── Quiz API ────────────────────────────────────────────────────────────────

export async function generateQuiz(
  documentId: string,
  topic?: string
): Promise<QuizDetail> {
  const res = await authFetch("/quiz/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, topic }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Quiz generation failed" }));
    throw new Error(err.detail || "Quiz generation failed");
  }

  return res.json();
}

export async function getQuiz(quizId: string): Promise<QuizDetail> {
  const res = await authFetch(`/quiz/${quizId}`);
  if (!res.ok) {
    throw new Error("Failed to load quiz");
  }
  return res.json();
}

export async function submitQuiz(
  quizId: string,
  answers: string[]
): Promise<QuizSubmissionResult> {
  const res = await authFetch(`/quiz/${quizId}/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Quiz submission failed" }));
    throw new Error(err.detail || "Quiz submission failed");
  }

  return res.json();
}

export async function getQuizHistory(): Promise<QuizHistoryItem[]> {
  const res = await authFetch("/quiz/history");
  if (!res.ok) {
    throw new Error("Failed to fetch quiz history");
  }
  return res.json();
}

export async function renameQuizTopic(quizId: string, topic: string): Promise<void> {
  const res = await authFetch(`/quiz/${quizId}/rename`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to rename topic" }));
    throw new Error(err.detail || `Failed to rename topic (${res.status})`);
  }
}
