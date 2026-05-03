"""add request observability fields

Revision ID: d4e5f6a7b8c9
Revises: 3fd9b3a6f6c1
Create Date: 2026-05-03 20:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "3fd9b3a6f6c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("provider_name", sa.String(length=100), nullable=True))
    op.add_column("requests", sa.Column("route_reason", sa.String(length=100), nullable=True))
    op.add_column("requests", sa.Column("cache_status", sa.String(length=30), nullable=True))
    op.add_column("requests", sa.Column("failure_stage", sa.String(length=80), nullable=True))
    op.add_column("requests", sa.Column("failure_code", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "failure_code")
    op.drop_column("requests", "failure_stage")
    op.drop_column("requests", "cache_status")
    op.drop_column("requests", "route_reason")
    op.drop_column("requests", "provider_name")
