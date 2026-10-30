"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, readTaskEvents, taskApi } from "@/lib/task-api";
import { eventLabels, isTaskPlanItems, isTerminal, type HumanReply, type LocalTask, type StreamEvent, type TaskResponse, type TaskStatus } from "@/lib/task-types";

function message(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "访问令牌无效，请在连接设置中填写与后端一致的令牌";
    if (error.status === 501) return "后端尚未配置开发身份，请检查开发令牌和用户身份配置";
    if ([404, 405].includes(error.status)) return "会话不存在、无权访问，或后端尚未补齐会话接口，请按 backend-conversation-guide.md 修改后端";
  }
  if (error instanceof Error && error.name === "TimeoutError") return "请求超时，写入可能已成功，请先刷新会话，避免重复提交";
  return error instanceof Error ? error.message : "请求失败，请稍后重试";
}

function localTask(task: TaskResponse): LocalTask {
  return { ...task, messages: [], draft: "", cursor: "0-0", interrupts: [], timeline: [], todos: null, planError: "", artifacts: [] };
}

function mergeTask(local: LocalTask, remote: TaskResponse): LocalTask {
  if (remote.attempt < local.attempt) return local;
  return {
    ...local, ...remote,
    replyPending: remote.status === "waiting_human" && local.replyPending,
    draft: remote.attempt > local.attempt ? "" : local.draft,
  };
}

function applyEvent(task: LocalTask, item: StreamEvent): LocalTask {
  const attempt = typeof item.data.attempt === "number" ? item.data.attempt : task.attempt;
  if (attempt < task.attempt) return { ...task, cursor: item.id || task.cursor };
  const next = { ...task, attempt, cursor: item.id || task.cursor, draft: attempt > task.attempt ? "" : task.draft };
  const statuses: Record<string, TaskStatus> = {
    queued: "queued", started: "running", resuming: "running", waiting_human: "waiting_human",
    completed: "succeeded", failed: "failed", cancelled: "cancelled", resume_rejected: "waiting_human",
  };
  if (statuses[item.event]) next.status = statuses[item.event];
  if (item.event === "completed" && item.data.status === "queued") next.status = "queued";
  if (item.event === "text_delta" && typeof item.data.text === "string") next.draft = (next.draft + item.data.text).slice(-500_000);
  if (item.event === "plan_updated") {
    if (isTaskPlanItems(item.data.todos)) {
      next.todos = item.data.todos;
      next.planError = "";
    } else {
      next.planError = "计划更新事件格式不正确，已保留上一次有效计划。";
    }
  }
  if (item.event === "waiting_human" && Array.isArray(item.data.interrupts)) next.interrupts = item.data.interrupts;
  if (["resuming", "completed", "cancelled"].includes(item.event)) next.interrupts = [];
  if (["resuming", "waiting_human", "completed", "failed", "cancelled", "resume_rejected", "resume_error"].includes(item.event)) next.replyPending = false;
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
    next.timeline = [...task.timeline, { key: item.id || crypto.randomUUID(), event: item.event, label, time: new Date().toISOString() }].slice(-100);
  }
  return next;
}

export function useTaskWorkspace() {
  const [token, setToken] = useState(""); // 当前标签页的认证令牌
  const [tasks, setTasks] = useState<LocalTask[]>([]); // 服务端会话列表，不再使用浏览器伪造历史
  const [selectedId, setSelectedId] = useState<string | null>(null); // 当前会话编号
  const [ready, setReady] = useState(false); // 会话列表是否已加载
  const [busy, setBusy] = useState(false); // 写入请求进行中
  const [error, setError] = useState(""); // 可见错误信息
  const [connection, setConnection] = useState<"idle" | "connecting" | "live" | "retrying" | "closed">("idle");
  const [reconnect, setReconnect] = useState(0); // 手动重连计数
  const tokenRef = useRef(token); // 防止旧身份请求污染当前页面
  const cursors = useRef(new Map<string, string>()); // 当前页面已消费的 SSE 游标
  const writing = useRef(false); // 阻止同一页面重复提交
  const initialTask = useRef<string | null>(null); // 刷新前地址栏中的会话编号
  useEffect(() => { tokenRef.current = token; }, [token]);

  useEffect(() => {
    initialTask.current = new URLSearchParams(window.location.search).get("task");
    try { setToken(sessionStorage.getItem("harness-token") ?? ""); } catch { /* 存储禁用时使用内存令牌。 */ }
  }, []);

  const patch = useCallback((id: string, update: (task: LocalTask) => LocalTask) => {
    setTasks((items) => items.map((item) => item.task_id === id ? update(item) : item));
  }, []);

  const hydrate = useCallback(async (auth: string, id: string, signal?: AbortSignal) => {
    const [summary, messages] = await Promise.all([taskApi.get(auth, id, signal), taskApi.messages(auth, id, signal)]);
    if (signal?.aborted || tokenRef.current !== auth) return;
    patch(id, (local) => ({ ...mergeTask(local, summary), messages }));
    // 当前执行状态接口只支持完成或人工中断时读取，避免执行中不断请求产生冲突。
    if (summary.status === "waiting_human" || summary.status === "succeeded") {
      try {
        const execution = await taskApi.execution(auth, id, signal);
        if (signal?.aborted || tokenRef.current !== auth) return;
        patch(id, (local) => {
          // 请求期间可能已开始下一轮，旧的计划和中断不能覆盖新状态。
          if (local.attempt !== summary.attempt || local.status !== summary.status) return local;
          return { ...local, todos: execution.todos, artifacts: execution.artifacts, interrupts: execution.interrupts, planError: "" };
        });
      } catch (reason) {
        if (signal?.aborted || tokenRef.current !== auth) return;
        patch(id, (local) => local.attempt !== summary.attempt || local.status !== summary.status ? local : {
          ...local,
          planError: reason instanceof ApiError && reason.status === 409
            ? "执行状态正在变化，稍后自动重新读取计划。"
            : message(reason),
        });
      }
    }
  }, [patch]);

  useEffect(() => {
    const controller = new AbortController();
    setTasks([]); setSelectedId(null); setReady(false); setError(""); cursors.current.clear();
    if (!token) { setReady(true); return; }
    async function load() {
      try {
        const list = await taskApi.list(token, controller.signal);
        if (controller.signal.aborted) return;
        setTasks(list.map(localTask));
        const id = initialTask.current;
        if (id && list.some((task) => task.task_id === id)) setSelectedId(id);
      } catch (reason) { if (!controller.signal.aborted) setError(message(reason)); }
      finally { if (!controller.signal.aborted) setReady(true); }
    }
    void load();
    return () => controller.abort();
  }, [token]);

  useEffect(() => {
    if (!ready) return;
    const url = new URL(window.location.href);
    if (selectedId) url.searchParams.set("task", selectedId); else url.searchParams.delete("task");
    window.history.replaceState(null, "", url);
  }, [selectedId, ready]);

  useEffect(() => {
    if (!selectedId || !token || !ready) { setConnection("idle"); return; }
    const id = selectedId;
    const controller = new AbortController();
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    let refreshing = false;
    async function refresh() {
      if (refreshing || controller.signal.aborted) return;
      refreshing = true;
      try { await hydrate(token, id, controller.signal); }
      catch (reason) {
        if (!controller.signal.aborted && reason instanceof ApiError && [401, 403, 404, 501].includes(reason.status)) setError(message(reason));
      } finally { refreshing = false; }
    }
    async function poll() {
      await refresh();
      if (!controller.signal.aborted) refreshTimer = setTimeout(() => void poll(), 5000);
    }
    async function connect() {
      let attempts = 0;
      while (!controller.signal.aborted) {
        setConnection(attempts ? "retrying" : "connecting");
        try {
          await readTaskEvents(token, id, cursors.current.get(id) ?? "0-0", controller.signal, (event) => {
            if (controller.signal.aborted) return;
            const previous = cursors.current.get(id);
            if (event.id && previous) {
              const [a, b] = event.id.split("-").map(BigInt);
              const [c, d] = previous.split("-").map(BigInt);
              if (a < c || (a === c && b <= d)) return;
            }
            if (event.id) cursors.current.set(id, event.id);
            patch(id, (task) => applyEvent(task, event));
            // 计划事件已携带完整清单，不再额外查询执行状态接口。
            if (!["text_delta", "plan_updated", "tool_requested", "tool_returned", "tool_failed"].includes(event.event)) void refresh();
            if (["resume_rejected", "resume_error"].includes(event.event)) setError(typeof event.data.message === "string" ? event.data.message : "人工回复处理失败");
          }, () => { if (!controller.signal.aborted) setConnection("live"); });
          if (!controller.signal.aborted) throw new Error("事件连接已断开");
        } catch (reason) {
          if (controller.signal.aborted) return;
          if ((reason instanceof ApiError && reason.status < 500) || ++attempts > 5) {
            setError(message(reason)); setConnection("closed"); return;
          }
          await new Promise<void>((resolve) => {
            const done = () => { clearTimeout(timer); controller.signal.removeEventListener("abort", done); resolve(); };
            const timer = setTimeout(done, Math.min(attempts * 1500, 8000));
            controller.signal.addEventListener("abort", done, { once: true });
          });
        }
      }
    }
    void poll();
    void connect();
    return () => { controller.abort(); clearTimeout(refreshTimer); };
  }, [selectedId, token, ready, reconnect, hydrate, patch]);

  function configure(value: string) {
    const next = value.trim();
    try { if (next) sessionStorage.setItem("harness-token", next); else sessionStorage.removeItem("harness-token"); } catch { /* 允许仅内存使用。 */ }
    setToken(next); setReconnect((value) => value + 1);
  }

  async function submit(content: string) {
    if (!token) { setError("请先配置访问令牌"); return false; }
    if (writing.current) return false;
    writing.current = true; setBusy(true); setError("");
    const id = selectedId;
    try {
      const response = id ? await taskApi.send(token, id, content, crypto.randomUUID()) : await taskApi.create(token, content);
      if (tokenRef.current !== token) return false;
      if (id) patch(id, (task) => mergeTask(task, response));
      else { setTasks((items) => [localTask(response), ...items]); setSelectedId(response.task_id); }
      await hydrate(token, response.task_id).catch((reason) => setError(`消息已接收，但读取历史失败：${message(reason)}`));
      return true;
    } catch (reason) { setError(message(reason)); return false; }
    finally { writing.current = false; setBusy(false); }
  }

  async function resume(answers: Record<string, HumanReply>) {
    if (!selectedId || writing.current) return;
    writing.current = true; setBusy(true); setError("");
    try {
      await taskApi.resume(token, selectedId, answers);
      if (tokenRef.current !== token) return;
      patch(selectedId, (task) => ({ ...task, replyPending: true }));
    } catch (reason) { setError(message(reason)); }
    finally { writing.current = false; setBusy(false); }
  }

  async function cancel() {
    if (!selectedId || writing.current) return;
    writing.current = true; setBusy(true); setError("");
    try {
      const remote = await taskApi.cancel(token, selectedId);
      if (tokenRef.current !== token) return;
      patch(selectedId, (task) => ({ ...mergeTask(task, remote), interrupts: [] }));
      await hydrate(token, selectedId);
    } catch (reason) { setError(message(reason)); }
    finally { writing.current = false; setBusy(false); }
  }

  async function rename(title: string) {
    if (!selectedId || writing.current) return false;
    writing.current = true; setBusy(true); setError("");
    try {
      const remote = await taskApi.rename(token, selectedId, title);
      if (tokenRef.current !== token) return false;
      patch(selectedId, (task) => mergeTask(task, remote));
      return true;
    } catch (reason) { setError(message(reason)); return false; }
    finally { writing.current = false; setBusy(false); }
  }

  async function openTask(id: string) {
    if (!token || !/^[0-9a-f-]{36}$/i.test(id)) { setError("请先配置令牌，并填写有效任务编号"); return false; }
    try {
      const remote = await taskApi.get(token, id);
      if (tokenRef.current !== token) return false;
      setTasks((items) => items.some((task) => task.task_id === id) ? items : [localTask(remote), ...items]);
      setSelectedId(id); return true;
    } catch (reason) { setError(message(reason)); return false; }
  }

  const selected = tasks.find((task) => task.task_id === selectedId) ?? null;
  return { tasks, selectedId, selected, setSelectedId, token, configure, ready, busy, error, setError, connection, submit, resume, cancel, rename, openTask, retry: () => { setError(""); setReconnect((value) => value + 1); }, canSend: !selected || !["failed", "cancelled"].includes(selected.status), active: selected ? !isTerminal(selected.status) : false };
}
