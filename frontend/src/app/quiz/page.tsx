/**
 * app/quiz/page.tsx
 *
 * Adaptive Quiz & Diagnostics — protected route.
 *
 * Features:
 *  - Generate MCQ quiz from any READY document, optionally scoped to a topic
 *  - Deterministic auto-grading (server-side)
 *  - Weak topic detection (< 60% accuracy)
 *  - Quiz history table with Practice button for weak topics
 *
 * Auth: useAuth(true) → redirects to /login if not authenticated.
 */

"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, Suspense, useCallback } from "react";
import { useAuth } from "../../../hooks/useAuth";
import { useToast } from "../../../components/Toast";
import {
  generateQuiz,
  getDocuments,
  getQuizHistory,
  renameQuizTopic,
  submitQuiz,
} from "../../../lib/api";
import {
  DocumentSummary,
  QuizDetail,
  QuizHistoryItem,
  QuizSubmissionResult,
} from "../../../types";

function QuizComponent() {
  const { loading: authLoading } = useAuth(true);
  const toast = useToast();
  const searchParams = useSearchParams();
  const initialDocId = searchParams.get("doc");
  const initialTopic = searchParams.get("topic") || "";

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string>("");
  const [topic, setTopic] = useState<string>(initialTopic);
  const [currentQuiz, setCurrentQuiz] = useState<QuizDetail | null>(null);
  const [userAnswers, setUserAnswers] = useState<Record<number, string>>({});
  const [submissionResult, setSubmissionResult] = useState<QuizSubmissionResult | null>(null);
  const [history, setHistory] = useState<QuizHistoryItem[]>([]);
  const [showIncorrectOnly, setShowIncorrectOnly] = useState(false);

  const [generating, setGenerating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingQuizId, setEditingQuizId] = useState<string | null>(null);
  const [editingTopic, setEditingTopic] = useState<string>("");

  const loadHistory = useCallback(async () => {
    try {
      setLoadingHistory(true);
      const hist = await getQuizHistory();
      setHistory(hist);
    } catch {
      // Non-fatal
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  // Load docs and history after auth resolves
  useEffect(() => {
    if (authLoading) return;

    async function loadInitial() {
      try {
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
      }
    }
    loadInitial();
    loadHistory();
  }, [authLoading, initialDocId, loadHistory]);

  const handleGenerateQuiz = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!selectedDocId) {
      setError("Please select a study document.");
      return;
    }
    setGenerating(true);
    setError(null);
    setCurrentQuiz(null);
    setUserAnswers({});
    setSubmissionResult(null);
    setShowIncorrectOnly(false);
    try {
      const quiz = await generateQuiz(selectedDocId, topic.trim() || undefined);
      setCurrentQuiz(quiz);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Quiz generation failed";
      setError(msg);
    } finally {
      setGenerating(false);
    }
  };

  const handlePracticeWeakTopic = async (docId: string, weakTopic: string) => {
    setSelectedDocId(docId);
    setTopic(weakTopic);
    setGenerating(true);
    setError(null);
    setCurrentQuiz(null);
    setUserAnswers({});
    setSubmissionResult(null);
    setShowIncorrectOnly(false);
    try {
      const quiz = await generateQuiz(docId, weakTopic);
      setCurrentQuiz(quiz);
      window.scrollTo({ top: 120, behavior: "smooth" });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Quiz generation failed";
      setError(msg);
    } finally {
      setGenerating(false);
    }
  };

  const handleSelectOption = (questionIdx: number, optionText: string) => {
    if (submissionResult) return;
    setUserAnswers((prev) => ({ ...prev, [questionIdx]: optionText }));
  };

  const handleSubmitQuiz = async () => {
    const quizId = currentQuiz?.quiz_id || currentQuiz?.id;
    if (!currentQuiz || !quizId || submitting) return;

    const answersList: string[] = currentQuiz.questions.map((_, i) => userAnswers[i] || "");
    if (answersList.some((a) => !a)) {
      setError("Please answer all questions before submitting.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await submitQuiz(quizId, answersList);
      setSubmissionResult(result);
      await loadHistory();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Quiz submission failed";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRenameQuiz = async (quizId: string) => {
    const newTopic = editingTopic.trim();
    if (!newTopic) { setEditingQuizId(null); return; }
    try {
      await renameQuizTopic(quizId, newTopic);
      setHistory((prev) =>
        prev.map((h) => h.quiz_id === quizId ? { ...h, topic: newTopic } : h)
      );
      toast.success("Quiz topic renamed successfully.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to rename topic";
      toast.error(msg);
    } finally {
      setEditingQuizId(null);
    }
  };

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
    <div className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8 page-enter">
      {/* Header */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold" style={{ color: "var(--text-primary)" }}>
          Adaptive Quiz
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          Generate targeted MCQs from your study material, submit for auto-grading, and track weak topics.
        </p>
      </div>

      {error && (
        <div className="p-3.5 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 text-red-700 dark:text-red-300 text-xs">
          {error}
        </div>
      )}

      {/* Quiz generation */}
      <div
        className="rounded-2xl p-6 shadow-sm"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
      >
        <h2 className="text-base font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
          Generate New Quiz
        </h2>
        <form onSubmit={handleGenerateQuiz} className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
              Select Document
            </label>
            <select
              value={selectedDocId}
              onChange={(e) => setSelectedDocId(e.target.value)}
              disabled={generating || documents.length === 0}
              className="w-full px-3 py-2 text-xs rounded-lg border font-medium focus:ring-2 focus:outline-none"
              style={{
                borderColor: "var(--border)",
                background: "transparent",
                color: "var(--text-primary)",
              }}
            >
              {documents.length === 0 ? (
                <option value="">No ready documents</option>
              ) : (
                documents.map((d) => {
                  const docId = d.document_id || d.id || "";
                  return (
                    <option key={docId} value={docId}>
                      {d.filename} ({d.subject || "General"})
                    </option>
                  );
                })
              )}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
              Topic (Optional)
            </label>
            <input
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. Normalization, Transactions"
              disabled={generating}
              className="w-full px-3 py-2 text-xs rounded-lg border focus:outline-none focus:ring-2"
              style={{
                borderColor: "var(--border)",
                background: "transparent",
                color: "var(--text-primary)",
              }}
            />
          </div>

          <button
            type="submit"
            disabled={generating || documents.length === 0}
            className="w-full py-2.5 rounded-lg text-white font-medium text-xs transition-all hover:brightness-105 active:scale-[0.98] shadow-sm disabled:opacity-50 flex items-center justify-center gap-2 focus-visible:ring-2 focus-visible:outline-none"
            style={{ background: "var(--accent)" }}
          >
            {generating ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Generating…</span>
              </>
            ) : (
              <span>Generate Quiz</span>
            )}
          </button>
        </form>

        {documents.length === 0 && (
          <p className="text-xs mt-3 text-center sm:text-left" style={{ color: "var(--text-muted)" }}>
            No ready documents found.{" "}
            <Link
              href="/documents"
              className="font-semibold underline transition-colors hover:brightness-110"
              style={{ color: "var(--accent)" }}
            >
              Upload a PDF to start practicing →
            </Link>
          </p>
        )}
      </div>

      {/* Active quiz */}
      {currentQuiz && (
        <div
          className="rounded-2xl p-6 shadow-sm space-y-6"
          style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
        >
          <div
            className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-4 gap-2"
            style={{ borderBottom: "1px solid var(--border)" }}
          >
            <div>
              <span
                className="text-xs font-semibold uppercase tracking-wider"
                style={{ color: "var(--accent-text)" }}
              >
                Topic: {currentQuiz.topic}
              </span>
              <h2 className="text-lg font-bold mt-0.5" style={{ color: "var(--text-primary)" }}>
                {currentQuiz.questions.length} Questions
              </h2>
            </div>
            {submissionResult && (
              <div className="flex items-center gap-3">
                <div className="text-right">
                  <span className="text-xs block" style={{ color: "var(--text-muted)" }}>Score</span>
                  <span className="text-base font-bold" style={{ color: "var(--text-primary)" }}>
                    {submissionResult.score} / {submissionResult.total} ({submissionResult.percentage.toFixed(1)}%)
                  </span>
                </div>
                {submissionResult.percentage < 60 && (
                  <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-400 border border-rose-200 dark:border-rose-900">
                    ⚠️ Weak Topic
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Review Filter Bar (visible when graded) */}
          {submissionResult && (
            <div
              className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 rounded-xl border gap-3"
              style={{
                background: "var(--bg-surface-2)",
                borderColor: "var(--border)",
              }}
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                  Review Mode:
                </span>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {submissionResult.results.filter((r) => !r.is_correct).length} incorrect of {submissionResult.total} questions
                </span>
              </div>
              <button
                type="button"
                onClick={() => setShowIncorrectOnly((prev) => !prev)}
                className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 self-start sm:self-auto active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
                style={{
                  background: showIncorrectOnly ? "var(--accent)" : "var(--bg-surface)",
                  color: showIncorrectOnly ? "#ffffff" : "var(--text-secondary)",
                  border: `1px solid ${showIncorrectOnly ? "var(--accent)" : "var(--border)"}`,
                }}
                aria-pressed={showIncorrectOnly}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                </svg>
                <span>{showIncorrectOnly ? "Showing Incorrect Only" : "Show Incorrect Answers Only"}</span>
              </button>
            </div>
          )}

          {/* Questions or Empty Review State */}
          {submissionResult && showIncorrectOnly && currentQuiz.questions.every((_, idx) => submissionResult.results[idx]?.is_correct) ? (
            <div
              className="p-8 rounded-xl text-center space-y-2 border border-dashed"
              style={{
                borderColor: "var(--border)",
                background: "var(--bg-surface-2)",
              }}
            >
              <div className="text-2xl">🎉</div>
              <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                No incorrect answers. Great job!
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                You scored 100% on this quiz. Every answer you submitted was correct.
              </p>
              <button
                type="button"
                onClick={() => setShowIncorrectOnly(false)}
                className="mt-2 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all hover:bg-[var(--bg-hover)] active:scale-[0.98]"
                style={{
                  border: "1px solid var(--border)",
                  color: "var(--accent-text)",
                  background: "var(--bg-surface)",
                }}
              >
                Show all questions
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              {currentQuiz.questions
                .map((q, qIdx) => ({ q, qIdx }))
                .filter(({ qIdx }) => {
                  if (!submissionResult || !showIncorrectOnly) return true;
                  return submissionResult.results[qIdx]?.is_correct === false;
                })
                .map(({ q, qIdx }) => {
                  const selectedOption = userAnswers[qIdx];
                  const qResult = submissionResult?.results[qIdx];
                  return (
                    <div
                      key={qIdx}
                      className="p-4 rounded-xl border transition-colors"
                      style={{
                        borderColor: qResult
                          ? qResult.is_correct ? "#10b98155" : "#f43f5e55"
                          : "var(--border)",
                        background: qResult
                          ? qResult.is_correct ? "#10b9811a" : "#f43f5e1a"
                          : "var(--bg-surface-2)",
                      }}
                    >
                      <p className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
                        <span style={{ color: "var(--accent-text)" }} className="mr-2">Q{qIdx + 1}.</span>
                        {q.question}
                      </p>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {q.options.map((opt, optIdx) => {
                          const isSelected = selectedOption === opt;
                          let style: React.CSSProperties = {
                            border: "1px solid var(--border)",
                            background: "var(--bg-surface)",
                            color: "var(--text-secondary)",
                          };

                          if (submissionResult) {
                            if (opt === qResult?.correct_answer) {
                              style = { border: "1px solid #10b981", background: "#10b9811a", color: "#065f46" };
                            } else if (isSelected && !qResult?.is_correct) {
                              style = { border: "1px solid #f43f5e", background: "#f43f5e1a", color: "#9f1239", textDecoration: "line-through" };
                            } else {
                              style = { border: "1px solid var(--border)", background: "var(--bg-surface)", color: "var(--text-muted)", opacity: "0.6" };
                            }
                          } else if (isSelected) {
                            style = {
                              border: "1px solid var(--accent)",
                              background: "var(--accent-surface)",
                              color: "var(--accent-text)",
                            };
                          }

                          return (
                            <button
                              key={optIdx}
                              type="button"
                              onClick={() => handleSelectOption(qIdx, opt)}
                              disabled={Boolean(submissionResult)}
                              className={`p-3 rounded-lg text-xs font-medium text-left transition-all ${
                                !submissionResult
                                  ? "hover:border-[var(--accent)] hover:bg-[var(--bg-hover)] active:scale-[0.99] focus-visible:ring-2 focus-visible:outline-none cursor-pointer"
                                  : "cursor-default"
                              }`}
                              style={style}
                            >
                              <span className="font-mono mr-2" style={{ color: "var(--text-muted)" }}>
                                {String.fromCharCode(65 + optIdx)}.
                              </span>
                              {opt}
                            </button>
                          );
                        })}
                      </div>

                      {qResult && !qResult.is_correct && (
                        <div className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                          Correct: <span className="font-semibold">{qResult.correct_answer}</span>
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          )}

          {/* Submit / Result */}
          {!submissionResult ? (
            <div
              className="flex justify-end pt-4"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <button
                onClick={handleSubmitQuiz}
                disabled={submitting}
                className="px-6 py-2.5 rounded-lg text-white font-medium text-xs transition-all hover:brightness-105 active:scale-[0.98] shadow-sm disabled:opacity-50 flex items-center gap-2 focus-visible:ring-2 focus-visible:outline-none"
                style={{ background: "var(--accent)" }}
              >
                {submitting ? (
                  <>
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>Grading…</span>
                  </>
                ) : (
                  <span>Submit for Grading</span>
                )}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {submissionResult.percentage < 60 ? (
                <div
                  className="p-4 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                  style={{
                    background: "#f43f5e1a",
                    border: "1px solid #f43f5e55",
                  }}
                >
                  <div>
                    <span className="text-[10px] font-bold block uppercase tracking-wider text-rose-700 dark:text-rose-400">
                      Weak Topic Detected (&lt;60%)
                    </span>
                    <div className="text-sm font-bold mt-0.5" style={{ color: "var(--text-primary)" }}>
                      {currentQuiz.topic}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                      {submissionResult.percentage.toFixed(0)}% accuracy ({submissionResult.score}/{submissionResult.total} correct)
                    </div>
                  </div>
                  <button
                    onClick={() => handlePracticeWeakTopic(currentQuiz.document_id, currentQuiz.topic)}
                    disabled={generating}
                    className="px-4 py-2 rounded-lg text-white text-xs font-semibold shadow-sm transition-all hover:bg-rose-700 active:scale-[0.98] self-start sm:self-auto disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:outline-none"
                    style={{ background: "#e11d48" }}
                  >
                    Practice Again
                  </button>
                </div>
              ) : (
                <div
                  className="p-4 rounded-xl"
                  style={{ background: "#10b9811a", border: "1px solid #10b98155" }}
                >
                  <span className="text-[10px] font-bold block uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                    Topic Mastered (≥60%)
                  </span>
                  <div className="text-sm font-bold mt-0.5" style={{ color: "var(--text-primary)" }}>
                    {currentQuiz.topic}
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                    {submissionResult.percentage.toFixed(0)}% accuracy ({submissionResult.score}/{submissionResult.total} correct)
                  </div>
                </div>
              )}

              <div
                className="p-4 rounded-xl flex items-center justify-between"
                style={{ background: "var(--bg-surface-2)", border: "1px solid var(--border)" }}
              >
                <div>
                  <span className="text-xs font-semibold block" style={{ color: "var(--text-primary)" }}>
                    Results saved
                  </span>
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                    Your results have been recorded in your learning history.
                  </span>
                </div>
                <button
                  onClick={() => {
                    setCurrentQuiz(null);
                    setSubmissionResult(null);
                    setUserAnswers({});
                    setShowIncorrectOnly(false);
                  }}
                  className="px-4 py-2 rounded-lg text-xs font-semibold transition-all hover:bg-[var(--bg-hover)] active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
                  style={{
                    background: "var(--bg-surface)",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border)",
                  }}
                >
                  Take Another Quiz
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* History */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
            Quiz History
          </h2>
          <button
            onClick={loadHistory}
            className="text-xs transition-colors hover:text-[var(--text-primary)] active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none rounded px-1.5 py-0.5"
            style={{ color: "var(--text-muted)" }}
          >
            ↻ Reload
          </button>
        </div>

        {loadingHistory ? (
          <div className="py-8 text-center text-xs" style={{ color: "var(--text-muted)" }}>
            Loading history…
          </div>
        ) : history.length === 0 ? (
          <div
            className="py-8 text-center border border-dashed rounded-xl text-xs"
            style={{
              borderColor: "var(--border)",
              background: "var(--bg-surface)",
              color: "var(--text-muted)",
            }}
          >
            No quiz attempts yet. Generate a quiz above to get started.
          </div>
        ) : (
          <div
            className="overflow-x-auto rounded-xl shadow-sm"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
          >
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr
                  className="font-semibold"
                  style={{
                    borderBottom: "1px solid var(--border)",
                    background: "var(--bg-surface-2)",
                    color: "var(--text-muted)",
                  }}
                >
                  <th className="py-3 px-4">Topic</th>
                  <th className="py-3 px-4">Questions</th>
                  <th className="py-3 px-4">Score</th>
                  <th className="py-3 px-4">Accuracy</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4 text-right">Date</th>
                </tr>
              </thead>
              <tbody>
                {history.map((item) => {
                  const hasAttempt = item.latest_score !== null && item.latest_score !== undefined;
                  const pct = item.latest_percentage ?? 0;

                  return (
                    <tr
                      key={item.quiz_id}
                      style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    >
                      <td className="py-3 px-4 font-semibold" style={{ color: "var(--text-primary)" }}>
                        {editingQuizId === item.quiz_id ? (
                          <form
                            onSubmit={(e) => { e.preventDefault(); handleRenameQuiz(item.quiz_id); }}
                            className="flex items-center gap-1.5"
                          >
                            <input
                              autoFocus
                              value={editingTopic}
                              onChange={(e) => setEditingTopic(e.target.value)}
                              onBlur={() => handleRenameQuiz(item.quiz_id)}
                              onKeyDown={(e) => e.key === "Escape" && setEditingQuizId(null)}
                              className="w-full px-2 py-0.5 rounded border text-xs"
                              style={{
                                background: "var(--bg-surface-2)",
                                borderColor: "var(--accent)",
                                color: "var(--text-primary)",
                              }}
                              maxLength={255}
                            />
                          </form>
                        ) : (
                          <div className="group flex items-center gap-1.5">
                            <span className="truncate max-w-[180px]">{item.topic}</span>
                            <button
                              type="button"
                              onClick={() => { setEditingQuizId(item.quiz_id); setEditingTopic(item.topic); }}
                              title="Rename topic"
                              aria-label="Rename topic"
                              className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-all text-[11px] p-1 rounded-md hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] focus-visible:ring-2 focus-visible:outline-none"
                              style={{ color: "var(--text-muted)" }}
                            >
                              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 012.828 2.828L11.828 15.828a2 2 0 01-1.414.586H8v-2.414a2 2 0 01.586-1.414z" />
                              </svg>
                            </button>
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                        {item.num_questions}
                      </td>
                      <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                        {hasAttempt ? `${item.latest_score} / ${item.num_questions}` : "Not attempted"}
                      </td>
                      <td className="py-3 px-4 font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                        {hasAttempt ? `${pct.toFixed(1)}%` : "—"}
                      </td>
                      <td className="py-3 px-4">
                        {hasAttempt ? (
                          pct >= 80 ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900">
                              Strong (≥80%)
                            </span>
                          ) : pct >= 60 ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-400 border border-blue-200 dark:border-blue-900">
                              Good (60–79%)
                            </span>
                          ) : (
                            <div className="flex items-center gap-2">
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-400 border border-rose-200 dark:border-rose-900 shrink-0">
                                Weak (&lt;60%)
                              </span>
                              <button
                                onClick={() => handlePracticeWeakTopic(item.document_id, item.topic)}
                                disabled={generating}
                                className="px-2 py-0.5 rounded text-white text-[10px] font-semibold transition-all hover:bg-rose-700 active:scale-[0.98] shadow-sm shrink-0 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:outline-none"
                                style={{ background: "#e11d48" }}
                              >
                                Practice
                              </button>
                            </div>
                          )
                        ) : (
                          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>Not attempted</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right" style={{ color: "var(--text-muted)" }}>
                        {item.latest_attempt_at
                          ? new Date(item.latest_attempt_at).toLocaleDateString()
                          : item.created_at
                          ? new Date(item.created_at).toLocaleDateString()
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default function QuizPage() {
  return (
    <Suspense
      fallback={
        <div className="flex-1 flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
          <span className="text-xs">Loading quiz…</span>
        </div>
      }
    >
      <QuizComponent />
    </Suspense>
  );
}
