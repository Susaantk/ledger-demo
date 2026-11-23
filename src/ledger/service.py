"""Core business logic for managing transactions, budgets, and reporting."""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Iterable

from .models import Budget, BudgetStatus, Transaction, TransactionKind

_CENT = Decimal("0.01")


class LedgerService:
    """In-memory expense and budget tracker."""

    def __init__(self, transactions: Iterable[Transaction] = ()) -> None:
        self._transactions: list[Transaction] = list(transactions)
        self._budgets: dict[str, Budget] = {}
        self._counter = len(self._transactions)

    @property
    def transactions(self) -> list[Transaction]:
        return list(self._transactions)

    def add_transaction(
        self,
        *,
        occurred_on: date,
        category: str,
        amount: Decimal | str | int | float,
        kind: TransactionKind = "expense",
        description: str = "",
    ) -> Transaction:
        value = Decimal(str(amount)).quantize(_CENT)
        if value <= 0:
            raise ValueError("amount must be positive")
        clean_category = category.strip().lower()
        if not clean_category:
            raise ValueError("category must be non-empty")
        if kind not in ("expense", "income"):
            raise ValueError(f"unsupported transaction kind: {kind}")
        self._counter += 1
        tx = Transaction(
            id=f"tx-{self._counter:04d}",
            occurred_on=occurred_on,
            category=clean_category,
            amount=value,
            kind=kind,
            description=description.strip(),
        )
        self._transactions.append(tx)
        return tx

    def balance(self) -> Decimal:
        """Net balance: total income minus total expenses."""
        total = Decimal("0.00")
        for tx in self._transactions:
            total += tx.amount if tx.kind == "income" else -tx.amount
        return total.quantize(_CENT)

    def spending_by_category(self) -> dict[str, Decimal]:
        """Returns total spending grouped by category."""
        totals: dict[str, Decimal] = {}
        for tx in self._transactions:
            totals[tx.category] = (totals.get(tx.category, Decimal("0.00")) + tx.amount).quantize(_CENT)
        return totals

    def set_budget(self, category: str, monthly_limit: Decimal | str | int | float) -> Budget:
        limit = Decimal(str(monthly_limit)).quantize(_CENT)
        if limit <= 0:
            raise ValueError("monthly_limit must be positive")
        clean_category = category.strip().lower()
        if not clean_category:
            raise ValueError("category must be non-empty")
        budget = Budget(category=clean_category, monthly_limit=limit)
        self._budgets[clean_category] = budget
        return budget

    def budget_status(self, category: str, year: int, month: int) -> BudgetStatus:
        clean_category = category.strip().lower()
        if clean_category not in self._budgets:
            raise KeyError(f"no budget configured for category '{clean_category}'")
        limit = self._budgets[clean_category].monthly_limit
        spent = sum(
            (
                tx.amount
                for tx in self._transactions
                if tx.kind == "expense"
                and tx.category == clean_category
                and tx.occurred_on.year == year
                and tx.occurred_on.month == month
            ),
            Decimal("0.00"),
        ).quantize(_CENT)
        remaining = (limit - spent).quantize(_CENT)
        return BudgetStatus(
            category=clean_category,
            limit=limit,
            spent=spent,
            remaining=remaining,
            over_budget=spent > limit,
        )

    def search(self, query: str) -> list[Transaction]:
        """Case-insensitive substring search over category and description."""
        needle = query.strip().lower()
        if not needle:
            return []
        return [
            tx
            for tx in self._transactions
            if needle in tx.category or needle in tx.description.lower()
        ]

    def export_csv(self) -> str:
        """Exports all transactions as a CSV string."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "occurred_on", "category", "kind", "amount", "description"])
        for tx in self._transactions:
            writer.writerow([tx.id, tx.occurred_on.isoformat(), tx.category, tx.kind, str(tx.amount), tx.description])
        return buffer.getvalue()
