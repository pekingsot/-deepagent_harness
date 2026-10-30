# 会话改造：当前实施状态

此前需要手动复制的后端改法，已在本轮授权下合入 Python 源码。不要再把旧文档的整段代码覆盖到当前文件。

请阅读 [本轮逐文件修改前后对照](conversation-changes-20261030.md)，其中标注了当前文件和行号、旧代码和新代码，不使用影响复制的 diff 加减号。

## 你仍需手动执行

先停止 API 与 Worker，然后在项目根目录执行：

```powershell
uv run alembic upgrade head
uv run harness-api
```

新迁移为 migrations/alembic/versions/7e42ab9013cd_add_conversation_title.py，接在现有消息表迁移 622b123e76fc 后面。迁移增加 title，并尽量从旧表回填首条输入和最终回答；旧表没有保留的中间消息无法凭空恢复。

本轮没有执行数据库迁移或测试。旧 running/queued 任务涉及队列故障恢复，不能仅靠更新表结构恢复；请优先处理好旧的执行，再做迁移。

## 当前接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /api/v1/tasks | 新建会话及首条消息 |
| GET | /api/v1/tasks | 最近五十条会话 |
| GET | /api/v1/tasks/{id} | 当前会话摘要与轮次 |
| GET | /api/v1/tasks/{id}/messages | 会话消息历史 |
| POST | /api/v1/tasks/{id}/messages | 向同一会话追加消息 |
| PATCH | /api/v1/tasks/{id} | 修改 title |
| GET | /api/v1/tasks/{id}/events | 跨多个轮次的 SSE |
| GET | /api/v1/tasks/{id}/execution | 人工中断及 checkpoint 状态 |
| POST | /api/v1/tasks/{id}/resume | 提交人工回复 |
| POST | /api/v1/tasks/{id}/cancel | 取消排队或等待人工的会话 |

追加消息正文是 {"id":"客户端生成的 UUID","content":"补充内容"}。同一消息编号对应相同正文时不重复插入，不同正文会拒绝。

执行中补充的信息在下一轮读取，不修改已经发出的模型调用。所有数据库行锁仅用于短事务，执行模型时不持有这些锁。
