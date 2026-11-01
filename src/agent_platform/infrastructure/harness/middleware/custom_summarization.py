from deepagents.backends import BackendProtocol
from langchain.agents.middleware.summarization import SummarizationMiddleware




def get_SummarizationMiddleware(model,backend:BackendProtocol | None = None):
    """"""
    # 与 Agent 使用同一个 Backend，保存被压缩的原始历史。


