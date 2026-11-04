"""Source registry and verification status for every encoded rule.

Each rule in this package cites one or more source IDs below and carries a
``Status``. The engine treats UNKNOWN required inputs as blocking, and
CONFLICTING rules resolve to the more restrictive reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Status(StrEnum):
    PRIMARY = "PRIMARY"
    """Read directly in an exchange, clearing-corporation or SEBI document."""

    BROKER_OFFICIAL = "BROKER_OFFICIAL"
    """Read directly on Zerodha's own site/docs. Broker policy; may change without a circular."""

    SECONDARY = "SECONDARY"
    """Seen only in a third-party summary or search snippet. Must be confirmed before live use."""

    CONFLICTING = "CONFLICTING"
    """Sources disagree. The engine applies the more restrictive reading."""

    ASSUMPTION = "ASSUMPTION"
    """Our modelling choice; no source states it. Must be reconciled against statements."""

    UNKNOWN = "UNKNOWN"
    """Not determined. Where the input is required, the engine blocks."""


class SourceKind(StrEnum):
    REGULATOR = "REGULATOR"
    EXCHANGE = "EXCHANGE"
    CLEARING = "CLEARING"
    BROKER = "BROKER"
    THIRD_PARTY = "THIRD_PARTY"


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    title: str
    publisher: str
    kind: SourceKind
    url: str
    doc_date: date | None
    checked_on: date
    note: str = ""


CHECKED = date(2026, 11, 4)
CHECKED_2 = date(2026, 11, 5)

_SOURCES: tuple[Source, ...] = (
    # ---- NSE / NSE Clearing / SEBI (primary) -------------------------------------------
    Source("NSE/CMTR/73927", "Capital Market Consolidated Circular (sessions, settlement, T2T, price bands, "
           "tick size, MPP, SL-limit validation, index circuit filter, short selling, 2026 holidays)",
           "NSE", SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/CMTR73927.zip",
           date(2026, 4, 28), CHECKED, "Compiles circulars to 31 Mar 2026; later circulars below supersede parts."),
    Source("NSE/CMTR/67133", "Revision in tick size of securities in CM segment - Update", "NSE",
           SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/CMTR67133.pdf",
           date(2025, 3, 13), CHECKED),
    Source("NSE/SURV/71526", "Securities moving to GSM Stage II (annexure: stage-wise GSM actions)", "NSE",
           SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/SURV71526.pdf",
           date(2025, 11, 28), CHECKED),
    Source("NSE/ESM-FAQ-1.1", "FAQ on Enhanced Surveillance Measure (ESM) v1.1", "NSE", SourceKind.EXCHANGE,
           "https://nsearchives.nseindia.com/web/sites/default/files/inline-files/"
           "FAQs%20-%20Enhanced%20Surveillance%20Measure%20%28ESM%29_25.7.2025.pdf",
           date(2025, 7, 25), CHECKED, "FAQ defers to circulars where they differ."),
    Source("NSE/SURV/75652", "Surveillance Measure for securities under IBC - Update (effective 10 Aug 2026)",
           "NSE", SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/SURV75652.pdf",
           date(2026, 8, 7), CHECKED),
    Source("NSE/CMTR/68802", "Algo Market Order pre-emptive cancellation (CM, effective 7 Jul 2025)", "NSE",
           SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/CMTR68802.pdf",
           date(2025, 6, 30), CHECKED),
    Source("SEBI/CAS-2026", "SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/2765/2026: Closing Auction Session "
           "and Pre-Open modifications (annexure to NSE/CMTR/72394)", "SEBI", SourceKind.REGULATOR,
           "https://nsearchives.nseindia.com/content/circulars/CMTR72394.zip", date(2026, 1, 16), CHECKED),
    Source("NSE/CMTR/73362", "Operational guidelines/SOP on Closing Auction Session (reference price, +/-3% band)",
           "NSE", SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/CMTR73362.pdf",
           date(2026, 3, 18), CHECKED),
    Source("NSE/CMTR/74969", "Modifications in the Pre-Open Call Auction framework (effective 7 Sep 2026)", "NSE",
           SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/CMTR74969.zip",
           date(2026, 7, 1), CHECKED),
    Source("NCL/CMPT/71904", "CM - Settlement Holidays for the Calendar Year 2026", "NSE Clearing",
           SourceKind.CLEARING, "https://nsearchives.nseindia.com/content/circulars/CMPT71904.pdf",
           date(2025, 12, 22), CHECKED),
    Source("NSE/2026-01-15-HOLIDAY", "CM changes in settlement schedule due to trading and settlement holiday on "
           "January 15, 2026 (title seen on a circular mirror; NSE original not yet read)", "NSE (via mirror)",
           SourceKind.THIRD_PARTY,
           "https://rhnvrm.github.io/stock-market-circulars/circulars/nse/2026/"
           "nse-2026-01-12-cf2aed00f9317bde-cm-changes-in-settlement-schedule-due-to-trading-and-settlement-"
           "holiday-on-janua", date(2026, 1, 12), CHECKED),
    Source("NSE/CMTR/72349", "Live Trading Session on February 01, 2026 - Presentation of Union Budget", "NSE",
           SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf",
           date(2026, 1, 16), CHECKED),
    Source("NCL/CMPT/72384", "Settlement schedule ... Live Trading Session on Sunday February 01, 2026",
           "NSE Clearing", SourceKind.CLEARING, "https://nsearchives.nseindia.com/content/circulars/CMPT72384.pdf",
           date(2026, 1, 19), CHECKED),
    Source("NSE/CMTR/76941", "Muhurat Trading session on account of Diwali (Sunday 8 Nov 2026)", "NSE",
           SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/CMTR76941.pdf",
           date(2026, 10, 19), CHECKED_2, "Session table read in full on 5 Nov 2026."),
    Source("NCL/CMPT/77037", "Timings on Muhurat Trading session (settlement schedule)", "NSE Clearing",
           SourceKind.CLEARING, "https://nsearchives.nseindia.com/content/circulars/CMPT77037.pdf",
           date(2026, 10, 21), CHECKED_2, "8 Nov trades: settlement M 2026211, settlement date 9 Nov 2026."),
    Source("NSE/INSP/45900", "Modifications in the STP messaging formats on account of implementation of the "
           "Stamp Duty", "NSE", SourceKind.EXCHANGE, "https://nsearchives.nseindia.com/content/circulars/INSP45900.pdf",
           date(2020, 9, 30), CHECKED_2, "Contract-note STT field (COUN) allows integer values only."),
    Source("STT-RULES-2004-DRAFT", "Securities Transaction Tax rules, 2004 draft: aggregation per client code, "
           "security and trading day (third-party copy)", "via scribd.com", SourceKind.THIRD_PARTY,
           "https://www.scribd.com/document/252690660/STT", None, CHECKED_2,
           "Draft text seen through a search summary; final rules not read."),
    # ---- Zerodha / Kite (broker official) ----------------------------------------------
    Source("ZERODHA/CHARGES", "Zerodha charges list", "Zerodha", SourceKind.BROKER, "https://zerodha.com/charges/",
           None, CHECKED, "Page shows no effective dates; values are a 2026-11-04 snapshot."),
    Source("ZERODHA/STT-ROUNDING", "How is the Securities Transaction Tax (STT) calculated?", "Zerodha",
           SourceKind.BROKER, "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/"
           "articles/how-is-the-securities-transaction-tax-stt-calculated", None, CHECKED_2,
           "STT rounded to the nearest rupee (50 paise and above up); aggregation level not stated."),
    Source("ZERODHA/DP-CHARGES", "What do DP charges mean?", "Zerodha", SourceKind.BROKER,
           "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/"
           "what-do-dp-charges-mean", None, CHECKED_2,
           "Once per scrip per sell day; funds statement, not contract note; 15.34 / 15.05 incl. GST."),
    Source("KITE/CA-ADJUSTMENT", "Kite charts not matching NSE/BSE records (corporate-action adjustment)", "Zerodha",
           SourceKind.BROKER, "https://support.zerodha.com/category/trading-and-markets/charts-and-orders/charts/"
           "articles/kite-charts-not-matching-as-per-the-records-in-nse-or-bse", None, CHECKED_2,
           "Historical OHLC adjusted for bonus, split, rights, spin-off and extraordinary dividends (>= 2%)."),
    Source("KITE/CA-FORUM-15971", "Kite forum: getting the right closing prices adjusted for corporate actions",
           "Zerodha (forum staff)", SourceKind.BROKER,
           "https://kite.trade/forum/discussion/15971/getting-the-right-closing-prices-adjusted-for-corporate-actions",
           None, CHECKED_2, "Adjusted before market open on the ex-date; volume adjusted except for dividends; "
           "no corporate-action API."),
    Source("ZERODHA/MTF-FAQ", "FAQs on Margin Trading Facility", "Zerodha", SourceKind.BROKER,
           "https://support.zerodha.com/category/trading-and-markets/margins/margin-trading-facility/articles/"
           "margin-trading-facility-mtf-faqs", None, CHECKED),
    Source("ZERODHA/MTF-LEDGER", "MTF funds statement entries", "Zerodha", SourceKind.BROKER,
           "https://support.zerodha.com/category/trading-and-markets/margins/margin-trading-facility/articles/"
           "mtf-funds-statement-entries", None, CHECKED,
           "Lists ledger entry names; states interest is debited 'on specific dates' without saying which."),
    Source("ZERODHA/CAS", "What is SEBI's Closing Auction Session (CAS), and how does it affect you?", "Zerodha",
           SourceKind.BROKER, "https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/"
           "articles/closing-auction-session", None, CHECKED),
    Source("ZERODHA/MIS-BLOCKS", "Why are intraday (MIS/CO) orders not allowed for some stocks?", "Zerodha",
           SourceKind.BROKER, "https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/"
           "articles/intraday-orders-not-allowed-for-some-stocks", None, CHECKED),
    Source("ZERODHA/SURV-INDICATORS", "What are surveillance measures and risks associated with them?", "Zerodha",
           SourceKind.BROKER, "https://support.zerodha.com/category/trading-and-markets/alerts-and-nudges/nudges/"
           "articles/surveillance-indicators", None, CHECKED),
    Source("ZERODHA/GSM2", "Why is buying restricted for GSM stage 2 and above stocks?", "Zerodha",
           SourceKind.BROKER, "https://support.zerodha.com/category/trading-and-markets/trading-faqs/"
           "trading-categories-and-groups/articles/gsm-stage-2-and-above", None, CHECKED),
    Source("ZERODHA/T2T", "What are trade to trade stocks?", "Zerodha", SourceKind.BROKER,
           "https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/articles/"
           "what-are-trade-to-trade-stocks", None, CHECKED),
    Source("ZERODHA/RMS-XT", "What does the error 'RMS: Blocked for XT s bse_cm CNC block type: INTRADAY SQROFF' "
           "mean?", "Zerodha", SourceKind.BROKER,
           "https://support.zerodha.com/category/trading-and-markets/margins/margin-leverage-and-product-and-order-"
           "types/articles/what-does-the-error-rms-blocked-for-xt-s-bse-cm-cnc-block-type-intraday-sqroff-mean",
           None, CHECKED),
    Source("ZERODHA/SHORT-DELIVERY", "What is short delivery and what are its consequences?", "Zerodha",
           SourceKind.BROKER, "https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/"
           "articles/what-is-short-delivery-and-what-are-its-consequences", None, CHECKED),
    Source("ZERODHA/STATIC-IP", "Static IP requirement for Kite API order placement", "Zerodha", SourceKind.BROKER,
           "https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip",
           None, CHECKED),
    Source("ZERODHA/KITE-API-FAQ", "Kite Connect API FAQs", "Zerodha", SourceKind.BROKER,
           "https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/"
           "kite-connect-api-faqs", None, CHECKED),
    Source("KITE/ORDERS", "Kite Connect v3 Orders API", "Zerodha", SourceKind.BROKER,
           "https://kite.trade/docs/connect/v3/orders/", None, CHECKED),
    Source("KITE/LIMITS", "Kite Connect v3 exceptions and rate limits", "Zerodha", SourceKind.BROKER,
           "https://kite.trade/docs/connect/v3/exceptions/", None, CHECKED),
    # ---- Seen only through search summaries (to be read before live use) ----------------
    Source("ZERODHA/BSE-GROUPS-SUMMARY", "Zerodha support articles on BSE Z, ZP/P and X groups (search summaries "
           "only; articles not yet read in full)", "Zerodha (via search)", SourceKind.THIRD_PARTY,
           "https://support.zerodha.com/category/trading-and-markets/alerts-and-nudges/kite-error-messages/"
           "articles/p-zp-category-stocks", None, CHECKED),
    Source("ZERODHA/ASM-SUMMARY", "Zerodha 'What is ASM' article (search summary only)", "Zerodha (via search)",
           SourceKind.THIRD_PARTY, "https://support.zerodha.com/category/trading-and-markets/trading-faqs/"
           "trading-categories-and-groups/articles/what-is-asm", None, CHECKED),
    Source("ZERODHA/BTST-SUMMARY", "Zerodha BTST risk and settlement-holiday articles (search summaries only)",
           "Zerodha (via search)", SourceKind.THIRD_PARTY,
           "https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/articles/btst-risk",
           None, CHECKED),
    Source("NSE/TICK-2024-SUMMARY", "NSE/CMTR/62174 (24 May 2024) tick size below Rs 250, effective 10 Jun 2024 "
           "(effective date from search summary; slab values confirmed in NSE/CMTR/67133)", "NSE (via search)",
           SourceKind.THIRD_PARTY, "https://nsearchives.nseindia.com/content/circulars/CMTR62174.pdf",
           date(2024, 5, 24), CHECKED),
    Source("SEBI/RETAIL-ALGO-2025-SUMMARY", "SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 on retail "
           "algo participation (search summaries only)", "SEBI (via search)", SourceKind.THIRD_PARTY,
           "https://www.sebi.gov.in/", date(2025, 2, 4), CHECKED),
    Source("NSE/ASM-2026-SUMMARY", "NSE ASM applicability circulars Jan-Apr 2026 (mirror summaries only)",
           "NSE (via mirror)", SourceKind.THIRD_PARTY,
           "https://rhnvrm.github.io/stock-market-circulars/circulars/nse/2026/", None, CHECKED),
    Source("PROJECT/POLICY", "Project scope policy (configs/example_policy.json, PROJECT_BRIEF.md)", "This project",
           SourceKind.BROKER, "configs/example_policy.json", None, CHECKED,
           "Not a market rule; our own scope decision."),
)

SOURCES: dict[str, Source] = {s.id: s for s in _SOURCES}


@dataclass(frozen=True, slots=True)
class Cite:
    """Citation attached to a rule value."""

    sources: tuple[str, ...]
    status: Status
    note: str = ""

    def __post_init__(self) -> None:
        unknown = [s for s in self.sources if s not in SOURCES]
        if unknown:
            raise ValueError(f"Unknown source id(s): {unknown}")
        if self.status is not Status.UNKNOWN and not self.sources:
            raise ValueError("A non-UNKNOWN rule must cite at least one source")
