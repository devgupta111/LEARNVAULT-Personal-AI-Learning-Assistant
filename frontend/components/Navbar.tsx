/**
 * components/Navbar.tsx
 *
 * Application navbar.
 *
 * Features:
 *  - Brand logo linking to /dashboard
 *  - Nav links (hidden on login page)
 *  - Auth state: shows Sign In button (unauthenticated) or user display name + Sign Out (authenticated)
 *  - Theme selector: Light / Dark / Green — persisted to localStorage via useTheme hook
 *  - No development/debug text (no "4 Agents" badge, no "dev-user" label, no "Day 7")
 *  - Hydration-safe: auth state and theme are read only client-side in useEffect
 */

"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { clearToken, getToken, getUser } from "../lib/api";
import { useTheme, Theme } from "../hooks/useTheme";
import { User } from "../types";

const NAV_LINKS = [
  { name: "Dashboard", href: "/dashboard" },
  { name: "Documents", href: "/documents" },
  { name: "RAG Chat", href: "/chat" },
  { name: "Quiz", href: "/quiz" },
];

const THEME_OPTIONS: { value: Theme; label: string; icon: string }[] = [
  { value: "light", label: "Light", icon: "☀️" },
  { value: "dark",  label: "Dark",  icon: "🌙" },
  { value: "green", label: "Green", icon: "🌿" },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, setTheme } = useTheme();

  // Hydration-safe auth state: initialize to null on server, read on client
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [mounted, setMounted] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const themeRef = useRef<HTMLDivElement>(null);

  // Read auth state client-side only (avoids hydration mismatch)
  useEffect(() => {
    setMounted(true);
    const token = getToken();
    const user = getUser();
    if (token && user) {
      setCurrentUser(user);
    } else {
      setCurrentUser(null);
    }
  }, [pathname]); // Re-check on every route change so sign-out/in reflects immediately

  // Close theme dropdown on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (themeRef.current && !themeRef.current.contains(e.target as Node)) {
        setThemeOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const handleLogout = () => {
    clearToken();
    setCurrentUser(null);
    router.push("/login");
  };

  // Don't show nav links on the login page
  const isLoginPage = pathname === "/login";

  // Compute display name: strip internal prefixes like "google_" from the stored ID
  const displayName = (() => {
    if (!currentUser) return "";
    const name = currentUser.username || currentUser.user_id || "";
    // Remove internal "google_" prefix if the display name wasn't resolved properly
    if (name.startsWith("google_") && name.length > 20) return "Student";
    return name;
  })();

  const activeThemeIcon = THEME_OPTIONS.find((t) => t.value === theme)?.icon ?? "🌙";

  return (
    <header
      className="sticky top-0 z-50 border-b"
      style={{
        background: "var(--bg-surface)",
        borderColor: "var(--border)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
      }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* ── Left: Brand ── */}
        <div className="flex items-center gap-5 min-w-0">
          <Link
            href="/"
            className="flex items-center gap-2 font-bold text-base shrink-0"
            style={{ color: "var(--text-primary)" }}
          >
            <span
              className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-black text-white shadow-sm shrink-0"
              style={{ background: "var(--accent)" }}
            >
              AI
            </span>
            <span className="hidden sm:inline">Personal AI Assistant</span>
          </Link>

          {/* Nav links */}
          {!isLoginPage && (
            <nav className="hidden md:flex items-center gap-0.5">
              {NAV_LINKS.map((link) => {
                const isActive = pathname === link.href || pathname.startsWith(link.href + "/");
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="px-3 py-1.5 rounded-md text-sm font-medium transition-colors"
                    style={
                      isActive
                        ? {
                            background: "var(--bg-surface-2)",
                            color: "var(--text-primary)",
                          }
                        : {
                            color: "var(--text-secondary)",
                          }
                    }
                    onMouseEnter={(e) => {
                      if (!isActive) {
                        (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                        (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) {
                        (e.currentTarget as HTMLElement).style.background = "";
                        (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                      }
                    }}
                  >
                    {link.name}
                  </Link>
                );
              })}
            </nav>
          )}
        </div>

        {/* ── Right: Theme picker + Auth ── */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Theme selector dropdown */}
          <div className="relative" ref={themeRef}>
            <button
              type="button"
              onClick={() => setThemeOpen((o) => !o)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors"
              style={{
                background: "var(--bg-surface-2)",
                color: "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
              title="Change theme"
              aria-label="Theme selector"
            >
              <span className="text-sm leading-none">{activeThemeIcon}</span>
              <span className="hidden sm:inline">Theme</span>
              <svg
                className={`w-3 h-3 transition-transform ${themeOpen ? "rotate-180" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {themeOpen && (
              <div
                className="absolute right-0 mt-1.5 w-36 rounded-xl shadow-xl overflow-hidden z-50"
                style={{
                  background: "var(--bg-surface)",
                  border: "1px solid var(--border)",
                }}
              >
                {THEME_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => {
                      setTheme(opt.value);
                      setThemeOpen(false);
                    }}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs font-medium text-left transition-colors"
                    style={
                      theme === opt.value
                        ? {
                            background: "var(--accent-surface)",
                            color: "var(--accent-text)",
                          }
                        : {
                            color: "var(--text-secondary)",
                          }
                    }
                    onMouseEnter={(e) => {
                      if (theme !== opt.value) {
                        (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                        (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (theme !== opt.value) {
                        (e.currentTarget as HTMLElement).style.background = "";
                        (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                      }
                    }}
                  >
                    <span>{opt.icon}</span>
                    <span>{opt.label}</span>
                    {theme === opt.value && (
                      <svg className="w-3 h-3 ml-auto" fill="currentColor" viewBox="0 0 20 20">
                        <path
                          fillRule="evenodd"
                          d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                          clipRule="evenodd"
                        />
                      </svg>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Auth state */}
          {mounted ? (
            currentUser ? (
              <div className="flex items-center gap-2">
                {/* Avatar + name */}
                <div
                  className="hidden sm:flex items-center gap-2 px-2.5 py-1.5 rounded-lg"
                  style={{ background: "var(--bg-surface-2)" }}
                >
                  <div
                    className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                    style={{ background: "var(--accent)" }}
                  >
                    {displayName.charAt(0).toUpperCase()}
                  </div>
                  <span
                    className="text-xs font-medium max-w-[120px] truncate"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {displayName}
                  </span>
                </div>

                <button
                  onClick={handleLogout}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                  style={{
                    background: "var(--bg-surface-2)",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border)",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                    (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = "var(--bg-surface-2)";
                    (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                  }}
                >
                  Sign Out
                </button>
              </div>
            ) : (
              !isLoginPage && (
                <Link
                  href="/login"
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-white transition-colors shadow-sm"
                  style={{ background: "var(--accent)" }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.background = "var(--accent-hover)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = "var(--accent)";
                  }}
                >
                  Sign In
                </Link>
              )
            )
          ) : (
            // SSR placeholder — same height, invisible — prevents layout shift
            <div className="w-16 h-7 rounded-lg" style={{ background: "var(--bg-surface-2)" }} />
          )}
        </div>
      </div>
    </header>
  );
}
