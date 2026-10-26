"""Versioned recurring category budgets; retain monthly rows as historical records."""
from alembic import op
import sqlalchemy as sa

revision = "0009_budget_cycles"
down_revision = "0008_goal_tracking_category_icon"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("budget_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("effective_start", sa.Date(), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("interval_count", sa.Integer(), nullable=False),
        sa.Column("renewal_day", sa.Integer()),
        sa.Column("limit_amount", sa.Numeric(18, 2), nullable=False),
        sa.UniqueConstraint("category_id", "effective_start", name="uq_budget_rule_category_start"),
        sa.CheckConstraint("period_type IN ('calendar_month','monthly_day','days','weeks','months')", name="ck_budget_rule_type"),
        sa.CheckConstraint("interval_count BETWEEN 1 AND 120", name="ck_budget_rule_interval"),
        sa.CheckConstraint("renewal_day IS NULL OR renewal_day BETWEEN 1 AND 31", name="ck_budget_rule_day"),
        sa.CheckConstraint("limit_amount >= 0", name="ck_budget_rule_limit"))
    op.create_index("ix_budget_rules_category_id", "budget_rules", ["category_id"])
    op.create_index("ix_budget_rules_effective_start", "budget_rules", ["effective_start"])
    # Seed only the next calendar month. This preserves every recorded month and
    # lets an existing current-month limit renew until the owner changes it.
    op.execute("""
        INSERT INTO budget_rules (id, category_id, effective_start, period_type, interval_count, limit_amount)
        SELECT gen_random_uuid(), b.category_id,
               (date_trunc('month', CURRENT_DATE) + interval '1 month')::date,
               'calendar_month', 1, b.limit_amount
        FROM budgets b
        WHERE b.period_start = date_trunc('month', CURRENT_DATE)::date
          AND NOT EXISTS (SELECT 1 FROM budgets future
                          WHERE future.category_id = b.category_id
                            AND future.period_start > b.period_start)
    """)


def downgrade():
    op.drop_index("ix_budget_rules_effective_start", table_name="budget_rules")
    op.drop_index("ix_budget_rules_category_id", table_name="budget_rules")
    op.drop_table("budget_rules")
