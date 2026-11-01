"use client";

import { useState } from "react";

export function useTaskComposer(identity: string, taskId: string | null) {
  const [drafts, setDrafts] = useState<Record<string, string>>({}); // 各账号、会话的未发送草稿
  const key = JSON.stringify([identity, taskId]); // null 表示新任务输入区，避免与已有任务混用

  function setPrompt(value: string) {
    // 捕获本次渲染的任务键：旧提交完成后只清空原任务草稿。
    setDrafts((current) => ({ ...current, [key]: value }));
  }

  function clearNewDraft() {
    setDrafts((current) => ({ ...current, [JSON.stringify([identity, null])]: "" }));
  }

  function forgetTask(id: string) {
    setDrafts((current) => {
      const next = { ...current };
      delete next[JSON.stringify([identity, id])];
      return next;
    });
  }

  return { prompt: drafts[key] ?? "", setPrompt, clearNewDraft, forgetTask };
}
