"""soft delete generation tasks

Revision ID: d8c21b64a0f1
Revises: c4e91a27b6d8
Create Date: 2026-09-20 17:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8c21b64a0f1"
down_revision: Union[str, None] = "c4e91a27b6d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("generation_tasks")}
    if "deleted_at" not in columns:
        op.add_column("generation_tasks", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("generation_tasks")}
    if "deleted_at" in columns:
        op.drop_column("generation_tasks", "deleted_at")
