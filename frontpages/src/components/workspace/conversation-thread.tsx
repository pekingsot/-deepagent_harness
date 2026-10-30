"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDown, Clipboard, Check, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/workspace/markdown";
import type { LocalTask } from "@/lib/task-types";

export function ConversationThread({ task }: { task: LocalTask }) {
  const viewport = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => {
    if (following && viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [task.messages, task.draft, following]);

  async function copy(id: string, content: string) {
    try { await navigator.clipboard.writeText(content); setCopied(id); setTimeout(() => setCopied(null), 1500); }
    catch { setCopied(null); }
  }

  return <div className="thread-container">
    <div className="thread-scroll" ref={viewport} onScroll={() => {
      const el = viewport.current;
      if (el) setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < 100);
    }}>
      <div className="thread-inner">
        <div className="thread-date">{new Date(task.created_at).toLocaleDateString("zh-CN")} · 当前会话</div>
        {!task.messages.length && <p role="status" className="text-center text-xs text-muted-foreground">正在读取会话消息…</p>}
        {task.messages.map((item) => item.role === "user" ? (
          <div className="user-message mb-6" key={item.id}>
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              <span>你</span>
              {item.state === "pending" && <span>已收到，等待处理</span>}
              {item.state === "processing" && <span>正在处理</span>}
              {item.state === "failed" && <span>未完成处理</span>}
            </div>
            <p>{item.content}</p>
          </div>
        ) : (
          <div className="assistant-message mb-7 !pt-1" key={item.id}>
            <div className="mb-4 flex items-center gap-2.5"><span className="assistant-mark"><Sparkles className="size-4" /></span><span className="text-sm font-semibold">任务规划助手</span></div>
            <Markdown>{item.content}</Markdown>
            <Button variant="ghost" size="sm" className="mt-3" onClick={() => void copy(item.id, item.content)}>{copied === item.id ? <Check /> : <Clipboard />}{copied === item.id ? "已复制" : "复制"}</Button>
          </div>
        ))}
        {task.status === "running" && <div className="assistant-message !pt-1">
          <div className="mb-4 flex items-center gap-2.5"><span className="assistant-mark"><Sparkles className="size-4" /></span><span className="text-sm font-semibold">正在继续处理</span><span className="text-[10px] text-muted-foreground">第 {task.attempt} 轮</span></div>
          {task.draft ? <div className="streaming-text"><Markdown>{task.draft}</Markdown></div> : <p role="status" className="text-xs text-muted-foreground">正在结合当前会话内容生成回答…</p>}
        </div>}
        {task.error && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-xs text-red-800">{task.error}</p>}
      </div>
    </div>
    {!following && <Button variant="outline" size="icon" className="scroll-latest" aria-label="回到最新消息" onClick={() => setFollowing(true)}><ArrowDown /></Button>}
  </div>;
}
