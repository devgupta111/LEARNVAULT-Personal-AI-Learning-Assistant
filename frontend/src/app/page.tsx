/**
 * app/page.tsx
 *
 * Landing / home page.
 *
 * Shown to all visitors (authenticated or not) at "/".
 * Clean, student-facing content — no internal development labels.
 */

import Link from "next/link";

export const metadata = {
  title: "Personal AI Learning Assistant",
  description:
    "Upload your lecture notes and get grounded, citation-verified answers with adaptive practice quizzes.",
};

export default function Home() {
  return (
    <main className="flex-1 flex flex-col items-center justify-center px-4 py-16 sm:px-6 lg:px-8 max-w-5xl mx-auto text-center page-enter">
      {/* Hero heading */}
      <h1
        className="text-4xl sm:text-6xl font-extrabold tracking-tight mb-6"
        style={{ color: "var(--text-primary)" }}
      >
        Study Smarter with Your{" "}
        <span
          className="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-transparent"
        >
          Personal AI Learning Assistant
        </span>
      </h1>

      <p
        className="max-w-2xl text-lg sm:text-xl mb-10"
        style={{ color: "var(--text-secondary)" }}
      >
        Upload your lecture notes, ask questions grounded strictly in your study
        material with verified page citations, and test your knowledge with
        adaptive multiple-choice quizzes.
      </p>

      {/* CTA buttons */}
      <div className="flex flex-wrap items-center justify-center gap-4 mb-16">
        <Link
          href="/dashboard"
          className="px-6 py-3 rounded-xl font-semibold text-sm text-white transition-all shadow-md hover:shadow-lg"
          style={{ background: "var(--accent)" }}
        >
          Open Study Dashboard
        </Link>
        <Link
          href="/documents"
          className="px-6 py-3 rounded-xl font-semibold text-sm transition-colors"
          style={{
            background: "var(--bg-surface)",
            color: "var(--text-primary)",
            border: "1px solid var(--border)",
          }}
        >
          Upload Notes (PDF)
        </Link>
        <Link
          href="/chat"
          className="px-6 py-3 rounded-xl font-semibold text-sm transition-colors"
          style={{
            background: "var(--bg-surface)",
            color: "var(--text-primary)",
            border: "1px solid var(--border)",
          }}
        >
          Ask a Question
        </Link>
        <Link
          href="/quiz"
          className="px-6 py-3 rounded-xl font-semibold text-sm transition-colors"
          style={{
            background: "var(--bg-surface)",
            color: "var(--text-primary)",
            border: "1px solid var(--border)",
          }}
        >
          Practice Quiz
        </Link>
      </div>

      {/* Feature cards */}
      <div className="w-full grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-left">
        {[
          {
            label: "Smart Routing",
            title: "Grounded RAG Answers",
            desc: "Every answer is generated strictly from your uploaded notes — no hallucinated facts.",
          },
          {
            label: "Corrective Retrieval",
            title: "Automatic Query Refinement",
            desc: "When retrieval is weak, the system reformulates your query for a targeted retry.",
          },
          {
            label: "Verified Citations",
            title: "Page-Level Source Tracking",
            desc: "Every factual claim is graded and linked to the exact page in your document.",
          },
          {
            label: "Adaptive Quizzes",
            title: "Weak Topic Diagnostics",
            desc: "Generates targeted MCQs and tracks topics where your accuracy falls below 60%.",
          },
        ].map((card) => (
          <div
            key={card.label}
            className="p-4 rounded-xl shadow-sm"
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
            }}
          >
            <div
              className="text-xs font-semibold mb-1"
              style={{ color: "var(--accent-text)" }}
            >
              {card.label}
            </div>
            <h3
              className="text-sm font-bold mb-1"
              style={{ color: "var(--text-primary)" }}
            >
              {card.title}
            </h3>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              {card.desc}
            </p>
          </div>
        ))}
      </div>
    </main>
  );
}
