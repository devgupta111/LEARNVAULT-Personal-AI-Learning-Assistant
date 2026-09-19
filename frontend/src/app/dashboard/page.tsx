/**
 * app/dashboard/page.tsx
 *
 * Study Dashboard — protected route.
 *
 * Shows:
 *  - Metrics: total docs, ready, processing, failed
 *  - Weak topics detected from quiz history (accuracy < 60%)
 *  - Uploaded documents table with Chat / Quiz actions
 *
 * Auth: useAuth(true) → redirects to /login if not authenticated.
 * Loading: shows spinner until auth check AND data fetch complete.
 * No duplicate API calls: fetchData runs once on mount.
 */

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "../../../hooks/useAuth";
import { useToast } from "../../../components/Toast";
import { deleteDocument, getDocuments, getQuizHistory } from "../../../lib/api";
import { DocumentSummary, QuizHistoryItem } from "../../../types";
import DeleteConfirmModal from "../../../components/DeleteConfirmModal";

export default function DashboardPage() {
  const { loading: authLoading } = useAuth(true);
  const toast = useToast();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [quizHistory, setQuizHistory] = useState<QuizHistoryItem[]>([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; filename: string } | null>(null);

  const fetchData = async () => {
    try {
      setDataLoading(true);
      setError(null);
      const [docs, history] = await Promise.all([
        getDocuments(),
        getQuizHistory().catch(() => []),
      ]);
      setDocuments(docs);
      setQuizHistory(history);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load dashboard data";
      setError(msg);
    } finally {
      setDataLoading(false);
    }
  };

  // Only fetch once auth is resolved (not during redirect)
  useEffect(() => {
    if (!authLoading) {
      fetchData();
    }
  }, [authLoading]);

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    const docId = deleteTarget.id;
    setDeletingDocId(docId);
    setError(null);
    try {
      await deleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => (d.document_id || d.id) !== docId));
      toast.success("Document deleted successfully.");
      setDeleteTarget(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete document";
      setError(msg);
      toast.error(msg);
    } finally {
      setDeletingDocId(null);
    }
  };

  const loading = authLoading || dataLoading;

  const readyCount = documents.filter((d) => d.status === "READY").length;
  const processingCount = documents.filter((d) => d.status === "PROCESSING").length;
  const failedCount = documents.filter((d) => d.status === "FAILED").length;

  // Weak topics: latest attempt < 60% accuracy per unique topic
  const latestTopicMap = new Map<string, { topic: string; percentage: number; document_id: string }>();
  for (const item of quizHistory) {
    if (item.latest_percentage !== null && item.latest_percentage !== undefined) {
      if (!latestTopicMap.has(item.topic)) {
        latestTopicMap.set(item.topic, {
          topic: item.topic,
          percentage: item.latest_percentage,
          document_id: item.document_id,
        });
      }
    }
  }
  const weakTopics = Array.from(latestTopicMap.values()).filter((t) => t.percentage < 60);
  const hasDocuments = documents.length > 0;
  const hasQuizResults = latestTopicMap.size > 0;

  if (loading) {
    return (
      <div
        className="flex-1 flex flex-col items-center justify-center gap-3"
        style={{ color: "var(--text-muted)" }}
      >
        <span
          className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
        />
        <p className="text-sm">Loading your dashboard…</p>
      </div>
    );
  }

  return (
    <div
      className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8 page-enter"
    >
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold" style={{ color: "var(--text-primary)" }}>
            Study Dashboard
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
            Overview of your study materials and learning progress.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={fetchData}
            className="px-3.5 py-2 text-xs font-medium rounded-lg transition-all hover:bg-[var(--bg-hover)] active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
            style={{
              background: "var(--bg-surface)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
          >
            Refresh
          </button>
          <Link
            href="/documents"
            className="px-4 py-2 text-xs font-medium rounded-lg text-white shadow-sm transition-all hover:brightness-105 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
            style={{ background: "var(--accent)" }}
          >
            + Upload PDF
          </Link>
        </div>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Total Notes", value: documents.length, color: "var(--text-primary)" },
          { label: "Ready for Chat", value: readyCount, color: "#10b981" },
          { label: "Processing", value: processingCount, color: "#f59e0b" },
          { label: "Failed", value: failedCount, color: "#ef4444" },
        ].map((card) => (
          <div
            key={card.label}
            className="p-5 rounded-xl shadow-sm"
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
            }}
          >
            <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
              {card.label}
            </span>
            <p className="text-2xl font-bold mt-1" style={{ color: card.color }}>
              {card.value}
            </p>
          </div>
        ))}
      </div>

      {/* Weak Topics */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2
            className="text-lg font-semibold flex items-center gap-2"
            style={{ color: "var(--text-primary)" }}
          >
            <span>Weak Topics</span>
            {hasQuizResults && weakTopics.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-400 border border-rose-200 dark:border-rose-900">
                {weakTopics.length} detected
              </span>
            )}
          </h2>
          {hasQuizResults ? (
            <div className="flex items-center gap-3">
              <span className="text-[11px] hidden sm:block" style={{ color: "var(--text-muted)" }}>
                Weak = accuracy &lt; 60%
              </span>
              <Link href="/quiz" className="text-xs font-medium" style={{ color: "var(--accent-text)" }}>
                Go to Quizzes →
              </Link>
            </div>
          ) : hasDocuments ? (
            <div className="flex items-center gap-3">
              <Link href="/quiz" className="text-xs font-medium" style={{ color: "var(--accent-text)" }}>
                Go to Quizzes →
              </Link>
            </div>
          ) : null}
        </div>

        {!hasDocuments ? (
          /* CASE 1: No documents */
          <div
            className="p-4 rounded-xl border border-dashed text-xs"
            style={{
              borderColor: "var(--border)",
              background: "var(--bg-surface)",
              color: "var(--text-muted)",
            }}
          >
            Upload a study material and complete a quiz to see your weak-topic analysis.
          </div>
        ) : !hasQuizResults ? (
          /* CASE 2: Documents exist but no quiz results */
          <div
            className="p-4 rounded-xl border border-dashed text-xs"
            style={{
              borderColor: "var(--border)",
              background: "var(--bg-surface)",
              color: "var(--text-muted)",
            }}
          >
            Complete a quiz to see your weak-topic analysis.
          </div>
        ) : weakTopics.length === 0 ? (
          /* CASE 3: Quiz results exist, no weak topics */
          <div
            className="p-4 rounded-xl border border-dashed text-xs"
            style={{
              borderColor: "var(--border)",
              background: "var(--bg-surface)",
              color: "var(--text-muted)",
            }}
          >
            No weak topics detected. All tested topics scored at or above 60% accuracy.
          </div>
        ) : (
          /* CASE 3: Quiz results exist with weak topics */
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {weakTopics.map((item) => (
              <div
                key={item.topic}
                className="p-4 rounded-xl shadow-sm flex items-center justify-between gap-3"
                style={{
                  background: "var(--bg-surface)",
                  border: "1px solid #f43f5e55",
                }}
              >
                <div>
                  <div className="text-xs font-bold" style={{ color: "var(--text-primary)" }}>
                    {item.topic}
                  </div>
                  <div className="text-[11px] font-mono font-medium mt-0.5 text-rose-500">
                    {item.percentage.toFixed(0)}% accuracy
                  </div>
                </div>
                <Link
                  href={`/quiz?doc=${item.document_id}&topic=${encodeURIComponent(item.topic)}`}
                  className="px-3 py-1 rounded-lg text-white text-xs font-semibold transition-all hover:bg-rose-700 active:scale-[0.98] shadow-sm shrink-0 focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:outline-none"
                  style={{ background: "#e11d48" }}
                >
                  Practice
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Documents Table */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
            Uploaded Materials
          </h2>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {documents.length} {documents.length === 1 ? "document" : "documents"}
          </span>
        </div>

        {error && (
          <div className="p-4 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300 text-sm">
            {error}
          </div>
        )}

        {documents.length === 0 ? (
          <div
            className="py-16 px-4 text-center rounded-2xl border border-dashed"
            style={{
              borderColor: "var(--border)",
              background: "var(--bg-surface)",
            }}
          >
            <div className="text-4xl mb-3">📚</div>
            <h3 className="text-base font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
              No documents uploaded yet
            </h3>
            <p className="text-xs max-w-sm mx-auto mb-6" style={{ color: "var(--text-muted)" }}>
              Upload a lecture note or textbook PDF to start asking questions and generating practice quizzes.
            </p>
            <Link
              href="/documents"
              className="px-4 py-2 text-xs font-medium rounded-lg text-white shadow-sm transition-all hover:brightness-105 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none inline-block"
              style={{ background: "var(--accent)" }}
            >
              Upload Your First Document
            </Link>
          </div>
        ) : (
          <div
            className="overflow-x-auto rounded-xl shadow-sm"
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
            }}
          >
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr
                  className="text-xs font-semibold"
                  style={{
                    borderBottom: "1px solid var(--border)",
                    background: "var(--bg-surface-2)",
                    color: "var(--text-muted)",
                  }}
                >
                  <th className="py-3 px-4">Filename</th>
                  <th className="py-3 px-4">Subject</th>
                  <th className="py-3 px-4">Pages</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Uploaded</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => {
                  const docId = doc.document_id || doc.id || "";
                  return (
                    <tr
                      key={docId}
                      className="transition-colors text-xs"
                      style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    >
                      <td className="py-3.5 px-4 font-medium" style={{ color: "var(--text-primary)" }}>
                        <span className="flex items-center gap-2">
                          <span>📄</span>
                          <span className="truncate max-w-[200px] sm:max-w-xs">{doc.filename}</span>
                        </span>
                      </td>
                      <td className="py-3.5 px-4" style={{ color: "var(--text-secondary)" }}>
                        {doc.subject || "General"}
                      </td>
                      <td className="py-3.5 px-4" style={{ color: "var(--text-secondary)" }}>
                        {doc.page_count ?? "—"}
                      </td>
                      <td className="py-3.5 px-4">
                        {doc.status === "READY" && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                            Ready
                          </span>
                        )}
                        {doc.status === "PROCESSING" && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                            Processing…
                          </span>
                        )}
                        {doc.status === "FAILED" && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-400 border border-rose-200 dark:border-rose-800">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                            Failed
                          </span>
                        )}
                      </td>
                      <td className="py-3.5 px-4" style={{ color: "var(--text-muted)" }}>
                        {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {doc.status === "READY" && (
                            <>
                              <Link
                                href={`/chat?doc=${docId}`}
                                className="px-2.5 py-1 text-xs font-medium rounded-lg transition-all hover:brightness-95 active:scale-[0.98] hover:shadow-xs focus-visible:ring-2 focus-visible:outline-none"
                                style={{
                                  background: "var(--accent-surface)",
                                  color: "var(--accent-text)",
                                }}
                              >
                                Chat
                              </Link>
                              <Link
                                href={`/quiz?doc=${docId}`}
                                className="px-2.5 py-1 text-xs font-medium rounded-lg transition-all bg-purple-50 hover:bg-purple-100 text-purple-700 dark:bg-purple-950/60 dark:hover:bg-purple-900/60 dark:text-purple-300 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
                              >
                                Quiz
                              </Link>
                            </>
                          )}
                          <button
                            type="button"
                            onClick={() => setDeleteTarget({ id: docId, filename: doc.filename })}
                            disabled={deletingDocId === docId}
                            title="Delete document"
                            className="px-2.5 py-1 text-xs font-medium rounded-lg transition-all disabled:opacity-50 ml-1 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/60 hover:bg-rose-50 dark:hover:bg-rose-950/50 hover:border-rose-300 dark:hover:border-rose-800 active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:outline-none"
                          >
                            {deletingDocId === docId ? "Deleting…" : "Delete"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <DeleteConfirmModal
        isOpen={Boolean(deleteTarget)}
        filename={deleteTarget?.filename || ""}
        isDeleting={Boolean(deletingDocId)}
        onConfirm={handleConfirmDelete}
        onCancel={() => {
          if (!deletingDocId) {
            setDeleteTarget(null);
          }
        }}
      />
    </div>
  );
}
