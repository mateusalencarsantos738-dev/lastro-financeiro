from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db import Base


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="checking")
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="expense")
    is_entertainment: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    icon: Mapped[str | None] = mapped_column(String(40))


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        CheckConstraint("kind IN ('income','expense','refund','transfer_in','transfer_out','investment')", name="ck_transaction_kind"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    description: Mapped[str] = mapped_column(String(180))
    transaction_date: Mapped[date] = mapped_column(Date, index=True)
    competence_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="settled")
    settled_date: Mapped[date | None] = mapped_column(Date)
    related_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TransactionLifecycleEvent(Base):
    __tablename__ = "transaction_lifecycle_events"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", "period_start", name="uq_budget_category_period"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class BudgetRule(Base):
    __tablename__ = "budget_rules"
    __table_args__ = (
        UniqueConstraint("category_id", "effective_start", name="uq_budget_rule_category_start"),
        CheckConstraint("period_type IN ('calendar_month','monthly_day','days','weeks','months')", name="ck_budget_rule_type"),
        CheckConstraint("interval_count BETWEEN 1 AND 120", name="ck_budget_rule_interval"),
        CheckConstraint("renewal_day IS NULL OR renewal_day BETWEEN 1 AND 31", name="ck_budget_rule_day"),
        CheckConstraint("limit_amount >= 0", name="ck_budget_rule_limit"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    effective_start: Mapped[date] = mapped_column(Date, index=True)
    period_type: Mapped[str] = mapped_column(String(20))
    interval_count: Mapped[int] = mapped_column(Integer, default=1)
    renewal_day: Mapped[int | None] = mapped_column(Integer)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    is_migrated_seed: Mapped[bool] = mapped_column(Boolean, default=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Investment(Base):
    __tablename__ = "investments"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    institution: Mapped[str | None] = mapped_column(String(120))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    opening_contribution: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    acquired_on: Mapped[date | None] = mapped_column(Date)
    current_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    valuation_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class InvestmentEvent(Base):
    __tablename__ = "investment_events"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_investment_event_amount_positive"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    investment_id: Mapped[UUID] = mapped_column(ForeignKey("investments.id", ondelete="RESTRICT"), index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    event_date: Mapped[date] = mapped_column(Date, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_bill_amount_positive"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    description: Mapped[str] = mapped_column(String(180))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    paid_date: Mapped[date | None] = mapped_column(Date)
    payment_transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"))


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    target_date: Mapped[date | None] = mapped_column(Date)
    tracking_mode: Mapped[str] = mapped_column(String(12), default="none")


class GoalTrackingAccount(Base):
    __tablename__ = "goal_tracking_accounts"
    goal_id: Mapped[UUID] = mapped_column(ForeignKey("goals.id", ondelete="RESTRICT"), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), primary_key=True)


class GoalContribution(Base):
    __tablename__ = "goal_contributions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    goal_id: Mapped[UUID] = mapped_column(ForeignKey("goals.id", ondelete="RESTRICT"), index=True)
    amount_delta: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    contributed_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class GoalAllocation(Base):
    __tablename__ = "goal_allocations"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    goal_id: Mapped[UUID] = mapped_column(ForeignKey("goals.id", ondelete="RESTRICT"), index=True)
    amount_delta: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    allocated_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class CreditCard(Base):
    __tablename__ = "credit_cards"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), unique=True)
    closing_day: Mapped[int] = mapped_column(Integer)
    due_day: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("closing_day BETWEEN 1 AND 31", name="ck_card_closing_day"),
        CheckConstraint("due_day BETWEEN 1 AND 31", name="ck_card_due_day"),
    )


class CreditPurchase(Base):
    __tablename__ = "credit_purchases"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    card_id: Mapped[UUID] = mapped_column(ForeignKey("credit_cards.id", ondelete="RESTRICT"), index=True)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"), unique=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    installment_count: Mapped[int] = mapped_column(Integer)
    purchase_date: Mapped[date] = mapped_column(Date)
    merchant: Mapped[str] = mapped_column(String(180))
    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_credit_purchase_amount"),
        CheckConstraint("installment_count BETWEEN 1 AND 120", name="ck_credit_purchase_count"),
    )


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    card_id: Mapped[UUID] = mapped_column(ForeignKey("credit_cards.id", ondelete="RESTRICT"), index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    paid_date: Mapped[date | None] = mapped_column(Date)
    __table_args__ = (UniqueConstraint("card_id", "due_date", name="uq_invoice_card_due"),)


class Installment(Base):
    __tablename__ = "installments"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    purchase_id: Mapped[UUID] = mapped_column(ForeignKey("credit_purchases.id", ondelete="RESTRICT"), index=True)
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    paid_date: Mapped[date | None] = mapped_column(Date)
    __table_args__ = (
        UniqueConstraint("purchase_id", "sequence", name="uq_installment_purchase_sequence"),
        CheckConstraint("amount > 0", name="ck_installment_amount_positive"),
    )


class TransactionRevision(Base):
    __tablename__ = "transaction_revisions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(180))
    before_state: Mapped[dict] = mapped_column(JSON)
    after_state: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvestmentValuation(Base):
    __tablename__ = "investment_valuations"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    investment_id: Mapped[UUID] = mapped_column(ForeignKey("investments.id", ondelete="RESTRICT"), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    valuation_date: Mapped[date] = mapped_column(Date, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)


class NetWorthSnapshot(Base):
    __tablename__ = "net_worth_snapshots"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    as_of_date: Mapped[date] = mapped_column(Date, index=True, unique=True)
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    investments: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    liabilities: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_worth: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecurringPlan(Base):
    __tablename__ = "recurring_plans"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_recurring_plan_amount_positive"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    description: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    start_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RecurringOccurrence(Base):
    __tablename__ = "recurring_occurrences"
    __table_args__ = (UniqueConstraint("plan_id", "due_date", name="uq_recurring_plan_due"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("recurring_plans.id", ondelete="RESTRICT"), index=True)
    due_date: Mapped[date] = mapped_column(Date)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id", ondelete="RESTRICT"), unique=True)
    realized_at: Mapped[date] = mapped_column(Date)
