import type { TaskExecution, ExecutionResult, HumanReply, StreamEvent, TaskMessage, TaskResponse } from "@/lib/task-types";
import { isTaskExecution, isTaskPlanItems } from "@/lib/task-types";

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function check(response: Response) {
  if (response.ok) return;
  if (response.status === 401) window.location.replace("/login");
  let detail = `任务服务返回错误（${response.status}）`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) detail = body.detail.map((item: { msg?: string }) => item.msg ?? "参数不正确").join("；");
  } catch { /* 非 JSON 错误保留状态码提示。 */ }
  throw new ApiError(detail, response.status);
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/backend/tasks${path}`, {
    ...options,
    signal: options.signal
      ? AbortSignal.any([options.signal, AbortSignal.timeout(20_000)])
      : AbortSignal.timeout(20_000),
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  await check(response);
  if (response.status === 204 || response.status === 202 && options.method === "DELETE") return undefined as T;
  return response.json() as Promise<T>;
}

export const taskApi = {
  delete: (id: string) => api<void>(`/${id}`, { method: "DELETE" }),
  executions: async (id: string, signal?: AbortSignal): Promise<TaskExecution[]> => {
    const records = await api<unknown>(`/${id}/executions`, { signal });
    if (!Array.isArray(records) || !records.every(isTaskExecution)) throw new Error("执行轮次数据格式不正确");
    return records;
  },
  list: (signal?: AbortSignal) => api<TaskResponse[]>("", { signal }),
  messages: (id: string, signal?: AbortSignal) => api<TaskMessage[]>(`/${id}/messages`, { signal }),
  send: (id: string, content: string, messageId: string) => api<TaskResponse>(`/${id}/messages`, { method: "POST", body: JSON.stringify({ id: messageId, content }) }),
  rename: (id: string, title: string) => api<TaskResponse>(`/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  create: (prompt: string) => api<TaskResponse>("", { method: "POST", body: JSON.stringify({ agent: "task_planning", prompt }) }),
  get: (id: string, signal?: AbortSignal) => api<TaskResponse>(`/${id}`, { signal }),
  execution: async (id: string, signal?: AbortSignal): Promise<ExecutionResult> => {
    const result = await api<ExecutionResult>(`/${id}/execution`, { signal });
    // 校验真实接口数据，避免把缺失或错误的计划误显示为空计划。
    if (!isTaskPlanItems(result.todos)) {
      throw new Error("任务计划数据格式不正确，请确认后端 execution 接口已返回 todos。");
    }
    if (!Array.isArray(result.artifacts) || result.artifacts.some((item) =>
      !item || typeof item.path !== "string" || !item.path.startsWith("/deliverables/") || typeof item.content !== "string"
    )) {
      throw new Error("交付物数据格式不正确，请确认后端 execution 接口已返回 artifacts。");
    }
    return result;
  },
  resume: (id: string, answers: Record<string, HumanReply>) => api<TaskResponse>(`/${id}/resume`, { method: "POST", body: JSON.stringify({ answers }) }),
  cancel: (id: string) => api<TaskResponse>(`/${id}/cancel`, { method: "POST" }),
};

export async function checkBackend(): Promise<void> {
  const response = await fetch("/api/backend/health", {
    cache: "no-store", signal: AbortSignal.timeout(20_000),
  });
  await check(response);
  const body: unknown = await response.json();
  if (!body || typeof body !== "object" || !("status" in body) || body.status !== "ok") {
    throw new Error("后端健康检查返回了不符合约定的响应");
  }
}

export async function readTaskEvents(id: string, cursor: string, signal: AbortSignal, onEvent: (event: StreamEvent) => void, onOpen: () => void) {
  const response = await fetch(`/api/backend/tasks/${id}/events`, {
    headers: { Accept: "text/event-stream", "Last-Event-ID": cursor },
    signal, cache: "no-store",
  });
  await check(response);
  if (!response.headers.get("content-type")?.includes("text/event-stream") || !response.body) {
    throw new Error("任务服务没有返回有效的事件流");
  }
  onOpen();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let eventId = "";
  let data: string[] = [];

  function line(value: string) {
    if (value === "") {
      if (data.length) {
        const payload: unknown = JSON.parse(data.join("\n"));
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("事件数据格式不正确");
        if (event === "auth_expired") {
          window.location.replace("/login");
          throw new ApiError("登录已失效", 401);
        }
        onEvent({ id: eventId, event, data: payload as Record<string, unknown> });
      }
      event = "message"; eventId = ""; data = [];
      return;
    }
    if (value.startsWith(":")) return;
    const separator = value.indexOf(":");
    const field = separator < 0 ? value : value.slice(0, separator);
    const raw = separator < 0 ? "" : value.slice(separator + 1);
    const content = raw.startsWith(" ") ? raw.slice(1) : raw;
    if (field === "data") data.push(content);
    if (field === "event") event = content;
    if (field === "id" && /^\d+-\d+$/.test(content)) eventId = content;
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      // 保留跨网络片段的半行、半条事件及 UTF-8 字符。
      let newline: number;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        line(buffer.slice(0, newline).replace(/\r$/, ""));
        buffer = buffer.slice(newline + 1);
      }
      if (done) {
        if (buffer) line(buffer.replace(/\r$/, ""));
        line("");
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
