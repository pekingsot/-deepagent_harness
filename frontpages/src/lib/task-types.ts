export type TaskStatus = "queued" | "running" | "cancelling" | "waiting_human" | "succeeded" | "failed" | "cancelled";

export interface TaskResponse {
  deletion_requested?: boolean; // 删除意图已持久化时禁止继续提交新工作
  title: string; // 会话名称，可独立于第一条消息修改
  prompt: string; // 第一条消息，用于会话摘要
  attempt: number; // 当前执行轮次，用于区分不同轮次的流式事件
  task_id: string; // 后端任务编号
  status: TaskStatus; // 数据库中的业务状态
  result: string | null; // 最终回答
  error: string | null; // 失败原因
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
}

export interface TaskMessage {
  id: string; // 消息唯一编号
  role: "user" | "assistant"; // 消息发送方
  content: string; // 消息正文
  state: "pending" | "processing" | "applied" | "failed" | "cancelled"; // 消息处理或停止情况
  position: number; // 服务端生成的消息顺序
  created_at: string; // 服务端消息创建时间
}

export type TaskInterrupt = {
  id: string; // 人工回复必须对应的中断编号
  payload:
    | { type: "user_input"; question: string }
    | { type: "tool_approval"; tool_name: string; tool_call_id: string; args: Record<string, unknown> };
};

export type HumanReply = { type: "user_input"; answer: string } | { type: "tool_approval"; approved: boolean };

export interface TaskPlanItem {
  content: string; // 计划项的具体工作内容
  status: "pending" | "in_progress" | "completed"; // 待执行、执行中、已完成
}

export function isTaskPlanItems(value: unknown): value is TaskPlanItem[] {
  // HTTP 和 SSE 共用同一份校验，错误事件不能覆盖已有计划。
  return Array.isArray(value) && value.every((item: unknown) => {
    if (!item || typeof item !== "object") return false;
    const plan = item as Record<string, unknown>;
    return typeof plan.content === "string" && Boolean(plan.content.trim()) &&
      typeof plan.status === "string" && ["pending", "in_progress", "completed"].includes(plan.status);
  });
}

export interface ExecutionResult {
  status: "waiting" | "completed";
  interrupts: TaskInterrupt[];
  output: string | null;
  todos: TaskPlanItem[]; // checkpoint 中保存的当前任务计划
  artifacts: TaskArtifact[]; // 当前任务生成的文本交付物
}

export interface TaskArtifact {
  path: string; // 虚拟工作区中的交付物路径
  content: string; // 用于预览和下载的文本内容
}

export interface StreamEvent {
  id: string; // Redis Stream 游标，用于去重及断线续读
  event: string; // 后端事件名称
  data: Record<string, unknown>; // 事件对应的数据
}

export interface TaskExecution {
  attempt: number; // 所属轮次
  title: string; // 本轮执行标题，不是会话名称
  status: TaskStatus; // 本轮保存的业务状态
  todos: TaskPlanItem[]; // 本轮步骤
  output: string | null; // 此轮完整或部分结果
  error: string | null; // 此轮失败原因
  created_at: string; // 开始时间
  updated_at: string; // 快照版本，避免旧查询覆盖新事件
}

export function isTaskExecution(value: unknown): value is TaskExecution {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.attempt === "number" && Number.isInteger(item.attempt) && item.attempt >= 1 &&
    typeof item.title === "string" && Boolean(item.title.trim()) &&
    typeof item.status === "string" && Object.hasOwn(statusLabels, item.status) &&
    isTaskPlanItems(item.todos) && (item.output === null || typeof item.output === "string") &&
    (item.error === null || typeof item.error === "string") &&
    typeof item.created_at === "string" && typeof item.updated_at === "string";
}

export interface TimelineItem {
  attempt: number; // 动态所属轮次，历史面板只展示该轮动态
  label: string; // 包含工具或子 Agent 名称的可读事件说明
  key: string; // 列表展示的唯一编号
  event: string; // 执行事件名称
  time: string; // 前端接收时间，不代表服务端发生时间
}

export interface LocalTask extends TaskResponse {
  executions: TaskExecution[]; // 按轮次保存的标题、步骤与结果
  artifacts: TaskArtifact[]; // 从执行记录读取的文本交付物
  todos: TaskPlanItem[] | null; // null 表示尚未读取，空数组表示没有结构化计划
  planError: string; // 计划读取失败的提示，不影响聊天历史展示
  messages: TaskMessage[]; // 服务端返回的完整会话记录
  draft: string; // SSE 接收的过程文本，最终回答单独保存在 result
  cursor: string; // 已处理事件编号
  interrupts: TaskInterrupt[]; // 当前待处理的人工问题
  timeline: TimelineItem[]; // 当前任务的执行过程
  replyPending?: boolean; // 人工回复已入队，等待 Worker 接收
}

export const statusLabels: Record<TaskStatus, string> = {
  queued: "排队中", running: "执行中", cancelling: "正在停止", waiting_human: "等待你回复",
  succeeded: "本轮完成", failed: "执行失败", cancelled: "本轮已停止",
};

export const eventLabels: Record<string, string> = {
  tool_requested: "请求调用工具",
  tool_returned: "工具已返回",
  tool_failed: "工具返回错误",
  plan_updated: "任务计划已更新",
  message_received: "补充信息已接收",
  queued: "任务已保存", started: "开始执行任务", waiting_human: "需要你的确认",
  resuming: "继续执行任务", completed: "任务已完成", failed: "执行失败",
  cancelling: "已请求停止，等待执行退出", cancelled: "本轮已停止", resume_rejected: "回复未被接受", resume_error: "恢复执行异常",
};

export function isTerminal(status: TaskStatus) {
  return ["succeeded", "failed", "cancelled"].includes(status);
}
