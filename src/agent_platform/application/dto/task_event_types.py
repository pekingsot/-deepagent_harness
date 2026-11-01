"""无需持久化业务状态的执行中回调事件。"""

STREAMING_EVENTS = frozenset(
    {
        "text_delta",
        "plan_updated",
        "execution_titled",
        "tool_requested",
        "tool_returned",
        "tool_failed",
    }
)
