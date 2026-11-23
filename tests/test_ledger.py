"""Unit tests for ledger-demo."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ledger.service import LedgerService
from ledger.store import load_transactions, save_transactions


def test_add_transaction_and_balance():
    svc = LedgerService()
    svc.add_transaction(occurred_on=date(2026, 11, 1), category="Salary", amount="3000.00", kind="income", description="Paycheck")
    svc.add_transaction(occurred_on=date(2026, 11, 2), category="Food", amount="45.50", description="Groceries")
    svc.add_transaction(occurred_on=date(2026, 11, 3), category="Transport", amount="14.50", description="Train")
    assert svc.balance() == Decimal("2940.00")


def test_add_transaction_rejects_invalid_inputs():
    svc = LedgerService()
    with pytest.raises(ValueError, match="positive"):
        svc.add_transaction(occurred_on=date(2026, 11, 1), category="food", amount="0")
    with pytest.raises(ValueError, match="non-empty"):
        svc.add_transaction(occurred_on=date(2026, 11, 1), category="   ", amount="10")


def test_spending_by_category_for_expenses():
    svc = LedgerService()
    svc.add_transaction(occurred_on=date(2026, 11, 1), category="food", amount="20.00")
    svc.add_transaction(occurred_on=date(2026, 11, 2), category="food", amount="15.25")
    svc.add_transaction(occurred_on=date(2026, 11, 3), category="books", amount="30.00")
    assert svc.spending_by_category() == {"food": Decimal("35.25"), "books": Decimal("30.00")}


def test_spending_by_category_excludes_income():
    svc = LedgerService()
    svc.add_transaction(occurred_on=date(2026, 11, 1), category="salary", amount="3000.00", kind="income", description="Paycheck")
    svc.add_transaction(occurred_on=date(2026, 11, 2), category="food", amount="40.00", kind="expense", description="Groceries")
    svc.add_transaction(occurred_on=date(2026, 11, 3), category="food", amount="10.00", kind="income", description="Grocery refund")
    svc.add_transaction(occurred_on=date(2026, 11, 4), category="books", amount="25.50", kind="expense", description="Novel")
    assert svc.spending_by_category() == {"food": Decimal("40.00"), "books": Decimal("25.50")}


def test_budget_status_tracks_monthly_spending():
    svc = LedgerService()
    svc.set_budget("food", "100.00")
    svc.add_transaction(occurred_on=date(2026, 10, 28), category="food", amount="90.00")
    svc.add_transaction(occurred_on=date(2026, 11, 5), category="food", amount="65.00")
    svc.add_transaction(occurred_on=date(2026, 11, 10), category="food", amount="50.00")

    status = svc.budget_status("food", 2026, 11)
    assert status.spent == Decimal("115.00")
    assert status.remaining == Decimal("-15.00")
    assert status.over_budget is True


def test_search_and_export_csv():
    svc = LedgerService()
    svc.add_transaction(occurred_on=date(2026, 11, 1), category="coffee", amount="5.75", description="Morning latte")
    svc.add_transaction(occurred_on=date(2026, 11, 2), category="books", amount="22.00", description="Python handbook")

    assert len(svc.search("latte")) == 1
    assert len(svc.search("BOOKS")) == 1
    assert svc.search("   ") == []

    csv_text = svc.export_csv()
    assert "tx-0001,2026-11-01,coffee,expense,5.75,Morning latte" in csv_text


def test_store_round_trip(tmp_path: Path):
    svc = LedgerService()
    svc.add_transaction(occurred_on=date(2026, 11, 4), category="travel", amount="120.00", description="Flight")
    target = tmp_path / "data" / "ledger.json"

    save_transactions(target, svc.transactions)
    loaded = load_transactions(target)
    assert loaded == svc.transactions
