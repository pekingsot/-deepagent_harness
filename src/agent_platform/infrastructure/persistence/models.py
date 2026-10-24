"""Use SQLAlchemy's current typed declarative API for future ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
