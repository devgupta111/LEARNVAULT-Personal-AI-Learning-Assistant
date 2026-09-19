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
import { useToast } from "../../../components/Toast";
import { deleteDocument, getDocuments, uploadDocument } from "../../../lib/api";
import { DocumentSummary } from "../../../types";

export default function DocumentsPage() {
  const { loading: authLoading } = useAuth(true);
  const toast = useToast();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [subject, setSubject] = useState("General");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
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
  }, [authLoading]);

  // Poll every 3s while any document is PROCESSING
  useEffect(() => {
    const hasProcessing = documents.some((d) => d.status === "PROCESSING");
    if (!hasProcessing) return;
    const interval = setInterval(fetchDocs, 3000);
    return () => clearInterval(interval);
  }, [documents]);

  const [isDragging, setIsDragging] = useState(false);

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const validateAndSetFile = (file: File | undefined | null) => {
    setError(null);
    setSuccessMsg(null);
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are supported.");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setError("File is too large. Maximum size is 20 MB.");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setSelectedFile(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    validateAndSetFile(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!uploading) setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (uploading) return;
    const file = e.dataTransfer.files?.[0];
    validateAndSetFile(file);
  };

  const handleRemoveFile = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedFile(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
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
      await uploadDocument(selectedFile, subject.trim() || "General");
      const msg = "Uploaded successfully! Your document is being processed and will be ready shortly.";
      setSuccessMsg(msg);
      toast.success(msg);
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await fetchDocs();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      setError(msg);
      toast.error(msg);
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteDocument = async (docId: string, filename: string) => {
    const confirmed = window.confirm(
      `Delete "${filename}"?\n\nThis will permanently remove the document, all chat sessions, messages, quizzes, and quiz attempts linked to it.\n\nThis action cannot be undone.`
    );
    if (!confirmed) return;
    setDeletingDocId(docId);
    setError(null);
    try {
      await deleteDocument(docId);
      setDocuments((prev) => prev.filter((d) => (d.document_id || d.id) !== docId));
      toast.success("Document deleted successfully.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete document";
      setError(msg);
      toast.error(msg);
    } finally {
      setDeletingDocId(null);
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
          Upload PDF lecture notes, course materials, or textbooks. Documents are automatically extracted, chunked, and indexed for Chat and Quiz.
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
                PDF Document <span className="font-normal text-[11px]" style={{ color: "var(--text-muted)" }}>(Max 20 MB)</span>
              </label>

              {/* Hidden native input, preserved for access & file chooser */}
              <input
                ref={fileInputRef}
                id="pdf-upload-input"
                type="file"
                accept=".pdf,application/pdf"
                onChange={handleFileChange}
                disabled={uploading}
                className="sr-only"
                aria-label="Upload PDF File"
              />

              {!selectedFile ? (
                /* Empty / Dropzone State */
                <div
                  role="button"
                  tabIndex={uploading ? -1 : 0}
                  onClick={() => !uploading && fileInputRef.current?.click()}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === " ") && !uploading) {
                      e.preventDefault();
                      fileInputRef.current?.click();
                    }
                  }}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  aria-label="Choose a PDF file or drag and drop here"
                  className={`group relative flex flex-col items-center justify-center p-6 border-2 border-dashed rounded-xl cursor-pointer transition-all duration-150 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 ${
                    isDragging ? "ring-2" : ""
                  } ${uploading ? "opacity-50 cursor-not-allowed" : "hover:border-[var(--accent)] hover:bg-[var(--bg-hover)]"}`}
                  style={{
                    borderColor: isDragging ? "var(--accent)" : "var(--border)",
                    background: isDragging ? "var(--accent-surface)" : "var(--bg-surface-2)",
                  }}
                >
                  <div
                    className="w-10 h-10 rounded-full flex items-center justify-center mb-2 transition-transform group-hover:scale-110 shadow-xs"
                    style={{ background: "var(--accent-surface)", color: "var(--accent-text)" }}
                  >
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <span className="text-xs font-semibold text-center" style={{ color: "var(--text-primary)" }}>
                    <span style={{ color: "var(--accent-text)" }}>Click to browse</span> or drag &amp; drop PDF here
                  </span>
                  <span className="text-[11px] mt-1" style={{ color: "var(--text-muted)" }}>
                    Accepts .pdf files up to 20 MB
                  </span>
                </div>
              ) : (
                /* Selected File Preview State */
                <div
                  className="flex items-center justify-between p-3.5 rounded-xl border transition-all"
                  style={{
                    background: "var(--bg-surface-2)",
                    borderColor: "var(--accent-border)",
                  }}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 text-xs font-bold shadow-xs uppercase"
                      style={{ background: "var(--accent-surface)", color: "var(--accent-text)" }}
                    >
                      PDF
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span
                          className="text-xs font-semibold truncate max-w-[200px] sm:max-w-xs"
                          title={selectedFile.name}
                          style={{ color: "var(--text-primary)" }}
                        >
                          {selectedFile.name}
                        </span>
                        <span
                          className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 shrink-0"
                        >
                          Ready
                        </span>
                      </div>
                      <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                        {formatFileSize(selectedFile.size)}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0 ml-3">
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                      className="px-2.5 py-1 text-[11px] font-medium rounded-lg border transition-all hover:bg-[var(--bg-hover)] active:scale-[0.98] disabled:opacity-50 focus-visible:ring-2 focus-visible:outline-none"
                      style={{
                        background: "var(--bg-surface)",
                        borderColor: "var(--border)",
                        color: "var(--text-secondary)",
                      }}
                    >
                      Change
                    </button>
                    <button
                      type="button"
                      onClick={handleRemoveFile}
                      disabled={uploading}
                      title="Remove selected file"
                      aria-label="Remove selected file"
                      className="p-1.5 text-xs font-medium rounded-lg transition-all hover:bg-rose-50 dark:hover:bg-rose-950/50 text-rose-600 dark:text-rose-400 active:scale-[0.98] disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:outline-none"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>
              )}
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
              className="px-5 py-2.5 rounded-lg text-white text-xs font-medium transition-all hover:brightness-105 active:scale-[0.98] shadow-sm disabled:opacity-50 flex items-center gap-2 focus-visible:ring-2 focus-visible:outline-none"
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
            className="text-xs transition-colors hover:text-[var(--text-primary)] active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none rounded px-1.5 py-0.5"
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
                        <div className="flex items-center justify-end gap-2">
                          {doc.status === "READY" && (
                            <>
                              <Link
                                href={`/chat?doc=${docId}`}
                                className="px-2.5 py-1 text-xs font-medium rounded-lg transition-all hover:brightness-95 active:scale-[0.98] hover:shadow-xs focus-visible:ring-2 focus-visible:outline-none"
                                style={{
                                  background: "var(--accent-surface)",
                                  color: "var(--accent-text)",
                                }}
                              >
                                Chat
                              </Link>
                              <Link
                                href={`/quiz?doc=${docId}`}
                                className="px-2.5 py-1 text-xs font-medium rounded-lg transition-all bg-purple-50 hover:bg-purple-100 text-purple-700 dark:bg-purple-950/60 dark:hover:bg-purple-900/60 dark:text-purple-300 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
                              >
                                Quiz
                              </Link>
                            </>
                          )}
                          <button
                            type="button"
                            onClick={() => handleDeleteDocument(docId, doc.filename)}
                            disabled={deletingDocId === docId}
                            title="Delete document"
                            className="px-2.5 py-1 text-xs font-medium rounded-lg transition-all disabled:opacity-50 ml-1 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/60 hover:bg-rose-50 dark:hover:bg-rose-950/50 hover:border-rose-300 dark:hover:border-rose-800 active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:outline-none"
                          >
                            {deletingDocId === docId ? "Deleting…" : "Delete"}
                          </button>
                        </div>
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
