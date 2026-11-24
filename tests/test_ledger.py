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


def test_filter_expression_amount_threshold():
    svc = LedgerService()
    tx1 = svc.add_transaction(occurred_on=date(2026, 11, 1), category="coffee", amount="5.75", description="Latte")
    tx2 = svc.add_transaction(occurred_on=date(2026, 11, 2), category="food", amount="10.00", description="Lunch")
    tx3 = svc.add_transaction(occurred_on=date(2026, 11, 3), category="books", amount="22.50", description="Handbook")

    assert svc.filter_expression("tx.amount > 10") == [tx3]
    assert svc.filter_expression("tx.amount >= 10") == [tx2, tx3]
    assert svc.filter_expression("tx.amount < 10") == [tx1]


def test_filter_expression_compound_and_attribute_filters():
    svc = LedgerService()
    tx1 = svc.add_transaction(occurred_on=date(2026, 10, 15), category="food", amount="12.50", description="Dinner")
    tx2 = svc.add_transaction(occurred_on=date(2026, 11, 1), category="salary", amount="3000.00", kind="income", description="Paycheck")
    tx3 = svc.add_transaction(occurred_on=date(2026, 11, 5), category="food", amount="45.00", description="Weekly groceries")
    tx4 = svc.add_transaction(occurred_on=date(2026, 11, 12), category="books", amount="18.00", description="Python guide")

    assert svc.filter_expression("tx.kind == 'expense' and tx.occurred_on.month == 11") == [tx3, tx4]
    assert svc.filter_expression("tx.occurred_on.year == 2026 and tx.occurred_on.day >= 10") == [tx1, tx4]
    assert svc.filter_expression("tx.category in ('food', 'books') and 15 <= tx.amount <= 50") == [tx3, tx4]
    assert svc.filter_expression("not (tx.kind == 'income') and 'groceries' in tx.description") == [tx3]
    assert svc.filter_expression("tx.id == 'tx-0002' or tx.category in {'books'}") == [tx2, tx4]
    assert svc.filter_expression("tx.amount * 2 + 5 > 40 and tx.kind != 'income'") == [tx3, tx4]
    assert svc.filter_expression("-tx.amount < -20 and tx.category not in ['salary']") == [tx3]


@pytest.mark.parametrize(
    "bad_expr",
    [
        "",
        "   ",
        "tx.amount >",
        "import os",
        "tx.amount > 10; import os",
        "__import__('os').system('echo hi')",
        "eval('1 + 1')",
        "exec('x = 1')",
        "open('/etc/passwd')",
        "len(tx.category) > 2",
        "tx.category.lower() == 'food'",
        "tx.occurred_on.isoformat() == '2026-11-01'",
        "tx.occurred_on.isoformat",
        "amount > 10",
        "__builtins__",
        "tx.__class__",
        "tx.__dict__",
        "tx.amount.__class__",
        "tx.occurred_on.__class__",
        "tx.nonexistent == 1",
        "'a'.__class__",
        "[c for c in tx.category]",
        "(lambda x: x)(tx)",
        "(x := 1)",
        "f'{tx.category}'",
        "tx.amount ** 2 > 10",
        "tx.category[0] == 'f'",
        "{**{'a': 1}}",
    ],
)
def test_filter_expression_rejects_unsafe_and_malformed(bad_expr: str):
    empty_svc = LedgerService()
    populated_svc = LedgerService()
    populated_svc.add_transaction(occurred_on=date(2026, 11, 1), category="food", amount="20.00", description="Lunch")

    with pytest.raises(ValueError):
        empty_svc.filter_expression(bad_expr)
    with pytest.raises(ValueError):
        populated_svc.filter_expression(bad_expr)


def test_filter_expression_rejects_runtime_invalid_operations():
    svc = LedgerService()
    svc.add_transaction(occurred_on=date(2026, 11, 1), category="food", amount="20.00")

    with pytest.raises(ValueError):
        svc.filter_expression("tx.amount / 0 > 1")
    with pytest.raises(ValueError):
        svc.filter_expression("tx.category > 10")
    with pytest.raises(ValueError):
        svc.filter_expression("'a' * 1000000000")
    with pytest.raises(ValueError):
        svc.filter_expression("'%999999999s' % tx.category")
