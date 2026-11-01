"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { ArrowUp, ArrowUpRight, Check, ChevronRight, Circle, Clipboard, Clock3, Command, Download, FileText, Layers3, ListChecks, LoaderCircle, Menu, MessageSquare, PanelLeftClose, PanelRightClose, PanelRightOpen, Plus, Search, Settings2, ShieldCheck, Sparkles, Square, SquarePen, Trash2, Workflow, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AccountMenu } from "@/components/auth/account-menu";
import { useAuthUser } from "@/components/auth/auth-provider";
import { InterruptForm } from "@/components/workspace/interrupt-form";
import { ConversationThread } from "@/components/workspace/conversation-thread";
import { TaskPlan } from "@/components/workspace/task-plan";
import { Markdown } from "@/components/workspace/markdown";
import { TaskArtifacts } from "@/components/workspace/task-artifacts";
import { useTaskWorkspace } from "@/hooks/use-task-workspace";
import { useTaskComposer } from "@/hooks/use-task-composer";
import { canCancelTask } from "@/lib/task-state";
import { isTerminal, statusLabels, type TaskStatus } from "@/lib/task-types";
import { cn } from "@/lib/utils";

const suggestions = [
  { icon: ListChecks, color: "sage", title: "规划一个新版本", description: "从版本目标到可执行的交付计划", prompt: "帮我制定一个为期两周的游戏版本研发计划，包括目标拆解、任务分工、依赖关系、风险和验收标准。缺少关键信息时，请使用 ask_user 向我提问。" },
  { icon: FileText, color: "sand", title: "梳理策划需求", description: "把零散的想法整理成清晰的需求", prompt: "我想设计一个游戏的新地图玩法。请先使用 ask_user 询问我的目标和现有设定，再帮我规划策划文档的结构、需要补充的内容和评审步骤。" },
  { icon: Workflow, color: "blue", title: "拆解复杂任务", description: "明确先后顺序，让每一步都有方向", prompt: "帮我规划一次内部智能客服的上线工作，拆解知识准备、意图处理、人工转接、验收及灰度发布步骤，标明依赖和风险。需要我决定的事项请使用 ask_user 提问。" },
  { icon: ShieldCheck, color: "rose", title: "准备上线检查", description: "提前识别遗漏与交付风险", prompt: "帮我制定游戏新版本的上线检查计划，覆盖配置、数据、回滚、监控和客服准备，按上线前、上线中、上线后三个阶段组织。请先使用 ask_user 向我确认版本范围。" },
];

function time(value: string) { return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); }

function StatusBadge({ status }: { status: TaskStatus }) {
  return <Badge className={cn("status-badge", `status-${status}`)}><span className={cn("size-1.5 rounded-full bg-current", ["running", "cancelling"].includes(status) && "animate-pulse")} />{statusLabels[status]}</Badge>;
}

export function Workspace() {
  const workspace = useTaskWorkspace();
  const user = useAuthUser();
  const { selected: task, busy } = workspace;
  const { prompt, setPrompt, clearNewDraft, forgetTask } = useTaskComposer(`${user.tenant_id}:${user.id}`, workspace.selectedId);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [copyId, setCopyId] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [executionSelection, setExecutionSelection] = useState<{ taskId: string; attempt: number } | null>(null); // 手动查看的历史轮次
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; title: string } | null>(null); // 确认框固定目标，切换会话不改变删除对象
  const composer = useRef<HTMLTextAreaElement>(null);

  function settings() { setSettingsOpen(true); }
  function newTask() { workspace.setSelectedId(null); workspace.setError(""); clearNewDraft(); setSidebarOpen(false); composer.current?.focus(); }
  async function submit() {
    if (!prompt.trim() || busy || !workspace.ready || !workspace.canSend) return;
    if (await workspace.submit(prompt.trim())) { setPrompt(""); setInspectorOpen(true); }
  }
  function exportResult() {
    if (!task?.result) return;
    const url = URL.createObjectURL(new Blob([`# 任务交付\n\n${task.prompt}\n\n---\n\n${task.result}`], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `任务交付-${task.task_id.slice(0, 8)}.md`; anchor.click(); URL.revokeObjectURL(url);
  }
  const filtered = workspace.tasks.filter((item) => `${item.title} ${item.prompt}`.toLowerCase().includes(search.toLowerCase()));
  const canCancel = task && canCancelTask(task.status);
  const historical = task && executionSelection?.taskId === task.task_id
    ? task.executions.find((item) => item.attempt === executionSelection.attempt) : undefined;
  const currentExecution = task?.status === "queued" ? undefined : task?.executions.find((item) => item.attempt === task.attempt && (item.status === task.status || (task.status === "cancelling" && item.status === "running")));
  const panelTask = task && historical ? {
    ...task, attempt: historical.attempt, status: historical.status, todos: historical.todos,
    result: historical.output, error: historical.error,
  } : task;
  const panelTitle = historical?.title ?? currentExecution?.title ??
    (task?.status === "queued" ? "等待新一轮执行" : task?.status === "cancelled" && !currentExecution ? "本次请求已停止" : task?.attempt ? `第 ${task.attempt} 轮执行` : "等待首次执行");
  const panelTimeline = !historical && (task?.status === "queued" || (task?.status === "cancelled" && !currentExecution)) ? [] : task?.timeline.filter((item) => item.attempt === panelTask?.attempt) ?? [];


  return (
    <div className="workspace-shell">
      {sidebarOpen && <button className="mobile-backdrop" aria-label="关闭导航" onClick={() => setSidebarOpen(false)} />}
      <aside className={cn("sidebar", sidebarOpen && "is-open")}>
        <div className="brand"><span className="brand-mark"><Command className="size-5" /></span><span>Agent<span className="font-normal text-muted-foreground"> Workspace</span></span><button className="ml-auto text-muted-foreground lg:hidden" aria-label="关闭导航" onClick={() => setSidebarOpen(false)}><PanelLeftClose className="size-4" /></button></div>
        <div className="grid gap-2 px-3">
          <Button variant="outline" className="new-task-button" onClick={newTask}><Plus className="size-4" />新工作任务<span className="ml-auto text-[10px] font-normal text-muted-foreground">任务规划</span></Button>
          <Button variant="outline" className="new-task-button" disabled title="普通聊天功能即将开放"><MessageSquare className="size-4" />新对话<span className="ml-auto text-[10px] font-normal text-muted-foreground">即将开放</span></Button>
        </div>
        <nav className="sidebar-nav" aria-label="工作区导航">
          {user.role === "admin" && <Link href="/admin/users" className="nav-item"><ShieldCheck />用户管理<ArrowUpRight className="ml-auto size-3.5" /></Link>}
          <button className="nav-item active" onClick={newTask}><Layers3 />任务工作台<span className="ml-auto nav-count">{workspace.tasks.length}</span></button>
        </nav>
        <div className="history-heading"><span>最近工作任务</span><button aria-label="搜索任务" onClick={() => setSearchOpen((open) => !open)}><Search className="size-3.5" /></button></div>
        {searchOpen && <div className="px-3 pb-2"><Input aria-label="搜索会话" className="h-8 text-xs" autoFocus placeholder="搜索任务…" value={search} onChange={(event) => setSearch(event.target.value)} /></div>}
        <div className="history-list">
          {filtered.length ? filtered.map((item) => <div key={item.task_id} className="flex items-center gap-1"><button className={cn("history-item flex-1 min-w-0", item.task_id === workspace.selectedId && "selected")} onClick={() => { workspace.setSelectedId(item.task_id); workspace.setError(""); setSidebarOpen(false); }}><MessageSquare className="size-3.5 shrink-0" /><span className="truncate">{item.title}</span>{item.status === "running" ? <LoaderCircle className="ml-auto size-3 animate-spin shrink-0" /> : item.status === "waiting_human" ? <span className="ml-auto size-1.5 shrink-0 rounded-full bg-amber-500" /> : null}</button><Button variant="ghost" size="icon" className="size-7 shrink-0 text-muted-foreground" disabled={busy} aria-label={`永久删除 ${item.title}`} onClick={() => setDeleteTarget({ id: item.task_id, title: item.title })}><Trash2 className="size-3.5" /></Button></div>) : <div className="history-empty">{search ? "没有找到相关任务" : "你的下一项任务，从这里开始。"}</div>}
        </div>
        <div className="sidebar-bottom"><div className="private-note"><ShieldCheck className="size-3.5" /><span>专注于你的内部工作</span></div><button className="profile-button" onClick={settings}><span className="profile-avatar">{user.display_name.slice(0, 1)}</span><span className="text-left"><span className="block text-xs font-medium">{user.display_name}</span><span className="block text-[10px] text-muted-foreground">{user.tenant_name}</span></span><Settings2 className="ml-auto size-4 text-muted-foreground" /></button></div>
      </aside>

      <div className="workspace-content">
        <header className="workspace-header">
          <Button variant="ghost" size="icon" aria-label="打开导航" className="lg:hidden" onClick={() => setSidebarOpen(true)}><Menu /></Button>
          <span className="header-breadcrumb">工作空间<ChevronRight className="size-3.5" /><strong>任务规划</strong></span>
          <Badge className="ml-3 hidden border-transparent bg-muted text-muted-foreground sm:inline-flex">工作台</Badge>
          <div className="ml-auto flex items-center gap-1.5">
            {task && <StatusBadge status={task.status} />}
            <Button variant="ghost" size="icon" aria-label="账号设置" onClick={settings}><Settings2 /></Button>
            <div className="mx-1 h-4 w-px bg-border" />
            <Button variant="ghost" size="icon" aria-label={inspectorOpen ? "收起任务面板" : "打开任务面板"} onClick={() => setInspectorOpen((open) => !open)}>{inspectorOpen ? <PanelRightClose /> : <PanelRightOpen />}</Button>
          </div>
        </header>

        <div className="workspace-body">
          <main className="main-panel">
            {workspace.error && <div role="alert" className="error-banner"><span>{workspace.error}</span><Button variant="ghost" size="sm" onClick={workspace.retry}>重新连接</Button><Button variant="ghost" size="icon" aria-label="关闭提示" onClick={() => workspace.setError("")}><X /></Button></div>}
            {task ? <>
              <div className="task-heading"><span className="truncate">{task.title}</span><Button size="icon" variant="ghost" aria-label="修改任务名称" onClick={() => { setTitleDraft(task.title); setRenameOpen(true); }}><SquarePen /></Button>{task.result && <Button size="icon" variant="ghost" aria-label="导出 Markdown" title="导出 Markdown" onClick={exportResult}><Download /></Button>}</div>
              <ConversationThread key={task.task_id} task={task} />
            </> : <div className="welcome-scroll"><div className="welcome">
              <div className="welcome-label"><span />YOUR IDEAS, IN MOTION</div>
              <div className="welcome-symbol"><Sparkles strokeWidth={1.4} /></div>
              <h1>把想法，变成下一步<span>复杂的任务，一起理清。</span></h1>
              <p className="welcome-description">告诉我你想达成的目标。<br className="sm:hidden" />我来拆解任务、梳理路径，陪你逐步推进。</p>
              <div className="suggestions">{suggestions.map((suggestion) => <button key={suggestion.title} className="suggestion-card" onClick={() => { setPrompt(suggestion.prompt); composer.current?.focus(); }}><span className={cn("suggestion-icon", suggestion.color)}><suggestion.icon className="size-[18px]" /></span><span className="block text-[13px] font-medium">{suggestion.title}</span><span className="suggestion-description">{suggestion.description}</span><ArrowUpRight className="suggestion-arrow" /></button>)}</div>
              <div className="welcome-tip"><Clock3 className="size-3.5" />长任务可以慢慢完成，关键节点由你确认。</div>
            </div></div>}

            <div className="composer-area">
              {task && <div className="next-task-note">
                <span className={cn("connection-dot", workspace.connection === "live" && "live")} />
                <span role="status">{task.status === "cancelling" ? "正在停止本轮执行，请稍候…" : task.status === "cancelled" ? "本轮已停止，可输入正确内容继续" : task.status === "failed" ? "本轮执行失败，可修改要求后继续发送" : isTerminal(task.status) ? "本轮执行已结束，可继续发送消息" : workspace.connection === "live" ? "正在接收回答" : workspace.connection === "retrying" ? "正在恢复连接…" : workspace.connection === "connecting" ? "正在连接任务服务…" : "正在同步任务状态"}</span>
                <Button variant="ghost" size="sm" className="ml-auto" onClick={newTask}><Plus />新工作任务</Button>
              </div>}
              {task?.status === "waiting_human" ? (
                task.replyPending ? <p role="status" className="chat-pending">回复已提交，等待继续执行…</p> : task.interrupts.length ? (
                  <div className="chat-reply-area">
                    <InterruptForm
                      key={task.interrupts.map((item) => item.id).join(",")}
                      interrupts={task.interrupts}
                      busy={busy}
                      onSubmit={workspace.resume}
                    />
                  </div>
                ) : <div className="chat-pending">正在读取待回答的问题…<Button variant="ghost" size="sm" onClick={workspace.retry}>重新读取</Button></div>
              ) : <form className="composer" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
                <Textarea
                  ref={composer}
                  aria-label="发送消息"
                  placeholder={task ? "继续提问，或补充当前任务的信息…" : "描述你的工作目标，Agent 会规划步骤并执行…"}
                  className="composer-input"
                  value={prompt}
                  maxLength={32000}
                  onChange={(event) => setPrompt(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault();
                      void submit();
                    }
                  }}
                  disabled={busy || !workspace.canSend}
                />
                <div className="composer-toolbar">
                  <span className="agent-chip"><Sparkles className="size-3.5" />任务规划助手</span>
                  <span className="composer-hint">Enter 发送 · Shift + Enter 换行</span>
                  {(canCancel || task?.status === "cancelling") && <Button type="button" variant="outline" size="sm" aria-label="停止本轮" disabled={busy || task?.status === "cancelling"} onClick={() => void workspace.cancel()}>
                    {task?.status === "cancelling" ? <LoaderCircle className="animate-spin" /> : <Square className="size-3.5" />}{task?.status === "cancelling" ? "正在停止" : "停止本轮"}
                  </Button>}
                  <Button type="submit" size="icon" aria-label="发送消息" className="send-button" disabled={!prompt.trim() || busy || !workspace.ready || !workspace.canSend}>
                    {busy ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}
                  </Button>
                </div>
              </form>}
              {task && task.status !== "waiting_human" && <p className="mt-2 text-center text-[10px] text-muted-foreground">补充信息保留在当前任务中。执行中发送的消息会等待当前轮结束后处理。</p>}
              {task?.status === "cancelling" && <p role="status" className="mt-2 text-center text-xs text-muted-foreground">正在停止当前执行，确认退出后显示已停止。</p>}
              <p className="composer-disclaimer">AI 帮你推进工作，重要信息与执行结果请核实。</p>
            </div>
          </main>

          {inspectorOpen && <>
            <button className="inspector-backdrop" aria-label="关闭任务面板" onClick={() => setInspectorOpen(false)} />
            <aside className="inspector">
              <div className="inspector-heading"><ListChecks className="size-4" /><span>任务面板</span><Button variant="ghost" size="icon" className="ml-auto size-7" aria-label="关闭任务面板" onClick={() => setInspectorOpen(false)}><X /></Button></div>
              <div className="inspector-scroll">{task ? <>
                <div className="inspector-task-name">{panelTitle}</div><StatusBadge status={panelTask?.status ?? task.status} />
                <label className="mt-4 block text-xs text-muted-foreground">执行轮次
                  <select aria-label="查看执行轮次" className="mt-2 w-full rounded-md border bg-background p-2 text-xs" value={historical?.attempt ?? ""} onChange={(event) => setExecutionSelection(event.target.value ? { taskId: task.task_id, attempt: Number(event.target.value) } : null)}>
                    <option value="">当前 · {task.status === "queued" ? "等待开始" : `第 ${task.attempt} 轮`}</option>
                    {task.executions.filter((item) => item.attempt < task.attempt || task.status === "queued" || (task.status === "cancelled" && !currentExecution)).map((item) => <option key={item.attempt} value={item.attempt}>第 {item.attempt} 轮 · {item.title}</option>)}
                  </select>
                </label>
                <Tabs defaultValue="plan" className="mt-6"><TabsList className="w-full"><TabsTrigger className="flex-1" value="plan">任务计划</TabsTrigger><TabsTrigger className="flex-1" value="activity">执行动态</TabsTrigger><TabsTrigger className="flex-1" value="details">任务详情</TabsTrigger></TabsList>
                  <TabsContent value="plan"><TaskPlan task={panelTask ?? task} onRetry={workspace.retry} />
                    {historical ? <div className="mt-5 space-y-3 text-xs">{historical.error && <p role="alert" className="text-red-700">{historical.error}</p>}{historical.output && <><p className="font-medium">本轮保存的结果</p><Markdown>{historical.output}</Markdown></>}</div> : <TaskArtifacts key={task.task_id} artifacts={task.artifacts} />}</TabsContent>
                  <TabsContent value="activity"><div className="timeline">{panelTimeline.length ? panelTimeline.map((item, index) => <div className="timeline-item" key={item.key}><span className={cn("timeline-dot", index === panelTimeline.length - 1 && "current")}>{item.event === "completed" ? <Check className="size-2.5" /> : <Circle className="size-1.5 fill-current" />}</span><div><span className="break-words text-xs font-medium">{item.label}</span><span className="mt-1 block text-[10px] text-muted-foreground">{time(item.time)}</span></div></div>) : <p className="py-5 text-xs leading-6 text-muted-foreground">暂无执行事件。任务开始后，进展会显示在这里。</p>}</div><p className="text-[10px] leading-5 text-muted-foreground">时间为当前浏览器接收事件的时间。</p></TabsContent>
                  <TabsContent value="details"><dl className="task-details"><dt>任务编号</dt><dd className="flex items-start gap-1"><code>{task.task_id}</code><button aria-label="复制任务编号" className="shrink-0 text-muted-foreground" onClick={() => { void navigator.clipboard.writeText(task.task_id).then(() => { setCopyId(true); setTimeout(() => setCopyId(false), 1500); }).catch(() => workspace.setError("复制失败，请手动选择任务编号")); }}>{copyId ? <Check className="size-3.5" /> : <Clipboard className="size-3.5" />}</button></dd><dt>执行助手</dt><dd>任务规划助手</dd><dt>创建时间</dt><dd>{new Date(task.created_at).toLocaleString("zh-CN")}</dd><dt>最后业务更新</dt><dd>{new Date(task.updated_at).toLocaleString("zh-CN")}</dd></dl></TabsContent>
                </Tabs>
                {task.status === "waiting_human" && task.interrupts.length > 0 && <p className="mt-5 rounded-xl border bg-muted/40 p-4 text-xs leading-6">需要你补充的信息已显示在聊天区下方。</p>}
                {task.replyPending && <p className="mt-5 rounded-xl border bg-muted/40 p-4 text-xs leading-6">回复已提交，正在等待 Worker 继续执行。</p>}
                {task.status === "waiting_human" && !task.interrupts.length && !task.replyPending && <p className="mt-5 rounded-xl border bg-muted/40 p-4 text-xs leading-6">正在等待执行事件。若问题未显示，请尝试重新连接。<Button variant="ghost" size="sm" className="mt-2" onClick={workspace.retry}>重新连接</Button></p>}
                {canCancel && !historical && <Button variant="outline" size="sm" className="mt-6 w-full text-muted-foreground" disabled={busy} onClick={() => void workspace.cancel()}>停止本轮执行</Button>}
              </> : <div className="inspector-empty"><span><Workflow className="size-6" /></span><h2>让每一步，都清晰可见</h2><p>任务开始后，你可以在这里查看执行动态、补充信息和确认操作。</p><div><b>01</b>描述你想达成的目标</div><div><b>02</b>Agent 规划并逐步推进</div><div><b>03</b>确认关键事项，收获结果</div></div>}</div>
              <div className="inspector-footer"><ShieldCheck className="size-3.5" />关键操作，由你掌握</div>
            </aside>
          </>}
        </div>
      </div>

      {settingsOpen && <AccountMenu open={settingsOpen} onOpenChange={setSettingsOpen} />}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open && !busy) setDeleteTarget(null); }}>
        <DialogContent>
          <DialogTitle>永久删除会话</DialogTitle>
          <DialogDescription className="mt-2 text-sm leading-6 text-muted-foreground">
            将永久删除“{deleteTarget?.title}”的聊天、执行历史、文件和恢复现场，无法恢复。
          </DialogDescription>
            {workspace.error && <p role="alert" className="mt-4 text-sm text-red-700">{workspace.error}</p>}
            <div className="mt-5 flex justify-end gap-2">
            <Button variant="outline" disabled={busy} onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button disabled={busy} onClick={() => {
              if (!deleteTarget) return;
              const id = deleteTarget.id;
              void workspace.deleteTask(id).then((deleted) => {
                if (deleted) { forgetTask(id); setDeleteTarget(null); }
              });
            }}>{busy ? "正在删除…" : "永久删除"}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent>
          <DialogTitle className="text-lg font-semibold">修改任务名称</DialogTitle>
          <DialogDescription className="mt-2 text-sm text-muted-foreground">名称只用于辨识，不会改变当前会话的记忆。</DialogDescription>
          <form onSubmit={(event) => {
            event.preventDefault();
            void workspace.rename(titleDraft.trim()).then((saved) => { if (saved) setRenameOpen(false); });
          }}>
            <Input className="mt-5" aria-label="任务名称" maxLength={120} value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} />
            <Button type="submit" className="mt-5 w-full" disabled={busy || !titleDraft.trim()}>保存名称</Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
