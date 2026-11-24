"""Unit tests for ledger-demo."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ledger import LedgerService, MonthlySummary, Transaction
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


def test_monthly_summary_mixed_transactions():
    svc = LedgerService(
        transactions=[
            Transaction(id="tx-0001", occurred_on=date(2026, 11, 1), category="salary", amount=Decimal("3000"), kind="income"),
            Transaction(id="tx-0002", occurred_on=date(2026, 11, 5), category="food", amount=Decimal("10.5"), kind="expense"),
        ]
    )
    svc.add_transaction(occurred_on=date(2026, 11, 10), category="food", amount="24.75", kind="expense")
    svc.add_transaction(occurred_on=date(2026, 11, 12), category="food", amount="5", kind="income")
    svc.add_transaction(occurred_on=date(2026, 11, 15), category="transport", amount="14.25", kind="expense")
    # Different month in same year and same month in different year should be excluded.
    svc.add_transaction(occurred_on=date(2026, 10, 31), category="food", amount="99.00", kind="expense")
    svc.add_transaction(occurred_on=date(2025, 11, 1), category="salary", amount="5000.00", kind="income")
    svc.add_transaction(occurred_on=date(2025, 11, 2), category="books", amount="40.00", kind="expense")

    summary = svc.monthly_summary(2026, 11)
    assert summary == MonthlySummary(
        year=2026,
        month=11,
        total_income=Decimal("3005.00"),
        total_expenses=Decimal("49.50"),
        net=Decimal("2955.50"),
        expenses_by_category={"food": Decimal("35.25"), "transport": Decimal("14.25")},
    )
    assert summary.total_income.as_tuple().exponent == -2
    assert summary.total_expenses.as_tuple().exponent == -2
    assert summary.net.as_tuple().exponent == -2
    assert all(val.as_tuple().exponent == -2 for val in summary.expenses_by_category.values())

    with pytest.raises(FrozenInstanceError):
        summary.net = Decimal("0.00")  # type: ignore[misc]


def test_monthly_summary_empty_month():
    svc = LedgerService()
    svc.add_transaction(occurred_on=date(2026, 10, 15), category="food", amount="25.00")

    summary = svc.monthly_summary(2026, 11)
    assert summary == MonthlySummary(
        year=2026,
        month=11,
        total_income=Decimal("0.00"),
        total_expenses=Decimal("0.00"),
        net=Decimal("0.00"),
        expenses_by_category={},
    )
    assert summary.total_income.as_tuple().exponent == -2
    assert summary.total_expenses.as_tuple().exponent == -2
    assert summary.net.as_tuple().exponent == -2


def test_filter_transactions_single_filters_and_insertion_order():
    svc = LedgerService()
    # Intentionally add transactions out of chronological order to verify insertion order preservation.
    t1 = svc.add_transaction(occurred_on=date(2026, 11, 10), category="Food", amount="50.00", kind="expense", description="Dinner")
    t2 = svc.add_transaction(occurred_on=date(2026, 11, 1), category="Salary", amount="3000.00", kind="income", description="Paycheck")
    t3 = svc.add_transaction(occurred_on=date(2026, 11, 15), category="food", amount="20.00", kind="expense", description="Lunch")
    t4 = svc.add_transaction(occurred_on=date(2026, 11, 5), category="Transport", amount="20.00", kind="expense", description="Pass")
    t5 = svc.add_transaction(occurred_on=date(2026, 11, 10), category="Food", amount="10.00", kind="income", description="Refund")

    assert svc.filter_transactions() == [t1, t2, t3, t4, t5]

    # Date bounds (inclusive) and insertion order preserved.
    assert svc.filter_transactions(start_date=date(2026, 11, 10)) == [t1, t3, t5]
    assert svc.filter_transactions(end_date=date(2026, 11, 5)) == [t2, t4]
    assert svc.filter_transactions(start_date=date(2026, 11, 10), end_date=date(2026, 11, 10)) == [t1, t5]

    # Category filter is case-insensitive, trimmed, and exact (not substring).
    assert svc.filter_transactions(category="  FoOd  ") == [t1, t3, t5]
    assert svc.filter_transactions(category="foo") == []

    # Kind filter.
    assert svc.filter_transactions(kind="income") == [t2, t5]
    assert svc.filter_transactions(kind="expense") == [t1, t3, t4]

    # Amount bounds (inclusive) with both Decimal and str.
    assert svc.filter_transactions(min_amount=Decimal("50.00")) == [t1, t2]
    assert svc.filter_transactions(max_amount="20.00") == [t3, t4, t5]
    assert svc.filter_transactions(min_amount="20.00", max_amount=Decimal("20.00")) == [t3, t4]


def test_filter_transactions_combined_and_empty_matches():
    svc = LedgerService(
        transactions=[
            Transaction(id="tx-0001", occurred_on=date(2026, 11, 3), category="  Food ", amount=Decimal("25.00"), kind="expense"),
        ]
    )
    t1 = svc.transactions[0]
    t2 = svc.add_transaction(occurred_on=date(2026, 11, 6), category="food", amount="45.00", kind="expense")
    svc.add_transaction(occurred_on=date(2026, 11, 6), category="food", amount="45.00", kind="income")
    svc.add_transaction(occurred_on=date(2026, 11, 8), category="food", amount="80.00", kind="expense")
    svc.add_transaction(occurred_on=date(2026, 11, 6), category="books", amount="35.00", kind="expense")

    matched = svc.filter_transactions(
        start_date=date(2026, 11, 3),
        end_date=date(2026, 11, 7),
        category="FOOD",
        kind="expense",
        min_amount="25.00",
        max_amount=Decimal("50.00"),
    )
    assert matched == [t1, t2]

    # Non-matching combinations and empty service.
    assert svc.filter_transactions(start_date=date(2026, 12, 1)) == []
    assert svc.filter_transactions(category="travel") == []
    assert svc.filter_transactions(category="books", kind="income") == []
    assert svc.filter_transactions(min_amount="100.00") == []
    assert LedgerService().filter_transactions(category="food") == []


def test_filter_transactions_invalid_bounds():
    svc = LedgerService()
    svc.add_transaction(occurred_on=date(2026, 11, 5), category="food", amount="25.00")

    with pytest.raises(ValueError):
        svc.filter_transactions(start_date=date(2026, 11, 10), end_date=date(2026, 11, 9))

    with pytest.raises(ValueError):
        svc.filter_transactions(min_amount=Decimal("50.00"), max_amount=Decimal("25.00"))

    with pytest.raises(ValueError):
        svc.filter_transactions(min_amount="100.00", max_amount="20.00")
