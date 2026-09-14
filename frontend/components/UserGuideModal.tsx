/**
 * components/UserGuideModal.tsx
 *
 * Lightweight user guide modal accessible from the profile dropdown.
 * Keyboard: Escape closes. Click-outside closes.
 */

"use client";

import { useEffect, useRef } from "react";

interface Props {
  onClose: () => void;
}

interface GuideItem {
  term?: string;
  desc: string;
}

interface Section {
  id: string;
  emoji: string;
  title: string;
  items: GuideItem[];
}

const SECTIONS: Section[] = [
  {
    id: "start",
    emoji: "🚀",
    title: "Getting Started",
    items: [
      { desc: "Personal AI Learning Assistant helps you master your course materials through grounded Q&A and adaptive quizzes." },
      { desc: "Uploading study material: Upload lecture notes, textbooks, or course handouts in PDF format (up to 20 MB) on the Documents page." },
      { desc: "Using Chat: Ask natural-language questions about your notes and receive factual, grounded answers with exact page references." },
      { desc: "Using Quiz: Test your knowledge with auto-generated multiple-choice questions graded deterministically to track your progress." },
      { desc: "All your study materials, conversations, and quizzes are private and scoped strictly to your account." },
    ],
  },
  {
    id: "documents",
    emoji: "📄",
    title: "Documents",
    items: [
      { term: "Document", desc: "A PDF file containing your study notes, textbook chapters, or lecture slides uploaded to your account." },
      { term: "Processing", desc: "Your document is being read, analyzed, and prepared for search and quiz generation. This typically takes 30–120 seconds." },
      { term: "Ready", desc: "Preparation complete. The document is fully ready for grounded RAG Chat and Quiz generation." },
      { term: "Failed", desc: "The document could not be processed (e.g. image-only scan without selectable text or corrupt file). Try uploading a clean text-based PDF." },
      { term: "Subject / Course", desc: "An optional subject tag (such as DBMS or Operating Systems) to organize your notes and guide generated quizzes." },
    ],
  },
  {
    id: "chat",
    emoji: "💬",
    title: "RAG Chat",
    items: [
      { term: "RAG", desc: "Retrieval-Augmented Generation. Instead of generating answers from general internet knowledge, the assistant retrieves exact passages directly from your uploaded study material." },
      { term: "Grounded Answer", desc: "Every response is strictly based on the content of your uploaded notes. If sufficient information cannot be found in your material, the assistant will state that it cannot answer rather than guessing or fabricating facts." },
      { term: "Citation", desc: "A verifiable reference pointing directly to the specific page number(s) in your uploaded document where the fact was found." },
      { term: "Source", desc: "A clickable reference badge showing the document name and verified page number for each retrieved fact." },
      { term: "Chat Session", desc: "A conversation thread associated with a document. You can maintain multiple sessions and delete any session when no longer needed." },
    ],
  },
  {
    id: "quiz",
    emoji: "🎯",
    title: "Quiz & Scoring",
    items: [
      { term: "Quiz", desc: "A set of practice questions generated directly from your study material to evaluate your understanding and retention." },
      { term: "MCQ", desc: "Multiple-Choice Questions featuring 4 options (A–D). Only one option is correct." },
      { term: "Score", desc: "The total count of correctly answered questions on a completed quiz attempt." },
      { term: "Accuracy", desc: "Calculated as (Score ÷ Total Questions) × 100%. Graded deterministically — scores are based strictly on whether your selected option matches the correct answer." },
      { term: "Not Attempted", desc: "A quiz that was generated but has not yet been answered or submitted for grading." },
      { term: "Score Bands", desc: "Performance is categorized into three clear achievement tiers:" },
      { term: "80–100%", desc: "Strong understanding — excellent command and mastery of the topic." },
      { term: "60–79%", desc: "Good understanding — solid foundation, with room for targeted revision." },
      { term: "Below 60%", desc: "Needs practice / Weak Topic — requires additional study and practice." },
      { term: "Rename Topic", desc: "You can rename any quiz topic in Quiz History using the pencil icon without losing your questions or attempt history." },
    ],
  },
  {
    id: "weak",
    emoji: "⚠️",
    title: "Weak Topic System",
    items: [
      { term: "Rule: accuracy < 60%", desc: "Any topic where your latest score is below 60% is automatically classified as a Weak Topic." },
      { term: "Explicit Cutoff", desc: "59% is classified as a Weak Topic. 60% is NOT a Weak Topic (it qualifies as Good understanding)." },
      { term: "Smart Practice", desc: "Clicking 'Practice' on any weak topic immediately generates a fresh quiz focusing on that specific area." },
      { term: "Achieving Mastery", desc: "Once you score 60% or higher on a weak topic, its status updates to Good or Strong, clearing the weak topic flag." },
    ],
  },
  {
    id: "delete",
    emoji: "🗑️",
    title: "Deleting Data & Confirmation",
    items: [
      { term: "Delete Document", desc: "Permanently deletes the PDF file, its search data, all associated chat sessions and messages, and all generated quizzes and attempts. This action is irreversible." },
      { term: "Delete Chat Session", desc: "Permanently deletes the selected conversation thread and its message history. Your document, other chat sessions, and quizzes remain intact." },
      { term: "Confirmation Required", desc: "All delete actions require explicit user confirmation to prevent accidental loss of study history or notes." },
      { desc: "Quizzes are tied to their source document and are permanently cleaned up when the parent document is deleted." },
    ],
  },
  {
    id: "tips",
    emoji: "💡",
    title: "Tips for Best Results",
    items: [
      { desc: "Upload clear study material: Clean, digital text-based PDFs give the most accurate extraction and reliable citations." },
      { desc: "Ask specific questions: Questions focusing on specific concepts, definitions, or comparisons produce the most detailed grounded answers." },
      { desc: "Check citations: Click source badges to cross-reference answers with the exact pages in your course notes." },
      { desc: "Use quizzes to find gaps: Take practice quizzes after reading a chapter to discover which concepts need more attention." },
      { desc: "Practice weak topics: Use the Practice button next to weak topics (<60%) to reinforce difficult concepts before exams." },
    ],
  },
];

export default function UserGuideModal({ onClose }: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, []);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (panelRef.current && !panelRef.current.contains(e.target as Node)) onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[999] flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)", backdropFilter: "blur(4px)" }}
      onClick={handleOverlayClick}
      aria-modal="true"
      role="dialog"
      aria-label="User Guide"
    >
      <div
        ref={panelRef}
        className="relative w-full max-w-2xl max-h-[85vh] flex flex-col rounded-2xl shadow-2xl overflow-hidden"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 shrink-0"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div>
            <h2 className="text-base font-bold flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span>📖</span>
              <span>User Guide</span>
            </h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              Key terms, grading rules, and features explained
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close user guide"
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-all hover:bg-[var(--bg-surface-2)] text-[var(--text-muted)] hover:text-[var(--text-primary)] focus-visible:ring-2 focus-visible:outline-none"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-7">
          {SECTIONS.map((section) => (
            <section key={section.id}>
              <h3
                className="text-xs font-bold uppercase tracking-wider mb-3 flex items-center gap-1.5"
                style={{ color: "var(--accent-text)" }}
              >
                <span>{section.emoji}</span>
                <span>{section.title}</span>
              </h3>
              <div className="space-y-2.5">
                {section.items.map((item, i) => (
                  <div key={i} className="flex gap-2.5">
                    {item.term ? (
                      <>
                        <span
                          className="shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-md leading-tight mt-0.5"
                          style={{ background: "var(--accent-surface)", color: "var(--accent-text)", whiteSpace: "nowrap" }}
                        >
                          {item.term}
                        </span>
                        <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                          {item.desc}
                        </p>
                      </>
                    ) : (
                      <p
                        className="text-xs leading-relaxed pl-2"
                        style={{ color: "var(--text-secondary)", borderLeft: "2px solid var(--border)" }}
                      >
                        {item.desc}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>

        {/* Footer */}
        <div
          className="px-6 py-3 flex items-center justify-between shrink-0"
          style={{ borderTop: "1px solid var(--border)", background: "var(--bg-surface-2)" }}
        >
          <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>Personal AI Learning Assistant — Help</span>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg text-xs font-medium transition-all hover:brightness-105 active:scale-[0.98] shadow-sm focus-visible:ring-2 focus-visible:outline-none"
            style={{ background: "var(--accent)", color: "#fff" }}
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
