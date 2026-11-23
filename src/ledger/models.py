"""Domain models for the expense and budget ledger."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

TransactionKind = Literal["expense", "income"]


@dataclass(frozen=True)
class Transaction:
    id: str
    occurred_on: date
    category: str
    amount: Decimal
    kind: TransactionKind = "expense"
    description: str = ""


@dataclass(frozen=True)
class Budget:
    category: str
    monthly_limit: Decimal


@dataclass(frozen=True)
class BudgetStatus:
    category: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal
    over_budget: bool
