"use client";

import { useState } from "react";
import { Download, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import type { TaskArtifact } from "@/lib/task-types";

export function TaskArtifacts({ artifacts }: { artifacts: TaskArtifact[] }) {
  const [selected, setSelected] = useState<TaskArtifact | null>(null);

  function download(item: TaskArtifact) {
    const url = URL.createObjectURL(new Blob([item.content], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = item.path.split("/").pop() || "交付物.txt";
    link.click();
    // 给浏览器时间开始读取文件，再释放下载资源。
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section aria-label="任务交付物" className="mt-6 border-t pt-5">
    <h3 className="mb-3 flex items-center gap-2 text-xs font-medium"><FileText className="size-4" />交付物<span className="ml-auto text-[10px] text-muted-foreground">{artifacts.length} 个文件</span></h3>
    {artifacts.length ? <ul className="space-y-2">{artifacts.map((item) => <li key={item.path} className="flex min-w-0 items-center gap-1 rounded-lg border bg-background p-2">
      <button className="artifact-open min-w-0 flex-1 text-left" onClick={() => setSelected(item)} title={item.path}><span className="block truncate">{item.path.split("/").pop()}</span><span className="mt-1 block text-[10px] text-muted-foreground">点击预览</span></button>
      <Button variant="ghost" size="icon" className="size-7 shrink-0" aria-label={`下载 ${item.path}`} onClick={() => download(item)}><Download className="size-3.5" /></Button>
    </li>)}</ul> : <p className="text-[11px] leading-6 text-muted-foreground">暂无交付文件。任务结束或暂停后，生成的文本文件会显示在这里。</p>}
    <Dialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null); }}>
      <DialogContent className="flex max-h-[85dvh] flex-col sm:max-w-3xl">
        <DialogTitle className="break-all pr-6 text-sm">{selected?.path.split("/").pop()}</DialogTitle>
        <DialogDescription className="break-all text-xs">{selected?.path}</DialogDescription>
        <pre className="min-h-0 overflow-auto whitespace-pre-wrap break-words rounded-xl border bg-muted/40 p-4 text-xs leading-6">{selected?.content}</pre>
        <Button variant="outline" size="sm" className="self-start" onClick={() => { if (selected) download(selected); }}><Download className="size-3.5" />下载原文件</Button>
      </DialogContent>
    </Dialog>
  </section>;
}
