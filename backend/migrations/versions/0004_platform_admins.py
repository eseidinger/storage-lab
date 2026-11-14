"""Store global platform administrators in metadata.

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("identity", sa.String(600), primary_key=True),
        sa.Column("granted_by", sa.String(600), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "platform_admin_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor", sa.String(600), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("identity", sa.String(600), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("platform_admin_events")
    op.drop_table("platform_admins")
