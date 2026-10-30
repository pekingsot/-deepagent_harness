# 任务提交、执行与流式返回

代码已接入以下流程，本轮未运行测试或连接外部服务验证。

1. FastAPI 接收输入，使用服务端认证身份创建任务。
2. Application 调用 Domain 保存任务，数据库提交后投递 Redis Streams 队列。
3. Worker 领取消息，通过 Application 调用 Runtime 执行 Agent。
4. Runtime 把模型消息转换为文本回调，Application 将文本、进度和人工问题写入独立事件 Stream。
5. 前端订阅 SSE，按事件编号读取。最终结果保存在 PostgreSQL，执行现场由 checkpoint 保存。
6. 人工回复通过 HTTP 入队，由 Worker 读取同一任务的 checkpoint 继续执行。

## 配置与启动

保留现有数据库、Redis、模型及 checkpoint 配置，在根目录 `.env` 设置：

```dotenv
HARNESS_ENVIRONMENT=development
HARNESS_WORKER_ENABLED=true
HARNESS_WORKER_CONCURRENCY=1
HARNESS_DEVELOPMENT_TOKEN=替换成自己生成的随机访问令牌
HARNESS_DEVELOPMENT_PRINCIPAL='{"tenant_id":1,"user_id":1,"project_id":"local"}'
```

开发身份只在 development 环境生效。前端不能指定租户、用户或项目身份；正式认证适配器尚未接入。真实令牌不要提交到 Git。

```powershell
uv run harness-api
```

该模式同时启动 API 和一个消费者。独立部署时，API 设置 `HARNESS_WORKER_ENABLED=false`，另一个终端执行 `uv run harness-worker`。两者使用相同业务数据库、Redis 队列配置、模型及 checkpoint 配置。当前只运行一个消费者，尚未实现多消费者抢占保护。

## HTTP 接口

所有接口携带 `Authorization: Bearer 自己配置的令牌`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/tasks` | 创建并入队，返回 202 和 task_id |
| GET | `/api/v1/tasks/{task_id}` | 查询业务状态、最终结果或失败信息 |
| GET | `/api/v1/tasks/{task_id}/events` | SSE：进度、模型文本和人工问题 |
| GET | `/api/v1/tasks/{task_id}/execution` | 从 checkpoint 读取人工问题或最终回答 |
| POST | `/api/v1/tasks/{task_id}/resume` | 人工回复入队，返回 202 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消排队中或等待人工回复的任务 |

创建请求：

```json
{
  "agent": "task_planning",
  "prompt": "请制定一个游戏版本研发计划。缺少必要信息时，先使用 ask_user 询问我。"
}
```

任务状态：queued、running、waiting_human、succeeded、failed、cancelled。执行中暂不支持强制停止。

## SSE 读取与断线重连

```powershell
curl.exe -N -H "Authorization: Bearer 自己的令牌" "http://127.0.0.1:8000/api/v1/tasks/替换为任务编号/events"
```

文本事件示例：

```text
id: 1790000000000-0
event: text_delta
data: {"text":"首先分析版本目标"}

```

| 事件 | 含义 |
| --- | --- |
| queued | 已保存任务，准备投递队列 |
| started | Worker 已开始处理 |
| text_delta | 模型文本片段，可能跨多个模型轮次 |
| waiting_human | 等待人工回复，data.interrupts 包含中断编号和问题 |
| resuming | Worker 开始处理人工回复 |
| resume_rejected | 人工回复不符合当前中断要求 |
| resume_error | 恢复执行异常，需要查询任务及 checkpoint 状态 |
| completed | 已完成，data.output 为最终回答 |
| failed | 执行失败 |
| cancelled | 已取消 |

completed、failed、cancelled 会结束连接；waiting_human 会保留连接，等待人工回复。文本片段用于展示过程，最终回答以 completed.output 或任务查询的 result 为准。

客户端记录最近的 id，重连携带 `Last-Event-ID: 上次编号`，或者使用 `?after=上次编号`，Header 优先。默认 `0-0` 从头读取。每个连接通过 XREAD 独立读取，不使用消费组，不会抢走 Worker 的队列消息。

浏览器原生 EventSource 无法直接设置 Authorization Header，当前认证方式请使用 fetch 流式读取。网络读取可能拆分一条 SSE 事件，前端需要按 SSE 格式拼接解析。

任务事件暂不裁剪、不设置过期时间。仅应用进程重启不会清理 Redis 事件，原游标仍可读取；任务消费进程中断后的 pending 接管尚未实现。

## 人工回复

从 waiting_human 事件或 execution 接口取出真实中断编号，提交到 resume 接口：

```json
{
  "answers": {
    "替换为实际中断编号": {
      "type": "user_input",
      "answer": "目标是两周内上线一个新地图版本。"
    }
  }
}
```

工具审批使用 `{"type":"tool_approval","approved":true}`。需要一次对应当前全部待处理中断，Worker 中的 Runtime 校验编号与回复类型。HTTP 202 仅表示已入队，不代表 Agent 已恢复完成。

## 代码位置

| 职责 | 文件 |
| --- | --- |
| HTTP 提交、查询、恢复与 SSE | `src/agent_platform/interface/api/routes/v1/agent_tasks.py` |
| 应用协调和事件发布 | `src/agent_platform/application/services/agent_task_application_service.py` |
| 领域规则与状态变化 | `src/agent_platform/domain/services/agent_task_domain_service.py`、`domain/aggregates/agent_task.py` |
| 队列消费 | `src/agent_platform/workers/agent_task_worker.py` |
| Redis 任务队列 | `src/agent_platform/infrastructure/messaging/redis_job_queue.py` |
| Redis 执行事件 | `src/agent_platform/infrastructure/messaging/redis_task_events.py` |
| DeepAgents 文本转换与 checkpoint 恢复 | `src/agent_platform/infrastructure/harness/runtime/deepagents_task_runtime.py` |
| 无参缓存工厂与具体实现装配 | `src/agent_platform/bootstrap/wiring.py` |

事务只包围短小的数据库读写，执行模型和等待 SSE 时不持有业务数据库事务。事件写入故障会记录日志，不将成功任务改成失败；最终状态仍可查询，SSE 空闲时定期读取终态兜底，丢失的文本片段不会自动补写。

数据库与 Redis 投递的原子一致性、pending 消息接管、重复执行保护、并发人工回复控制、事件清理策略尚未实现，属于下一阶段可靠性工作。