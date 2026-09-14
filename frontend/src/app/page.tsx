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
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "../../lib/api";

export default function Home() {
  const router = useRouter();

  // Redirect authenticated user to /dashboard immediately
  useEffect(() => {
    if (getToken()) {
      router.replace("/dashboard");
    }
  }, [router]);

  return (
    <main className="flex-1 flex flex-col items-center justify-center px-4 py-12 sm:py-16 sm:px-6 lg:px-8 max-w-5xl mx-auto text-center page-enter w-full">
      {/* Hero heading */}
      <h1
        className="text-3xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight mb-4 sm:mb-6"
        style={{ color: "var(--text-primary)" }}
      >
        Learn Smarter with Your{" "}
        <span
          className="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-transparent inline-block"
        >
          Own Study Material
        </span>
      </h1>

      <p
        className="max-w-2xl text-base sm:text-lg lg:text-xl mb-8 sm:mb-10 px-2 leading-relaxed"
        style={{ color: "var(--text-secondary)" }}
      >
        Upload lecture notes, PDFs, and textbooks. Ask grounded questions
        with source citations and practice with adaptive quizzes.
      </p>

      {/* CTA buttons */}
      <div className="flex flex-wrap items-center justify-center gap-3 sm:gap-3.5 mb-12 sm:mb-16 w-full max-w-lg sm:max-w-none">
        <Link
          href="/login"
          className="w-full sm:w-auto px-6 py-3 rounded-xl font-semibold text-sm text-white shadow-md transition-all hover:brightness-105 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none text-center"
          style={{ background: "var(--accent)" }}
        >
          Get Started →
        </Link>
        <Link
          href="/documents"
          className="hero-cta-btn w-full sm:w-auto px-5 py-3 rounded-xl font-semibold text-sm shadow-sm transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none text-center"
        >
          Upload Notes
        </Link>
        <Link
          href="/chat"
          className="hero-cta-btn w-full sm:w-auto px-5 py-3 rounded-xl font-semibold text-sm shadow-sm transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none text-center"
        >
          Ask Questions
        </Link>
        <Link
          href="/quiz"
          className="hero-cta-btn w-full sm:w-auto px-5 py-3 rounded-xl font-semibold text-sm shadow-sm transition-all active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none text-center"
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
    </main>
  );
}
