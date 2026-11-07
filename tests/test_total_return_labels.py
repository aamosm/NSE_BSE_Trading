import math
from datetime import date
from types import SimpleNamespace

import pytest

from marketlab.quant import labels
from marketlab.quant.panel import Panel
from synthetic import WeekdayCalendar, index_csv, row, sessions


class DividendActions:
    def __init__(self, isin, ex_date):
        self.action = SimpleNamespace(dividend_cash=10.0, price_factor=None)
        self.isin = isin
        self.ex_date = ex_date

    def factor(self, isin, day):
        return None

    def get(self, isin, day):
        return self.action if (isin, day) == (self.isin, self.ex_date) else None


def test_forward_label_includes_dividend_cash_and_optional_tri(tmp_path):
    days = sessions(6, date(2026, 1, 5))
    isin = "INE00AA01001"
    panel = Panel(tmp_path / "panel.sqlite3")
    for day in days:
        panel.add_session(day, [row(isin, "AAA", 100.0, 101.0, 99.0, 100.0, 100.0, 100_000, 10_000_000)])
        panel.add_index_file(day, index_csv(day, 10_000.0))
    panel.compute_implied_factors(WeekdayCalendar())
    panel.compute_discontinuities(WeekdayCalendar())

    action = DividendActions(isin, days[2])
    tri = {days[1]: (10_000.0, 0.0), days[3]: (10_100.0, 0.0)}
    label = labels.forward_return(panel, isin, days[0], 2, sessions=days, actions=action,
                                  benchmark_total_return_index=tri)

    assert label.status == labels.RESOLVED
    assert label.gross == pytest.approx(0.0)
    assert label.dividend_cash == pytest.approx(10.0)
    assert label.total_return == pytest.approx(0.10)
    assert label.total_return_log == pytest.approx(math.log(1.1))
    assert label.relative_total_return == pytest.approx(math.log(1.1) - math.log(1.01))
    panel.close()
