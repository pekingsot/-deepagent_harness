from agent_platform.domain.types.common import StrictModel


class ErrorResponse(StrictModel):
    code: str
    message: str
