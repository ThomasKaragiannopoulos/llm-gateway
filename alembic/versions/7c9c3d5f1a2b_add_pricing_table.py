"""add pricing table

Revision ID: 7c9c3d5f1a2b
Revises: c3a7a5d1b2d9
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7c9c3d5f1a2b"
down_revision = "c3a7a5d1b2d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pricing",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model", sa.String(length=200), nullable=False, unique=True),
        sa.Column("input_per_1k", sa.Float(), nullable=False, server_default="0"),
        sa.Column("output_per_1k", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cached_per_1k", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("pricing")
