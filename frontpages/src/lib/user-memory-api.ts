import { accountApi } from "@/lib/auth-api";

export interface UserMemory {
  id: number; // 记忆的整数主键
  content: string; // 当前保存的记忆内容
  created_at: string; // 创建时间
  updated_at: string; // 最近修改时间
}

export interface UserMemoryPage {
  items: UserMemory[]; // 当前页属于本人的记忆
  next_cursor: number | null; // 下一页游标，为空表示没有下一页
}

export const userMemoryApi = {
  list: (cursor: number | null, signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: "20" });
    if (cursor !== null) query.set("cursor", String(cursor));
    return accountApi<UserMemoryPage>(`user-memories?${query}`, { signal });
  },
  update: (id: number, content: string) => accountApi<void>(`user-memories/${id}`, {
    method: "PATCH", body: JSON.stringify({ content }),
  }),
  remove: (id: number) => accountApi<void>(`user-memories/${id}`, { method: "DELETE" }),
};
