"""JSON file persistence for ledger transactions."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import Transaction


def save_transactions(path: Path, transactions: list[Transaction]) -> None:
    """Writes transactions as formatted JSON."""
    payload = [
        {
            "id": tx.id,
            "occurred_on": tx.occurred_on.isoformat(),
            "category": tx.category,
            "amount": str(tx.amount),
            "kind": tx.kind,
            "description": tx.description,
        }
        for tx in transactions
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_transactions(path: Path) -> list[Transaction]:
    """Loads transactions from a JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Transaction(
            id=item["id"],
            occurred_on=date.fromisoformat(item["occurred_on"]),
            category=item["category"],
            amount=Decimal(item["amount"]),
            kind=item.get("kind", "expense"),
            description=item.get("description", ""),
        )
        for item in raw
    ]
