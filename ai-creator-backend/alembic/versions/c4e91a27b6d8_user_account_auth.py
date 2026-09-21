"""user account auth

Revision ID: c4e91a27b6d8
Revises: 812f786ece0f
Create Date: 2026-09-20 16:50:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e91a27b6d8"
down_revision: Union[str, None] = "812f786ece0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "username" not in columns:
        op.add_column("users", sa.Column("username", sa.String(length=80), nullable=True))
    if "password_hash" not in columns:
        op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    if "ix_users_username" not in indexes:
        op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_username" in indexes:
        op.drop_index("ix_users_username", table_name="users")
    if "password_hash" in columns:
        op.drop_column("users", "password_hash")
    if "username" in columns:
        op.drop_column("users", "username")
