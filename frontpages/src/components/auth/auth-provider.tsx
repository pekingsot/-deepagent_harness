"use client";
import { createContext, useContext, useEffect } from "react";
import type { AuthUser } from "@/lib/auth-types";
import { accountApi } from "@/lib/auth-api";

const AuthContext = createContext<AuthUser | null>(null);

export function AuthProvider({ user, children }: { user: AuthUser; children: React.ReactNode }) {
  useEffect(() => {
    // 定期发现账号禁用或密码修改；卸载工作台时一并中止 SSE。
    const controller = new AbortController();
    const timer = setInterval(() => { void accountApi("auth/me", { signal: controller.signal }).catch(() => undefined); }, 30_000);
    const channel = new BroadcastChannel("harness-auth");
    channel.onmessage = () => window.location.replace("/login");
    return () => { controller.abort(); clearInterval(timer); channel.close(); };
  }, []);
  return <AuthContext.Provider value={user}>{children}</AuthContext.Provider>;
}

export function useAuthUser() {
  const user = useContext(AuthContext);
  if (!user) throw new Error("当前页面需要已登录用户");
  return user;
}

export function leaveWorkspace() {
  const channel = new BroadcastChannel("harness-auth");
  channel.postMessage("logout"); channel.close();
  window.location.replace("/login");
}
