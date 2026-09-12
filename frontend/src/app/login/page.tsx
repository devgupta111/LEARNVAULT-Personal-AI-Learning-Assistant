/**
 * app/login/page.tsx
 *
 * Login page.
 *
 * Auth flow:
 *  1. If user already has a valid token in localStorage → redirect to /dashboard immediately.
 *  2. Show Google Sign-In button (renders via Google Identity Services).
 *  3. On Google credential received → POST /auth/google → store token → redirect to /dashboard.
 *
 * "Rendering..." root cause:
 *   The GIS library is loaded via <Script strategy="afterInteractive"> which fires
 *   asynchronously. We poll with setInterval until window.google.accounts.id is ready,
 *   then render the button. The spinner is shown ONLY while waiting for GIS to load.
 *   It is always eventually replaced by the button or an error — never stuck indefinitely.
 *
 * Security:
 *  - Google ID token is verified server-side (FastAPI /auth/google → google-auth-library).
 *  - Frontend never trusts Google token directly; only stores the app JWT returned by backend.
 *  - Google `sub` is the stable user identity; email is display-only.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { GOOGLE_CLIENT_ID, getToken, loginUser, loginWithGoogle } from "../../../lib/api";

declare global {
  interface Window {
    google?: any;
  }
}

export default function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [gisReady, setGisReady] = useState(false);
  const [gisTimeout, setGisTimeout] = useState(false);
  const initializedRef = useRef(false);

  // Redirect immediately if already authenticated
  useEffect(() => {
    if (getToken()) {
      router.replace("/dashboard");
    }
  }, [router]);

  // Handle the Google credential callback
  const handleCredentialResponse = async (response: { credential?: string }) => {
    if (!response?.credential) {
      setError("No credential received from Google. Please try again.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await loginWithGoogle(response.credential);
      router.replace("/dashboard");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Google authentication failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  // Initialize Google Identity Services and render the Sign-In button
  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const initGIS = () => {
      if (initializedRef.current) return;
      if (typeof window === "undefined" || !window.google?.accounts?.id) return;

      initializedRef.current = true;

      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleCredentialResponse,
        auto_select: false,
        cancel_on_tap_outside: true,
      });

      const container = document.getElementById("google-signin-btn");
      if (container) {
        container.innerHTML = "";
        window.google.accounts.id.renderButton(container, {
          theme: "outline",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          width: 300,
          logo_alignment: "left",
        });
      }

      setGisReady(true);
      if (intervalId) clearInterval(intervalId);
      if (timeoutId) clearTimeout(timeoutId);
    };

    if (window.google?.accounts?.id) {
      initGIS();
    } else {
      intervalId = setInterval(() => {
        if (window.google?.accounts?.id) {
          initGIS();
        }
      }, 100);

      // After 8 seconds, stop polling and show a timeout error
      timeoutId = setTimeout(() => {
        if (intervalId) clearInterval(intervalId);
        if (!initializedRef.current) {
          setGisTimeout(true);
        }
      }, 8000);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
      if (timeoutId) clearTimeout(timeoutId);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDevLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      await loginUser("dev-user");
      router.replace("/dashboard");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Sign-in failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 flex items-center justify-center px-4 py-12 page-enter">
      <div
        className="w-full max-w-md rounded-2xl p-8 shadow-2xl"
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Brand */}
        <div className="text-center mb-8">
          <div
            className="inline-flex w-14 h-14 rounded-2xl text-white items-center justify-center font-black text-xl mb-4 shadow-lg"
            style={{ background: "var(--accent)" }}
          >
            AI
          </div>
          <h1
            className="text-2xl font-bold"
            style={{ color: "var(--text-primary)" }}
          >
            Personal AI Learning Assistant
          </h1>
          <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
            Sign in to access your study dashboard
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <div className="mb-5 p-3.5 rounded-lg text-xs text-center bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Loading overlay */}
        {loading && (
          <div
            className="mb-5 p-3.5 rounded-lg text-xs text-center flex items-center justify-center gap-2"
            style={{
              background: "var(--accent-surface)",
              color: "var(--accent-text)",
              border: "1px solid var(--accent-border)",
            }}
          >
            <span
              className="w-4 h-4 border-2 border-t-transparent rounded-full animate-spin"
              style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
            />
            <span>Verifying with server…</span>
          </div>
        )}

        {/* Google Sign-In */}
        <div className="flex flex-col items-center py-4 gap-3">
          {/* GIS renders its button inside this div */}
          <div
            id="google-signin-btn"
            className="min-h-[44px] flex items-center justify-center w-full"
          />

          {/* Show spinner while GIS library is loading */}
          {!gisReady && !gisTimeout && !loading && (
            <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
              <span
                className="w-3.5 h-3.5 border-2 border-t-transparent rounded-full animate-spin"
                style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
              />
              <span>Loading Google Sign-In…</span>
            </div>
          )}

          {/* Timeout: GIS failed to load (network issue or blocked) */}
          {gisTimeout && (
            <div className="text-xs text-center px-2" style={{ color: "var(--text-muted)" }}>
              Google Sign-In could not load. Check your internet connection or try refreshing.
            </div>
          )}
        </div>

        {/* Divider + local access */}
        <div
          className="mt-6 pt-6"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <p className="text-xs text-center mb-3" style={{ color: "var(--text-muted)" }}>
            Or continue without a Google account:
          </p>
          <button
            type="button"
            onClick={handleDevLogin}
            disabled={loading}
            className="w-full py-2.5 rounded-xl text-xs font-medium transition-colors disabled:opacity-50"
            style={{
              background: "var(--bg-surface-2)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.background = "var(--bg-surface-2)";
            }}
          >
            Continue as Guest
          </button>
        </div>
      </div>
    </div>
  );
}
