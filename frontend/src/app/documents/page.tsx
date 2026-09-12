/**
 * app/documents/page.tsx
 *
 * Document management — protected route.
 *
 * Features:
 *  - Upload PDF (max 20MB) with subject/course name
 *  - List all uploaded documents with status, page count, upload date
 *  - Polling every 3s while any document is in PROCESSING state
 *  - Chat / Quiz action buttons for READY documents
 *
 * Auth: useAuth(true) → redirects to /login if not authenticated.
 */

"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../../hooks/useAuth";
import { getDocuments, uploadDocument } from "../../../lib/api";
import { DocumentSummary } from "../../../types";

export default function DocumentsPage() {
  const { loading: authLoading } = useAuth(true);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [subject, setSubject] = useState("General");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const fetchDocs = async () => {
    try {
      const docs = await getDocuments();
      setDocuments(docs);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load documents";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  // Fetch only after auth is resolved
  useEffect(() => {
    if (!authLoading) {
      fetchDocs();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading]);

  // Poll every 3s while any document is PROCESSING
  useEffect(() => {
    const hasProcessing = documents.some((d) => d.status === "PROCESSING");
    if (!hasProcessing) return;
    const interval = setInterval(fetchDocs, 3000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documents]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null);
    setSuccessMsg(null);
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are supported.");
      setSelectedFile(null);
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setError("File is too large. Maximum size is 20 MB.");
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setError("Please choose a PDF file to upload.");
      return;
    }
    setUploading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await uploadDocument(selectedFile, subject.trim() || "General");
      setSuccessMsg(`Uploaded successfully. Processing extraction & embeddings… (ID: ${res.document_id.slice(0, 8)}…)`);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await fetchDocs();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      setError(msg);
    } finally {
      setUploading(false);
    }
  };

  if (authLoading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3" style={{ color: "var(--text-muted)" }}>
        <span
          className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
        />
      </div>
    );
  }

  return (
    <div className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8 page-enter">
      {/* Header */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold" style={{ color: "var(--text-primary)" }}>
          Document Management
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          Upload PDF lecture notes, course materials, or textbooks. Documents are automatically extracted, chunked, and indexed for RAG Chat and Quiz.
        </p>
      </div>

      {/* Upload card */}
      <div
        className="rounded-2xl p-6 shadow-sm"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
      >
        <h2 className="text-base font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
          Upload New Document
        </h2>

        {error && (
          <div className="mb-4 p-3.5 rounded-lg text-xs bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300">
            {error}
          </div>
        )}
        {successMsg && (
          <div className="mb-4 p-3.5 rounded-lg text-xs bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/50 text-emerald-700 dark:text-emerald-300 flex items-center gap-2">
            <span>✓</span>
            <span>{successMsg}</span>
          </div>
        )}

        <form onSubmit={handleUpload} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
                Select PDF File
              </label>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,application/pdf"
                onChange={handleFileChange}
                disabled={uploading}
                className="w-full px-3 py-2 rounded-lg border text-xs focus:outline-none"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--bg-surface-2)",
                  color: "var(--text-secondary)",
                }}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>
                Subject / Course
              </label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="e.g. DBMS, Operating Systems"
                disabled={uploading}
                className="w-full px-3 py-2 rounded-lg border text-xs focus:outline-none focus:ring-2"
                style={{
                  borderColor: "var(--border)",
                  background: "transparent",
                  color: "var(--text-primary)",
                }}
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={uploading || !selectedFile}
              className="px-5 py-2.5 rounded-lg text-white text-xs font-medium transition-colors shadow-sm disabled:opacity-50 flex items-center gap-2"
              style={{ background: "var(--accent)" }}
            >
              {uploading ? (
                <>
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Uploading…</span>
                </>
              ) : (
                <span>Upload PDF</span>
              )}
            </button>
          </div>
        </form>
      </div>

      {/* Documents table */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
            Your Study Notes
          </h2>
          <button
            onClick={fetchDocs}
            className="text-xs transition-colors"
            style={{ color: "var(--text-muted)" }}
          >
            ↻ Reload
          </button>
        </div>

        {loading ? (
          <div className="py-12 text-center flex flex-col items-center gap-2" style={{ color: "var(--text-muted)" }}>
            <span
              className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin"
              style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
            />
            <p className="text-xs">Loading documents…</p>
          </div>
        ) : documents.length === 0 ? (
          <div
            className="py-12 text-center border border-dashed rounded-xl text-xs"
            style={{
              borderColor: "var(--border)",
              background: "var(--bg-surface)",
              color: "var(--text-muted)",
            }}
          >
            No study documents uploaded yet. Upload a PDF above to get started.
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
                      style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    >
                      <td className="py-3 px-4 font-medium" style={{ color: "var(--text-primary)" }}>
                        {doc.filename}
                      </td>
                      <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                        {doc.subject || "General"}
                      </td>
                      <td className="py-3 px-4" style={{ color: "var(--text-secondary)" }}>
                        {doc.page_count != null ? `${doc.page_count} pages` : "Processing"}
                      </td>
                      <td className="py-3 px-4">
                        {doc.status === "READY" && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                            Ready
                          </span>
                        )}
                        {doc.status === "PROCESSING" && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-semibold bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                            Processing…
                          </span>
                        )}
                        {doc.status === "FAILED" && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-400 border border-rose-200 dark:border-rose-800">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                            Failed
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4" style={{ color: "var(--text-muted)" }}>
                        {doc.created_at ? new Date(doc.created_at).toLocaleString() : "—"}
                      </td>
                      <td className="py-3 px-4 text-right">
                        {doc.status === "READY" && (
                          <div className="flex items-center justify-end gap-2">
                            <Link
                              href={`/chat?doc=${docId}`}
                              className="font-medium transition-colors"
                              style={{ color: "var(--accent-text)" }}
                            >
                              Chat
                            </Link>
                            <span style={{ color: "var(--border)" }}>|</span>
                            <Link
                              href={`/quiz?doc=${docId}`}
                              className="font-medium text-purple-600 dark:text-purple-400 transition-colors"
                            >
                              Quiz
                            </Link>
                          </div>
                        )}
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
