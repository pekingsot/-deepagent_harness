"use client";

import { useEffect, useState } from "react";
import { Brain, ChevronLeft, ChevronRight, LoaderCircle, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { userMemoryApi, type UserMemory, type UserMemoryPage } from "@/lib/user-memory-api";

type MemoryEditor = { mode: "edit" | "delete"; memory: UserMemory };

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "操作失败，请稍后重试";
}

function date(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export function UserMemoryManager() {
  const [page, setPage] = useState<UserMemoryPage>({ items: [], next_cursor: null }); // 当前页
  const [cursors, setCursors] = useState<(number | null)[]>([null]); // 已访问页面的游标
  const [revision, setRevision] = useState(0); // 操作后刷新列表
  const [loading, setLoading] = useState(true); // 列表请求状态
  const [error, setError] = useState(""); // 列表错误
  const [notice, setNotice] = useState(""); // 成功反馈
  const [editor, setEditor] = useState<MemoryEditor | null>(null); // 当前编辑或删除的记录
  const [draft, setDraft] = useState(""); // 编辑内容
  const [busy, setBusy] = useState(false); // 防止重复提交
  const [formError, setFormError] = useState(""); // 保留编辑草稿并显示操作错误
  const cursor = cursors[cursors.length - 1];

  useEffect(() => {
    const controller = new AbortController();
    void userMemoryApi.list(cursor, controller.signal)
      .then((next) => { if (!controller.signal.aborted) { setPage(next); setError(""); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(errorMessage(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [cursor, revision]);

  function refresh() {
    setLoading(true); setError(""); setRevision((value) => value + 1);
  }

  function open(mode: MemoryEditor["mode"], memory: UserMemory) {
    setEditor({ mode, memory }); setDraft(memory.content); setFormError(""); setNotice("");
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor || busy) return;
    if (editor.mode === "edit" && !draft.trim()) { setFormError("记忆内容不能为空"); return; }
    setBusy(true); setFormError("");
    try {
      const id = editor.memory.id;
      if (editor.mode === "edit") {
        await userMemoryApi.update(id, draft.trim());
        setNotice("记忆已修改，后续检索将使用更新后的内容。");
      } else {
        await userMemoryApi.remove(id);
        setNotice("记忆已删除。");
      }
      setEditor(null);
      // 删除当前页最后一条时返回上一页，避免停留在无内容的历史页。
      if (editor.mode === "delete" && page.items.length === 1 && cursors.length > 1) {
        setLoading(true); setError(""); setCursors((items) => items.slice(0, -1));
      } else refresh();
    } catch (reason) { setFormError(errorMessage(reason)); }
    finally { setBusy(false); }
  }

  return <>
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div><CardTitle className="flex items-center gap-2"><Brain className="size-5" />我的长期记忆</CardTitle><CardDescription className="mt-2 leading-6">查看 AI 已保存的偏好和背景信息。不准确的内容可以修改，不再需要的可以删除。</CardDescription></div>
          <Button variant="ghost" size="icon" aria-label="刷新长期记忆" disabled={loading} onClick={refresh}><RefreshCw className={loading ? "animate-spin" : ""} /></Button>
        </div>
      </CardHeader>
      <CardContent>
        {notice && <p role="status" className="mb-4 rounded-lg bg-secondary p-3 text-sm text-primary">{notice}</p>}
        {error ? <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4"><p className="text-sm text-destructive">{error}</p><Button variant="outline" size="sm" className="mt-3" onClick={refresh}>重新加载</Button></div>
          : loading ? <div role="status" className="grid min-h-48 place-content-center gap-3 text-center text-sm text-muted-foreground"><LoaderCircle className="mx-auto size-5 animate-spin" />正在读取记忆…</div>
          : page.items.length ? <ul className="space-y-3">{page.items.map((memory) => <li key={memory.id} className="rounded-xl border bg-background p-4 sm:p-5">
            <p className="whitespace-pre-wrap break-words text-sm leading-7">{memory.content}</p>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-3">
              <span className="text-xs leading-5 text-muted-foreground">更新于 {date(memory.updated_at)}</span>
              <div className="flex gap-1"><Button variant="ghost" size="sm" onClick={() => open("edit", memory)}><Pencil />修改</Button><Button variant="ghost" size="sm" className="text-destructive" onClick={() => open("delete", memory)}><Trash2 />删除</Button></div>
            </div>
          </li>)}</ul> : <div className="grid min-h-52 place-content-center text-center"><Brain className="mx-auto mb-4 size-8 text-muted-foreground/60" /><h3 className="text-sm font-medium">还没有保存的长期记忆</h3><p className="mt-2 max-w-sm text-xs leading-6 text-muted-foreground">执行任务时，可以让 AI 记住你的偏好。保存成功后，会显示在这里。</p></div>}
        <div className="mt-5 flex items-center justify-between gap-2 border-t pt-4 text-xs text-muted-foreground">
          <span>第 {cursors.length} 页 · 每页最多 20 条</span>
          <div className="flex gap-2"><Button variant="outline" size="sm" disabled={loading || cursors.length === 1} onClick={() => { setLoading(true); setError(""); setCursors((items) => items.slice(0, -1)); }}><ChevronLeft />上一页</Button><Button variant="outline" size="sm" disabled={loading || !!error || page.next_cursor === null} onClick={() => { const next = page.next_cursor; if (next !== null) { setLoading(true); setError(""); setCursors((items) => [...items, next]); } }}>下一页<ChevronRight /></Button></div>
        </div>
      </CardContent>
    </Card>
    <p className="mt-4 text-xs leading-6 text-muted-foreground">这里只管理你本人的长期记忆，修改或删除不会清除历史任务与聊天记录。</p>
    <Dialog open={editor !== null} onOpenChange={(open) => { if (!open && !busy) setEditor(null); }}>
      <DialogContent className="max-w-xl">
        <DialogTitle className="text-lg font-semibold">{editor?.mode === "delete" ? "删除这条记忆？" : "修改长期记忆"}</DialogTitle>
        <DialogDescription className="mt-2 text-sm leading-6 text-muted-foreground">{editor?.mode === "delete" ? "删除后，这条内容将不再参与长期记忆检索。此操作不可撤销。" : "请填写完整、准确的内容。保存时会同步更新检索向量。"}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={submit}>
          {editor?.mode === "edit" ? <div><label htmlFor="memory-content" className="mb-2 block text-sm font-medium">记忆内容</label><Textarea id="memory-content" className="min-h-44 max-h-[45dvh] resize-y" autoFocus value={draft} maxLength={8000} disabled={busy} onChange={(event) => setDraft(event.target.value)} /><p className="mt-2 text-right text-xs text-muted-foreground">{draft.length} / 8000</p></div>
            : <p className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-4 text-sm leading-6">{editor?.memory.content}</p>}
          {formError && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2"><Button type="button" variant="outline" disabled={busy} onClick={() => setEditor(null)}>取消</Button><Button type="submit" variant={editor?.mode === "delete" ? "destructive" : "default"} disabled={busy || (editor?.mode === "edit" && (!draft.trim() || draft.trim() === editor.memory.content))}>{busy && <LoaderCircle className="animate-spin" />}{busy ? "正在处理…" : editor?.mode === "delete" ? "确认删除" : "保存修改"}</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  </>;
}
