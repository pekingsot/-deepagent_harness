"use client";
import { useState } from "react";
import { Command, ArrowRight, LoaderCircle, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { accountApi } from "@/lib/auth-api";

export function LoginForm() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      await accountApi("auth/login", { method: "POST", body: JSON.stringify({
        username: String(data.get("username")).trim().toLowerCase(), password: data.get("password"),
      }) });
      // 完整导航重新加载服务端身份，清理上一个账号的工作台状态。
      window.location.replace("/");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "登录失败"); setBusy(false); }
  }
  return <main className="grid min-h-dvh place-items-center bg-[#f6f7f3] px-5 py-12">
    <div className="w-full max-w-[420px]">
      <div className="mb-9 flex items-center justify-center gap-3 text-lg font-semibold tracking-tight"><span className="brand-mark"><Command className="size-5" /></span>Agent Workspace</div>
      <Card className="border-border/80 shadow-xl shadow-black/[0.025]">
        <CardHeader className="pb-5"><CardTitle className="text-2xl">欢迎回来</CardTitle><CardDescription>登录你的企业工作空间，继续推进每一个想法。</CardDescription></CardHeader>
        <CardContent><form className="space-y-5" onSubmit={login}>
          <div className="space-y-2"><label htmlFor="username" className="text-sm font-medium">登录名</label><Input id="username" name="username" autoComplete="username" required minLength={3} maxLength={64} placeholder="你的账号" disabled={busy} /></div>
          <div className="space-y-2"><label htmlFor="password" className="text-sm font-medium">密码</label><Input id="password" name="password" type="password" autoComplete="current-password" required maxLength={128} disabled={busy} /></div>
          {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-destructive">{error}</p>}
          <Button className="w-full" size="lg" disabled={busy}>{busy ? <LoaderCircle className="animate-spin" /> : <>进入工作空间<ArrowRight /></>}</Button>
        </form><p className="mt-5 text-center text-xs leading-6 text-muted-foreground">账号由管理员创建。忘记密码请联系公司管理员。</p></CardContent>
      </Card><p className="mt-7 flex items-center justify-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="size-3.5" />企业身份认证 · 数据按账号隔离</p>
    </div>
  </main>;
}
