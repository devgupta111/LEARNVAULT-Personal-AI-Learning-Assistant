/**
 * components/Navbar.tsx
 *
 * Professional Application Navbar.
 *
 * Requirements:
 *  - Dynamic Logo Navigation:
 *      * Authenticated user: "Personal AI Assistant" logo links to /dashboard
 *      * Unauthenticated user: "Personal AI Assistant" logo links to /
 *  - Main Navigation:
 *      * Dashboard, Documents, RAG Chat, Quiz
 *  - Authenticated State:
 *      * Profile control on the right: [Avatar] [User Name] ▼
 *      * User Name displays ONLY actual user-provided name/username.
 *      * NEVER displays email or internal IDs (no email in navbar or dropdown header).
 *      * If no user-provided name exists (e.g. guest), displays a clean neutral avatar.
 *      * Avatar: profile image if available, initials only if real name exists, else neutral SVG icon.
 *      * Dropdown contains:
 *          - User header ([Avatar] [Name])
 *          - 👤 Profile (navigates to /profile)
 *          - 🎨 Theme › (Light, Dark, Green selector with active state indicator)
 *          - 🚪 Sign Out (clears auth and redirects to /)
 *      * NO permanent buttons for Theme or Sign Out in the authenticated navbar.
 *      * Listens for "user-updated" events to update name/initials immediately on profile edit.
 *  - Unauthenticated State:
 *      * Shows [Theme ▼] dropdown and [Sign In] button on the right.
 *      * Logged-out users can change theme freely before logging in.
 *      * Does NOT show Profile, username, email, or Sign Out.
 *  - Accessibility & Polish:
 *      * Keyboard accessible (Escape closes dropdowns), click-outside closes dropdowns.
 *      * Route changes close dropdowns.
 *      * Hydration-safe (client-side mounted check).
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

const THEMES: { value: Theme; label: string; icon: string }[] = [
  { value: "light", label: "Light", icon: "☀️" },
  { value: "dark", label: "Dark", icon: "🌙" },
  { value: "green", label: "Green", icon: "🌿" },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, setTheme } = useTheme();

  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [mounted, setMounted] = useState(false);

  // Authenticated profile dropdown
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [profileThemeSubmenuOpen, setProfileThemeSubmenuOpen] = useState(false);
  const profileDropdownRef = useRef<HTMLDivElement>(null);

  // Unauthenticated public theme dropdown
  const [publicThemeOpen, setPublicThemeOpen] = useState(false);
  const publicThemeRef = useRef<HTMLDivElement>(null);

  // Read auth state client-side only and listen for real-time profile updates
  useEffect(() => {
    setMounted(true);

    const syncAuth = () => {
      const token = getToken();
      const user = getUser();
      if (token && user) {
        setCurrentUser(user);
      } else {
        setCurrentUser(null);
      }
    };

    syncAuth();

    // Listen for custom "user-updated" events dispatched after profile edits
    window.addEventListener("user-updated", syncAuth);
    return () => {
      window.removeEventListener("user-updated", syncAuth);
    };
  }, [pathname]);

  // Close all menus on route change
  useEffect(() => {
    setProfileMenuOpen(false);
    setProfileThemeSubmenuOpen(false);
    setPublicThemeOpen(false);
  }, [pathname]);

  // Close menus on outside click or Escape key
  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if (
        profileDropdownRef.current &&
        !profileDropdownRef.current.contains(e.target as Node)
      ) {
        setProfileMenuOpen(false);
        setProfileThemeSubmenuOpen(false);
      }
      if (
        publicThemeRef.current &&
        !publicThemeRef.current.contains(e.target as Node)
      ) {
        setPublicThemeOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setProfileMenuOpen(false);
        setProfileThemeSubmenuOpen(false);
        setPublicThemeOpen(false);
      }
    };

    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const loggingOutRef = useRef(false);

  const handleLogout = (e?: React.MouseEvent) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    // Guard against repeated/duplicate clicks
    if (loggingOutRef.current) return;
    loggingOutRef.current = true;

    // 1. Close dropdown menus immediately
    setProfileMenuOpen(false);
    setProfileThemeSubmenuOpen(false);

    // 2. Clear authentication token & user from localStorage and dispatch sync event
    clearToken();

    // 3. Clear local component state
    setCurrentUser(null);

    // 4. Redirect immediately to public landing page "/"
    router.replace("/");

    setTimeout(() => {
      loggingOutRef.current = false;
    }, 800);
  };

  const isLoginPage = pathname === "/login";

  // Dynamic Logo Destination:
  // Authenticated user → /dashboard
  // Unauthenticated user → /
  const logoHref = currentUser ? "/dashboard" : "/";

  // Strict User Name Rule:
  // ONLY display user's actual provided name.
  // NEVER derive from email, user_id, sub, or hardcode generic terms.
  const hasActualName = Boolean(
    currentUser?.username &&
      currentUser.username.trim() &&
      currentUser.username !== "dev-user" &&
      !currentUser.username.startsWith("google_")
  );

  const displayName = hasActualName ? currentUser!.username!.trim() : null;

  // Avatar initials: derive ONLY if real verified name exists
  const initials = displayName
    ? displayName
        .split(" ")
        .filter(Boolean)
        .map((p) => p[0].toUpperCase())
        .slice(0, 2)
        .join("")
    : null;

  const profilePicture = currentUser?.picture || null;
  const currentThemeIcon = THEMES.find((t) => t.value === theme)?.icon || "🌙";

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
        {/* ── Left: Brand Logo (Dynamic Destination) & Main Navigation ── */}
        <div className="flex items-center gap-6 min-w-0">
          <Link
            href={logoHref}
            className="flex items-center gap-2.5 font-bold text-base shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 rounded-lg"
            style={{ color: "var(--text-primary)" }}
            title={currentUser ? "Dashboard" : "Home"}
          >
            <span
              className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-black text-white shadow-sm shrink-0"
              style={{ background: "var(--accent)" }}
            >
              AI
            </span>
            <span className="font-semibold tracking-tight">Personal AI Assistant</span>
          </Link>

          {/* Main Navigation Links */}
          {!isLoginPage && (
            <nav className="hidden md:flex items-center gap-1" aria-label="Main Navigation">
              {NAV_LINKS.map((link) => {
                const isActive = pathname === link.href || pathname.startsWith(link.href + "/");
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors"
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

        {/* ── Right: Authenticated User Control OR Public Theme + Sign In ── */}
        <div className="flex items-center gap-2.5 shrink-0">
          {mounted ? (
            currentUser ? (
              /* ── AUTHENTICATED NAVBAR: Profile Dropdown Control ── */
              <div className="relative" ref={profileDropdownRef}>
                <button
                  type="button"
                  onClick={() => setProfileMenuOpen((prev) => !prev)}
                  aria-haspopup="true"
                  aria-expanded={profileMenuOpen}
                  aria-label="User profile menu"
                  className="flex items-center gap-2 py-1.5 px-2 sm:px-2.5 rounded-xl text-xs font-medium transition-colors border"
                  style={{
                    background: profileMenuOpen ? "var(--bg-surface-2)" : "transparent",
                    borderColor: profileMenuOpen ? "var(--border)" : "transparent",
                    color: "var(--text-primary)",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.background = "var(--bg-surface-2)";
                    (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
                  }}
                  onMouseLeave={(e) => {
                    if (!profileMenuOpen) {
                      (e.currentTarget as HTMLElement).style.background = "transparent";
                      (e.currentTarget as HTMLElement).style.borderColor = "transparent";
                    }
                  }}
                >
                  {/* Avatar: profile picture > initials > neutral SVG icon */}
                  {profilePicture ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={profilePicture}
                      alt="Avatar"
                      className="w-7 h-7 rounded-full object-cover shrink-0"
                      referrerPolicy="no-referrer"
                    />
                  ) : initials ? (
                    <div
                      className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-sm"
                      style={{ background: "var(--accent)" }}
                    >
                      {initials}
                    </div>
                  ) : (
                    <div
                      className="w-7 h-7 rounded-full flex items-center justify-center text-white shrink-0 shadow-sm"
                      style={{ background: "var(--accent)" }}
                    >
                      <svg className="w-4 h-4 opacity-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                        />
                      </svg>
                    </div>
                  )}

                  {/* Display actual user name only if available */}
                  {displayName && (
                    <span className="hidden sm:inline-block max-w-[130px] truncate text-xs font-medium">
                      {displayName}
                    </span>
                  )}

                  {/* Dropdown Chevron */}
                  <svg
                    className={`w-3.5 h-3.5 transition-transform duration-150 ${
                      profileMenuOpen ? "rotate-180" : ""
                    }`}
                    style={{ color: "var(--text-muted)" }}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {/* Dropdown Menu */}
                {profileMenuOpen && (
                  <div
                    className="absolute right-0 mt-2 w-64 rounded-2xl shadow-2xl overflow-hidden z-50 border page-enter"
                    style={{
                      background: "var(--bg-surface)",
                      borderColor: "var(--border)",
                    }}
                    role="menu"
                    aria-orientation="vertical"
                  >
                    {/* Header: [Avatar] [User Name] — NO EMAIL displayed */}
                    <div
                      className="px-4 py-3.5 flex items-center gap-3 border-b"
                      style={{ borderColor: "var(--border)" }}
                    >
                      {profilePicture ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={profilePicture}
                          alt="Avatar"
                          className="w-9 h-9 rounded-full object-cover shrink-0"
                          referrerPolicy="no-referrer"
                        />
                      ) : initials ? (
                        <div
                          className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-sm"
                          style={{ background: "var(--accent)" }}
                        >
                          {initials}
                        </div>
                      ) : (
                        <div
                          className="w-9 h-9 rounded-full flex items-center justify-center text-white shrink-0 shadow-sm"
                          style={{ background: "var(--accent)" }}
                        >
                          <svg className="w-5 h-5 opacity-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                            />
                          </svg>
                        </div>
                      )}

                      <div className="min-w-0 flex-1">
                        {displayName ? (
                          <p className="text-xs font-semibold truncate" style={{ color: "var(--text-primary)" }}>
                            {displayName}
                          </p>
                        ) : (
                          <p className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
                            Profile
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Menu Items */}
                    <div className="p-1.5 space-y-0.5">
                      {/* 👤 Profile */}
                      <Link
                        href="/profile"
                        onClick={() => setProfileMenuOpen(false)}
                        className="flex items-center gap-2.5 w-full px-3 py-2 rounded-xl text-xs font-medium transition-colors"
                        style={{ color: "var(--text-secondary)" }}
                        role="menuitem"
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                          (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLElement).style.background = "";
                          (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                        }}
                      >
                        <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={1.75}
                            d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                          />
                        </svg>
                        <span>Profile</span>
                      </Link>

                      {/* 🎨 Theme with Submenu toggle */}
                      <div>
                        <button
                          type="button"
                          onClick={() => setProfileThemeSubmenuOpen((prev) => !prev)}
                          className="flex items-center justify-between w-full px-3 py-2 rounded-xl text-xs font-medium transition-colors"
                          style={{
                            color: profileThemeSubmenuOpen ? "var(--text-primary)" : "var(--text-secondary)",
                            background: profileThemeSubmenuOpen ? "var(--bg-surface-2)" : "",
                          }}
                          role="menuitem"
                          aria-expanded={profileThemeSubmenuOpen}
                          onMouseEnter={(e) => {
                            (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                            (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                          }}
                          onMouseLeave={(e) => {
                            if (!profileThemeSubmenuOpen) {
                              (e.currentTarget as HTMLElement).style.background = "";
                              (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                            }
                          }}
                        >
                          <span className="flex items-center gap-2.5">
                            <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={1.75}
                                d="M7 21a4 4 0 01-4-4 5 5 0 015-5h4a5 5 0 015 5 4 4 0 01-4 4H7zM16 3.13a4 4 0 010 7.75"
                              />
                            </svg>
                            <span>Theme</span>
                          </span>

                          <span className="flex items-center gap-1.5" style={{ color: "var(--text-muted)" }}>
                            <span className="capitalize text-[11px]">{theme}</span>
                            <svg
                              className={`w-3.5 h-3.5 transition-transform duration-150 ${
                                profileThemeSubmenuOpen ? "rotate-90" : ""
                              }`}
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth={2}
                            >
                              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                            </svg>
                          </span>
                        </button>

                        {/* Theme Submenu */}
                        {profileThemeSubmenuOpen && (
                          <div
                            className="mt-1 mb-1 ml-4 pl-2 space-y-0.5 border-l"
                            style={{ borderColor: "var(--border)" }}
                          >
                            {THEMES.map((opt) => {
                              const isSelected = theme === opt.value;
                              return (
                                <button
                                  key={opt.value}
                                  type="button"
                                  onClick={() => {
                                    setTheme(opt.value);
                                  }}
                                  className="flex items-center justify-between w-full px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors"
                                  style={
                                    isSelected
                                      ? {
                                          background: "var(--accent-surface)",
                                          color: "var(--accent-text)",
                                        }
                                      : {
                                          color: "var(--text-secondary)",
                                        }
                                  }
                                  onMouseEnter={(e) => {
                                    if (!isSelected) {
                                      (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                                      (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                                    }
                                  }}
                                  onMouseLeave={(e) => {
                                    if (!isSelected) {
                                      (e.currentTarget as HTMLElement).style.background = "";
                                      (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                                    }
                                  }}
                                >
                                  <span className="flex items-center gap-2">
                                    <span className="text-xs">{opt.icon}</span>
                                    <span>{opt.label}</span>
                                  </span>
                                  {isSelected && (
                                    <svg className="w-3.5 h-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                                      <path
                                        fillRule="evenodd"
                                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                                        clipRule="evenodd"
                                      />
                                    </svg>
                                  )}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      {/* Divider */}
                      <div className="my-1 border-t" style={{ borderColor: "var(--border)" }} />

                      {/* 🚪 Sign Out */}
                      <button
                        type="button"
                        onClick={handleLogout}
                        className="flex items-center gap-2.5 w-full px-3 py-2 rounded-xl text-xs font-medium transition-colors text-left"
                        style={{ color: "var(--text-secondary)" }}
                        role="menuitem"
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                          (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLElement).style.background = "";
                          (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                        }}
                      >
                        <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={1.75}
                            d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                          />
                        </svg>
                        <span>Sign Out</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              /* ── LOGGED-OUT NAVBAR: [Theme ▼] + [Sign In] ── */
              <div className="flex items-center gap-2">
                {/* Public Theme Dropdown (usable without logging in) */}
                <div className="relative" ref={publicThemeRef}>
                  <button
                    type="button"
                    onClick={() => setPublicThemeOpen((prev) => !prev)}
                    aria-haspopup="true"
                    aria-expanded={publicThemeOpen}
                    aria-label="Theme selector"
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-medium transition-colors border"
                    style={{
                      background: publicThemeOpen ? "var(--bg-surface-2)" : "var(--bg-surface)",
                      borderColor: "var(--border)",
                      color: "var(--text-secondary)",
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                      (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                    }}
                    onMouseLeave={(e) => {
                      if (!publicThemeOpen) {
                        (e.currentTarget as HTMLElement).style.background = "var(--bg-surface)";
                        (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                      }
                    }}
                  >
                    <span className="text-sm leading-none">{currentThemeIcon}</span>
                    <span className="hidden sm:inline">Theme</span>
                    <svg
                      className={`w-3 h-3 transition-transform duration-150 ${
                        publicThemeOpen ? "rotate-180" : ""
                      }`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {/* Public Theme Menu */}
                  {publicThemeOpen && (
                    <div
                      className="absolute right-0 mt-1.5 w-36 rounded-xl shadow-xl overflow-hidden z-50 border page-enter"
                      style={{
                        background: "var(--bg-surface)",
                        borderColor: "var(--border)",
                      }}
                    >
                      {THEMES.map((opt) => {
                        const isSelected = theme === opt.value;
                        return (
                          <button
                            key={opt.value}
                            type="button"
                            onClick={() => {
                              setTheme(opt.value);
                              setPublicThemeOpen(false);
                            }}
                            className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-left transition-colors"
                            style={
                              isSelected
                                ? {
                                    background: "var(--accent-surface)",
                                    color: "var(--accent-text)",
                                  }
                                : {
                                    color: "var(--text-secondary)",
                                  }
                            }
                            onMouseEnter={(e) => {
                              if (!isSelected) {
                                (e.currentTarget as HTMLElement).style.background = "var(--bg-hover)";
                                (e.currentTarget as HTMLElement).style.color = "var(--text-primary)";
                              }
                            }}
                            onMouseLeave={(e) => {
                              if (!isSelected) {
                                (e.currentTarget as HTMLElement).style.background = "";
                                (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)";
                              }
                            }}
                          >
                            <span className="flex items-center gap-2">
                              <span>{opt.icon}</span>
                              <span>{opt.label}</span>
                            </span>
                            {isSelected && (
                              <svg className="w-3.5 h-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                                <path
                                  fillRule="evenodd"
                                  d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                                  clipRule="evenodd"
                                />
                              </svg>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Sign In Button */}
                {!isLoginPage && (
                  <Link
                    href="/login"
                    className="px-3.5 py-1.5 rounded-xl text-xs font-semibold text-white transition-all shadow-sm"
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
                )}
              </div>
            )
          ) : (
            /* SSR placeholder to prevent layout shift */
            <div className="w-20 h-8 rounded-xl opacity-0" />
          )}
        </div>
      </div>
    </header>
  );
}
