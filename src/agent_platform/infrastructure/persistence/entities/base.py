from sqlalchemy.orm import DeclarativeBase


class BaseTable(DeclarativeBase):
    """所有orm模型共用的基类"""
