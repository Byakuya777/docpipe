"""M2: batch table and document.batch_id

Documents created in M1 predate batches, so batch_id is added nullable,
backfilled into one synthetic batch, and only then made NOT NULL — the
existing rows are adopted rather than dropped.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batch",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("total_documents", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="processing", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column(
        "document",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Adopt any pre-batch documents into one synthetic batch, so NOT NULL below
    # can be applied without deleting history.
    conn = op.get_bind()
    orphans = conn.execute(
        sa.text("SELECT count(*) FROM document WHERE batch_id IS NULL")
    ).scalar_one()
    if orphans:
        adopted_id = conn.execute(
            sa.text(
                """
                INSERT INTO batch (total_documents, status)
                SELECT count(*),
                       CASE WHEN count(*) FILTER (WHERE status = 'failed') = count(*)
                            THEN 'failed' ELSE 'completed' END
                FROM document WHERE batch_id IS NULL
                RETURNING id
                """
            )
        ).scalar_one()
        conn.execute(
            sa.text("UPDATE document SET batch_id = :b WHERE batch_id IS NULL"),
            {"b": adopted_id},
        )

    op.alter_column("document", "batch_id", nullable=False)
    op.create_foreign_key(
        "document_batch_id_fkey",
        "document",
        "batch",
        ["batch_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Spec §5's index. The status-only index from 0001 becomes redundant —
    # every status query is now scoped to a batch.
    op.create_index("ix_document_batch_id_status", "document", ["batch_id", "status"])
    op.drop_index("ix_document_status", table_name="document")


def downgrade() -> None:
    op.create_index("ix_document_status", "document", ["status"])
    op.drop_index("ix_document_batch_id_status", table_name="document")
    op.drop_constraint("document_batch_id_fkey", "document", type_="foreignkey")
    op.drop_column("document", "batch_id")
    op.drop_table("batch")
