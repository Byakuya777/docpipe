"""M4: record how much of the document the analysis saw

Extraction stops early on long documents, so a summary can cover 12 of 600
pages. Without these counts that is indistinguishable from full coverage.

Nullable because results written before this migration have no page counts —
the UI treats NULL as "unknown" rather than claiming full coverage.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("result", sa.Column("pages_read", sa.Integer(), nullable=True))
    op.add_column("result", sa.Column("total_pages", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("result", "total_pages")
    op.drop_column("result", "pages_read")
