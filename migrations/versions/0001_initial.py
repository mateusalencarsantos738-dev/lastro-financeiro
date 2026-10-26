"""Initial personal finance schema"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("accounts",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("categories", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(80), nullable=False, unique=True), sa.Column("kind", sa.String(20), nullable=False), sa.Column("is_entertainment", sa.Boolean(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False))
    op.create_table("transactions",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("kind", sa.String(20), nullable=False), sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT")), sa.Column("description", sa.String(180), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False), sa.Column("competence_date", sa.Date(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("settled_date", sa.Date()), sa.Column("related_id", sa.Uuid()), sa.Column("idempotency_key", sa.String(120), unique=True), sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transaction_amount_positive"), sa.CheckConstraint("kind IN ('income','expense','refund','transfer_in','transfer_out','investment')", name="ck_transaction_kind"))
    for table, column, name in [("transactions", "account_id", "ix_transactions_account_id"), ("transactions", "category_id", "ix_transactions_category_id"), ("transactions", "transaction_date", "ix_transactions_transaction_date"), ("transactions", "competence_date", "ix_transactions_competence_date"), ("transactions", "related_id", "ix_transactions_related_id")]:
        op.create_index(name, table, [column])
    op.create_table("budgets", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False), sa.Column("period_start", sa.Date(), nullable=False), sa.Column("limit_amount", sa.Numeric(18, 2), nullable=False), sa.UniqueConstraint("category_id", "period_start", name="uq_budget_category_period"))
    op.create_index("ix_budgets_category_id", "budgets", ["category_id"])
    op.create_table("idempotency_records", sa.Column("key", sa.String(120), primary_key=True), sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("result_id", sa.Uuid(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("investments", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(120), nullable=False, unique=True), sa.Column("kind", sa.String(40), nullable=False), sa.Column("current_value", sa.Numeric(18, 2), nullable=False), sa.Column("valuation_date", sa.Date()), sa.Column("notes", sa.Text()))
    op.create_table("investment_events", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("investment_id", sa.Uuid(), sa.ForeignKey("investments.id", ondelete="RESTRICT"), nullable=False), sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False), sa.Column("kind", sa.String(20), nullable=False), sa.Column("amount", sa.Numeric(18, 2), nullable=False), sa.Column("event_date", sa.Date(), nullable=False), sa.Column("idempotency_key", sa.String(120), unique=True), sa.Column("notes", sa.Text()), sa.CheckConstraint("amount > 0", name="ck_investment_event_amount_positive"))
    op.create_index("ix_investment_events_investment_id", "investment_events", ["investment_id"])
    op.create_index("ix_investment_events_account_id", "investment_events", ["account_id"])
    op.create_index("ix_investment_events_event_date", "investment_events", ["event_date"])
    op.create_table("bills", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("description", sa.String(180), nullable=False), sa.Column("amount", sa.Numeric(18, 2), nullable=False), sa.Column("due_date", sa.Date(), nullable=False), sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT")), sa.Column("paid_date", sa.Date()), sa.CheckConstraint("amount > 0", name="ck_bill_amount_positive"))
    op.create_index("ix_bills_due_date", "bills", ["due_date"])
    op.create_table("goals", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(120), nullable=False, unique=True), sa.Column("target_amount", sa.Numeric(18, 2), nullable=False), sa.Column("allocated_amount", sa.Numeric(18, 2), nullable=False), sa.Column("target_date", sa.Date()))

def downgrade():
    op.drop_table("goals"); op.drop_index("ix_bills_due_date", table_name="bills"); op.drop_table("bills")
    op.drop_index("ix_investment_events_event_date", table_name="investment_events"); op.drop_index("ix_investment_events_account_id", table_name="investment_events"); op.drop_index("ix_investment_events_investment_id", table_name="investment_events"); op.drop_table("investment_events")
    op.drop_table("investments"); op.drop_table("idempotency_records"); op.drop_index("ix_budgets_category_id", table_name="budgets"); op.drop_table("budgets")
    op.drop_index("ix_transactions_related_id", table_name="transactions"); op.drop_index("ix_transactions_competence_date", table_name="transactions"); op.drop_index("ix_transactions_transaction_date", table_name="transactions"); op.drop_index("ix_transactions_category_id", table_name="transactions"); op.drop_index("ix_transactions_account_id", table_name="transactions"); op.drop_table("transactions")
    op.drop_table("categories"); op.drop_table("accounts")
