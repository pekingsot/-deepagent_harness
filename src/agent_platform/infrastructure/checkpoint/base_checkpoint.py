from abc import ABC

from langgraph.checkpoint.base import BaseCheckpointSaver




class BaseCustomCheckPoint(BaseCheckpointSaver,ABC):
    """包装了一层基础BaseCheckPointSaver防止包更新带来的一些问题"""