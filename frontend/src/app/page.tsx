/**
 * app/page.tsx
 *
 * Landing / home page.
 *
 * Product-facing messaging focusing on student benefits:
 *  - Grounded RAG Answers
 *  - Source Citations
 *  - Adaptive Quizzes
 *  - Weak Topic Practice
 *  - No internal development or agent architecture jargon.
 */

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "../../lib/api";
import UserGuideModal from "../../components/UserGuideModal";

export default function Home() {
  const router = useRouter();
  const [showGuide, setShowGuide] = useState(false);

  // Redirect authenticated user to /dashboard immediately
  useEffect(() => {
    if (getToken()) {
      router.replace("/dashboard");
    }
  }, [router]);

  return (
    <main className="flex-1 flex flex-col items-center justify-center px-4 py-16 sm:px-6 lg:px-8 max-w-5xl mx-auto text-center page-enter">
      {/* Hero heading */}
      <h1
        className="text-4xl sm:text-6xl font-extrabold tracking-tight mb-6"
        style={{ color: "var(--text-primary)" }}
      >
        Learn Smarter with Your{" "}
        <span
          className="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-transparent"
        >
          Own Study Material
        </span>
      </h1>

      <p
        className="max-w-2xl text-lg sm:text-xl mb-10"
        style={{ color: "var(--text-secondary)" }}
      >
        Upload lecture notes, PDFs, and textbooks. Ask grounded questions
        with source citations and practice with adaptive quizzes.
      </p>

      {/* CTA buttons */}
      <div className="flex flex-wrap items-center justify-center gap-3.5 mb-16">
        <Link
          href="/login"
          className="px-6 py-3 rounded-xl font-semibold text-sm text-white shadow-md transition-all hover:brightness-105 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
          style={{ background: "var(--accent)" }}
        >
          Get Started →
        </Link>
        <button
          type="button"
          onClick={() => setShowGuide(true)}
          className="hero-cta-btn px-6 py-3 rounded-xl font-semibold text-sm shadow-sm transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none flex items-center gap-2 cursor-pointer"
        >
          <span>📖</span>
          <span>Read User Guide</span>
        </button>
        <Link
          href="/documents"
          className="hero-cta-btn px-5 py-3 rounded-xl font-semibold text-sm shadow-sm transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
        >
          Upload Notes
        </Link>
        <Link
          href="/chat"
          className="hero-cta-btn px-5 py-3 rounded-xl font-semibold text-sm shadow-sm transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
        >
          Ask Questions
        </Link>
        <Link
          href="/quiz"
          className="hero-cta-btn px-5 py-3 rounded-xl font-semibold text-sm shadow-sm transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
        >
          Practice Quiz
        </Link>
      </div>

      {/* Feature cards */}
      <div className="w-full grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-left">
        {[
          {
            label: "Study Assistant",
            title: "Grounded RAG Answers",
            desc: "Answers are derived directly from your uploaded material with zero made-up facts.",
          },
          {
            label: "Verification",
            title: "Source Citations",
            desc: "Every factual point is verified and linked directly to exact page numbers in your notes.",
          },
          {
            label: "Active Recall",
            title: "Adaptive Quizzes",
            desc: "Generate tailored multiple-choice practice quizzes from any lecture or document.",
          },
          {
            label: "Mastery",
            title: "Weak Topic Practice",
            desc: "Diagnose areas where accuracy is below 60% and focus practice where you need it most.",
          },
        ].map((card) => (
          <div
            key={card.title}
            className="p-5 rounded-2xl shadow-sm border transition-transform hover:-translate-y-0.5"
            style={{
              background: "var(--bg-surface)",
              borderColor: "var(--border)",
            }}
          >
            <div
              className="text-xs font-semibold mb-1"
              style={{ color: "var(--accent-text)" }}
            >
              {card.label}
            </div>
            <h3
              className="text-sm font-bold mb-1.5"
              style={{ color: "var(--text-primary)" }}
            >
              {card.title}
            </h3>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
              {card.desc}
            </p>
          </div>
        ))}
      </div>

      {/* User Guide Modal for unauthenticated visitors */}
      {showGuide && <UserGuideModal onClose={() => setShowGuide(false)} />}
    </main>
  );
}
