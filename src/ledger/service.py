"""Core business logic for managing transactions, budgets, and reporting."""
from __future__ import annotations

import ast
import csv
import io
import math
import operator
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable

from .models import Budget, BudgetStatus, MonthlySummary, Transaction, TransactionKind

_CENT = Decimal("0.01")

_ALLOWED_TX_ATTRS = frozenset({"id", "occurred_on", "category", "amount", "kind", "description"})
_ALLOWED_DATE_ATTRS = frozenset({"year", "month", "day"})
_ALLOWED_CONSTANT_TYPES = (bool, int, float, str, type(None))

_COMPARE_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}

_NUMERIC_BINOPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _coerce_numeric_pair(left: Any, right: Any) -> tuple[Any, Any]:
    if isinstance(left, Decimal) and isinstance(right, float):
        if not math.isfinite(right):
            raise ValueError("non-finite float operand is not supported")
        return left, Decimal(str(right))
    if isinstance(left, float) and isinstance(right, Decimal):
        if not math.isfinite(left):
            raise ValueError("non-finite float operand is not supported")
        return Decimal(str(left)), right
    return left, right


def _validate_expr_node(node: ast.AST) -> None:
    if isinstance(node, ast.Expression):
        _validate_expr_node(node.body)
        return

    if isinstance(node, ast.Constant):
        if type(node.value) not in _ALLOWED_CONSTANT_TYPES:
            raise ValueError(f"unsupported literal type: {type(node.value).__name__}")
        return

    if isinstance(node, ast.Name):
        if not isinstance(node.ctx, ast.Load) or node.id != "tx":
            raise ValueError(f"disallowed name: {node.id}")
        return

    if isinstance(node, ast.Attribute):
        if not isinstance(node.ctx, ast.Load):
            raise ValueError("disallowed attribute context")
        if node.attr.startswith("_"):
            raise ValueError(f"disallowed attribute access: {node.attr}")
        if (
            isinstance(node.value, ast.Name)
            and isinstance(node.value.ctx, ast.Load)
            and node.value.id == "tx"
        ):
            if node.attr not in _ALLOWED_TX_ATTRS:
                raise ValueError(f"disallowed transaction attribute: {node.attr}")
            return
        if (
            isinstance(node.value, ast.Attribute)
            and isinstance(node.value.ctx, ast.Load)
            and isinstance(node.value.value, ast.Name)
            and isinstance(node.value.value.ctx, ast.Load)
            and node.value.value.id == "tx"
            and node.value.attr == "occurred_on"
        ):
            if node.attr not in _ALLOWED_DATE_ATTRS:
                raise ValueError(f"disallowed date attribute: {node.attr}")
            return
        raise ValueError(f"disallowed attribute access: {node.attr}")

    if isinstance(node, (ast.List, ast.Tuple)):
        if not isinstance(node.ctx, ast.Load):
            raise ValueError("disallowed container context")
        for elt in node.elts:
            _validate_expr_node(elt)
        return

    if isinstance(node, ast.Set):
        for elt in node.elts:
            _validate_expr_node(elt)
        return

    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if key is None:
                raise ValueError("dictionary unpacking is not allowed")
            _validate_expr_node(key)
            _validate_expr_node(value)
        return

    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise ValueError(f"disallowed boolean operator: {type(node.op).__name__}")
        for value in node.values:
            _validate_expr_node(value)
        return

    if isinstance(node, ast.Compare):
        _validate_expr_node(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            if type(op) not in _COMPARE_OPS:
                raise ValueError(f"disallowed comparison operator: {type(op).__name__}")
            _validate_expr_node(comparator)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.Not, ast.UAdd, ast.USub)):
            raise ValueError(f"disallowed unary operator: {type(node.op).__name__}")
        _validate_expr_node(node.operand)
        return

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            raise ValueError(f"disallowed binary operator: {type(node.op).__name__}")
        _validate_expr_node(node.left)
        _validate_expr_node(node.right)
        return

    raise ValueError(f"disallowed expression element: {type(node).__name__}")


def _parse_filter_expression(expr: str) -> ast.expr:
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("expression must be a non-empty string")
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError(f"invalid expression syntax: {exc}") from exc
    _validate_expr_node(tree)
    return tree.body


def _eval_expr_node(node: ast.AST, tx: Transaction) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id == "tx":
            return tx
        raise ValueError(f"disallowed name: {node.id}")

    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "tx":
            if node.attr in _ALLOWED_TX_ATTRS:
                return getattr(tx, node.attr)
        elif (
            isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "tx"
            and node.value.attr == "occurred_on"
            and node.attr in _ALLOWED_DATE_ATTRS
        ):
            return getattr(tx.occurred_on, node.attr)
        raise ValueError(f"disallowed attribute access: {node.attr}")

    if isinstance(node, ast.List):
        return [_eval_expr_node(elt, tx) for elt in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_eval_expr_node(elt, tx) for elt in node.elts)

    if isinstance(node, ast.Set):
        return {_eval_expr_node(elt, tx) for elt in node.elts}

    if isinstance(node, ast.Dict):
        return {
            _eval_expr_node(key, tx): _eval_expr_node(value, tx)
            for key, value in zip(node.keys, node.values)
            if key is not None
        }

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for value_node in node.values:
                result = _eval_expr_node(value_node, tx)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value_node in node.values:
                result = _eval_expr_node(value_node, tx)
                if result:
                    return result
            return result
        raise ValueError(f"disallowed boolean operator: {type(node.op).__name__}")

    if isinstance(node, ast.Compare):
        left = _eval_expr_node(node.left, tx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_expr_node(comparator, tx)
            op_func = _COMPARE_OPS[type(op)]
            if not op_func(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.UnaryOp):
        operand = _eval_expr_node(node.operand, tx)
        if isinstance(node.op, ast.Not):
            return not operand
        if not _is_number(operand):
            raise ValueError(f"unary arithmetic requires numeric operand, got {type(operand).__name__}")
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError(f"disallowed unary operator: {type(node.op).__name__}")

    if isinstance(node, ast.BinOp):
        left = _eval_expr_node(node.left, tx)
        right = _eval_expr_node(node.right, tx)
        if isinstance(node.op, ast.Add):
            if _is_number(left) and _is_number(right):
                left, right = _coerce_numeric_pair(left, right)
                return left + right
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            raise ValueError(
                f"unsupported operands for +: {type(left).__name__} and {type(right).__name__}"
            )
        op_func = _NUMERIC_BINOPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"disallowed binary operator: {type(node.op).__name__}")
        if not (_is_number(left) and _is_number(right)):
            raise ValueError(
                f"arithmetic operator {type(node.op).__name__} requires numeric operands"
            )
        left, right = _coerce_numeric_pair(left, right)
        return op_func(left, right)

    raise ValueError(f"disallowed expression element: {type(node).__name__}")


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
            if tx.kind != "expense":
                continue
            totals[tx.category] = (totals.get(tx.category, Decimal("0.00")) + tx.amount).quantize(_CENT)
        return totals

    def monthly_summary(self, year: int, month: int) -> MonthlySummary:
        """Returns income, expense, net, and category-level expense totals for a given month."""
        total_income = Decimal("0.00")
        total_expenses = Decimal("0.00")
        raw_expenses_by_category: dict[str, Decimal] = {}
        for tx in self._transactions:
            if tx.occurred_on.year != year or tx.occurred_on.month != month:
                continue
            if tx.kind == "income":
                total_income += tx.amount
            elif tx.kind == "expense":
                total_expenses += tx.amount
                raw_expenses_by_category[tx.category] = (
                    raw_expenses_by_category.get(tx.category, Decimal("0.00")) + tx.amount
                )
        quantized_income = total_income.quantize(_CENT)
        quantized_expenses = total_expenses.quantize(_CENT)
        net = (quantized_income - quantized_expenses).quantize(_CENT)
        expenses_by_category = {
            category: amount.quantize(_CENT)
            for category, amount in raw_expenses_by_category.items()
        }
        return MonthlySummary(
            year=year,
            month=month,
            total_income=quantized_income,
            total_expenses=quantized_expenses,
            net=net,
            expenses_by_category=expenses_by_category,
        )

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

    def filter_expression(self, expr: str) -> list[Transaction]:
        """Filters transactions using a validated safe expression over `tx`."""
        parsed = _parse_filter_expression(expr)
        matched: list[Transaction] = []
        for tx in self._transactions:
            try:
                result = _eval_expr_node(parsed, tx)
            except (TypeError, ZeroDivisionError, ArithmeticError, InvalidOperation) as exc:
                raise ValueError(f"expression evaluation failed: {exc}") from exc
            if bool(result):
                matched.append(tx)
        return matched

    def export_csv(self) -> str:
        """Exports all transactions as a CSV string."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "occurred_on", "category", "kind", "amount", "description"])
        for tx in self._transactions:
            writer.writerow([tx.id, tx.occurred_on.isoformat(), tx.category, tx.kind, str(tx.amount), tx.description])
        return buffer.getvalue()
