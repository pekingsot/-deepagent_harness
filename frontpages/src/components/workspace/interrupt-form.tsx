"use client";

import { useState } from "react";
import { ArrowUpRight, Check, ShieldCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { HumanReply, TaskInterrupt } from "@/lib/task-types";
import { cn } from "@/lib/utils";

function replyText(reply: HumanReply | undefined) {
  return reply?.type === "user_input" ? reply.answer : "";
}

export function InterruptForm({ interrupts, busy, onSubmit }: { interrupts: TaskInterrupt[]; busy: boolean; onSubmit: (answers: Record<string, HumanReply>) => Promise<void> }) {
  const [answers, setAnswers] = useState<Record<string, HumanReply>>({});
  const complete = interrupts.every((item) => {
    const reply = answers[item.id];
    return reply && (reply.type === "tool_approval" || reply.answer.trim().length > 0);
  });

  return (
    <form className="interrupt-form" onSubmit={(event) => { event.preventDefault(); if (complete) void onSubmit(answers); }}>
      <div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="size-4 text-emerald-700" />接下来，需要你来决定</div>
      <p className="mt-1 text-xs leading-6 text-muted-foreground">补充信息或确认操作后，Agent 会从暂停处继续。</p>
      {interrupts.map((item, index) => (
        <div className="mt-5" key={item.id}>
          {item.payload.type === "user_input" ? (
            <>
              <label htmlFor={`answer-${item.id}`} className="mb-2 block text-sm leading-6">{interrupts.length > 1 && `${index + 1}. `}{item.payload.question}</label>
              <Textarea id={`answer-${item.id}`} disabled={busy} maxLength={16000} placeholder="在这里补充你的想法…" value={replyText(answers[item.id])} onChange={(event) => setAnswers((current) => ({ ...current, [item.id]: { type: "user_input", answer: event.target.value } }))} />
            </>
          ) : (
            <>
              <div className="text-sm">允许执行 <code className="rounded bg-muted px-1.5 py-0.5">{item.payload.tool_name}</code> 吗？</div>
              <details className="my-3 rounded-lg border bg-background p-3 text-xs"><summary className="cursor-pointer text-muted-foreground">查看操作参数</summary><pre className="mt-3 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(item.payload.args, null, 2)}</pre></details>
              <div className="flex gap-2" role="group" aria-label="是否允许工具执行">
                {[true, false].map((approved) => {
                  const reply = answers[item.id];
                  const selected = reply?.type === "tool_approval" && reply.approved === approved;
                  return <Button key={String(approved)} type="button" variant="outline" disabled={busy} aria-pressed={selected} className={cn("flex-1", selected && "border-emerald-700 bg-emerald-50 text-emerald-800")} onClick={() => setAnswers((current) => ({ ...current, [item.id]: { type: "tool_approval", approved } }))}>{approved ? <Check /> : <X />}{approved ? "允许" : "拒绝"}</Button>;
                })}
              </div>
            </>
          )}
        </div>
      ))}
      <Button type="submit" disabled={!complete || busy} className="mt-5 w-full">{busy ? "正在提交…" : "确认并继续"}<ArrowUpRight /></Button>
    </form>
  );
}
