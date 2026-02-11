"""admin audit log and key metadata

Revision ID: 3fd9b3a6f6c1
Revises: 9c2d6a0a3f2b
Create Date: 2026-02-11 12:40:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "3fd9b3a6f6c1"
down_revision = "9c2d6a0a3f2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("created_by", sa.Uuid(), nullable=True))
    op.add_column("api_keys", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("revoked_reason", sa.String(length=300), nullable=True))
    op.create_foreign_key(
        "fk_api_keys_created_by",
        "api_keys",
        "tenants",
        ["created_by"],
        ["id"],
    )
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("actor_tenant_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_admin_actions_actor", "admin_actions", ["actor_tenant_id"])
    op.create_index("ix_admin_actions_created_at", "admin_actions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_actions_created_at", table_name="admin_actions")
    op.drop_index("ix_admin_actions_actor", table_name="admin_actions")
    op.drop_table("admin_actions")
    op.drop_constraint("fk_api_keys_created_by", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "revoked_reason")
    op.drop_column("api_keys", "revoked_at")
    op.drop_column("api_keys", "last_used_at")
    op.drop_column("api_keys", "created_by")
