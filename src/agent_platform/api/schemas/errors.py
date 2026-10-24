from agent_platform.domain.common.models import StrictModel


class ErrorResponse(StrictModel):
    code: str
    message: str
