"""Audit financial corrections and preserve valuation snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0003_audit_valuations"
down_revision = "0002_credit_cards"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("transactions", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("bills", sa.Column("payment_transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id", ondelete="RESTRICT")))
    op.create_table("transaction_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(180), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_transaction_revisions_transaction_id", "transaction_revisions", ["transaction_id"])
    op.create_table("investment_valuations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("investment_id", sa.Uuid(), sa.ForeignKey("investments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("value", sa.Numeric(18,2), nullable=False),
        sa.Column("valuation_date", sa.Date(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), unique=True))
    op.create_index("ix_investment_valuations_investment_id", "investment_valuations", ["investment_id"])
    op.create_index("ix_investment_valuations_valuation_date", "investment_valuations", ["valuation_date"])
    op.create_table("net_worth_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("as_of_date", sa.Date(), nullable=False, unique=True),
        sa.Column("cash", sa.Numeric(18,2), nullable=False),
        sa.Column("investments", sa.Numeric(18,2), nullable=False),
        sa.Column("liabilities", sa.Numeric(18,2), nullable=False),
        sa.Column("net_worth", sa.Numeric(18,2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_net_worth_snapshots_as_of_date", "net_worth_snapshots", ["as_of_date"])

def downgrade():
    op.drop_index("ix_net_worth_snapshots_as_of_date", table_name="net_worth_snapshots")
    op.drop_table("net_worth_snapshots")
    op.drop_index("ix_investment_valuations_valuation_date", table_name="investment_valuations")
    op.drop_index("ix_investment_valuations_investment_id", table_name="investment_valuations")
    op.drop_table("investment_valuations")
    op.drop_index("ix_transaction_revisions_transaction_id", table_name="transaction_revisions")
    op.drop_table("transaction_revisions")
    op.drop_column("bills", "payment_transaction_id")
    op.drop_column("transactions", "version")
