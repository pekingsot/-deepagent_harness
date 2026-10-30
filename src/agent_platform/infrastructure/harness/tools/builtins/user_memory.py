from typing import Annotated

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool
from pydantic import Field, JsonValue

from agent_platform.application.services.user_memory_application_service import (
    UserMemoryApplicationService,
)
from agent_platform.domain.types.common import TaskContext


def create_user_memory_tools(
    service: UserMemoryApplicationService,
) -> list[BaseTool]:
    """注入记忆服务，工具内部不创建数据库连接或向量模型。"""

    @tool
    async def save_user_memory(
        content: Annotated[str, Field(strict=True, min_length=1, max_length=8000)],
        runtime: ToolRuntime[TaskContext],
    ) -> dict[str, JsonValue]:
        """用户明确要求记住长期偏好或事实时使用，每次保存一条独立记忆。"""
        if not isinstance(runtime.context, TaskContext):
            raise RuntimeError("记忆工具缺少可信的任务上下文")

        memory_id = await service.save(
            principal=runtime.context,
            content=content,
        )

        return {
            "saved": True,
            "memory_id": memory_id,
        }

    @tool
    async def search_user_memory(
        query: Annotated[str, Field(strict=True, min_length=1, max_length=2000)],
        runtime: ToolRuntime[TaskContext],
        limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 5,
    ) -> list[dict[str, JsonValue]]:
        """检索当前用户在其他会话中保存的偏好或事实，查询应描述需要的信息。"""
        if not isinstance(runtime.context, TaskContext):
            raise RuntimeError("记忆工具缺少可信的任务上下文")

        matches = await service.search(
            principal=runtime.context,
            query=query,
            limit=limit,
        )

        return [
            {
                "id": item.id,
                "content": item.content,
                "similarity": item.similarity,
            }
            for item in matches
        ]

    @tool
    async def delete_user_memory(
        memory_id: Annotated[
            int,
            Field(strict=True, gt=0, le=9223372036854775807),
        ],
        runtime: ToolRuntime[TaskContext],
    ) -> dict[str, JsonValue]:
        """用户明确要求忘记某条记忆时，使用检索结果中的真实编号删除。"""
        if not isinstance(runtime.context, TaskContext):
            raise RuntimeError("记忆工具缺少可信的任务上下文")

        deleted = await service.delete(
            principal=runtime.context,
            memory_id=memory_id,
        )

        return {
            "memory_id": memory_id,
            "deleted": deleted,
        }

    @tool
    async def update_user_memory(
        memory_id: Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)],
        content: Annotated[str, Field(strict=True, min_length=1, max_length=8000)],
        runtime: ToolRuntime[TaskContext],
    ) -> dict[str, JsonValue]:
        """用户要求纠正已有记忆时，使用真实编号替换原条目的完整正文。"""
        if not isinstance(runtime.context, TaskContext):
            raise RuntimeError("记忆工具缺少可信的任务上下文")
        updated = await service.update(
            principal=runtime.context,
            memory_id=memory_id,
            content=content,
        )
        return {"memory_id": memory_id, "updated": updated}

    @tool
    async def list_user_memories(
        runtime: ToolRuntime[TaskContext],
        cursor: Annotated[int | None, Field(strict=True, gt=0, le=9223372036854775807)] = None,
        limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 20,
    ) -> dict[str, JsonValue]:
        """分页列出用户记忆。首个请求不传游标，后续使用返回的 next_cursor，不能用语义检索替代完整列表。"""
        if not isinstance(runtime.context, TaskContext):
            raise RuntimeError("记忆工具缺少可信的任务上下文")
        page = await service.list_recent(
            principal=runtime.context,
            cursor=cursor,
            limit=limit,
        )
        return {
            "items": [item.model_dump(mode="json") for item in page.items],
            "next_cursor": page.next_cursor,
            "has_more": page.next_cursor is not None,
        }

    return [
        save_user_memory,
        search_user_memory,
        list_user_memories,
        update_user_memory,
        delete_user_memory,
    ]
