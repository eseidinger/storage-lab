"""Store worker-generated credentials until one-time retrieval.

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("credentials", sa.Column("deliverable_secret", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("credentials", "deliverable_secret")
