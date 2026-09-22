"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { me } from "@/lib/api";

type AuthState = {
  token: string | null;
  username: string | null;
  ready: boolean;
  setToken: (token: string | null) => void;
  logout: () => void;
};

const AuthContext = createContext<AuthState | null>(null);
const STORAGE_KEY = "edb_token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const setToken = useCallback((t: string | null) => {
    setTokenState(t);
    if (typeof window !== "undefined") {
      if (t) localStorage.setItem(STORAGE_KEY, t);
      else localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUsername(null);
  }, [setToken]);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) {
      setReady(true);
      return;
    }
    setTokenState(saved);
    me(saved)
      .then((u) => setUsername(u.username))
      .catch(() => {
        localStorage.removeItem(STORAGE_KEY);
        setTokenState(null);
      })
      .finally(() => setReady(true));
  }, []);

  useEffect(() => {
    if (!token) {
      setUsername(null);
      return;
    }
    me(token)
      .then((u) => setUsername(u.username))
      .catch(() => logout());
  }, [token, logout]);

  const value = useMemo(
    () => ({ token, username, ready, setToken, logout }),
    [token, username, ready, setToken, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}
