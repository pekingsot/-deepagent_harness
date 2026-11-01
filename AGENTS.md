# 项目协作约定

- 用户从 Java 转向 Python，使用明确的业务名称和 Service、Repository、DTO、VO 职责命名。
- 中文注释和文档字符串；新增字段、实例属性旁写明用途。
- Interface 是 interface/api、interface/vo 等入站适配；只调用应用用例，不在路由实现领域规则。
- Domain 聚合根放 domain/aggregates，维护实际业务不变量；业务类型与查询投影放 domain/types，不与模型权重的 models 目录混淆。
- 仓储接口放 domain/repositories，实现放 infrastructure/persistence/repositories，两侧同名文件对应，例如 memory_repository.py。
- Application 的具体应用服务直接放 services，类名采用 XxxApplicationService，不为单一实现额外拆接口与 Impl；输入输出放 dto，队列和 Runtime 等外部能力契约放 interfaces。
- Domain 不导入 Application、Infrastructure、Bootstrap、Interface 或数据库、Agent 框架；Application 不导入基础设施实现。
- Harness 已属于 infrastructure/harness，框架图、工具、中间件和 Backend 不作为独立领域层。
- AgentTask 是任务聚合；TaskPlanningAgent 是技术执行者，二者不能混同。
- Domain 的具体领域服务放 domain/services，组织领域规则和仓储调用；Application 协调领域能力、事务、队列与 Runtime，不重复判断业务状态。
- ORM 放 infrastructure/persistence/entities/，与领域聚合、应用 DTO 分开。
- Bootstrap 组装具体依赖、管理生命周期，不能被底层反向导入；业务服务不查找 Container 或 Request。
- Engine、连接池和模型按进程复用，Session 按短操作隔离，不跨并发任务共享。
- 优先使用成熟组件，现有框架抽象不重复包装；尚未接入声明式事务传播，不把普通 begin 或自动提交冒充完整事务传播。
- 不为目录形式预建空类，不为尚未实现的 Service 预建接口与 Impl，不为每张表强行建立聚合。
- 没有用户授权不修改文件；授权重构不重置已有 Git 改动，不做破坏性的真实外部服务验证。
- 名称变化是内部显式变更，不随意加兼容壳；修改时同步更新导入、启动入口、文档和测试。

- Container 只保存共享资源；应用服务通过 bootstrap/wiring.py 的无参 lru_cache 工厂获取，关闭资源时清理工厂缓存。当前联调只启动一个消费者，开发身份必须显式配置且只在 development 环境生效。

## Git 管理约定

- 新建的源码、测试、数据库迁移、配置模板及项目文档，应在完成检查后主动执行 `git add` 纳入 Git 管理，不要留作未跟踪文件。
- 密钥、实际环境配置、下载的模型权重、依赖目录、缓存及临时产物应通过 `.gitignore` 排除，不得使用强制添加绕过忽略规则。
- 默认只添加到暂存区；未经用户要求，不执行 `git commit` 或 `git push`。保留用户已有的暂存安排，不批量暂存与当前工作无关的修改。
