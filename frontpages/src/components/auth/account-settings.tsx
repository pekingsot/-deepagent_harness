"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Brain, KeyRound } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { UserMemoryManager } from "@/components/account/user-memory-manager";
import { accountApi } from "@/lib/auth-api";
import { leaveWorkspace, useAuthUser } from "@/components/auth/auth-provider";

export function AccountSettings() {
  const user = useAuthUser();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return;
    const data = new FormData(event.currentTarget);
    if (data.get("new") !== data.get("confirm")) { setError("两次新密码不一致"); return; }
    setBusy(true); setError("");
    try {
      await accountApi("auth/password", { method: "PUT", body: JSON.stringify({ current_password: data.get("current"), new_password: data.get("new") }) });
      leaveWorkspace();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "修改失败"); setBusy(false); }
  }
  return <main className="min-h-dvh bg-muted/40 px-4 py-8 sm:px-6 sm:py-10"><div className="mx-auto max-w-3xl">
    <Button asChild variant="ghost" className="mb-6"><Link href="/"><ArrowLeft />返回工作台</Link></Button>
    <header className="mb-7"><h1 className="text-2xl font-semibold tracking-tight">个人中心</h1><p className="mt-2 break-words text-sm text-muted-foreground">{user.display_name} · {user.tenant_name} · @{user.username}</p></header>
    <Tabs defaultValue="memory">
      <TabsList className="mb-2 grid h-11 w-full grid-cols-2 sm:w-80"><TabsTrigger value="memory" className="h-9 gap-2"><Brain className="size-4" />长期记忆</TabsTrigger><TabsTrigger value="security" className="h-9 gap-2"><KeyRound className="size-4" />账号安全</TabsTrigger></TabsList>
      <TabsContent value="memory"><UserMemoryManager /></TabsContent>
      <TabsContent value="security">
    <Card><CardHeader><CardTitle>修改密码</CardTitle><CardDescription>维护账号安全，密码修改后需要重新登录。</CardDescription></CardHeader><CardContent>
      <form onSubmit={save} className="space-y-5">
        <div className="space-y-2"><label htmlFor="current" className="text-sm">当前密码</label><Input id="current" name="current" type="password" autoComplete="current-password" required maxLength={128} disabled={busy} /></div>
        <div className="space-y-2"><label htmlFor="new" className="text-sm">新密码</label><Input id="new" name="new" type="password" autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy} /></div>
        <div className="space-y-2"><label htmlFor="confirm" className="text-sm">确认新密码</label><Input id="confirm" name="confirm" type="password" autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy} /></div>
        <p className="text-xs leading-6 text-muted-foreground">密码至少12位。修改成功后，你的所有旧会话都会失效，需要重新登录。</p>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <Button disabled={busy}><KeyRound />{busy ? "正在保存…" : "保存并重新登录"}</Button>
      </form>
    </CardContent></Card>
      </TabsContent>
    </Tabs>
  </div></main>;
}
