"""Series/group classification and surveillance-framework restrictions.

The common belief that 'low-priced stocks cannot be traded intraday' is, in the rules, a set of
classifications that often *coincide* with low prices and small market caps: trade-for-trade
(T2T) series, GSM/ESM/ASM/IBC surveillance stages, periodic call auctions and broker intraday
lists. A stock's price alone does not move it into T2T. What price alone changes is its tick size
(Rs 0.01 below Rs 250) and the absolute market-protection floor (Rs 1.5 at LTP <= Rs 50).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .provenance import Cite, Status
from .types import Exchange, Framework, RuleUnknown, SurveillanceFlag

D = Decimal


@dataclass(frozen=True, slots=True)
class SeriesRule:
    exchange: Exchange
    code: str
    trade_for_trade: bool = False
    in_scope: bool = True  # project scope (main-board equity, T+1 rolling or T2T)
    broker_blocks_mis: bool = False
    broker_blocks_btst: bool = False
    broker_blocks_fresh_buy: bool = False
    cite: Cite = field(default_factory=lambda: Cite((), Status.UNKNOWN))
    note: str = ""


_T2T_NSE = Cite(("NSE/CMTR/73927",), Status.PRIMARY,
                "Trade-for-trade securities trade in BE/BZ series; settled trade by trade with no netting (section 1.4).")
_SCOPE = Cite(("PROJECT/POLICY",), Status.ASSUMPTION, "Outside the initial project universe.")
_BSE_T2T = Cite(("ZERODHA/RMS-XT",), Status.BROKER_OFFICIAL,
                "XT, T (and NSE BE) delivery only; intraday and BTST blocked; selling before demat credit rejected.")
_BSE_SUMMARY = Cite(("ZERODHA/BSE-GROUPS-SUMMARY",), Status.SECONDARY,
                    "From search summaries of Zerodha articles; read the articles before live use.")

SERIES_RULES: dict[tuple[Exchange, str], SeriesRule] = {(r_.exchange, r_.code): r_ for r_ in (
    # NSE
    SeriesRule(Exchange.NSE, "EQ", cite=Cite(("NSE/CMTR/73927",), Status.PRIMARY, "Rolling settlement series.")),
    SeriesRule(Exchange.NSE, "BE", trade_for_trade=True, broker_blocks_mis=True, broker_blocks_btst=True,
               cite=_T2T_NSE),
    SeriesRule(Exchange.NSE, "BZ", trade_for_trade=True, broker_blocks_mis=True, broker_blocks_btst=True,
               cite=_T2T_NSE, note="Companies not complying with listing requirements."),
    SeriesRule(Exchange.NSE, "SM", in_scope=False, cite=_SCOPE, note="SME (lot-based)."),
    SeriesRule(Exchange.NSE, "ST", in_scope=False, cite=_SCOPE, note="SME trade-for-trade."),
    SeriesRule(Exchange.NSE, "SZ", in_scope=False, cite=_SCOPE, note="SME non-compliant."),
    SeriesRule(Exchange.NSE, "T0", in_scope=False, cite=_SCOPE, note="Optional T+0 beta series."),
    SeriesRule(Exchange.NSE, "BL", in_scope=False, cite=_SCOPE, note="Block deal window."),
    # BSE
    SeriesRule(Exchange.BSE, "A", cite=Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
                                            "Treated as normal rolling group; BSE group definitions not yet read.")),
    SeriesRule(Exchange.BSE, "B", cite=Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION,
                                            "Treated as normal rolling group; BSE group definitions not yet read.")),
    SeriesRule(Exchange.BSE, "T", trade_for_trade=True, broker_blocks_mis=True, broker_blocks_btst=True,
               cite=_BSE_T2T),
    SeriesRule(Exchange.BSE, "XT", trade_for_trade=True, broker_blocks_mis=True, broker_blocks_btst=True,
               cite=_BSE_T2T),
    SeriesRule(Exchange.BSE, "X", broker_blocks_mis=True, broker_blocks_btst=True, cite=_BSE_SUMMARY),
    SeriesRule(Exchange.BSE, "Z", broker_blocks_mis=True, broker_blocks_btst=True, cite=_BSE_SUMMARY,
               note="BTST block is our conservative assumption."),
    SeriesRule(Exchange.BSE, "ZP", broker_blocks_mis=True, broker_blocks_btst=True, broker_blocks_fresh_buy=True,
               cite=_BSE_SUMMARY, note="Buys blocked: CDSL does not allow credit."),
    SeriesRule(Exchange.BSE, "P", broker_blocks_mis=True, broker_blocks_btst=True, broker_blocks_fresh_buy=True,
               cite=_BSE_SUMMARY, note="Buys blocked: CDSL does not allow credit."),
    *(SeriesRule(Exchange.BSE, g, in_scope=False, cite=_SCOPE, note="SME / institutional trading platform.")
      for g in ("M", "MT", "MS", "TS", "SS", "ST")),
)}


def series_rule(exchange: Exchange, code: str) -> SeriesRule:
    try:
        return SERIES_RULES[(exchange, code.upper())]
    except KeyError:
        raise RuleUnknown(f"Series/group {code!r} on {exchange} is not classified") from None


# ---------------------------------------------------------------------------------------------
# Surveillance frameworks
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Restrictions:
    trade_for_trade: bool = False
    max_band_pct: Decimal | None = None  # band must be at or below this
    margin_pct: Decimal | None = None  # exchange minimum margin on the position
    asd_pct: Decimal | None = None  # Additional Surveillance Deposit from buyers
    once_a_week: bool = False
    no_upward_movement: bool = False
    call_auction_only: bool = False
    broker_blocks_fresh_buy: bool = False
    broker_blocks_mis: bool = False
    cites: tuple[Cite, ...] = ()
    labels: tuple[str, ...] = ()

    def merge(self, o: Restrictions) -> Restrictions:
        def mn(a: Decimal | None, b: Decimal | None) -> Decimal | None:
            return b if a is None else a if b is None else min(a, b)

        def mx(a: Decimal | None, b: Decimal | None) -> Decimal | None:
            return b if a is None else a if b is None else max(a, b)

        return Restrictions(
            trade_for_trade=self.trade_for_trade or o.trade_for_trade,
            max_band_pct=mn(self.max_band_pct, o.max_band_pct),
            margin_pct=mx(self.margin_pct, o.margin_pct),
            asd_pct=mx(self.asd_pct, o.asd_pct),
            once_a_week=self.once_a_week or o.once_a_week,
            no_upward_movement=self.no_upward_movement or o.no_upward_movement,
            call_auction_only=self.call_auction_only or o.call_auction_only,
            broker_blocks_fresh_buy=self.broker_blocks_fresh_buy or o.broker_blocks_fresh_buy,
            broker_blocks_mis=self.broker_blocks_mis or o.broker_blocks_mis,
            cites=self.cites + o.cites,
            labels=self.labels + o.labels,
        )


@dataclass(frozen=True, slots=True)
class StageRule:
    framework: Framework
    stage: int
    effective_from: date
    effective_to: date | None
    r: Restrictions


_GSM = Cite(("NSE/SURV/71526",), Status.PRIMARY, "Stage-wise GSM actions (4-stage framework).")
_GSM_Z = Cite(("ZERODHA/GSM2", "ZERODHA/MIS-BLOCKS"), Status.BROKER_OFFICIAL,
              "Zerodha blocks fresh buys at GSM stage 2+ (does not collect ASD) and blocks MIS on GSM stocks.")
_GSM_START = date(2023, 11, 17)  # NSE/SURV/59425 revision cited by NSE/SURV/71526; start date not read directly
_ESM = Cite(("NSE/ESM-FAQ-1.1",), Status.PRIMARY, "ESM stage actions (FAQ v1.1, July 2025).")
_ESM_START = date(2025, 7, 25)
_IBC = Cite(("NSE/SURV/75652",), Status.PRIMARY, "Revised IBC framework (non-derivative securities).")
_IBC_Z = Cite(("ZERODHA/SURV-INDICATORS",), Status.BROKER_OFFICIAL, "Zerodha blocks fresh buys where ASD applies.")
_IBC_START = date(2026, 8, 10)
_ASM = Cite(("NSE/ASM-2026-SUMMARY", "ZERODHA/ASM-SUMMARY"), Status.SECONDARY,
            "ASM stage margins not read from primary source. MIS block is our conservative assumption.")
_ASM_T2T = Cite(("ZERODHA/SURV-INDICATORS",), Status.BROKER_OFFICIAL, "LT-ASM stage 4 moves the stock to T2T.")
_ASM_START = date(2026, 1, 1)
_USM = Cite(("ZERODHA/MIS-BLOCKS",), Status.BROKER_OFFICIAL, "Zerodha blocks MIS for the unsolicited SMS category.")
_NPH = Cite(("NSE/CMTR/73927",), Status.PRIMARY, "Non-promoter holding < 25%: maximum price band 10% (section 3.1 F).")

STAGE_RULES: tuple[StageRule, ...] = (
    StageRule(Framework.GSM, 1, _GSM_START, None, Restrictions(
        max_band_pct=D("5"), margin_pct=D("100"), broker_blocks_mis=True,
        cites=(_GSM, _GSM_Z), labels=("GSM I",))),
    StageRule(Framework.GSM, 2, _GSM_START, None, Restrictions(
        trade_for_trade=True, max_band_pct=D("5"), asd_pct=D("50"), broker_blocks_fresh_buy=True,
        broker_blocks_mis=True, cites=(_GSM, _GSM_Z), labels=("GSM II",))),
    StageRule(Framework.GSM, 3, _GSM_START, None, Restrictions(
        trade_for_trade=True, max_band_pct=D("5"), asd_pct=D("100"), once_a_week=True,
        broker_blocks_fresh_buy=True, broker_blocks_mis=True,
        cites=(_GSM, _GSM_Z), labels=("GSM III",))),
    StageRule(Framework.GSM, 4, _GSM_START, None, Restrictions(
        trade_for_trade=True, max_band_pct=D("5"), asd_pct=D("100"), once_a_week=True, no_upward_movement=True,
        broker_blocks_fresh_buy=True, broker_blocks_mis=True,
        cites=(_GSM, _GSM_Z), labels=("GSM IV",))),
    StageRule(Framework.ESM, 1, _ESM_START, None, Restrictions(
        trade_for_trade=True, max_band_pct=D("5"), margin_pct=D("100"), broker_blocks_mis=True,
        cites=(_ESM,), labels=("ESM I",))),
    StageRule(Framework.ESM, 2, _ESM_START, None, Restrictions(
        trade_for_trade=True, max_band_pct=D("2"), margin_pct=D("100"), call_auction_only=True,
        broker_blocks_mis=True, cites=(_ESM,), labels=("ESM II",))),
    StageRule(Framework.IBC, 0, _IBC_START, None, Restrictions(
        trade_for_trade=True, max_band_pct=D("5"), margin_pct=D("100"), broker_blocks_mis=True,
        cites=(_IBC,), labels=("IBC 0",))),
    StageRule(Framework.IBC, 1, _IBC_START, None, Restrictions(
        trade_for_trade=True, max_band_pct=D("2"), margin_pct=D("100"), asd_pct=D("100"),
        broker_blocks_fresh_buy=True, broker_blocks_mis=True,
        cites=(_IBC, _IBC_Z), labels=("IBC I",))),
    StageRule(Framework.IBC, 2, _IBC_START, None, Restrictions(
        trade_for_trade=True, max_band_pct=D("2"), margin_pct=D("100"), asd_pct=D("100"), once_a_week=True,
        broker_blocks_fresh_buy=True, broker_blocks_mis=True,
        cites=(_IBC, _IBC_Z), labels=("IBC II",))),
    *(StageRule(Framework.LT_ASM, s, _ASM_START, None, Restrictions(
        broker_blocks_mis=True, cites=(_ASM,), labels=(f"LT-ASM {s}",)))
      for s in (1, 2, 3)),
    StageRule(Framework.LT_ASM, 4, _ASM_START, None, Restrictions(
        trade_for_trade=True, broker_blocks_mis=True, cites=(_ASM, _ASM_T2T),
        labels=("LT-ASM 4",))),
    *(StageRule(Framework.ST_ASM, s, _ASM_START, None, Restrictions(
        broker_blocks_mis=True, cites=(_ASM,), labels=(f"ST-ASM {s}",)))
      for s in (1, 2)),
    StageRule(Framework.USM, 1, _ASM_START, None, Restrictions(
        broker_blocks_mis=True, cites=(_USM,), labels=("USM",))),
    StageRule(Framework.LOW_NPH, 1, date(2022, 4, 22), None, Restrictions(
        max_band_pct=D("10"), cites=(_NPH,), labels=("Low non-promoter holding",))),
)


def stage_rule(flag: SurveillanceFlag, on: date) -> StageRule:
    for r in STAGE_RULES:
        if (r.framework is flag.framework and r.stage == flag.stage and r.effective_from <= on
                and (r.effective_to is None or on <= r.effective_to)):
            return r
    raise RuleUnknown(f"No verified rule for {flag.framework} stage {flag.stage} on {on}")


def restrictions_for(flags: frozenset[SurveillanceFlag], on: date) -> Restrictions:
    merged = Restrictions()
    for f in sorted(flags, key=lambda f: (f.framework, f.stage)):
        merged = merged.merge(stage_rule(f, on).r)
    return merged
