"""Monthly recurring plans and realized occurrences."""
from alembic import op
import sqlalchemy as sa

revision = "0004_recurring_plans"
down_revision = "0003_audit_valuations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recurring_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("description", sa.String(180), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT")),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_recurring_plan_amount_positive"))
    op.create_table("recurring_occurrences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("recurring_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("realized_at", sa.Date(), nullable=False),
        sa.UniqueConstraint("plan_id", "due_date", name="uq_recurring_plan_due"))
    op.create_index("ix_recurring_occurrences_plan_id", "recurring_occurrences", ["plan_id"])


def downgrade():
    op.drop_index("ix_recurring_occurrences_plan_id", table_name="recurring_occurrences")
    op.drop_table("recurring_occurrences")
    op.drop_table("recurring_plans")
