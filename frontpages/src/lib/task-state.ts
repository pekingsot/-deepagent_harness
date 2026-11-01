import { isTaskExecution, type TaskExecution, eventLabels, isTaskPlanItems, statusLabels, type LocalTask, type StreamEvent, type TaskResponse, type TaskStatus } from "./task-types";

// 保留微秒，避免同一毫秒内的停止和重新排队被误判为同一版本。
function version(value: string) {
  return value.replace("+00:00", "Z").replace(/(?:\.(\d+))?Z$/, (_, digits: string | undefined) => `.${(digits ?? "").padEnd(6, "0")}Z`);
}

export function mergeExecutions(local: TaskExecution[], incoming: TaskExecution[]): TaskExecution[] {
  const records = new Map(local.map((item) => [item.attempt, item]));
  for (const item of incoming) {
    const existing = records.get(item.attempt);
    if (!existing || version(item.updated_at) >= version(existing.updated_at)) records.set(item.attempt, item);
  }
  return [...records.values()].sort((a, b) => b.attempt - a.attempt);
}

function acceptsStatus(current: LocalTask, incoming: TaskStatus, attempt: number, updatedAt?: string) {
  if (attempt < current.attempt) return false;
  if (attempt > current.attempt) return true;
  const newer = updatedAt !== undefined && version(updatedAt) > version(current.updated_at);
  if (updatedAt && version(updatedAt) < version(current.updated_at)) return false;
  // 本轮停止后，只有服务端确认的新输入能在同轮次重新排队。
  if (["cancelled", "failed"].includes(current.status)) return incoming === current.status || (incoming === "queued" && newer);
  if (current.status === "cancelling") return incoming === "cancelling" || incoming === "cancelled";
  return true;
}

export function mergeTask(local: LocalTask, remote: TaskResponse): LocalTask {
  if (!acceptsStatus(local, remote.status, remote.attempt, remote.updated_at)) return local;
  return {
    ...local, ...remote,
    ...(["succeeded", "cancelled", "failed"].includes(local.status) && remote.status === "queued"
      ? { draft: "", todos: null, interrupts: [], result: null, error: null } : {}),
    replyPending: remote.status === "waiting_human" && local.replyPending,
    draft: remote.attempt > local.attempt || (["succeeded", "cancelled", "failed"].includes(local.status) && remote.status === "queued") ? "" : local.draft,
  };
}

export function applyEvent(task: LocalTask, item: StreamEvent): LocalTask {
  const attempt = typeof item.data.attempt === "number" ? item.data.attempt : task.attempt;
  const cursor = item.id || task.cursor;
  if (attempt < task.attempt) {
    return { ...task, cursor };
  }
  const next = {
    ...task, attempt, cursor, draft: attempt > task.attempt ? "" : task.draft,
    ...(attempt > task.attempt ? { todos: null, interrupts: [], result: null, error: null } : {}),
  };
  const statuses: Record<string, TaskStatus> = {
    queued: "queued", started: "running", resuming: "running", waiting_human: "waiting_human",
    completed: "succeeded", failed: "failed", cancelling: "cancelling", cancelled: "cancelled", resume_rejected: "waiting_human",
  };
  let incoming = statuses[item.event];
  if (item.event === "completed" && item.data.status === "queued") incoming = "queued";
  if (["state", "message_received", "execution_titled", "plan_updated"].includes(item.event) && typeof item.data.status === "string" && Object.hasOwn(statusLabels, item.data.status)) {
    incoming = item.data.status as TaskStatus;
  }
  const updatedAt = typeof item.data.updated_at === "string" ? item.data.updated_at : undefined;
  if (incoming && !acceptsStatus(task, incoming, attempt, updatedAt)) return { ...task, cursor };
  if (!incoming && ["queued", "cancelled", "failed"].includes(task.status) && attempt === task.attempt) return { ...task, cursor };
  if (incoming) {
    next.status = incoming;
    if (updatedAt) next.updated_at = updatedAt;
    if (["succeeded", "cancelled", "failed"].includes(task.status) && incoming === "queued") {
      next.draft = ""; next.todos = null; next.interrupts = []; next.result = null; next.error = null;
    }
  }
  if (isTaskExecution(item.data.execution)) {
    next.executions = mergeExecutions(task.executions ?? [], [item.data.execution]);
  }
  if (item.event === "text_delta" && typeof item.data.text === "string") next.draft = (next.draft + item.data.text).slice(-500_000);
  if (item.event === "plan_updated") {
    if (isTaskPlanItems(item.data.todos)) {
      next.todos = item.data.todos;
      next.planError = "";
    } else next.planError = "计划更新事件格式不正确，已保留上一次有效计划。";
  }
  if (item.event === "waiting_human" && Array.isArray(item.data.interrupts)) next.interrupts = item.data.interrupts;
  if (["resuming", "completed", "cancelling", "cancelled"].includes(item.event)) next.interrupts = [];
  if (["resuming", "waiting_human", "completed", "failed", "cancelling", "cancelled", "resume_rejected", "resume_error"].includes(item.event)) next.replyPending = false;
  if (item.event === "completed" && typeof item.data.output === "string") next.result = item.data.output;
  if (item.event === "failed" && typeof item.data.error === "string") next.error = item.data.error;
  if (!["text_delta", "state"].includes(item.event)) {
    const tool = typeof item.data.tool_name === "string" ? item.data.tool_name : "";
    const agent = typeof item.data.subagent === "string" ? item.data.subagent : "";
    const target = tool === "task" ? `子 Agent${agent ? ` · ${agent}` : ""}` : tool;
    const path = typeof item.data.file_path === "string" ? item.data.file_path : "";
    const elapsed = typeof item.data.elapsed_ms === "number" && Number.isFinite(item.data.elapsed_ms) && item.data.elapsed_ms >= 0
      ? ` · ${(item.data.elapsed_ms / 1000).toFixed(2)}s（请求至返回）` : "";
    const label = `${eventLabels[item.event] ?? "执行状态更新"}${target ? `：${target}` : ""}${path ? ` · ${path}` : ""}${elapsed}`;
    next.timeline = [...task.timeline, { attempt, key: item.id || crypto.randomUUID(), event: item.event, label, time: new Date().toISOString() }].slice(-100);
  }
  return next;
}

export function canCancelTask(status: TaskStatus) {
  return ["queued", "running", "waiting_human"].includes(status);
}
