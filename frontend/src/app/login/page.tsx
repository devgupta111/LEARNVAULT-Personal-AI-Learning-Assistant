/**
 * app/login/page.tsx
 *
 * Professional Login page.
 *
 * Authentication & UX Rules:
 *  - Returning authenticated user visiting /login → instantly redirects to /dashboard (no flash of login UI).
 *  - Meaningful status: Shows "Signing in..." while authentication is actually in flight.
 *  - Reliable lifecycle: SUCCESS → authenticate → redirect; FAILURE → show error → stop loading → allow retry.
 *  - Never hangs on "Rendering..." or leaves the UI stuck indefinitely.
 *  - Clean Google Identity Services integration with fallback to Guest login.
 *  - Security: Google ID token verified strictly server-side by FastAPI (/auth/google).
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { GOOGLE_CLIENT_ID, getToken, loginUser, loginWithGoogle } from "../../../lib/api";
import UserGuideModal from "../../../components/UserGuideModal";

interface GoogleIdentityServices {
  accounts?: {
    id?: {
      initialize: (config: {
        client_id: string;
        callback: (response: { credential?: string }) => void;
        auto_select?: boolean;
        cancel_on_tap_outside?: boolean;
      }) => void;
      renderButton: (
        parent: HTMLElement,
        options: {
          theme?: string;
          size?: string;
          text?: string;
          shape?: string;
          width?: number;
          logo_alignment?: string;
        }
      ) => void;
    };
  };
}

declare global {
  interface Window {
    google?: GoogleIdentityServices;
  }
}

export default function LoginPage() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [gisReady, setGisReady] = useState(false);
  const [gisTimeout, setGisTimeout] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const initializedRef = useRef(false);

  // 1. Returning authenticated user: redirect to /dashboard immediately
  useEffect(() => {
    if (getToken()) {
      router.replace("/dashboard");
      return;
    }
    setCheckingAuth(false);
  }, [router]);

  // 2. Google Identity Services credential response
  const handleCredentialResponse = async (response: { credential?: string }) => {
    if (!response?.credential) {
      setError("No credential received from Google. Please try again.");
      setLoading(false);
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
      setLoading(false);
    }
  };

  // 3. Initialize Google Identity Services safely
  useEffect(() => {
    if (checkingAuth) return;

    let intervalId: ReturnType<typeof setInterval> | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const initGIS = () => {
      if (initializedRef.current) return;
      if (typeof window === "undefined" || !window.google?.accounts?.id) return;

      initializedRef.current = true;

      try {
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
      } catch (e) {
        console.warn("Google Sign-In initialization notice:", e);
      }

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

      // 6-second timeout before graceful notification
      timeoutId = setTimeout(() => {
        if (intervalId) clearInterval(intervalId);
        if (!initializedRef.current) {
          setGisTimeout(true);
        }
      }, 6000);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
      if (timeoutId) clearTimeout(timeoutId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkingAuth]);

  const handleGuestLogin = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      await loginUser("dev-user");
      router.replace("/dashboard");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Guest sign-in failed";
      setError(msg);
      setLoading(false);
    }
  };

  // If already authenticated, show brief non-flashing spinner while redirecting
  if (checkingAuth) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="flex items-center gap-3" style={{ color: "var(--text-muted)" }}>
          <span
            className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin"
            style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
          />
          <span className="text-sm">Checking session…</span>
        </div>
      </div>
    );
  }

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
            className="inline-flex w-14 h-14 rounded-2xl text-white items-center justify-center mb-4 shadow-lg"
            style={{ background: "var(--accent)" }}
          >
            {/* Vault/book icon — same as navbar logo for brand consistency */}
            <svg
              width="26"
              height="26"
              viewBox="0 0 18 18"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <rect x="3" y="2" width="2" height="14" rx="1" fill="white" fillOpacity="0.9" />
              <rect x="5" y="2" width="10" height="14" rx="1.5" fill="white" fillOpacity="0.25" stroke="white" strokeWidth="1" strokeOpacity="0.7" />
              <line x1="7.5" y1="6" x2="13" y2="6" stroke="white" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.9" />
              <line x1="7.5" y1="8.5" x2="13" y2="8.5" stroke="white" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.9" />
              <line x1="7.5" y1="11" x2="11" y2="11" stroke="white" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.7" />
            </svg>
          </div>
          <h1
            className="text-2xl font-bold"
            style={{ color: "var(--text-primary)" }}
          >
            Welcome to LearnVault
          </h1>
          <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
            Sign in or create your account to continue.
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <div className="mb-5 p-3.5 rounded-xl text-xs text-center bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Signing in active state */}
        {loading && (
          <div
            className="mb-5 p-3.5 rounded-xl text-xs text-center flex items-center justify-center gap-2.5 font-medium"
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
            <span>Signing in…</span>
          </div>
        )}

        {/* Google Sign-In */}
        <div className="flex flex-col items-center py-4 gap-3">
          {/* GIS renders its official button inside this container */}
          <div
            id="google-signin-btn"
            className="min-h-[44px] flex items-center justify-center w-full"
          />

          {/* Show spinner ONLY while waiting for Google Identity script to connect */}
          {!gisReady && !gisTimeout && !loading && (
            <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
              <span
                className="w-3.5 h-3.5 border-2 border-t-transparent rounded-full animate-spin"
                style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
              />
              <span>Connecting to Google…</span>
            </div>
          )}

          {/* Timeout notification: Google script blocked or network slow */}
          {gisTimeout && !gisReady && (
            <div className="text-xs text-center px-2" style={{ color: "var(--text-muted)" }}>
              Google Sign-In is taking longer to load. You can continue as Guest below.
            </div>
          )}
        </div>

        {/* Divider + Guest Access */}
        <div
          className="mt-6 pt-6"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <p className="text-xs text-center mb-3" style={{ color: "var(--text-muted)" }}>
            Or continue without a Google account:
          </p>
          <button
            type="button"
            onClick={handleGuestLogin}
            disabled={loading}
            className="btn-secondary w-full py-2.5 rounded-xl text-xs font-semibold focus-visible:ring-2 focus-visible:outline-none"
          >
            Continue as Guest
          </button>
        </div>

        {/* User Guide link for visitors before login */}
        <div className="mt-6 pt-4 text-center" style={{ borderTop: "1px solid var(--border-subtle)" }}>
          <button
            type="button"
            onClick={() => setShowGuide(true)}
            className="inline-flex items-center gap-1.5 text-xs transition-colors hover:underline focus-visible:ring-2 focus-visible:outline-none rounded px-2 py-1"
            style={{ color: "var(--text-muted)" }}
          >
            <span>📖</span>
            <span>New here? Read the User Guide</span>
          </button>
        </div>
      </div>

      {/* User Guide Modal */}
      {showGuide && <UserGuideModal onClose={() => setShowGuide(false)} />}
    </div>
  );
}
