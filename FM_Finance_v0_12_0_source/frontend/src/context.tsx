import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import type { AppSettings, RulesResponse, User } from "./types";
import { setCompanyRules } from "./format";
import { applyTheme, isTheme } from "./theme";

// ---------- Toasts ----------
type ToastKind = "success" | "error";
interface Toast { id: number; kind: ToastKind; text: string }
interface ToastApi { success: (text: string) => void; error: (text: string) => void }

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const push = useCallback((kind: ToastKind, text: string) => {
    const id = nextId.current++;
    setToasts((t) => [...t, { id, kind, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  const value = useMemo<ToastApi>(() => ({
    success: (t) => push("success", t),
    error: (t) => push("error", t),
  }), [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>{t.text}</div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

// ---------- Auth ----------
interface AuthState {
  user: User | null;
  settings: AppSettings | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Replace the signed-in user after a change made elsewhere (for example the chosen look). */
  updateUser: (u: User) => void;
  /** v0.10.0: the current company's rules (terms, methods, formats, custom fields...). */
  rules: RulesResponse | null;
  /** Use after saving rules so every screen picks them up. */
  setRules: (r: RulesResponse) => void;
}

async function loadRules(u: User): Promise<RulesResponse | null> {
  if (u.role === "none") return null;
  try {
    return await api.rules();
  } catch {
    return null;  // the defaults in format.ts still work
  }
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [rules, setRulesState] = useState<RulesResponse | null>(null);
  const setRules = useCallback((r: RulesResponse | null) => {
    setCompanyRules(r);
    setRulesState(r);
  }, []);

  const loadSession = useCallback(async () => {
    try {
      const me = await api.me();
      setRules(await loadRules(me));
      setSettings(await api.settings());
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [setRules]);

  useEffect(() => {
    void loadSession();
    const onUnauthorized = () => setUser(null);
    window.addEventListener("fm:unauthorized", onUnauthorized);
    return () => window.removeEventListener("fm:unauthorized", onUnauthorized);
  }, [loadSession]);

  const login = useCallback(async (email: string, password: string) => {
    const u = await api.login(email, password);
    setRules(await loadRules(u));
    setSettings(await api.settings());
    setUser(u);
  }, [setRules]);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    if (user && isTheme(user.theme_effective)) applyTheme(user.theme_effective);
  }, [user]);

  const value = useMemo(() => ({ user, settings, loading, login, logout, updateUser: setUser, rules, setRules }),
    [user, settings, loading, login, logout, rules, setRules]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
