import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type User } from "./api";

interface AuthCtx {
  user: User | null; loading: boolean;
  login: (u: string, p: string) => Promise<void>; logout: () => Promise<void>;
  canWrite: boolean; isAdmin: boolean;
}
const Ctx = createContext<AuthCtx>(null!);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<User>("/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
    const onUnauthorized = () => setUser(null);
    window.addEventListener("unauthorized", onUnauthorized);
    return () => window.removeEventListener("unauthorized", onUnauthorized);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setUser(await api.post<User>("/auth/login", { username, password }));
  }, []);
  const logout = useCallback(async () => {
    await api.post("/auth/logout").catch(() => undefined);
    setUser(null);
  }, []);

  return (
    <Ctx.Provider value={{ user, loading, login, logout, canWrite: !!user && user.role !== "viewer", isAdmin: user?.role === "admin" }}>
      {children}
    </Ctx.Provider>
  );
}
