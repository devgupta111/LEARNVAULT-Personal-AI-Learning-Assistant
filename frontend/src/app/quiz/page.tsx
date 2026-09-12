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

import { useSearchParams } from "next/navigation";
import { useEffect, useState, Suspense } from "react";
import { useAuth } from "../../../hooks/useAuth";
import {
  generateQuiz,
  getDocuments,
  getQuizHistory,
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
  const searchParams = useSearchParams();
  const initialDocId = searchParams.get("doc");
  const initialTopic = searchParams.get("topic");

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string>("");
  const [topic, setTopic] = useState<string>("");
  const [currentQuiz, setCurrentQuiz] = useState<QuizDetail | null>(null);
  const [userAnswers, setUserAnswers] = useState<Record<number, string>>({});
  const [submissionResult, setSubmissionResult] = useState<QuizSubmissionResult | null>(null);
  const [history, setHistory] = useState<QuizHistoryItem[]>([]);

  const [generating, setGenerating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialTopic) setTopic(initialTopic);
  }, [initialTopic]);

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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, initialDocId]);

  const loadHistory = async () => {
    try {
      setLoadingHistory(true);
      const hist = await getQuizHistory();
      setHistory(hist);
    } catch {
      // Non-fatal
    } finally {
      setLoadingHistory(false);
    }
  };

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
            className="w-full py-2.5 rounded-lg text-white font-medium text-xs transition-colors shadow-sm disabled:opacity-50 flex items-center justify-center gap-2"
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

          {/* Questions */}
          <div className="space-y-6">
            {currentQuiz.questions.map((q, qIdx) => {
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
                          className="p-3 rounded-lg text-xs font-medium text-left transition-all"
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

          {/* Submit / Result */}
          {!submissionResult ? (
            <div
              className="flex justify-end pt-4"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <button
                onClick={handleSubmitQuiz}
                disabled={submitting}
                className="px-6 py-2.5 rounded-lg text-white font-medium text-xs transition-colors shadow-sm disabled:opacity-50 flex items-center gap-2"
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
                  className="p-4 rounded-xl flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"
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
                    className="px-4 py-2 rounded-lg text-white text-xs font-semibold shadow-sm transition-colors self-start sm:self-auto"
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
                  }}
                  className="px-4 py-2 rounded-lg text-xs font-semibold transition-colors"
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
            className="text-xs transition-colors"
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
                  const isWeak = hasAttempt && pct < 60;

                  return (
                    <tr
                      key={item.quiz_id}
                      style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    >
                      <td className="py-3 px-4 font-semibold" style={{ color: "var(--text-primary)" }}>
                        {item.topic}
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
                          isWeak ? (
                            <div className="flex items-center gap-2">
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-400 border border-rose-200 dark:border-rose-900 shrink-0">
                                Weak (&lt;60%)
                              </span>
                              <button
                                onClick={() => handlePracticeWeakTopic(item.document_id, item.topic)}
                                disabled={generating}
                                className="px-2 py-0.5 rounded text-white text-[10px] font-semibold transition-colors shadow-sm shrink-0"
                                style={{ background: "#e11d48" }}
                              >
                                Practice
                              </button>
                            </div>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900">
                              Mastered (≥60%)
                            </span>
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
