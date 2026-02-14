"""add api key name

Revision ID: 9c2d6a0a3f2b
Revises: 6b3457f1ab86
Create Date: 2026-02-11 11:32:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9c2d6a0a3f2b"
down_revision = "6b3457f1ab86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("name", sa.String(length=200), nullable=True))
    op.execute(
        "UPDATE api_keys SET name = 'key-' || substring(id::text, 1, 8) WHERE name IS NULL"
    )
    op.alter_column("api_keys", "name", nullable=False)
    op.create_index(
        "uq_api_keys_tenant_name", "api_keys", ["tenant_id", "name"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_api_keys_tenant_name", table_name="api_keys")
    op.drop_column("api_keys", "name")
