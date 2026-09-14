/**
 * components/Toast.tsx
 *
 * Reusable, theme-aware Toast Notification System.
 *
 * Supports:
 *  - "success", "error", and "info" notification types.
 *  - Auto-dismiss (default 4000ms).
 *  - Manual dismiss button.
 *  - Queue limit of 4 active notifications.
 *  - Full keyboard accessibility and screen reader support (role="status", aria-live="polite").
 *  - Styled cleanly using CSS variables across light, dark, and green themes.
 */

"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

export type ToastType = "success" | "error" | "info";

export interface ToastItem {
  id: string;
  type: ToastType;
  message: string;
  durationMs?: number;
}

export interface ToastMethods {
  success: (message: string, durationMs?: number) => void;
  error: (message: string, durationMs?: number) => void;
  info: (message: string, durationMs?: number) => void;
}

export interface ToastContextValue extends ToastMethods {
  toasts: ToastItem[];
  removeToast: (id: string) => void;
  toast: ToastMethods;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const removeToast = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (type: ToastType, message: string, durationMs = 4000) => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const newToast: ToastItem = { id, type, message, durationMs };

      setToasts((prev) => {
        const next = [...prev, newToast];
        return next.length > 4 ? next.slice(next.length - 4) : next;
      });

      if (durationMs > 0) {
        const timer = setTimeout(() => {
          removeToast(id);
        }, durationMs);
        timersRef.current.set(id, timer);
      }
    },
    [removeToast]
  );

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
    };
  }, []);

  const toastMethods = useMemo(
    () => ({
      success: (msg: string, dur?: number) => addToast("success", msg, dur),
      error: (msg: string, dur?: number) => addToast("error", msg, dur),
      info: (msg: string, dur?: number) => addToast("info", msg, dur),
    }),
    [addToast]
  );

  return (
    <ToastContext.Provider
      value={{
        toasts,
        removeToast,
        toast: toastMethods,
        ...toastMethods,
      }}
    >
      {children}
      <ToastContainer toasts={toasts} onDismiss={removeToast} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}

function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-2.5 max-w-sm w-full px-4 sm:px-0 pointer-events-none"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastCard({
  toast,
  onDismiss,
}: {
  toast: ToastItem;
  onDismiss: () => void;
}) {
  const isSuccess = toast.type === "success";
  const isError = toast.type === "error";

  const getBorderColor = () => {
    if (isSuccess) return "#10b981";
    if (isError) return "#f43f5e";
    return "var(--border)";
  };

  const getIcon = () => {
    if (isSuccess) {
      return (
        <svg className="w-4 h-4 text-emerald-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      );
    }
    if (isError) {
      return (
        <svg className="w-4 h-4 text-rose-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      );
    }
    return (
      <svg className="w-4 h-4 shrink-0" style={{ color: "var(--accent)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    );
  };

  return (
    <div
      className="pointer-events-auto flex items-start gap-3 p-3.5 rounded-xl shadow-lg border transition-all page-enter"
      style={{
        background: "var(--bg-surface)",
        borderColor: getBorderColor(),
      }}
    >
      <div className="pt-0.5">{getIcon()}</div>
      <p className="flex-1 text-xs font-medium leading-relaxed" style={{ color: "var(--text-primary)" }}>
        {toast.message}
      </p>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
