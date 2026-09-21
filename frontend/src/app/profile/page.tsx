/**
 * app/profile/page.tsx
 *
 * User Profile page — protected route.
 *
 * Requirements:
 *  - Displays verified user-provided information:
 *      * Name / username (editable)
 *      * Email address (STRICTLY READ-ONLY)
 *      * Profile picture (from provider, or neutral avatar)
 *      * Authentication Provider (e.g. Google or Guest / Local)
 *  - "Edit Profile" feature:
 *      * Allows editing display name / username.
 *      * Email is STRICTLY READ-ONLY and immutable.
 *      * Save Changes validates input, calls PUT /auth/profile with Bearer token.
 *      * Immediately updates frontend state and navbar via "user-updated" event without full reload.
 *  - STRICT PRIVACY & SECURITY:
 *      * NEVER exposes JWT, Google `sub`, database UUID, or internal user_id.
 *  - Auth: useAuth(true) redirects to /login if unauthenticated.
 *  - Theme-aware styling using CSS variables.
 */

"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../../../hooks/useAuth";
import { clearToken, getMe, updateProfile } from "../../../lib/api";
import { useRouter } from "next/navigation";
import { User } from "../../../types";

export default function ProfilePage() {
  const { user: initialUser, loading: authLoading } = useAuth(true);
  const router = useRouter();

  const [profile, setProfile] = useState<User | null>(initialUser);

  // Edit Profile mode state
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  // Fetch latest verified profile details from backend
  useEffect(() => {
    if (authLoading) return;
    let isMounted = true;

    async function loadProfile() {
      try {
        const data = await getMe();
        if (isMounted) {
          setProfile(data);
          setEditName(data.username || "");
        }
      } catch {
        // Fall back to stored local user if offline or network error
        if (isMounted && initialUser) {
          setEditName(initialUser.username || "");
        }
      }
    }

    loadProfile();
    return () => {
      isMounted = false;
    };
  }, [authLoading, initialUser]);

  const loggingOutRef = useRef(false);

  const handleLogout = () => {
    if (loggingOutRef.current) return;
    loggingOutRef.current = true;
    clearToken();
    router.replace("/");
  };

  const startEditing = () => {
    setEditName(profile?.username || "");
    setSaveError(null);
    setSaveSuccess(null);
    setIsEditing(true);
  };

  const cancelEditing = () => {
    setEditName(profile?.username || "");
    setSaveError(null);
    setIsEditing(false);
  };

  const handleSaveChanges = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanName = editName.trim();
    if (!cleanName) {
      setSaveError("Name cannot be blank.");
      return;
    }

    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);

    try {
      const updatedUser = await updateProfile(cleanName);
      setProfile(updatedUser);
      setIsEditing(false);
      setSaveSuccess("Profile updated successfully!");
      // Clear success notification after 4 seconds
      setTimeout(() => setSaveSuccess(null), 4000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to update profile";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  };

  if (authLoading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="flex items-center gap-3" style={{ color: "var(--text-muted)" }}>
          <span
            className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin"
            style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
          />
          <span className="text-sm">Loading profile…</span>
        </div>
      </div>
    );
  }

  const hasName = Boolean(
    profile?.username &&
      profile.username.trim() &&
      profile.username !== "dev-user" &&
      !profile.username.startsWith("google_")
  );
  const displayName = hasName ? profile!.username!.trim() : null;
  const email = profile?.email || null;
  const picture = profile?.picture || null;
  const authProvider = profile?.auth_provider === "google" ? "Google" : "Guest / Local";

  // Derive initials ONLY from the actual verified user name
  const initials = displayName
    ? displayName
        .split(" ")
        .filter(Boolean)
        .map((p) => p[0].toUpperCase())
        .slice(0, 2)
        .join("")
    : null;

  return (
    <div className="flex-1 max-w-4xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 page-enter">
      {/* Back button / breadcrumb */}
      <div className="mb-6">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 text-xs font-medium transition-all hover:text-[var(--text-primary)] active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none rounded-lg px-2 py-1"
          style={{ color: "var(--text-muted)" }}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back to Dashboard
        </Link>
      </div>

      <div
        className="rounded-2xl p-6 sm:p-8 shadow-xl"
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Header: Avatar, Name, and Top Actions */}
        <div
          className="flex flex-col sm:flex-row sm:items-center justify-between gap-6 pb-6 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <div className="flex items-center gap-4">
            {/* Avatar */}
            {picture ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={picture}
                alt="Profile"
                className="w-16 h-16 rounded-full object-cover shadow"
                referrerPolicy="no-referrer"
              />
            ) : initials ? (
              <div
                className="w-16 h-16 rounded-full flex items-center justify-center font-bold text-xl text-white shadow"
                style={{ background: "var(--accent)" }}
              >
                {initials}
              </div>
            ) : (
              <div
                className="w-16 h-16 rounded-full flex items-center justify-center text-white shadow"
                style={{ background: "var(--accent)" }}
              >
                <svg className="w-8 h-8 opacity-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.75}
                    d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                  />
                </svg>
              </div>
            )}

            <div>
              <h1 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
                {displayName || "Account Profile"}
              </h1>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                {authProvider} Authenticated
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 self-start sm:self-auto">
            {!isEditing && (
              <button
                type="button"
                onClick={startEditing}
                title="Edit Profile"
                aria-label="Edit Profile"
                className="btn-primary px-4 py-2 rounded-xl text-xs font-semibold shadow-sm inline-flex items-center gap-1.5 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 012.828 2.828L11.828 15.828a2 2 0 01-1.414.586H8v-2.414a2 2 0 01.586-1.414z" />
                </svg>
                <span>Edit Profile</span>
              </button>
            )}

            <button
              type="button"
              onClick={handleLogout}
              className="btn-secondary px-4 py-2 rounded-xl text-xs font-medium active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
            >
              Sign Out
            </button>
          </div>
        </div>

        {/* Notifications */}
        {saveSuccess && (
          <div className="mt-5 p-3 rounded-xl text-xs text-center font-medium bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400">
            {saveSuccess}
          </div>
        )}

        {saveError && (
          <div className="mt-5 p-3 rounded-xl text-xs text-center font-medium bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-400">
            {saveError}
          </div>
        )}

        {/* Profile Details or Edit Form */}
        <div className="mt-6">
          <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            {isEditing ? "Edit Account Profile" : "Profile Details"}
          </h2>

          {isEditing ? (
            /* ── EDIT PROFILE FORM ── */
            <form onSubmit={handleSaveChanges} className="space-y-4">
              <div
                className="rounded-xl p-5 space-y-4"
                style={{
                  background: "var(--bg-surface-2)",
                  border: "1px solid var(--border)",
                }}
              >
                {/* Name / Username Field (Editable) */}
                <div>
                  <label
                    htmlFor="profile-name"
                    className="block text-xs font-semibold mb-1.5"
                    style={{ color: "var(--text-primary)" }}
                  >
                    Name / Username
                  </label>
                  <input
                    id="profile-name"
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="Enter your name"
                    autoFocus
                    disabled={saving}
                    className="w-full px-3.5 py-2.5 rounded-xl text-xs font-medium border transition-colors focus:outline-none focus:ring-2"
                    style={{
                      background: "var(--bg-surface)",
                      color: "var(--text-primary)",
                      borderColor: "var(--border)",
                    }}
                  />
                  <p className="text-[11px] mt-1" style={{ color: "var(--text-muted)" }}>
                    This name will appear in your navbar profile and learning dashboard.
                  </p>
                </div>

                {/* Email Field (STRICTLY READ-ONLY) */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label
                      htmlFor="profile-email"
                      className="block text-xs font-semibold"
                      style={{ color: "var(--text-primary)" }}
                    >
                      Email Address
                    </label>
                    <span
                      className="text-[10px] font-bold px-2 py-0.5 rounded-md uppercase tracking-wider"
                      style={{
                        background: "var(--bg-surface)",
                        color: "var(--text-muted)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      Read Only
                    </span>
                  </div>
                  <input
                    id="profile-email"
                    type="text"
                    value={email || "No email linked"}
                    readOnly
                    disabled
                    aria-readonly="true"
                    className="w-full px-3.5 py-2.5 rounded-xl text-xs font-mono border opacity-70 cursor-not-allowed"
                    style={{
                      background: "var(--bg-surface)",
                      color: "var(--text-secondary)",
                      borderColor: "var(--border)",
                    }}
                  />
                  <p className="text-[11px] mt-1" style={{ color: "var(--text-muted)" }}>
                    Email is associated with your authenticated provider and cannot be modified.
                  </p>
                </div>

                {/* Auth Provider (Informational) */}
                <div>
                  <span className="block text-xs font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                    Sign-in Method
                  </span>
                  <div className="text-xs font-medium inline-flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
                    <span className="w-2 h-2 rounded-full" style={{ background: "var(--accent)" }} />
                    {authProvider}
                  </div>
                </div>
              </div>

              {/* Action Buttons: Save Changes & Cancel */}
              <div className="flex items-center gap-3 pt-2">
                <button
                  type="submit"
                  disabled={saving}
                  className="btn-primary px-5 py-2.5 rounded-xl text-xs font-semibold shadow-sm disabled:opacity-50 flex items-center gap-2 active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
                >
                  {saving ? (
                    <>
                      <span className="w-3.5 h-3.5 border-2 border-t-transparent rounded-full animate-spin border-white" />
                      <span>Saving…</span>
                    </>
                  ) : (
                    <span>Save Changes</span>
                  )}
                </button>

                <button
                  type="button"
                  onClick={cancelEditing}
                  disabled={saving}
                  className="btn-secondary px-4 py-2.5 rounded-xl text-xs font-medium active:scale-[0.98] focus-visible:ring-2 focus-visible:outline-none"
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            /* ── READ-ONLY VIEW ── */
            <div
              className="rounded-xl p-4 divide-y border"
              style={{
                background: "var(--bg-surface-2)",
                borderColor: "var(--border)",
              }}
            >
              {/* Display Name */}
              <div className="py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
                  Name
                </span>
                <span className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                  {displayName || "Not provided"}
                </span>
              </div>

              {/* Email */}
              <div className="py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
                    Email
                  </span>
                  <span
                    className="text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider"
                    style={{
                      background: "var(--bg-surface)",
                      color: "var(--text-muted)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    Read Only
                  </span>
                </div>
                <span className="text-xs font-medium font-mono" style={{ color: "var(--text-primary)" }}>
                  {email || "None linked"}
                </span>
              </div>

              {/* Authentication Provider */}
              <div className="py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
                  Sign-in Method
                </span>
                <span
                  className="text-xs font-medium inline-flex items-center gap-1.5"
                  style={{ color: "var(--text-primary)" }}
                >
                  <span className="w-2 h-2 rounded-full" style={{ background: "var(--accent)" }} />
                  {authProvider}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
