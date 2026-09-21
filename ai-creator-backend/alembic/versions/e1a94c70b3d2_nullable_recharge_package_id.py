"""nullable recharge package_id for custom amounts

Revision ID: e1a94c70b3d2
Revises: d8c21b64a0f1
Create Date: 2026-09-20 17:52:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1a94c70b3d2"
down_revision: Union[str, None] = "d8c21b64a0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("recharge_orders")}
    package = columns.get("package_id")
    if package and not package.get("nullable"):
        op.alter_column("recharge_orders", "package_id", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("recharge_orders")}
    package = columns.get("package_id")
    if package and package.get("nullable"):
        op.alter_column("recharge_orders", "package_id", existing_type=sa.String(length=32), nullable=False)
