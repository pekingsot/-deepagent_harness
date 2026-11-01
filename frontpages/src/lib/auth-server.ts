import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { AuthUser } from "@/lib/auth-types";

export const SESSION_COOKIE = "harness_session";

export async function currentUser(): Promise<AuthUser | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;
  const response = await fetch(new URL("/api/v1/auth/me", process.env.HARNESS_API_URL ?? "http://127.0.0.1:8000"), {
    headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(10_000),
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("暂时无法连接认证服务，请确认后端已启动");
  return response.json() as Promise<AuthUser>;
}

export async function requireUser(admin = false): Promise<AuthUser> {
  const user = await currentUser();
  if (!user) redirect("/login");
  if (admin && user.role !== "admin") redirect("/");
  return user;
}
