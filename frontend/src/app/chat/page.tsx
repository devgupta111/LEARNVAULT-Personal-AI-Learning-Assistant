/**
 * app/chat/page.tsx
 *
 * Grounded RAG Chat — protected route.
 *
 * Features:
 *  - Document selector (READY documents only)
 *  - Session management (list + create)
 *  - SSE streaming from POST /chat/stream
 *  - Citation display per message
 *  - Auth-gated: useAuth(true)
 *
 * Key bug fixes:
 *  - React key warning: sessions use sess.session_id (not sess.id) as key
 *  - Auth fetch gate: documents load only after auth resolves
 *  - No dev/debug text in headers
 */

"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, Suspense } from "react";
import { useAuth } from "../../../hooks/useAuth";
import {
  createSession,
  getDocuments,
  getSessionMessages,
  getSessions,
  streamChat,
} from "../../../lib/api";
import { ChatMessage, ChatSession, CitationItem, DocumentSummary } from "../../../types";

function ChatComponent() {
  const { loading: authLoading } = useAuth(true);
  const searchParams = useSearchParams();
  const initialDocId = searchParams.get("doc");

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string>("");
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingTokenText, setStreamingTokenText] = useState("");
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingTokenText]);

  // Load documents after auth resolves (avoids unnecessary API call before redirect)
  useEffect(() => {
    if (authLoading) return;

    async function loadInitial() {
      try {
        setLoadingDocs(true);
        const docs = await getDocuments();
        const readyDocs = docs.filter((d) => d.status === "READY");
        setDocuments(readyDocs);

        if (initialDocId && readyDocs.some((d) => (d.document_id || d.id) === initialDocId)) {
          setSelectedDocId(initialDocId);
        } else if (readyDocs.length > 0) {
          setSelectedDocId(readyDocs[0].document_id || readyDocs[0].id || "");
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to load documents";
        setError(msg);
      } finally {
        setLoadingDocs(false);
      }
    }
    loadInitial();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, initialDocId]);

  // Load sessions when selected document changes
  useEffect(() => {
    if (!selectedDocId) return;

    async function loadSessions() {
      try {
        setError(null);
        const sessList = await getSessions(selectedDocId);
        setSessions(sessList);

        if (sessList.length > 0) {
          const firstId = sessList[0].session_id || sessList[0].id || "";
          setActiveSessionId(firstId);
        } else {
          // Auto-create initial session
          const newSess = await createSession(selectedDocId);
          const newId = newSess.session_id || newSess.id || "";
          setSessions([newSess]);
          setActiveSessionId(newId);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to load sessions";
        setError(msg);
      }
    }
    loadSessions();
  }, [selectedDocId]);

  // Load messages when active session changes
  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      return;
    }
    async function loadMessages() {
      try {
        const history = await getSessionMessages(activeSessionId);
        setMessages(history);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to load messages";
        setError(msg);
      }
    }
    loadMessages();
  }, [activeSessionId]);

  const handleCreateNewSession = async () => {
    if (!selectedDocId) return;
    try {
      setError(null);
      const newSess = await createSession(selectedDocId);
      const newId = newSess.session_id || newSess.id || "";
      setSessions((prev) => {
        const filtered = prev.filter((s) => (s.session_id || s.id) !== newId);
        return [newSess, ...filtered];
      });
      setActiveSessionId(newId);
      setMessages([]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create session";
      setError(msg);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanMessage = inputMessage.trim();
    if (!cleanMessage || isStreaming || !activeSessionId || !selectedDocId) return;

    const userMsg: ChatMessage = {
      id: `temp-user-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      session_id: activeSessionId,
      sender: "user",
      content: cleanMessage,
      citations: [],
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputMessage("");
    setIsStreaming(true);
    setStreamingTokenText("");
    setError(null);

    let accumulated = "";

    await streamChat(
      activeSessionId,
      selectedDocId,
      cleanMessage,
      (token: string) => {
        accumulated += token;
        setStreamingTokenText(accumulated);
      },
      (citations: CitationItem[]) => {
        const assistantMsg: ChatMessage = {
          id: `temp-ast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
          session_id: activeSessionId,
          sender: "assistant",
          content: accumulated,
          citations,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setStreamingTokenText("");
        setIsStreaming(false);
      },
      (err: string) => {
        setError(err);
        setIsStreaming(false);
        setStreamingTokenText("");
      }
    );
  };

  const selectedDoc = documents.find((d) => (d.document_id || d.id) === selectedDocId);

  // Deduplicate to guarantee unique keys
  const uniqueDocuments = Array.from(
    new Map(documents.map((d) => [d.document_id || d.id || "", d])).values()
  );
  const uniqueSessions = Array.from(
    new Map(sessions.map((s) => [s.session_id || s.id || "", s])).values()
  );

  if (authLoading) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
        <span
          className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
        />
      </div>
    );
  }

  return (
    <div
      className="flex-1 flex flex-col md:flex-row h-[calc(100vh-4rem)] max-w-7xl w-full mx-auto p-4 gap-4"
    >
      {/* ── Left Sidebar ── */}
      <div
        className="w-full md:w-72 flex flex-col rounded-2xl p-4 shrink-0 shadow-sm"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
      >
        {/* Document selector */}
        <div className="mb-4">
          <label
            className="block text-xs font-semibold uppercase tracking-wider mb-2"
            style={{ color: "var(--text-muted)" }}
          >
            Study Document
          </label>
          {loadingDocs ? (
            <div className="text-xs py-2" style={{ color: "var(--text-muted)" }}>
              Loading documents…
            </div>
          ) : uniqueDocuments.length === 0 ? (
            <div
              className="text-xs p-2 border border-dashed rounded-lg"
              style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
            >
              No ready documents. Upload a PDF first.
            </div>
          ) : (
            <select
              value={selectedDocId}
              onChange={(e) => setSelectedDocId(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded-lg border font-medium focus:ring-2 focus:outline-none"
              style={{
                borderColor: "var(--border)",
                background: "transparent",
                color: "var(--text-primary)",
              }}
            >
              {uniqueDocuments.map((doc) => {
                const docId = doc.document_id || doc.id || "";
                return (
                  <option key={docId} value={docId}>
                    {doc.filename} ({doc.subject || "General"})
                  </option>
                );
              })}
            </select>
          )}
        </div>

        {/* New session button */}
        <button
          onClick={handleCreateNewSession}
          disabled={!selectedDocId || isStreaming}
          className="w-full py-2 px-3 rounded-lg text-xs font-semibold transition-colors flex items-center justify-center gap-2 mb-4 disabled:opacity-50"
          style={{
            background: "var(--accent-surface)",
            color: "var(--accent-text)",
          }}
        >
          <span>+</span>
          <span>New Chat Session</span>
        </button>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto space-y-1">
          <span
            className="text-[11px] font-semibold uppercase tracking-wider block mb-2 px-1"
            style={{ color: "var(--text-muted)" }}
          >
            Conversations ({uniqueSessions.length})
          </span>
          {uniqueSessions.map((sess, idx) => {
            // Fix: use session_id (not sess.id) as the React key
            const sessId = sess.session_id || sess.id || `sess-${idx}`;
            const isActive = sessId === activeSessionId;
            return (
              <button
                key={sessId}
                onClick={() => setActiveSessionId(sessId)}
                disabled={isStreaming}
                className="w-full text-left px-3 py-2 rounded-lg text-xs font-medium transition-colors"
                style={
                  isActive
                    ? { background: "var(--bg-surface-2)", color: "var(--text-primary)" }
                    : { color: "var(--text-secondary)" }
                }
              >
                <div className="truncate">Session #{uniqueSessions.length - idx}</div>
                <div className="text-[10px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                  {sess.created_at ? new Date(sess.created_at).toLocaleDateString() : ""}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Main Chat Area ── */}
      <div
        className="flex-1 flex flex-col rounded-2xl shadow-sm overflow-hidden"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
      >
        {/* Chat header */}
        <div
          className="p-4 flex items-center justify-between"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div>
            <h2 className="text-sm font-bold flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span>💬</span>
              <span>RAG Chat</span>
              {selectedDoc && (
                <span className="text-xs font-normal" style={{ color: "var(--text-muted)" }}>
                  — {selectedDoc.filename}
                </span>
              )}
            </h2>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
              Answers are grounded in your document with verified page citations.
            </p>
          </div>
          {isStreaming && (
            <div
              className="flex items-center gap-2 text-xs font-medium"
              style={{ color: "var(--accent-text)" }}
            >
              <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: "var(--accent)" }} />
              <span>Generating…</span>
            </div>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 text-red-700 dark:text-red-300 text-xs">
              {error}
            </div>
          )}

          {messages.length === 0 && !isStreaming && (
            <div className="py-20 text-center text-xs" style={{ color: "var(--text-muted)" }}>
              <div
                className="w-10 h-10 rounded-full flex items-center justify-center mx-auto mb-2 text-base"
                style={{ background: "var(--accent-surface)", color: "var(--accent-text)" }}
              >
                💡
              </div>
              <p className="font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
                Ask a question about your study material
              </p>
              <p className="max-w-xs mx-auto">
                Try: &quot;What is database normalization?&quot; or &quot;Explain the main concepts in chapter 1&quot;
              </p>
            </div>
          )}

          {messages.map((msg, msgIdx) => {
            const msgKey = msg.message_id || msg.id || `msg-${msgIdx}`;
            return (
              <div
                key={msgKey}
                className={`flex flex-col ${msg.sender === "user" ? "items-end" : "items-start"}`}
              >
                <div
                  className={`max-w-[85%] sm:max-w-2xl px-4 py-3 rounded-2xl text-xs sm:text-sm ${
                    msg.sender === "user"
                      ? "text-white rounded-br-none"
                      : "rounded-bl-none"
                  }`}
                  style={
                    msg.sender === "user"
                      ? { background: "var(--accent)" }
                      : { background: "var(--bg-surface-2)", color: "var(--text-primary)" }
                  }
                >
                  <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>

                  {/* Citations */}
                  {msg.citations && msg.citations.length > 0 && (
                    <div
                      className="mt-3 pt-3 space-y-1"
                      style={{ borderTop: "1px solid var(--border)" }}
                    >
                      <span
                        className="text-[11px] font-semibold block"
                        style={{ color: "var(--text-muted)" }}
                      >
                        Sources:
                      </span>
                      <div className="flex flex-wrap gap-2">
                        {msg.citations.map((c, i) => {
                          const citKey = c.parent_chunk_id
                            ? `cit-${msgKey}-${c.parent_chunk_id}`
                            : `cit-${msgKey}-${i}-${c.page_start ?? 0}`;
                          const cleanSourceNum = String(c.source_id ?? (i + 1))
                            .replace(/^source\s*/i, "")
                            .trim();
                          const matchedDoc =
                            uniqueDocuments.find((d) => (d.document_id || d.id) === c.document_id) ||
                            selectedDoc;
                          const filename = matchedDoc?.filename || "";
                          const pageText = c.page_start ? `Page ${c.page_start}` : "";

                          return (
                            <div
                              key={citKey}
                              className="px-2 py-1 rounded border text-[10px] flex items-center gap-1.5 shadow-sm"
                              style={{
                                background: "var(--bg-surface)",
                                borderColor: "var(--border)",
                                color: "var(--text-secondary)",
                              }}
                            >
                              <span className="font-semibold" style={{ color: "var(--accent-text)" }}>
                                [Source {cleanSourceNum}]
                              </span>
                              {filename && <span className="truncate max-w-[150px]">{filename}</span>}
                              {filename && pageText && <span style={{ color: "var(--text-muted)" }}>·</span>}
                              {pageText && <span>{pageText}</span>}
                              {c.subject && <span style={{ color: "var(--text-muted)" }}>({c.subject})</span>}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {/* Streaming bubble */}
          {isStreaming && (
            <div className="flex flex-col items-start">
              <div
                className="max-w-[85%] sm:max-w-2xl px-4 py-3 rounded-2xl text-xs sm:text-sm rounded-bl-none"
                style={{ background: "var(--bg-surface-2)", color: "var(--text-primary)" }}
              >
                <div className="whitespace-pre-wrap leading-relaxed">
                  {streamingTokenText}
                  <span
                    className="inline-block w-1.5 h-3 ml-1 animate-pulse align-middle"
                    style={{ background: "var(--accent)" }}
                  />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <form
          onSubmit={handleSendMessage}
          className="p-3 flex items-center gap-2"
          style={{
            borderTop: "1px solid var(--border)",
            background: "var(--bg-surface-2)",
          }}
        >
          <input
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            placeholder={
              !selectedDocId
                ? "Select or upload a document to begin…"
                : isStreaming
                ? "Generating answer…"
                : "Ask a question about your study material…"
            }
            disabled={isStreaming || !selectedDocId}
            className="flex-1 px-4 py-2.5 rounded-xl border text-xs sm:text-sm focus:outline-none focus:ring-2 disabled:opacity-50"
            style={{
              borderColor: "var(--border)",
              background: "var(--bg-surface)",
              color: "var(--text-primary)",
            }}
          />
          <button
            type="submit"
            disabled={isStreaming || !inputMessage.trim() || !selectedDocId}
            className="px-5 py-2.5 rounded-xl text-white font-medium text-xs sm:text-sm transition-colors shadow-sm disabled:opacity-40 shrink-0"
            style={{ background: "var(--accent)" }}
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex-1 flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
          <span className="text-xs">Loading chat…</span>
        </div>
      }
    >
      <ChatComponent />
    </Suspense>
  );
}
