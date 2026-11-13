"""Distinguish PostgreSQL migration credentials from runtime credentials.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credentials",
        sa.Column("access", sa.String(20), nullable=False, server_default="runtime"),
    )


def downgrade() -> None:
    op.drop_column("credentials", "access")
