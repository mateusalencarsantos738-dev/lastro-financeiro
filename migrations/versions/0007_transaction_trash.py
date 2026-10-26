"""Reversible transaction trash with lifecycle audit."""
from alembic import op
import sqlalchemy as sa

revision = "0007_transaction_trash"
down_revision = "0006_goal_allocation_order"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transactions", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_index("ix_transactions_deleted_at", "transactions", ["deleted_at"])
    op.create_table("transaction_lifecycle_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.CheckConstraint("action IN ('delete','restore')", name="ck_transaction_lifecycle_action"))
    op.create_index("ix_transaction_lifecycle_events_transaction_id", "transaction_lifecycle_events", ["transaction_id"])


def downgrade():
    op.drop_index("ix_transaction_lifecycle_events_transaction_id", table_name="transaction_lifecycle_events")
    op.drop_table("transaction_lifecycle_events")
    op.drop_index("ix_transactions_deleted_at", table_name="transactions")
    op.drop_column("transactions", "deleted_at")
