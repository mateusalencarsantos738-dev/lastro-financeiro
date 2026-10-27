from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["checking", "savings", "cash"] = "checking"
    opening_balance: Decimal = Decimal("0")


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["income", "expense"] = "expense"
    is_entertainment: bool = False
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    budget_limit: Decimal | None = None
    budget_period_type: Literal["calendar_month", "monthly_day", "days", "weeks", "months"] = "calendar_month"
    budget_interval_count: int = Field(default=1, ge=1, le=120)
    budget_renewal_day: int | None = Field(default=None, ge=1, le=31)
    budget_effective_start: date | None = None


class TransactionCreate(BaseModel):
    kind: Literal["income", "expense", "refund"]
    amount: Decimal
    account_id: UUID
    category_id: UUID | None = None
    description: str = Field(min_length=1, max_length=180)
    transaction_date: date
    competence_date: date | None = None
    related_transaction_id: UUID | None = None
    status: Literal["settled", "pending"] = "settled"
    notes: str | None = None


class TransferCreate(BaseModel):
    source_account_id: UUID
    destination_account_id: UUID
    amount: Decimal
    transaction_date: date
    description: str = "Transferência própria"


class BudgetCreate(BaseModel):
    category_id: UUID
    period_start: date | None = None
    effective_start: date | None = None
    limit_amount: Decimal
    period_type: Literal["calendar_month", "monthly_day", "days", "weeks", "months"] = "calendar_month"
    interval_count: int = Field(default=1, ge=1, le=120)
    renewal_day: int | None = Field(default=None, ge=1, le=31)


class BudgetCyclePreview(BaseModel):
    effective_start: date
    period_type: Literal["calendar_month", "monthly_day", "days", "weeks", "months"] = "calendar_month"
    interval_count: int = Field(default=1, ge=1, le=120)
    renewal_day: int | None = Field(default=None, ge=1, le=31)


class InvestmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=40)
    institution: str | None = Field(default=None, max_length=120)
    quantity: Decimal | None = None
    opening_contribution: Decimal | None = None
    acquired_on: date | None = None
    current_value: Decimal = Decimal("0")
    valuation_date: date | None = None


class InvestmentEventCreate(BaseModel):
    investment_id: UUID
    account_id: UUID
    kind: Literal["contribution", "withdrawal", "income", "fee"]
    amount: Decimal
    event_date: date


class BillCreate(BaseModel):
    description: str = Field(min_length=1, max_length=180)
    amount: Decimal
    due_date: date
    category_id: UUID | None = None


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: Decimal
    allocated_amount: Decimal = Decimal("0")
    target_date: date | None = None
    tracking_mode: Literal["none", "selected", "all"] = "none"
    account_ids: list[UUID] = Field(default_factory=list)


class GoalContributionCreate(BaseModel):
    amount_delta: Decimal
    contributed_on: date
    note: str = Field(min_length=1, max_length=180)


class CreditCardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    closing_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)


class CreditPurchaseCreate(BaseModel):
    card_id: UUID
    category_id: UUID
    total_amount: Decimal
    installment_count: int = Field(ge=1, le=120)
    purchase_date: date
    merchant: str = Field(min_length=1, max_length=180)


class CreditPurchaseUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    card_id: UUID | None = None
    category_id: UUID | None = None
    total_amount: Decimal | None = None
    installment_count: int | None = Field(default=None, ge=1, le=120)
    purchase_date: date | None = None
    merchant: str | None = Field(default=None, min_length=1, max_length=180)


class InvoicePayment(BaseModel):
    source_account_id: UUID
    paid_date: date


class BillPayment(BaseModel):
    source_account_id: UUID
    paid_date: date


class TransactionUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    amount: Decimal
    category_id: UUID | None = None
    description: str = Field(min_length=1, max_length=180)
    transaction_date: date
    reason: str = Field(min_length=1, max_length=180)
    confirmed: bool


class InvestmentValuationCreate(BaseModel):
    value: Decimal
    valuation_date: date


class RecurringPlanCreate(BaseModel):
    description: str = Field(min_length=1, max_length=180)
    kind: Literal["income", "expense"]
    amount: Decimal
    account_id: UUID
    category_id: UUID | None = None
    start_date: date


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
