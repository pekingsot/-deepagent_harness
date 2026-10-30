"""验证任务聚合根的业务规则，不依赖数据库和 Agent 框架。"""

import pytest
from pydantic import ValidationError

from agent_platform.domain.aggregates.agent_task import AgentTask, AgentTaskStatus
from agent_platform.domain.types.common import ConflictError, TaskContext


def make_task() -> AgentTask:
    return AgentTask(
        context=TaskContext(tenant_id=1, user_id=2, project_id="test"),
        prompt="制定游戏版本迭代计划",
    )


def test_lifecycle_preserves_identity_and_resume_does_not_restart() -> None:
    original = make_task()
    running = original.start()
    waiting = running.wait_for_user()
    resumed = waiting.resume()
    completed = resumed.complete("计划已生成")

    assert original.status == AgentTaskStatus.QUEUED
    assert original.attempt == 0
    assert completed.status == AgentTaskStatus.SUCCEEDED
    assert completed.result == "计划已生成"
    assert completed.attempt == 1
    assert all(task.id == original.id for task in (running, waiting, resumed, completed))
    assert completed.created_at == original.created_at
    assert completed.updated_at >= original.updated_at
    assert AgentTask.model_validate_json(completed.model_dump_json()) == completed


@pytest.mark.parametrize("operation", ["start", "resume", "cancel", "wait_for_user"])
def test_completed_task_cannot_be_reactivated(operation: str) -> None:
    task = make_task().start().complete("完成")
    with pytest.raises(ConflictError):
        getattr(task, operation)()


def test_waiting_task_requires_resume_before_completion() -> None:
    task = make_task().start().wait_for_user()
    with pytest.raises(ConflictError):
        task.complete("未经恢复的结果")


def test_cancelled_task_cannot_start() -> None:
    task = make_task().cancel()
    with pytest.raises(ConflictError):
        task.start()


def test_failure_requires_reason_and_cannot_restart() -> None:
    task = make_task().start()
    with pytest.raises(ValueError):
        task.fail("  ")
    failed = task.fail("模型服务不可用")
    assert failed.status == AgentTaskStatus.FAILED
    assert failed.error == "模型服务不可用"
    with pytest.raises(ConflictError):
        failed.start()


def test_rehydration_rejects_inconsistent_state() -> None:
    data = make_task().model_dump()
    data.update(status=AgentTaskStatus.FAILED, error=None)
    with pytest.raises(ValidationError):
        AgentTask.model_validate(data)


def test_task_cannot_be_mutated_directly() -> None:
    task = make_task()
    with pytest.raises(ValidationError):
        task.status = AgentTaskStatus.SUCCEEDED


def test_blank_prompt_and_blank_result_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentTask(context=make_task().context, prompt="  ")
    with pytest.raises(ValueError):
        make_task().start().complete("  ")
