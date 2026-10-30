"use client";

import { useState } from "react";
import { ArrowRight, Check, LoaderCircle, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { checkBackend } from "@/lib/task-api";

export function ConnectionSettings({ open, onOpenChange, token, onSave }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string;
  onSave: (value: string) => void;
}) {
  const [draft, setDraft] = useState(token); // 表单访问令牌，不写入日志
  const [checking, setChecking] = useState(false); // 健康检查进行中
  const [notice, setNotice] = useState(""); // 检查结果
  const [reachable, setReachable] = useState(false); // 仅表示后端可达，不表示认证成功

  async function check() {
    setChecking(true); setNotice(""); setReachable(false);
    try {
      await checkBackend();
      setReachable(true);
      setNotice("后端可访问。访问令牌会在发送消息时由后端校验。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "连接失败，请确认 FastAPI 已启动");
    } finally { setChecking(false); }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <span className="dialog-icon"><Settings2 className="size-5" /></span>
        <DialogTitle className="mt-4 text-lg font-semibold">连接你的工作空间</DialogTitle>
        <DialogDescription className="mt-2 text-sm leading-6 text-muted-foreground">先确认任务服务可以访问，再填写后端配置的开发访问令牌。</DialogDescription>
        <div className="mt-5 rounded-xl border bg-muted/40 p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs font-medium">后端服务</span>
            <Button type="button" size="sm" variant="outline" disabled={checking} onClick={() => void check()}>
              {checking ? <LoaderCircle className="animate-spin" /> : reachable ? <Check /> : null}
              {checking ? "检查中…" : "检查连接"}
            </Button>
          </div>
          <p className="mt-2 text-[11px] leading-6 text-muted-foreground">通过前端服务转发，地址在 frontpages/.env.local 中配置。</p>
          {notice && <p role="status" className={`mt-2 text-xs leading-6 ${reachable ? "text-emerald-700" : "text-destructive"}`}>{notice}</p>}
        </div>
        <form onSubmit={(event) => { event.preventDefault(); onSave(draft); onOpenChange(false); }}>
          <label htmlFor="access-token" className="mb-2 mt-5 block text-xs font-medium">访问令牌</label>
          <Input id="access-token" type="password" autoComplete="off" placeholder="与 HARNESS_DEVELOPMENT_TOKEN 一致" value={draft} onChange={(event) => setDraft(event.target.value)} />
          <p className="mt-3 text-xs leading-6 text-muted-foreground">这是后端开发访问令牌，不是模型 API Key。仅保留在当前标签页会话。</p>
          <div className="mt-6 flex gap-2">
            <Button type="button" variant="outline" onClick={() => { onSave(""); onOpenChange(false); }}>断开连接</Button>
            <Button type="submit" className="ml-auto" disabled={!draft.trim()}>保存连接<ArrowRight /></Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
