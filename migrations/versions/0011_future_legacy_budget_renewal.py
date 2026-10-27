"""Continue renewal after the last preconfigured future monthly budget."""
from alembic import op

revision = "0011_future_budget_renewal"
down_revision = "0010_budget_seed_origin"
branch_labels = None
depends_on = None


def upgrade():
    # Categories with explicitly recorded future months keep those rows. The
    # final future row becomes the starting value only after its own month ends.
    op.execute("""
        INSERT INTO budget_rules (id, category_id, effective_start, period_type,
                                  interval_count, limit_amount, is_migrated_seed)
        SELECT gen_random_uuid(), b.category_id,
               (b.period_start + interval '1 month')::date,
               'calendar_month', 1, b.limit_amount, TRUE
        FROM budgets b
        WHERE b.period_start = (
            SELECT MAX(other.period_start) FROM budgets other
            WHERE other.category_id = b.category_id
              AND other.period_start > date_trunc('month', CURRENT_DATE)::date
        )
          AND NOT EXISTS (SELECT 1 FROM budget_rules r WHERE r.category_id = b.category_id)
    """)


def downgrade():
    # This migration is data-only. Keep established rules on downgrade so
    # later user edits are never removed implicitly.
    pass
