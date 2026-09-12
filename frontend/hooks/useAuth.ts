/**
 * hooks/useAuth.ts
 *
 * Client-side authentication hook.
 *
 * - Reads token + user from localStorage (set by api.ts after login/Google auth).
 * - If requireAuth=true and no token exists, redirects to /login immediately.
 * - If requireAuth=false (login page), sets loading=false immediately.
 *   The login page itself handles the "already logged in → /dashboard" redirect.
 * - Never stays in an indefinite loading state: loading is always resolved in the
 *   same synchronous effect tick (localStorage is sync; no network call needed here).
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken, getUser } from "../lib/api";
import { User } from "../types";

export function useAuth(requireAuth: boolean = true) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  // Start as true so protected pages don't flash their content before the check
  const [loading, setLoading] = useState<boolean>(true);
  // Prevent running the effect more than once per mount
  const checked = useRef(false);

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;

    const token = getToken();
    const currentUser = getUser();

    if (requireAuth && !token) {
      // Not authenticated: redirect and keep loading=true so callers show a
      // spinner instead of flashing the page content before the redirect lands.
      router.replace("/login");
      return;
    }

    // Either we have a token (protected page) or auth is not required (public page).
    setUser(currentUser);
    setLoading(false);
  }, [requireAuth, router]);

  return { user, loading };
}
