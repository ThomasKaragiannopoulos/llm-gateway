"""add api key name

Revision ID: c3a7a5d1b2d9
Revises: 6b3457f1ab86
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3a7a5d1b2d9"
down_revision = "6b3457f1ab86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "name")
