"""Preserve chronological order for multiple goal allocations on one day."""
from alembic import op
import sqlalchemy as sa

revision = "0006_goal_allocation_order"
down_revision = "0005_investment_goal_detail"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("goal_allocations", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")))


def downgrade():
    op.drop_column("goal_allocations", "created_at")
