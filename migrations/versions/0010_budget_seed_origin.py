"""Mark legacy renewal seeds so later user rules supersede them safely."""
from alembic import op
import sqlalchemy as sa

revision = "0010_budget_seed_origin"
down_revision = "0009_budget_cycles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("budget_rules", sa.Column("is_migrated_seed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("""
        UPDATE budget_rules r SET is_migrated_seed = TRUE
        FROM budgets b
        WHERE r.category_id = b.category_id
          AND b.period_start = date_trunc('month', CURRENT_DATE)::date
          AND r.effective_start = (date_trunc('month', CURRENT_DATE) + interval '1 month')::date
          AND r.period_type = 'calendar_month' AND r.interval_count = 1
          AND r.renewal_day IS NULL AND r.limit_amount = b.limit_amount
    """)


def downgrade():
    op.drop_column("budget_rules", "is_migrated_seed")
