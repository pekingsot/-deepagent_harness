import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.language_models import BaseChatModel
from openai import APIConnectionError, InternalServerError, RateLimitError

logger = logging.getLogger(__name__)

FALLBACK_ERRORS = (
    APIConnectionError,
    RateLimitError,
    InternalServerError,
)


class CustomModelFallbackMiddleware(AgentMiddleware):
    def __init__(self, fallback_model: BaseChatModel):
        if not isinstance(fallback_model, BaseChatModel):
            raise TypeError("fallback_model must be an instance of BaseChatModel")
        self.fallback_model = fallback_model

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        try:
            return handler(request)
        except FALLBACK_ERRORS as e:
            logger.warning("主模型失败，切换备用模型：%s", type(e).__name__)
        fallback_request = request.override(model=self.fallback_model)
        return handler(fallback_request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable],
    ) -> ModelResponse:
        try:
            return await handler(request)
        except FALLBACK_ERRORS as e:
            logger.warning("主模型失败，切换备用模型：%s", type(e).__name__)
        fallback_request = request.override(model=self.fallback_model)
        return await handler(fallback_request)
