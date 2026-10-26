"""Investment metadata and goal allocation history."""
from alembic import op
import sqlalchemy as sa

revision = "0005_investment_goal_detail"
down_revision = "0004_recurring_plans"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("investments", sa.Column("institution", sa.String(120)))
    op.add_column("investments", sa.Column("quantity", sa.Numeric(20, 8)))
    op.add_column("investments", sa.Column("opening_contribution", sa.Numeric(18, 2)))
    op.add_column("investments", sa.Column("acquired_on", sa.Date()))
    op.create_table("goal_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount_delta", sa.Numeric(18, 2), nullable=False),
        sa.Column("allocated_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(180), nullable=False))
    op.create_index("ix_goal_allocations_goal_id", "goal_allocations", ["goal_id"])


def downgrade():
    op.drop_index("ix_goal_allocations_goal_id", table_name="goal_allocations")
    op.drop_table("goal_allocations")
    op.drop_column("investments", "acquired_on")
    op.drop_column("investments", "opening_contribution")
    op.drop_column("investments", "quantity")
    op.drop_column("investments", "institution")
