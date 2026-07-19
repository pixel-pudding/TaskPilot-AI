import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import {
  getToken,
  getMe,
  login as apiLogin,
  signup as apiSignup,
  logout as apiLogout,
  demoLogin as apiDemoLogin,
  type AuthUser,
} from "../api/taskpilot";

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, name: string) => Promise<void>;
  demoLogin: () => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshMe = async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await getMe();
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshMe();
    const onUnauthorized = () => setUser(null);
    window.addEventListener("taskpilot:unauthorized", onUnauthorized);
    return () => window.removeEventListener("taskpilot:unauthorized", onUnauthorized);
  }, []);

  const login = async (email: string, password: string) => {
    const res = await apiLogin(email, password);
    setUser(res.user);
  };

  const signup = async (email: string, password: string, name: string) => {
    const res = await apiSignup(email, password, name);
    setUser(res.user);
  };

  const demoLogin = async () => {
    const res = await apiDemoLogin();
    setUser(res.user);
  };

  const logout = () => {
    apiLogout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, demoLogin, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
