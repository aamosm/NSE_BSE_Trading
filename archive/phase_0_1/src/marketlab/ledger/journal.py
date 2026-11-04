"""Append-only double-entry journal in rupees.

Sign convention: debit = positive, credit = negative. Assets and expenses therefore carry positive
balances; liabilities, equity and income carry negative balances. Every entry must sum to zero and
every amount must already be exact to the paisa (rounding is the caller's documented decision).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

PAISA = Decimal("0.01")
ZERO = Decimal("0")


class LedgerError(Exception):
    """An accounting operation that would make the books wrong or inconsistent."""


@dataclass(frozen=True, slots=True)
class Posting:
    account: str
    amount: Decimal  # debit +, credit -


@dataclass(frozen=True, slots=True)
class JournalEntry:
    entry_id: int
    on: date
    kind: str
    memo: str
    postings: tuple[Posting, ...]
    ref: str = ""  # fill/event id that caused it


class Journal:
    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._balances: dict[str, Decimal] = defaultdict(lambda: ZERO)

    def post(self, on: date, kind: str, memo: str, postings: Iterable[Posting], ref: str = "") -> JournalEntry:
        ps = tuple(p for p in postings if p.amount != 0)
        if not ps:
            raise LedgerError(f"{kind}: entry has no non-zero postings")
        for p in ps:
            if not isinstance(p.amount, Decimal):
                raise LedgerError(f"{p.account}: amounts must be Decimal")
            if p.amount != p.amount.quantize(PAISA):
                raise LedgerError(f"{p.account}: {p.amount} is not exact to the paisa")
        total = sum((p.amount for p in ps), ZERO)
        if total != 0:
            raise LedgerError(f"{kind}: unbalanced entry (sum {total})")
        entry = JournalEntry(len(self._entries) + 1, on, kind, memo, ps, ref)
        self._entries.append(entry)
        for p in ps:
            self._balances[p.account] += p.amount
        return entry

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

    def balance(self, account: str) -> Decimal:
        return self._balances.get(account, ZERO)

    def balances(self, prefix: str = "") -> dict[str, Decimal]:
        return {a: b for a, b in sorted(self._balances.items()) if a.startswith(prefix) and b != 0}

    def total(self, prefix: str) -> Decimal:
        return sum((b for a, b in self._balances.items() if a.startswith(prefix)), ZERO)

    def trial_balance(self) -> Decimal:
        """Sum of all balances; zero for a consistent journal."""
        return sum(self._balances.values(), ZERO)
