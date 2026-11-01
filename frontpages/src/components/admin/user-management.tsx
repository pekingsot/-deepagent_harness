"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, KeyRound, LoaderCircle, Plus, ShieldCheck, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { accountApi } from "@/lib/auth-api";
import type { ManagedUser, UserPage } from "@/lib/auth-types";
import { leaveWorkspace, useAuthUser } from "@/components/auth/auth-provider";

type Editor = { mode: "create" } | { mode: "edit" | "password" | "status"; user: ManagedUser };

function date(value: string | null) { return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "尚未登录"; }

export function UserManagement() {
  const current = useAuthUser();
  const [page, setPage] = useState<UserPage>({ items: [], next_cursor: null });
  const [cursors, setCursors] = useState([0]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const cursor = cursors[cursors.length - 1];

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await accountApi<UserPage>(`users?after_id=${cursor}&limit=20`, { signal });
      if (!signal?.aborted) { setPage(next); setError(""); }
    } catch (reason) { if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "加载失败"); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [cursor]);
  useEffect(() => {
    const controller = new AbortController();
    // 数据请求完成后再更新界面，避免在 effect 中同步触发额外渲染。
    void accountApi<UserPage>(`users?after_id=${cursor}&limit=20`, { signal: controller.signal })
      .then((next) => { if (!controller.signal.aborted) { setPage(next); setError(""); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "加载失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [cursor]);
  function open(value: Editor) { setFormError(""); setNotice(""); setEditor(value); }

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!editor || busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true); setFormError("");
    try {
      if (editor.mode === "create") {
        await accountApi("users", { method: "POST", body: JSON.stringify({ username: String(data.get("username")).trim().toLowerCase(), display_name: data.get("display_name"), password: data.get("password"), role: data.get("role") }) });
      } else if (editor.mode === "edit") {
        await accountApi(`users/${editor.user.id}`, { method: "PATCH", body: JSON.stringify({ display_name: data.get("display_name"), role: data.get("role") }) });
      } else if (editor.mode === "password") {
        await accountApi(`users/${editor.user.id}/reset-password`, { method: "POST", body: JSON.stringify({ password: data.get("password") }) });
      } else {
        await accountApi(`users/${editor.user.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !editor.user.enabled }) });
      }
      if (editor.mode !== "create" && editor.user.id === current.id && (
        editor.mode === "password" || editor.mode === "status" || (editor.mode === "edit" && data.get("role") !== current.role)
      )) { leaveWorkspace(); return; }
      setEditor(null); setNotice("操作已保存"); await load();
    } catch (reason) { setFormError(reason instanceof Error ? reason.message : "保存失败"); }
    finally { setBusy(false); }
  }

  const title = !editor ? "" : editor.mode === "create" ? "创建用户" : editor.mode === "edit" ? "编辑用户" : editor.mode === "password" ? "重置密码" : editor.user.enabled ? "停用用户" : "启用用户";
  return <main className="min-h-dvh bg-muted/40 px-4 py-8 sm:px-8"><div className="mx-auto max-w-6xl">
    <div className="mb-8 flex flex-wrap items-center justify-between gap-4"><Button asChild variant="ghost"><Link href="/"><ArrowLeft />返回工作台</Link></Button><Badge className="gap-2"><ShieldCheck className="size-3.5" />{current.tenant_name} · 管理员</Badge></div>
    <div className="mb-7 flex items-center justify-between gap-4"><div><p className="mb-2 text-xs tracking-widest text-muted-foreground">WORKSPACE ADMIN</p><h1 className="flex items-center gap-3 text-2xl font-semibold tracking-tight"><Users className="size-6" />用户管理</h1><p className="mt-2 text-sm text-muted-foreground">管理公司成员、访问权限和账号安全。</p></div><Button onClick={() => open({ mode: "create" })}><Plus />创建用户</Button></div>
    {error && <div role="alert" className="mb-4 flex items-center justify-between rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-destructive">{error}<Button variant="outline" size="sm" onClick={() => { setLoading(true); void load(); }}>重试</Button></div>}
    {notice && <p role="status" className="mb-4 rounded-lg bg-secondary p-3 text-sm text-primary">{notice}</p>}
    <Card><CardHeader><CardTitle>公司成员</CardTitle><CardDescription>普通成员只能访问自己的任务与记忆。管理员可管理本公司的账号。</CardDescription></CardHeader><CardContent className="px-0 pb-0">
      <Table><TableHeader><TableRow><TableHead>成员</TableHead><TableHead>角色</TableHead><TableHead>状态</TableHead><TableHead>最近登录</TableHead><TableHead className="text-right">操作</TableHead></TableRow></TableHeader><TableBody>
        {loading ? <TableRow><TableCell colSpan={5} className="h-40 text-center text-muted-foreground"><LoaderCircle className="mx-auto mb-3 size-5 animate-spin" />正在加载成员…</TableCell></TableRow> : page.items.length ? page.items.map((user) => <TableRow key={user.id}>
          <TableCell><div className="flex items-center gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-full bg-secondary font-medium text-primary">{user.display_name.slice(0, 1)}</span><div><div className="font-medium">{user.display_name}{user.id === current.id && <span className="ml-2 text-xs text-muted-foreground">你</span>}</div><div className="mt-1 text-xs text-muted-foreground">@{user.username} · ID {user.id}</div></div></div></TableCell>
          <TableCell><Badge>{user.role === "admin" ? "管理员" : "成员"}</Badge></TableCell>
          <TableCell><span className={`inline-flex items-center gap-2 text-xs ${user.enabled ? "text-green-700" : "text-muted-foreground"}`}><span className={`size-1.5 rounded-full ${user.enabled ? "bg-green-500" : "bg-gray-400"}`} />{user.enabled ? "已启用" : "已停用"}</span></TableCell>
          <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{date(user.last_login_at)}</TableCell>
          <TableCell><div className="flex justify-end gap-1"><Button variant="ghost" size="sm" onClick={() => open({ mode: "edit", user })}>编辑</Button><Button variant="ghost" size="sm" onClick={() => open({ mode: "password", user })}><KeyRound className="size-3.5" />重置密码</Button><Button variant="ghost" size="sm" className={user.enabled ? "text-destructive" : ""} onClick={() => open({ mode: "status", user })}>{user.enabled ? "停用" : "启用"}</Button></div></TableCell>
        </TableRow>) : <TableRow><TableCell colSpan={5} className="h-36 text-center text-muted-foreground">当前页没有成员</TableCell></TableRow>}
      </TableBody></Table>
      <div className="flex items-center justify-between border-t px-5 py-4 text-xs text-muted-foreground"><span>第 {cursors.length} 页 · 每页最多 20 人</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={loading || cursors.length === 1} onClick={() => { setLoading(true); setCursors((items) => items.slice(0, -1)); }}><ChevronLeft />上一页</Button><Button variant="outline" size="sm" disabled={loading || page.next_cursor === null} onClick={() => { if (page.next_cursor !== null) { setLoading(true); setCursors((items) => [...items, page.next_cursor!]); } }}>下一页<ChevronRight /></Button></div></div>
    </CardContent></Card>
    <p className="mt-5 text-xs leading-6 text-muted-foreground">停用账号或修改角色、密码后，旧登录会话失效。系统会保留至少一名启用的管理员。</p>
    <Dialog open={editor !== null} onOpenChange={(value) => { if (!busy && !value) setEditor(null); }}><DialogContent key={editor ? `${editor.mode}-${editor.mode === "create" ? "new" : editor.user.id}` : "closed"}>
      <DialogTitle className="text-lg font-semibold">{title}</DialogTitle><DialogDescription className="mt-2 text-sm text-muted-foreground">{editor?.mode === "create" ? "登录名全系统唯一，新成员使用登录名和初始密码登录。" : editor ? `正在管理 ${editor.user.display_name}（@${editor.user.username}）` : ""}</DialogDescription>
      {editor && <form className="mt-6 space-y-4" onSubmit={save}>
        {editor.mode === "create" && <div className="space-y-2"><label htmlFor="new-username" className="text-sm">登录名</label><Input id="new-username" name="username" required minLength={3} maxLength={64} pattern="[a-z0-9][a-z0-9_.-]*" placeholder="小写字母、数字，至少3位" disabled={busy} /></div>}
        {(editor.mode === "create" || editor.mode === "edit") && <><div className="space-y-2"><label htmlFor="display-name" className="text-sm">显示名称</label><Input id="display-name" name="display_name" required maxLength={80} defaultValue={editor.mode === "edit" ? editor.user.display_name : ""} disabled={busy} /></div><div className="space-y-2"><label htmlFor="role" className="text-sm">角色</label><NativeSelect id="role" name="role" defaultValue={editor.mode === "edit" ? editor.user.role : "user"} disabled={busy}><option value="user">普通成员</option><option value="admin">管理员</option></NativeSelect></div></>}
        {(editor.mode === "create" || editor.mode === "password") && <div className="space-y-2"><label htmlFor="initial-password" className="text-sm">{editor.mode === "create" ? "初始密码" : "新密码"}</label><Input id="initial-password" name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required disabled={busy} /><p className="text-xs text-muted-foreground">至少12位，请通过安全渠道告知成员。</p></div>}
        {editor.mode === "status" && <p className="rounded-lg bg-muted p-4 text-sm leading-6">{editor.user.enabled ? "停用后将无法登录或继续发起任务，旧会话也会失效。已在执行中的任务不会被强制终止。" : "启用后，用户可使用现有密码重新登录。"}</p>}
        {editor.mode === "password" && <p className="text-xs text-muted-foreground">重置后该用户需要重新登录，历史任务和记忆保留。</p>}
        {formError && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-destructive">{formError}</p>}
        <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="outline" disabled={busy} onClick={() => setEditor(null)}>取消</Button><Button disabled={busy}>{busy && <LoaderCircle className="animate-spin" />}{busy ? "正在保存…" : "确认保存"}</Button></div>
      </form>}
    </DialogContent></Dialog>
  </div></main>;
}
