"""验证数据库轮次快照在仓储边界恢复严格领域类型，无需真实数据库。"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.task_execution import TaskExecutionStep
from agent_platform.infrastructure.persistence.entities.agent_task_executions import (
    AgentTaskExecutionRecord,
)
from agent_platform.infrastructure.persistence.repositories.agent_task_repository import (
    PostgresAgentTaskRepository,
)


class TestTaskExecutionRepository:
    @pytest.mark.parametrize("status", list(AgentTaskStatus))
    @pytest.mark.parametrize("has_steps", [False, True])
    def test_reads_database_strings_and_json_lists(self, status, has_steps):
        import asyncio

        now = datetime.now(UTC)
        task_id = uuid4()
        record = AgentTaskExecutionRecord(
            task_id=task_id,
            attempt=12,
            title="整理报告",
            status=status.value,
            todos=[{"content": "收集资料", "status": "completed"}] if has_steps else [],
            output=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
        session = AsyncMock()
        session.scalars.return_value = [record]
        principal = Principal(tenant_id=2, user_id=1, project_id="default")
        with patch(
            "agent_platform.infrastructure.persistence.repositories.agent_task_repository.current_session",
            return_value=session,
        ):
            records = asyncio.run(PostgresAgentTaskRepository().executions(principal, task_id))

        assert records[0].status is status
        assert isinstance(records[0].todos, tuple)
        assert records[0].created_at == now
        if has_steps:
            assert records[0].todos == (
                TaskExecutionStep(content="收集资料", status="completed"),
            )
        else:
            assert records[0].todos == ()

    def test_domain_validation_stays_strict(self):
        from agent_platform.domain.types.task_execution import TaskExecution

        with pytest.raises(ValidationError):
            TaskExecution.model_validate(
                {"attempt": 12, "title": "整理报告", "status": "running", "todos": []}
            )
