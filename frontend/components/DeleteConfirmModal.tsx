/**
 * components/DeleteConfirmModal.tsx
 *
 * Polished, accessible, theme-aware in-app confirmation modal for document deletion.
 * Replaces outdated browser-native window.confirm() dialogs.
 *
 * Features:
 *  - Matches LearnVault CSS variables (--bg-surface, --border, --text-primary, etc.)
 *  - Supports Light, Dark, and Green themes seamlessly
 *  - Strict accessibility: role="alertdialog", aria-modal="true", Escape to cancel, focus trapping & restoration
 *  - Double-click and loading protection during in-flight deletion
 *  - Safe wrapping for long filenames on mobile/desktop
 */

"use client";

import { useEffect, useRef } from "react";

interface DeleteConfirmModalProps {
  isOpen: boolean;
  filename: string;
  isDeleting?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function DeleteConfirmModal({
  isOpen,
  filename,
  isDeleting = false,
  onConfirm,
  onCancel,
}: DeleteConfirmModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const deleteButtonRef = useRef<HTMLButtonElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (isOpen) {
      previousActiveElement.current = document.activeElement as HTMLElement;
      // Focus Cancel button by default (safe default for destructive action)
      const timer = setTimeout(() => {
        cancelButtonRef.current?.focus();
      }, 50);
      document.body.style.overflow = "hidden";
      return () => {
        clearTimeout(timer);
        document.body.style.overflow = "";
        previousActiveElement.current?.focus();
      };
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      if (!isDeleting) {
        onCancel();
      }
      return;
    }

    if (e.key === "Tab") {
      const focusable = [cancelButtonRef.current, deleteButtonRef.current].filter(Boolean) as HTMLElement[];
      if (focusable.length < 2) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget && !isDeleting) {
      onCancel();
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
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="delete-modal-title"
      aria-describedby="delete-modal-desc"
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
        {/* Header with warning icon badge */}
        <div className="flex items-start gap-3.5 mb-4">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{
              background: "rgba(239, 68, 68, 0.12)",
              color: "#ef4444",
            }}
            aria-hidden="true"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
              />
            </svg>
          </div>

          <div className="flex-1 min-w-0">
            <h2
              id="delete-modal-title"
              className="text-lg font-bold tracking-tight"
              style={{ color: "var(--text-primary)" }}
            >
              Delete document?
            </h2>
          </div>
        </div>

        {/* Content Body */}
        <div id="delete-modal-desc" className="space-y-2.5 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <p className="font-medium break-all" style={{ color: "var(--text-primary)" }}>
            Delete &apos;{filename}&apos;?
          </p>
          <p>
            This will permanently remove the document, all chat sessions, messages, quizzes, and quiz attempts linked to it.
          </p>
          <p className="font-medium text-rose-600 dark:text-rose-400">
            This action cannot be undone.
          </p>
        </div>

        {/* Action Buttons */}
        <div
          className="mt-6 pt-4 flex items-center justify-end gap-3"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <button
            ref={cancelButtonRef}
            type="button"
            onClick={onCancel}
            disabled={isDeleting}
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
            ref={deleteButtonRef}
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-white transition-all bg-rose-600 hover:bg-rose-700 active:scale-[0.98] disabled:opacity-60 shadow-sm focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:outline-none flex items-center gap-1.5"
          >
            {isDeleting && (
              <span
                className="w-3.5 h-3.5 border-2 border-t-transparent rounded-full animate-spin"
                style={{ borderColor: "#ffffff", borderTopColor: "transparent" }}
              />
            )}
            <span>{isDeleting ? "Deleting…" : "Delete"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
