/**
 * components/EditDocumentModal.tsx
 *
 * Accessible, theme-aware in-app modal for editing document metadata (filename and subject).
 * Follows LearnVault design tokens and strict accessibility guidelines.
 *
 * Constraints & Features:
 *  - Filename / display filename: Maximum 60 characters with live counter (0/60)
 *  - Subject / Course: Maximum 40 characters with live counter (0/40)
 *  - Rejects blank values and trims surrounding whitespace
 *  - Live character counters updating dynamically on typing
 *  - Loading, error, and disabled states
 *  - Strict accessibility: role="dialog", aria-modal="true", Escape key dismissal, focus trapping & restoration
 *  - Preserves underlying document_id, page_count, status, storage path, and Qdrant data
 */

"use client";

import { useState, useEffect, useRef } from "react";
import { DocumentSummary } from "../types";
import { updateDocument } from "../lib/api";

interface EditDocumentModalProps {
  isOpen: boolean;
  document: DocumentSummary | null;
  onClose: () => void;
  onSuccess: (updatedDoc: DocumentSummary) => void;
}

export default function EditDocumentModal({
  isOpen,
  document: doc,
  onClose,
  onSuccess,
}: EditDocumentModalProps) {
  const [filename, setFilename] = useState("");
  const [subject, setSubject] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const modalRef = useRef<HTMLDivElement>(null);
  const filenameInputRef = useRef<HTMLInputElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const saveButtonRef = useRef<HTMLButtonElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);

  // Sync state when modal opens or document changes
  useEffect(() => {
    if (isOpen && doc) {
      setFilename(doc.filename || "");
      setSubject(doc.subject || "");
      setError(null);
      setIsSaving(false);

      previousActiveElement.current = (typeof window !== "undefined" ? window.document.activeElement : null) as HTMLElement | null;

      const timer = setTimeout(() => {
        filenameInputRef.current?.focus();
        filenameInputRef.current?.select();
      }, 50);

      if (typeof window !== "undefined") {
        window.document.body.style.overflow = "hidden";
      }

      return () => {
        clearTimeout(timer);
        if (typeof window !== "undefined") {
          window.document.body.style.overflow = "";
        }
        previousActiveElement.current?.focus();
      };
    }
  }, [isOpen, doc]);

  if (!isOpen || !doc) return null;

  const docId = doc.document_id || doc.id || "";

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      if (!isSaving) {
        onClose();
      }
      return;
    }

    if (e.key === "Tab") {
      const focusable = [
        filenameInputRef.current,
        saveButtonRef.current,
        cancelButtonRef.current,
      ].filter(Boolean) as HTMLElement[];

      if (focusable.length < 2) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey && (typeof window !== "undefined" ? window.document.activeElement : null) === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (typeof window !== "undefined" ? window.document.activeElement : null) === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget && !isSaving) {
      onClose();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const cleanFilename = filename.trim();
    const cleanSubject = subject.trim();

    if (!cleanFilename) {
      setError("Filename cannot be blank.");
      filenameInputRef.current?.focus();
      return;
    }

    if (cleanFilename.length > 60) {
      setError("Filename cannot exceed 60 characters.");
      filenameInputRef.current?.focus();
      return;
    }

    if (!cleanSubject) {
      setError("Subject cannot be blank.");
      return;
    }

    if (cleanSubject.length > 40) {
      setError("Subject cannot exceed 40 characters.");
      return;
    }

    setIsSaving(true);
    try {
      const updated = await updateDocument(docId, {
        filename: cleanFilename,
        subject: cleanSubject,
      });
      onSuccess(updated);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to update document metadata.";
      setError(msg);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 page-enter"
      style={{
        background: "rgba(0, 0, 0, 0.55)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
      }}
      onClick={handleBackdropClick}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="edit-doc-modal-title"
      aria-describedby="edit-doc-modal-desc"
    >
      <div
        ref={modalRef}
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl transition-all"
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header with reference pencil icon badge */}
        <div className="flex items-start gap-3.5 mb-4">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{
              background: "var(--accent-surface)",
              color: "var(--accent)",
            }}
            aria-hidden="true"
          >
            {/* Reference pencil icon */}
            <svg
              className="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 012.828 2.828L11.828 15.828a2 2 0 01-1.414.586H8v-2.414a2 2 0 01.586-1.414z"
              />
            </svg>
          </div>

          <div className="flex-1 min-w-0">
            <h2
              id="edit-doc-modal-title"
              className="text-lg font-bold tracking-tight"
              style={{ color: "var(--text-primary)" }}
            >
              Edit Document
            </h2>
            <p
              id="edit-doc-modal-desc"
              className="text-xs mt-0.5"
              style={{ color: "var(--text-muted)" }}
            >
              Update document filename and course subject metadata.
            </p>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div
            role="alert"
            className="mb-4 p-3 rounded-xl text-xs bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Filename Field */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label
                htmlFor="edit-doc-filename"
                className="block text-xs font-semibold"
                style={{ color: "var(--text-secondary)" }}
              >
                Filename
              </label>
              <span
                className={`text-[11px] font-mono ${
                  filename.length > 60
                    ? "text-rose-500 font-bold"
                    : filename.length >= 50
                    ? "text-amber-500"
                    : "text-[var(--text-muted)]"
                }`}
                aria-live="polite"
              >
                {filename.length}/60
              </span>
            </div>
            <input
              ref={filenameInputRef}
              id="edit-doc-filename"
              type="text"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              maxLength={60}
              disabled={isSaving}
              placeholder="e.g. Lecture 1 - Introduction.pdf"
              className="w-full px-3.5 py-2.5 rounded-xl text-xs font-medium border transition-colors focus:outline-none focus:ring-2"
              style={{
                background: "var(--bg-surface-2)",
                borderColor: "var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>

          {/* Subject Field */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label
                htmlFor="edit-doc-subject"
                className="block text-xs font-semibold"
                style={{ color: "var(--text-secondary)" }}
              >
                Subject / Course
              </label>
              <span
                className={`text-[11px] font-mono ${
                  subject.length > 40
                    ? "text-rose-500 font-bold"
                    : subject.length >= 35
                    ? "text-amber-500"
                    : "text-[var(--text-muted)]"
                }`}
                aria-live="polite"
              >
                {subject.length}/40
              </span>
            </div>
            <input
              id="edit-doc-subject"
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              maxLength={40}
              disabled={isSaving}
              placeholder="e.g. Operating Systems"
              className="w-full px-3.5 py-2.5 rounded-xl text-xs font-medium border transition-colors focus:outline-none focus:ring-2"
              style={{
                background: "var(--bg-surface-2)",
                borderColor: "var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>

          {/* Action Buttons */}
          <div
            className="mt-6 pt-4 flex items-center justify-end gap-3"
            style={{ borderTop: "1px solid var(--border)" }}
          >
            <button
              ref={cancelButtonRef}
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 rounded-xl text-xs font-semibold transition-all border disabled:opacity-50 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
              style={{
                background: "var(--bg-surface-2)",
                borderColor: "var(--border)",
                color: "var(--text-primary)",
              }}
            >
              Cancel
            </button>

            <button
              ref={saveButtonRef}
              type="submit"
              disabled={isSaving}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-white transition-all active:scale-[0.98] disabled:opacity-60 shadow-sm focus-visible:ring-2 focus-visible:outline-none flex items-center gap-1.5"
              style={{ background: "var(--accent)" }}
            >
              {isSaving ? (
                <>
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Saving…</span>
                </>
              ) : (
                <span>Save Changes</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
