# ledger-demo

A minimal, zero-dependency Python expense and budget ledger designed for demonstrating multi-agent SDLC workflows.

## Structure

- `src/ledger/models.py` — `Transaction`, `Budget`, and `BudgetStatus` dataclasses
- `src/ledger/store.py` — JSON persistence helpers
- `src/ledger/service.py` — `LedgerService` business logic (transactions, balances, budgets, CSV export, search)
- `tests/test_ledger.py` — `pytest` unit test suite

## Running Tests

```bash
python -m pytest -q
```
