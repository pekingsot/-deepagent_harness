"""记忆用例所需的异步向量能力，基础设施以结构类型实现。"""

from typing import Protocol


class TextEmbeddings(Protocol):
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def aembed_query(self, text: str) -> list[float]: ...
