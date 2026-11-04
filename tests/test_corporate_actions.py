"""Corporate actions and price provenance. Every expected number is worked by hand in the comment."""
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from marketlab.common import IST
from marketlab.corporate_actions import (
    ActionKind, AdjustmentBasis, Bar, CorporateAction, DoubleAdjustment, PriceSeries, SeriesKind, Unmodelled,
    adjust, apply_to_position, provider_series, reconcile_provider,
)

ISIN = "INE000A00001"
EX = date(2026, 11, 3)
NOW = datetime(2026, 11, 5, 18, tzinfo=IST)


def bar(d, close, volume=100):
    c = D(close)
    return Bar(d, c, c, c, c, volume)


def exchange(*bars, sid="nse-raw"):
    return PriceSeries(sid, SeriesKind.EXCHANGE_UNADJUSTED, ISIN, "NSE", "NSE bhavcopy", NOW, AdjustmentBasis.NONE,
                       tuple(bars))


SPLIT = CorporateAction("CA-SPLIT", ISIN, ActionKind.SPLIT, EX, EX, old_fv=D(10), new_fv=D(2))  # 1 -> 5 shares
BONUS = CorporateAction("CA-BONUS", ISIN, ActionKind.BONUS, EX, EX, ratio_new=1, ratio_held=1)  # 1:1
DIV = CorporateAction("CA-DIV", ISIN, ActionKind.DIVIDEND, EX, EX, payment_date=date(2026, 11, 20),
                      cash_per_share=D(5))
RAW = exchange(bar(date(2026, 11, 2), "1000", 100), bar(EX, "205", 600))


def test_split_adjusts_earlier_prices_and_volumes():
    adj = adjust(RAW, [SPLIT], derived_at=NOW, series_id="adj1")
    # factor 2/10 = 0.2: 1000 -> 200; volume 100 / 0.2 = 500; ex-date bar unchanged
    assert adj.bars[0].close == D("200.0") and adj.bars[0].volume == 500 and adj.bars[1] == RAW.bars[1]
    assert adj.kind is SeriesKind.DERIVED_ADJUSTED and adj.applied_action_ids == ("CA-SPLIT",)
    assert adj.parent_series_id == "nse-raw" and adj.basis is AdjustmentBasis.LISTED_ACTIONS


def test_bonus_factor():
    # 1:1 bonus: factor 1/2 -> 1000 becomes 500
    assert adjust(RAW, [BONUS], derived_at=NOW, series_id="b").bars[0].close == D("500")


def test_dividend_only_in_total_return_series():
    raw = exchange(bar(date(2026, 11, 2), "100"), bar(EX, "96"))
    assert adjust(raw, [DIV], derived_at=NOW, series_id="p").bars[0].close == D("100")  # price series ignores it
    tr = adjust(raw, [DIV], total_return=True, derived_at=NOW, series_id="t")
    assert tr.bars[0].close == D("95.00")  # factor (100 - 5) / 100 = 0.95
    assert tr.kind is SeriesKind.DERIVED_TOTAL_RETURN and tr.applied_action_ids == ("CA-DIV",)


@pytest.mark.parametrize("make", [
    lambda: provider_series(ISIN, "NSE", "kite", NOW, RAW.bars, "kite-v1"),  # basis unknown: may be adjusted
    lambda: adjust(RAW, [SPLIT], derived_at=NOW, series_id="adj"),  # already derived
])
def test_adjusting_provider_or_derived_data_is_refused(make):
    with pytest.raises(DoubleAdjustment):
        adjust(make(), [SPLIT], derived_at=NOW, series_id="again")


def test_the_same_action_cannot_be_listed_twice():
    with pytest.raises(DoubleAdjustment):
        adjust(RAW, [SPLIT, SPLIT], derived_at=NOW, series_id="x")


def test_action_for_another_security_is_refused():
    other = CorporateAction("CA-X", "INE000B00002", ActionKind.SPLIT, EX, EX, old_fv=D(10), new_fv=D(5))
    with pytest.raises(ValueError, match="another security"):
        adjust(RAW, [other], derived_at=NOW, series_id="x")


def test_position_effects_quantity_cost_and_dividend_timing():
    # Split 10 -> 2: 7 shares become 35; total cost unchanged
    assert apply_to_position(7, D("7000"), SPLIT).quantity == 35
    # Bonus 1:1 on 3 shares: 6 shares, cost still 300 (50 per share)
    b = apply_to_position(3, D("300"), BONUS)
    assert (b.quantity, b.cost_total) == (6, D("300"))
    # Dividend Rs 5 on 10 entitled shares: Rs 50 receivable, paid on 20 Nov, not on the ex-date
    d = apply_to_position(10, D("1000"), DIV)
    assert (d.quantity, d.dividend_receivable, d.dividend_payment_date) == (10, D("50"), date(2026, 11, 20))
    assert "TDS_UNMODELLED" in d.notes


def test_fractions_and_unmodelled_actions_are_reported_not_guessed():
    bonus_1_for_2 = CorporateAction("CA-B2", ISIN, ActionKind.BONUS, EX, EX, ratio_new=1, ratio_held=2)
    e = apply_to_position(3, D("300"), bonus_1_for_2)  # 3 x 1/2 = 1.5 -> 1 whole share, fraction reported
    assert e.quantity == 4 and "FRACTIONAL_BONUS_ENTITLEMENT_UNMODELLED" in e.notes
    odd_split = CorporateAction("CA-S3", ISIN, ActionKind.SPLIT, EX, EX, old_fv=D(10), new_fv=D(3))
    with pytest.raises(Unmodelled):
        apply_to_position(1, D("10"), odd_split)  # 10/3 shares
    rights = CorporateAction("CA-R", ISIN, ActionKind.RIGHTS, EX, EX)
    with pytest.raises(Unmodelled):
        apply_to_position(1, D("10"), rights)
    no_pay_date = CorporateAction("CA-D2", ISIN, ActionKind.DIVIDEND, EX, EX, cash_per_share=D(1))
    with pytest.raises(Unmodelled, match="payment date"):
        apply_to_position(1, D("10"), no_pay_date)


def test_provider_reconciliation_detects_adjusted_and_unadjusted_vintages():
    adjusted_kite = provider_series(ISIN, "NSE", "kite", NOW, (bar(date(2026, 11, 2), "200"), bar(EX, "205")), "k2")
    ok = reconcile_provider(adjusted_kite, RAW, [SPLIT])
    assert ok["consistent"] and ok["rows"][0]["expected_ratio"] == D("0.2")
    # Same values retrieved BEFORE the ex-date would not yet be adjusted: 200 vs 1000 is then a mismatch.
    early = provider_series(ISIN, "NSE", "kite", datetime(2026, 11, 2, 18, tzinfo=IST),
                            (bar(date(2026, 11, 2), "200"),), "k1")
    assert reconcile_provider(early, RAW, [SPLIT])["mismatched_days"] == [date(2026, 11, 2)]
    # An unadjusted provider series after the ex-date is inconsistent (double- or non-adjustment risk).
    stale = provider_series(ISIN, "NSE", "kite", NOW, RAW.bars, "k3")
    assert reconcile_provider(stale, RAW, [SPLIT])["consistent"] is False


def test_series_digest_changes_with_values():
    assert RAW.digest() != exchange(bar(date(2026, 11, 2), "1001", 100), bar(EX, "205", 600)).digest()
