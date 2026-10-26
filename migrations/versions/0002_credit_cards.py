"""Credit cards, invoices and installment obligations"""
from alembic import op
import sqlalchemy as sa

revision = "0002_credit_cards"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("credit_cards", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, unique=True), sa.Column("closing_day", sa.Integer(), nullable=False), sa.Column("due_day", sa.Integer(), nullable=False), sa.CheckConstraint("closing_day BETWEEN 1 AND 31", name="ck_card_closing_day"), sa.CheckConstraint("due_day BETWEEN 1 AND 31", name="ck_card_due_day"))
    op.create_table("credit_purchases", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("card_id", sa.Uuid(), sa.ForeignKey("credit_cards.id", ondelete="RESTRICT"), nullable=False), sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False, unique=True), sa.Column("total_amount", sa.Numeric(18,2), nullable=False), sa.Column("installment_count", sa.Integer(), nullable=False), sa.Column("purchase_date", sa.Date(), nullable=False), sa.Column("merchant", sa.String(180), nullable=False), sa.CheckConstraint("total_amount > 0", name="ck_credit_purchase_amount"), sa.CheckConstraint("installment_count BETWEEN 1 AND 120", name="ck_credit_purchase_count"))
    op.create_index("ix_credit_purchases_card_id", "credit_purchases", ["card_id"])
    op.create_table("invoices", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("card_id", sa.Uuid(), sa.ForeignKey("credit_cards.id", ondelete="RESTRICT"), nullable=False), sa.Column("due_date", sa.Date(), nullable=False), sa.Column("paid_date", sa.Date()), sa.UniqueConstraint("card_id", "due_date", name="uq_invoice_card_due"))
    op.create_index("ix_invoices_card_id", "invoices", ["card_id"])
    op.create_index("ix_invoices_due_date", "invoices", ["due_date"])
    op.create_table("installments", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("purchase_id", sa.Uuid(), sa.ForeignKey("credit_purchases.id", ondelete="RESTRICT"), nullable=False), sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("amount", sa.Numeric(18,2), nullable=False), sa.Column("due_date", sa.Date(), nullable=False), sa.Column("paid_date", sa.Date()), sa.UniqueConstraint("purchase_id", "sequence", name="uq_installment_purchase_sequence"), sa.CheckConstraint("amount > 0", name="ck_installment_amount_positive"))
    op.create_index("ix_installments_purchase_id", "installments", ["purchase_id"])
    op.create_index("ix_installments_invoice_id", "installments", ["invoice_id"])
    op.create_index("ix_installments_due_date", "installments", ["due_date"])

def downgrade():
    op.drop_index("ix_installments_due_date", table_name="installments")
    op.drop_index("ix_installments_invoice_id", table_name="installments")
    op.drop_index("ix_installments_purchase_id", table_name="installments")
    op.drop_table("installments")
    op.drop_index("ix_invoices_due_date", table_name="invoices")
    op.drop_index("ix_invoices_card_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_credit_purchases_card_id", table_name="credit_purchases")
    op.drop_table("credit_purchases")
    op.drop_table("credit_cards")
