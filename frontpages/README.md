# Agent Workspace

Next.js 16.4.3 App Router + TypeScript + React + Tailwind CSS 4 + shadcn/ui。

## 当前会话行为

- 一条会话对应一个 AgentTask，同一会话中的 task_id 和 checkpoint thread_id 保持不变。
- 首次发送创建会话，后续发送写入同一会话的消息表。
- 左侧从后端读取最近五十条会话，中间从后端读取消息历史，不再把 localStorage 当历史数据库。
- 标题可修改，不会改变上下文。
- 执行中的补充消息先入库，当前轮结束后串行处理；不是强行打断模型请求。
- 人工中断在聊天区填写，使用原中断编号恢复同一轮执行。
- succeeded 表示本轮完成，可以继续发送；失败、取消的会话暂不支持直接重试恢复。
- SSE 一轮完成后仍保持连接，通过 attempt 区分执行轮次。

## 启动

先停止旧 API 和 Worker。在项目根目录手动更新数据库：

```powershell
uv run alembic upgrade head
uv run harness-api
```

另一个终端：

```powershell
cd frontpages
npm.cmd install
npm.cmd run dev
```

依赖已经安装时无需重复 install。访问 http://127.0.0.1:3000。

`frontpages/.env.local` 中配置 `HARNESS_API_URL=http://127.0.0.1:8000`，修改后重启前端。令牌在页面连接设置中填写，必须与后端的 HARNESS_DEVELOPMENT_TOKEN 一致，不能填写模型 API Key。

后端需配置开发身份、数据库、Redis、checkpoint、模型及 Worker。HARNESS_WORKER_ENABLED=true、HARNESS_WORKER_CONCURRENCY=1 时 API 同时运行一个消费者；独立部署则关闭 API 内置消费者，单独运行 harness-worker。先只使用一个消费者。

连接检查只确认 /health 可达，不代表模型、认证和队列均已验证。

## 目录

- src/app/page.tsx：页面入口。
- src/app/api/backend/[...path]/route.ts：同源 API 转发，包含 SSE，不需要给 FastAPI 增加 CORS。
- src/components/workspace/workspace.tsx：导航、聊天输入和任务详情。
- src/components/workspace/conversation-thread.tsx：多条消息和当前轮文本展示。
- src/components/workspace/interrupt-form.tsx：人工输入和工具审批。
- src/components/ui：shadcn/ui 控件。
- src/hooks/use-task-workspace.ts：服务端历史、消息提交和事件生命周期。
- src/lib/task-api.ts：请求及 SSE 分段解析。
- src/lib/task-types.ts：接口数据类型。

## 数据与限制

访问令牌仅保存在当前标签页的 sessionStorage。会话消息保存在后端 PostgreSQL；模型上下文和中断现场保存在 checkpoint。长期偏好记忆是另一项能力，本次没有新增长期记忆读写。

消息 pending 表示已接收，processing 表示已交给执行器，applied 表示本轮正常完成；这不保证模型遵循了每一项要求。消息正文、模型回答及历史资料仍需按企业权限与资料使用规范管理。

SSE 使用 fetch 携带令牌并解析 UTF-8、半行和半条事件，按游标重连，最多自动重试五次。消息顺序以服务端 position 为准，时间线时间是浏览器接收事件的时间。

消息列表暂不分页，模型上下文暂未压缩。队列 pending 接管、数据库与 Redis 原子一致性、进程崩溃后自动恢复、无限历史和多消费者部署均未在本次交付中完成。

本轮未运行测试、构建、真实模型请求或数据库迁移。代码修改和实际联调通过不是同一件事。

本轮具体改动见 [修改前后对照](docs/conversation-changes-20261030.md)。
