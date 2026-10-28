from langchain_core.tools import tool
from langgraph.types import interrupt


@tool("ask_user")
def ask_user(question:str)->str:
    """当任务缺少必要信息时，向用户提问并等待回答。"""
    if not question.strip():
        raise ValueError("问题不能为空")

    answer = interrupt({
        "type":"user_input",
        "question":question,
    })

    if not isinstance(answer,str) or not answer.strip():
        raise ValueError("用户回答必须非空字符串")

    return answer


