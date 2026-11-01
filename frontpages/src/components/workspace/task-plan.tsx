"use client";

import { Circle, CircleCheck, ListChecks, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { LocalTask, TaskPlanItem } from "@/lib/task-types";
import { cn } from "@/lib/utils";

const labels: Record<TaskPlanItem["status"], string> = {
  pending: "待执行",
  in_progress: "执行中",
  completed: "已完成",
};

export function TaskPlan({ task, onRetry }: { task: LocalTask; onRetry: () => void }) {
  const items = task.todos;
  const active = task.status === "running" || task.status === "queued";
  const completed = items?.filter((item) => item.status === "completed").length ?? 0;

  return <section aria-label="任务计划" className="space-y-4">
    <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
      <ListChecks className="size-4 text-primary" />任务计划
      {items && items.length > 0 && <span className="ml-auto whitespace-nowrap text-[10px] font-normal text-muted-foreground">{completed} / {items.length} 项完成</span>}
    </div>

    {["cancelling", "cancelled"].includes(task.status) && <p role="status" className="text-xs text-muted-foreground">{task.status === "cancelling" ? "正在停止执行" : "执行已停止"}；以下保留最后收到的计划，不代表未完成步骤还在运行。</p>}
    {task.planError && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-6 text-amber-900">
      <p>计划读取失败：{task.planError}</p>
      <Button variant="ghost" size="sm" className="mt-1" onClick={onRetry}>重新读取</Button>
    </div>}

    {items && items.length > 0 ? <>
      <div role="progressbar" aria-label="计划完成进度" aria-valuemin={0} aria-valuemax={items.length} aria-valuenow={completed} className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary/70 transition-[width] duration-300" style={{ width: `${completed / items.length * 100}%` }} />
      </div>
      <ol className="space-y-3">
        {items.map((item, index) => {
          const Icon = item.status === "completed" ? CircleCheck : item.status === "in_progress" ? LoaderCircle : Circle;
          return <li key={`${index}:${item.content}`} className={cn(
            "flex items-start gap-3 rounded-xl border p-3",
            item.status === "completed" ? "border-primary/15 bg-primary/5" : "bg-background",
          )}>
            <Icon aria-hidden="true" className={cn("mt-0.5 size-4 shrink-0", item.status === "pending" ? "text-muted-foreground" : "text-primary", item.status === "in_progress" && active && "animate-spin")} />
            <div className="min-w-0 flex-1">
              <p className="break-words text-xs leading-6">{item.content}</p>
              <span className="mt-1 block text-[10px] text-muted-foreground">步骤 {index + 1} · {labels[item.status]}</span>
            </div>
          </li>;
        })}
      </ol>
      <p className="text-[10px] leading-5 text-muted-foreground">
        {active ? "当前展示最近收到的计划，后续计划变更会自动更新。" : "计划状态来自最近保存的执行记录；回答完成不代表计划中的工作已执行。"}
      </p>
    </> : <div role="status" className="rounded-xl border border-dashed p-5 text-xs leading-6 text-muted-foreground">
      {active ? <><LoaderCircle aria-hidden="true" className="mb-3 size-5 animate-spin" /><p>正在处理，等待助手生成结构化计划。</p></>
        : items === null && !task.planError && ["succeeded", "waiting_human"].includes(task.status) ? "正在读取任务计划…"
        : task.planError ? "暂时无法展示任务计划，聊天消息仍可正常查看。"
        : "暂无结构化计划。简单问答可能不会生成计划，可以要求助手将复杂任务拆解为具体步骤。"}
    </div>}
  </section>;
}
