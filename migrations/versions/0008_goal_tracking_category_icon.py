"""Track goals independently of balances and allow stable category icons."""
from alembic import op
import sqlalchemy as sa

revision = "0008_goal_tracking_category_icon"
down_revision = "0007_transaction_trash"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("categories", sa.Column("icon", sa.String(40)))
    op.add_column("goals", sa.Column("tracking_mode", sa.String(12), nullable=False, server_default="none"))
    op.create_check_constraint("ck_goal_tracking_mode", "goals", "tracking_mode IN ('none','selected','all')")
    op.create_table("goal_tracking_accounts",
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), primary_key=True))
    op.create_table("goal_contributions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount_delta", sa.Numeric(18, 2), nullable=False),
        sa.Column("contributed_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(180), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")))
    op.create_index("ix_goal_contributions_goal_id", "goal_contributions", ["goal_id"])


def downgrade():
    op.drop_index("ix_goal_contributions_goal_id", table_name="goal_contributions")
    op.drop_table("goal_contributions")
    op.drop_table("goal_tracking_accounts")
    op.drop_constraint("ck_goal_tracking_mode", "goals", type_="check")
    op.drop_column("goals", "tracking_mode")
    op.drop_column("categories", "icon")
