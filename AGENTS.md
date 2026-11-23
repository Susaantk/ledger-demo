# AGENTS.md — Repository Context for ledger-demo

`ledger-demo` is a small, pure-Python (3.12 stdlib only) expense and budget tracking library.

## Directory Map

| Path | Responsibility |
| --- | --- |
| `src/ledger/models.py` | Immutable `Transaction`, `Budget`, and `BudgetStatus` dataclasses |
| `src/ledger/store.py` | JSON serialization (`save_transactions`, `load_transactions`) |
| `src/ledger/service.py` | `LedgerService`: adding transactions, balances, category totals, budget tracking, search, CSV export |
| `tests/test_ledger.py` | `pytest` unit tests (`pythonpath = src` configured in `pytest.ini`) |

## Guidelines

1. **Zero third-party runtime dependencies:** Use Python 3.12 standard library only (`dataclasses`, `datetime`, `decimal`, `csv`, `json`, `pathlib`, `typing`).
2. **Money precision:** Amounts use `Decimal` (quantized to 2 decimal places when summarizing) to avoid float rounding errors.
3. **Security hygiene:** Never use `eval`/`exec`, avoid path traversal on file paths, and guard CSV exports against formula injection.
4. **Tests:** Run `python -m pytest -q` and keep every test passing; add unit tests in `tests/test_ledger.py` for any bug fix or new feature.
