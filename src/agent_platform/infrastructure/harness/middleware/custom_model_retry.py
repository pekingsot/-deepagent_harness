from langchain.agents.middleware import ModelRetryMiddleware
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)


class CustomModelRetryMiddleware(ModelRetryMiddleware):
    def __init__(self):
        super().__init__(
            max_retries=2,
            retry_on=(
                APIConnectionError,
                APITimeoutError,
                RateLimitError,
                InternalServerError,
            ),
            on_failure="error",
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=10.0,
            jitter=True,
        )
