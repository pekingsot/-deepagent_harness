"""验证本地向量模型能否正常工作。"""

from agent_platform.infrastructure.embeddings.bge import BgeEmbeddings


def main() -> None:
    print("正在加载本地 BGE 模型……", flush=True)

    embeddings = BgeEmbeddings()

    print("模型加载完成，正在生成向量……", flush=True)

    memories = [
        "用户希望代码注释使用中文。",
        "用户喜欢吃苹果。",
    ]

    vectors = embeddings.embed_documents(memories)
    query_vector = embeddings.embed_query("用户希望代码注释使用什么语言？")

    print(f"记忆向量维度：{len(vectors[0])}")
    print(f"问题向量维度：{len(query_vector)}")

    for content, vector in zip(memories, vectors, strict=True):
        score = sum(
            left * right
            for left, right in zip(query_vector, vector, strict=True)
        )
        print(f"相似度：{score:.4f}，记忆：{content}")


if __name__ == "__main__":
    main()