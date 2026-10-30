"""任务提交和查询入口，具体业务交给应用服务。"""

import json
from collections.abc import AsyncIterator
from time import monotonic
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from sse_starlette import EventSourceResponse

from agent_platform.application.dto.agent_task_dto import AgentTaskExecutionResult, ResumeAgentTask
from agent_platform.domain.types.common import ConflictError, NotFoundError
from agent_platform.domain.types.task_message import TaskMessage
from agent_platform.interface.api.dependencies import (
    CurrentPrincipal,
    CurrentTaskApplicationService,
    CurrentTaskEvents,
)
from agent_platform.interface.vo.agent_task_vo import (
    AgentTaskResponse,
    CreateAgentTaskRequest,
    RenameTaskRequest,
    SendTaskMessageRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    request: CreateAgentTaskRequest,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """保存任务后入队，返回编号，由 Worker 异步执行。"""
    task = await service.create(principal, request.to_command())
    return AgentTaskResponse.from_task(task)


@router.get("/{task_id}/execution", response_model=AgentTaskExecutionResult)
async def get_execution(
    task_id: UUID,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskExecutionResult:
    """重新打开页面时读取当前待回答问题或执行结果。"""
    try:
        return await service.get_execution_state(principal, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/resume", response_model=AgentTaskResponse, status_code=202)
async def resume_task(
    task_id: UUID,
    command: ResumeAgentTask,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """人工回复入队，202 表示已接收，执行结果通过 SSE 或查询接口获取。"""
    try:
        task = await service.request_resume(principal, task_id, command)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AgentTaskResponse.from_task(task)


@router.post("/{task_id}/cancel", response_model=AgentTaskResponse)
async def cancel_task(
    task_id: UUID,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """取消排队或等待人工回复的任务；执行中的任务暂不支持强制停止。"""
    try:
        task = await service.cancel(principal, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AgentTaskResponse.from_task(task)


@router.get("/{task_id}/events")
async def task_events(
    task_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
    events: CurrentTaskEvents,
    after: Annotated[str, Query(pattern=r"^\d+-\d+$", max_length=64)] = "0-0",
    last_event_id: Annotated[
        str | None, Header(alias="Last-Event-ID", pattern=r"^\d+-\d+$", max_length=64)
    ] = None,
) -> EventSourceResponse:
    """校验任务归属并读取事件，服务器关闭时主动结束事件流。"""
    try:
        task = await service.get(principal, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc

    shutdown_event = anyio.Event()  # SSE 组件收到服务器关闭信号时设置

    async def stream() -> AsyncIterator[dict[str, str]]:
        cursor = last_event_id or after
        last_status_check = monotonic()  # 空闲时每隔一段时间查询业务状态
        # 客户端断开由 SSE 组件检测，避免两个协程同时读取断连消息。
        while not shutdown_event.is_set():
            batch = await events.read(task.context, cursor, block_ms=1000)
            if shutdown_event.is_set():
                break

            if batch:
                for item in batch:
                    if shutdown_event.is_set():
                        return

                    yield {
                        "id": item.id,
                        "event": item.event,
                        "data": json.dumps(item.data, ensure_ascii=False),
                    }
                    cursor = item.id
            else:
                # 一轮完成后仍保持连接，后续消息继续使用同一个会话。
                if monotonic() - last_status_check >= 15:
                    current = await service.get(principal, task_id)
                    if shutdown_event.is_set():
                        break
                    last_status_check = monotonic()
                    data = json.dumps(
                        {
                            "attempt": current.attempt,
                            "status": current.status.value,
                            "output": current.result,
                            "error": current.error,
                        },
                        ensure_ascii=False,
                    )
                    # 状态通知不是持久化事件，不伪造 Redis 游标。
                    yield {"event": "state", "data": data}

    return EventSourceResponse(
        stream(),
        ping=15,  # 心跳交给 SSE 组件维护
        send_timeout=5,  # 客户端长期不读取时，停止阻塞发送
        shutdown_event=shutdown_event,
        shutdown_grace_period=3,  # 小于 Uvicorn 的关闭超时，优先让生成器自行退出
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{task_id}", response_model=AgentTaskResponse)
async def get_task(
    task_id: UUID,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """查询本人任务，未知编号和无权限均返回 404。"""
    try:
        task = await service.get(principal, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc
    return AgentTaskResponse.from_task(task)


@router.get("", response_model=list[AgentTaskResponse])
async def list_tasks(
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> list[AgentTaskResponse]:
    """读取当前身份最近的五十条会话。"""
    tasks = await service.list_recent(principal)
    return [AgentTaskResponse.from_task(task) for task in tasks]


@router.get("/{task_id}/messages", response_model=list[TaskMessage])
async def list_messages(
    task_id: UUID,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> list[TaskMessage]:
    """读取会话消息，权限由领域服务及仓储共同约束。"""
    try:
        return await service.messages(principal, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{task_id}/messages", response_model=AgentTaskResponse, status_code=202)
async def send_message(
    task_id: UUID,
    request: SendTaskMessageRequest,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """追加同一会话的消息，执行中收到的补充先入库排队。"""
    try:
        task = await service.send_message(principal, task_id, request.id, request.content)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentTaskResponse.from_task(task)


@router.patch("/{task_id}", response_model=AgentTaskResponse)
async def rename_task(
    task_id: UUID,
    request: RenameTaskRequest,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """修改会话名称，不新建任务或执行线程。"""
    try:
        task = await service.rename(principal, task_id, request.title)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentTaskResponse.from_task(task)
