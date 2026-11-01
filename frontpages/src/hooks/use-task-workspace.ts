"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthUser } from "@/components/auth/auth-provider";
import { applyEvent, mergeTask, mergeExecutions } from "@/lib/task-state";
import { ApiError, readTaskEvents, taskApi } from "@/lib/task-api";
import { isTerminal, type HumanReply, type LocalTask, type TaskResponse } from "@/lib/task-types";

function message(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "登录已失效，请重新登录";
    if ([404, 405].includes(error.status)) return "会话不存在或无权访问，请重新选择会话";
  }
  if (error instanceof Error && error.name === "TimeoutError") return "请求超时，写入可能已成功，请先刷新会话，避免重复提交";
  return error instanceof Error ? error.message : "请求失败，请稍后重试";
}

function localTask(task: TaskResponse): LocalTask {
  return { ...task, executions: [], messages: [], draft: "", cursor: "0-0", interrupts: [], timeline: [], todos: null, planError: "", artifacts: [] };
}

export function useTaskWorkspace() {
  const user = useAuthUser();
  const identity = `${user.tenant_id}:${user.id}`; // 用于隔离不同账号的页面状态
  const [tasks, setTasks] = useState<LocalTask[]>([]); // 服务端会话列表，不再使用浏览器伪造历史
  const [selectedId, setSelectedIdState] = useState<string | null>(null); // 当前会话编号
  const selectionRevision = useRef(0); // 用户切换会话后，旧提交不能抢回当前选择
  const setSelectedId = useCallback((id: string | null) => {
    selectionRevision.current += 1;
    setSelectedIdState(id);
  }, []);
  const [ready, setReady] = useState(false); // 会话列表是否已加载
  const [busy, setBusy] = useState(false); // 写入请求进行中
  const [error, setError] = useState(""); // 可见错误信息
  const [connection, setConnection] = useState<"idle" | "connecting" | "live" | "retrying" | "closed">("idle");
  const [reconnect, setReconnect] = useState(0); // 手动重连计数
  const identityRef = useRef(identity); // 防止旧身份请求污染当前页面
  const cursors = useRef(new Map<string, string>()); // 当前页面已消费的 SSE 游标
  const writing = useRef(false); // 阻止同一页面重复提交
  const initialTask = useRef<string | null>(null); // 刷新前地址栏中的会话编号
  useEffect(() => { identityRef.current = identity; }, [identity]);

  useEffect(() => {
    initialTask.current = new URLSearchParams(window.location.search).get("task");
    try { sessionStorage.removeItem("harness-token"); } catch { /* 浏览器禁用存储时仍可使用 Cookie 登录。 */ }
  }, []);

  const patch = useCallback((id: string, update: (task: LocalTask) => LocalTask) => {
    setTasks((items) => items.map((item) => item.task_id === id ? update(item) : item));
  }, []);

  const hydrate = useCallback(async (auth: string, id: string, signal?: AbortSignal) => {
    const [summary, messages, executions] = await Promise.all([taskApi.get(id, signal), taskApi.messages(id, signal), taskApi.executions(id, signal)]);
    if (signal?.aborted || identityRef.current !== auth) return;
    patch(id, (local) => {
      const merged = mergeTask(local, summary);
      const records = mergeExecutions(local.executions, executions);
      const current = merged.status === "queued" ? undefined : records.find((item) => item.attempt === merged.attempt && (item.status === merged.status || (merged.status === "cancelling" && item.status === "running")));
      return { ...merged, messages, executions: records, ...(current ? { todos: current.todos } : {}) };
    });
    // 当前执行状态接口只支持完成或人工中断时读取，避免执行中不断请求产生冲突。
    if (summary.status === "waiting_human" || summary.status === "succeeded") {
      try {
        const execution = await taskApi.execution(id, signal);
        if (signal?.aborted || identityRef.current !== auth) return;
        patch(id, (local) => {
          // 请求期间可能已开始下一轮，旧的计划和中断不能覆盖新状态。
          if (local.attempt !== summary.attempt || local.status !== summary.status) return local;
          return { ...local, todos: execution.todos, artifacts: execution.artifacts, interrupts: execution.interrupts, planError: "" };
        });
      } catch (reason) {
        if (signal?.aborted || identityRef.current !== auth) return;
        patch(id, (local) => local.attempt !== summary.attempt || local.status !== summary.status ? local : {
          ...local,
          planError: reason instanceof ApiError && reason.status === 409
            ? "执行状态正在变化，稍后自动重新读取计划。"
            : message(reason),
        });
      }
    }
    return summary;
  }, [patch]);

  useEffect(() => {
    const controller = new AbortController();
    setTasks([]); setSelectedId(null); setReady(false); setError(""); cursors.current.clear();
    
    async function load() {
      try {
        const list = await taskApi.list(controller.signal);
        if (controller.signal.aborted) return;
        setTasks(list.map(localTask));
        const id = initialTask.current;
        if (id && list.some((task) => task.task_id === id)) setSelectedId(id);
      } catch (reason) { if (!controller.signal.aborted) setError(message(reason)); }
      finally { if (!controller.signal.aborted) setReady(true); }
    }
    void load();
    return () => controller.abort();
  }, [identity, setSelectedId]);

  useEffect(() => {
    if (!ready) return;
    const url = new URL(window.location.href);
    if (selectedId) url.searchParams.set("task", selectedId); else url.searchParams.delete("task");
    window.history.replaceState(null, "", url);
  }, [selectedId, ready]);

  useEffect(() => {
    if (!selectedId || !ready) { setConnection("idle"); return; }
    const id = selectedId;
    const controller = new AbortController();
    let refreshing = false;
    let known: TaskResponse | undefined;
    let eventTimer: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      if (refreshing || controller.signal.aborted) return;
      refreshing = true;
      try { known = await hydrate(identity, id, controller.signal); }
      catch (reason) {
        if (!controller.signal.aborted && reason instanceof ApiError && [401, 403, 404, 501].includes(reason.status)) {
          setError(message(reason)); controller.abort(); setConnection("closed");
        }
      } finally { refreshing = false; }
    }
    async function connect() {
      let attempts = 0;
      while (!controller.signal.aborted) {
        setConnection(attempts ? "retrying" : "connecting");
        try {
          await readTaskEvents(id, cursors.current.get(id) ?? "0-0", controller.signal, (event) => {
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
            if (!["text_delta", "plan_updated", "execution_titled", "tool_requested", "tool_returned", "tool_failed"].includes(event.event)
              && (!known || event.data.updated_at !== known.updated_at)) {
              clearTimeout(eventTimer);
              eventTimer = setTimeout(() => void refresh(), 250);
            }
            if (["resume_rejected", "resume_error"].includes(event.event)) setError(typeof event.data.message === "string" ? event.data.message : "人工回复处理失败");
          }, () => { if (!controller.signal.aborted) { setConnection("live"); if (attempts > 0) void refresh(); } });
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
    void refresh();
    void connect();
    return () => { controller.abort(); clearTimeout(eventTimer); };
  }, [selectedId, identity, ready, reconnect, hydrate, patch]);

  async function submit(content: string) {
    if (writing.current) return false;
    writing.current = true; setBusy(true); setError("");
    const id = selectedId;
    let revision = selectionRevision.current;
    try {
      const response = id ? await taskApi.send(id, content, crypto.randomUUID()) : await taskApi.create(content);
      if (identityRef.current !== identity) return false;
      if (id) patch(id, (task) => mergeTask(task, response));
      else {
        setTasks((items) => [localTask(response), ...items]);
        if (selectionRevision.current === revision) {
          setSelectedId(response.task_id);
          revision = selectionRevision.current;
        }
      }
      await hydrate(identity, response.task_id).catch((reason) => {
        if (identityRef.current === identity && selectionRevision.current === revision) {
          setError(`消息已接收，但读取历史失败：${message(reason)}`);
        }
      });
      return true;
    } catch (reason) {
      if (identityRef.current === identity && selectionRevision.current === revision) setError(message(reason));
      return false;
    }
    finally { writing.current = false; setBusy(false); }
  }

  async function resume(answers: Record<string, HumanReply>) {
    if (!selectedId || writing.current) return;
    writing.current = true; setBusy(true); setError("");
    try {
      await taskApi.resume(selectedId, answers);
      if (identityRef.current !== identity) return;
      patch(selectedId, (task) => ({ ...task, replyPending: true }));
    } catch (reason) { setError(message(reason)); }
    finally { writing.current = false; setBusy(false); }
  }

  async function cancel() {
    if (!selectedId || writing.current) return;
    writing.current = true; setBusy(true); setError("");
    try {
      const remote = await taskApi.cancel(selectedId);
      if (identityRef.current !== identity) return;
      patch(selectedId, (task) => ({ ...mergeTask(task, remote), interrupts: [] }));
      await hydrate(identity, selectedId);
    } catch (reason) { setError(message(reason)); }
    finally { writing.current = false; setBusy(false); }
  }

  async function deleteTask(id: string) {
    if (writing.current) return false;
    writing.current = true; setBusy(true); setError("");
    try {
      try { await taskApi.delete(id); }
      catch (reason) {
        if (!(reason instanceof ApiError && reason.status === 404)) throw reason;
        // 区分会话已删除与后端缺少 DELETE 路由，不能把接口不存在当作成功。
        try { await taskApi.get(id); }
        catch (lookupError) {
          if (!(lookupError instanceof ApiError && lookupError.status === 404)) throw lookupError;
          // 两次查询均不存在，允许清除本地残留。
          cursors.current.delete(id);
          if (identityRef.current === identity) {
            setTasks((items) => items.filter((item) => item.task_id !== id));
            setSelectedIdState((current) => current === id ? null : current);
          }
          return identityRef.current === identity;
        }
        throw new Error("后端未提供会话删除接口，请确认 API 已更新并重启");
      }
      if (identityRef.current !== identity) return false;
      setTasks((items) => items.filter((item) => item.task_id !== id));
      cursors.current.delete(id);
      // 不抢占用户在删除等待期间切换到的另一会话。
      setSelectedIdState((current) => current === id ? null : current);
      return true;
    } catch (reason) {
      if (identityRef.current === identity) {
        setError(message(reason));
        await hydrate(identity, id).catch(() => {});
      }
      return false;
    } finally { writing.current = false; setBusy(false); }
  }

  async function rename(title: string) {
    if (!selectedId || writing.current) return false;
    writing.current = true; setBusy(true); setError("");
    try {
      const remote = await taskApi.rename(selectedId, title);
      if (identityRef.current !== identity) return false;
      patch(selectedId, (task) => mergeTask(task, remote));
      return true;
    } catch (reason) { setError(message(reason)); return false; }
    finally { writing.current = false; setBusy(false); }
  }

  async function openTask(id: string) {
    if (!/^[0-9a-f-]{36}$/i.test(id)) { setError("请填写有效任务编号"); return false; }
    try {
      const remote = await taskApi.get(id);
      if (identityRef.current !== identity) return false;
      setTasks((items) => items.some((task) => task.task_id === id) ? items : [localTask(remote), ...items]);
      setSelectedId(id); return true;
    } catch (reason) { setError(message(reason)); return false; }
  }

  const selected = tasks.find((task) => task.task_id === selectedId) ?? null;
  return { tasks, selectedId, selected, setSelectedId, ready, busy, error, setError, connection, submit, resume, cancel, rename, deleteTask, openTask, retry: () => { setError(""); setReconnect((value) => value + 1); }, canSend: !selected || (!selected.deletion_requested && selected.status !== "cancelling"), active: selected ? !isTerminal(selected.status) : false };
}
