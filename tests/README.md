# 测试约定

所有 Python 测试统一放在项目根目录 `tests/`，使用 `test_*.py` 命名，通过 pytest 执行。`scripts/` 仅保留初始化、运维等工具脚本。

| 目录 | 内容 | 执行条件 |
| --- | --- | --- |
| `tests/unit/` | 领域规则、应用服务、事务边界、架构依赖、使用模拟模型的 Agent 行为 | 离线执行，不连接真实服务，不读取真实模型权重 |
| `tests/integration/` | PostgreSQL、Redis、本地 BGE、OpenSandbox 等真实依赖 | 默认跳过，准备独立测试资源后显式启用 |

在项目根目录运行：

```powershell
uv run pytest tests/unit -q
uv run pytest tests -q
```

第二条命令也会收集集成测试，但未启用的场景会显示 `skipped`。单元测试的网络隔离和遥测禁用配置仅作用于 `tests/unit/`。

## 显式启用集成测试

每种真实依赖有独立开关，可按需选择，避免验证沙箱时顺带连接业务数据库。

| 开关 | 验证内容 | 配置 |
| --- | --- | --- |
| `HARNESS_RUN_DATABASE_INTEGRATION=1` | PostgreSQL 连接，执行只读 `SELECT 1` | 项目 `HARNESS_DATABASE_URL` 配置，指向测试库 |
| `HARNESS_RUN_EMBEDDINGS_INTEGRATION=1` | 本地 BGE 文档、查询向量的维度及归一化 | 项目 `models/` 下已有本地模型，不自动下载 |
| `HARNESS_RUN_SANDBOX_INTEGRATION=1` | 创建沙箱、执行命令、文件写入和读取，最后销毁沙箱 | `OPENSANDBOX_DOMAIN`、`OPENSANDBOX_API_KEY`；可选 `OPENSANDBOX_TEST_IMAGE` |
| `HARNESS_RUN_PIPELINE_INTEGRATION=1` | 原有任务链路和事件隔离验证 | 测试 PostgreSQL、`REDIS_URL`，数据库已完成迁移 |

例如，只执行沙箱测试：

```powershell
$env:HARNESS_RUN_SANDBOX_INTEGRATION = "1"
$env:OPENSANDBOX_DOMAIN = "测试服务器IP:端口"
$env:OPENSANDBOX_API_KEY = "测试环境密钥"
uv run pytest tests/integration/test_external_services.py -k sandbox -q
Remove-Item Env:HARNESS_RUN_SANDBOX_INTEGRATION
Remove-Item Env:OPENSANDBOX_API_KEY
```

测试代码不内嵌服务器地址和密钥。沙箱测试会创建真实容器；其他真实资源测试应使用专门的测试环境。

原 `demo.py`、`demo2.py`、`demo_ask_user.py` 和两份 Checkpoint 演示中的有效交互场景，由离线 Agent、Runtime 和中间件测试覆盖，不再保留需要人工输入的独立演示入口。原数据库、向量和沙箱演示已整理为 `test_external_services.py`，结构检查已并入 `test_architecture.py`。
