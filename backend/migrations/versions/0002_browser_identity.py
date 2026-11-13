"""Store a sealed, project-scoped S3 browser identity.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("capabilities", sa.Column("browser_credential", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("capabilities", "browser_credential")
