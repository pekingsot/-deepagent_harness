"""本地 BGE 中文向量模型。"""
from functools import lru_cache
from pathlib import Path
from threading import Lock

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from agent_platform.paths import PROJECT_ROOT


class BgeEmbeddings(Embeddings):
    """提供记忆内容和检索问题的向量编码。"""

    model_name = "BAAI/bge-large-zh-v1.5"

    def __init__(
        self,
        *,
        model_path: Path = (
            PROJECT_ROOT / "models" / "BAAI" / "bge-large-zh-v1.5"
        ),
        device: str = "cpu",
    ) -> None:
        if not model_path.is_dir():
            raise FileNotFoundError(f"向量模型目录不存在：{model_path}")

        self._model = SentenceTransformer(
            str(model_path),
            device=device,
            local_files_only=True,
        )
        self._lock = Lock()

        dimension = self._model.get_embedding_dimension()
        if dimension != 1024:
            raise ValueError(
                f"向量模型必须输出 1024 维，实际为：{dimension}"
            )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """为待保存的记忆内容生成向量。"""
        if not texts:
            return []

        if any(not text.strip() for text in texts):
            raise ValueError("待编码的内容不能为空白")

        # 同一个模型实例串行推理，避免并发堆积推理内存
        with self._lock:
            vectors = self._model.encode(
                texts,
                batch_size=8,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        """为检索问题生成向量。"""
        if not text.strip():
            raise ValueError("检索问题不能为空白")

        instruction = "为这个句子生成表示以用于检索相关文章："
        return self.embed_documents([instruction + text])[0]


@lru_cache(maxsize=1)
def get_embeddings():
    return BgeEmbeddings()
