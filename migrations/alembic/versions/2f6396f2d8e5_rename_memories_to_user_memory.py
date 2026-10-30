"""rename_memories_to_user_memory

Revision ID: 2f6396f2d8e5
Revises: 538635ba281f
Create Date: 2026-10-29 00:05:42.834742

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f6396f2d8e5'
down_revision: Union[str, Sequence[str], None] = '538635ba281f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table("memories", "user_memory")


def downgrade() -> None:
    """Downgrade schema."""
    op.rename_table("user_memory", "memories")
