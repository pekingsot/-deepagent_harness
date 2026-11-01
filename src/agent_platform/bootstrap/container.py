"""保存进程共享资源；业务服务不依赖此容器。"""

from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.interfaces.task_execution_guard import TaskExecutionGuard
from agent_platform.bootstrap.settings import Settings
from agent_platform.infrastructure.persistence.database import Database


class Container:
    def __init__(
        self,
        *,
        settings: Settings,
        runtime: AgentTaskRuntime,
        database: Database,
        execution_guard: TaskExecutionGuard,
    ) -> None:
        self.execution_guard = execution_guard  # 执行互斥资源
        self.settings = settings  # 应用启动配置
        self.runtime = runtime  # 当前进程复用的 Agent 执行入口
        self.database = database  # 数据库引擎与会话工厂，不保存共享 Session
