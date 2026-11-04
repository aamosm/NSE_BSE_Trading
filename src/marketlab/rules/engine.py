"""Deterministic order-validation engine.

``evaluate_order`` runs every applicable check and returns a ``Decision`` listing all PASS/WARN/
BLOCK results with reason codes, sources and verification status. It never contacts a broker.
Unknown required inputs BLOCK; they are never defaulted to permissive values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from . import bands, broker, instruments, mtf, sessions, ticks
from .calendar import MarketCalendar
from .provenance import CHECKED, Cite, Status
from .sessions import SessionKind
from .types import (
    IST,
    AccountState,
    Check,
    Decision,
    Exchange,
    InstrumentSnapshot,
    OrderRequest,
    OrderType,
    Outcome,
    Policy,
    PositionState,
    Product,
    RuleUnknown,
    Side,
    Validity,
)

D = Decimal
POLICY = Cite(("PROJECT/POLICY",), Status.ASSUMPTION, "Project scope policy, not a market rule.")
UNKNOWN_INPUT = Cite((), Status.UNKNOWN, "Required input not supplied in the snapshot.")
QTY_ALERT = 25000


@dataclass
class _Collector:
    items: list[Check] = field(default_factory=list)

    def add(self, code: str, outcome: Outcome, message: str, cite: Cite | None = None, **values: object) -> None:
        self.items.append(Check(
            code=code, outcome=outcome, message=message,
            sources=cite.sources if cite else (), status=str(cite.status) if cite else "",
            values=tuple((k, str(v)) for k, v in sorted(values.items())),
        ))

    def block(self, code: str, message: str, cite: Cite | None = None, **v: object) -> None:
        self.add(code, Outcome.BLOCK, message, cite, **v)

    def warn(self, code: str, message: str, cite: Cite | None = None, **v: object) -> None:
        self.add(code, Outcome.WARN, message, cite, **v)

    def ok(self, code: str, message: str, cite: Cite | None = None, **v: object) -> None:
        self.add(code, Outcome.PASS, message, cite, **v)


def evaluate_order(
    order: OrderRequest,
    inst: InstrumentSnapshot,
    position: PositionState,
    account: AccountState,
    *,
    calendar: MarketCalendar,
    policy: Policy | None = None,
) -> Decision:
    pol = policy or Policy()
    if order.submitted_at.tzinfo is None:
        raise ValueError("submitted_at must be timezone-aware")
    c = _Collector()
    local = order.submitted_at.astimezone(IST)
    d: date = local.date()

    # ---- 1. Basic shape and policy --------------------------------------------------------
    if order.quantity <= 0:
        c.block("QUANTITY_INVALID", f"Quantity must be a positive whole number of shares, got {order.quantity}.")
    if order.exchange is not inst.exchange:
        c.block("INSTRUMENT_EXCHANGE_MISMATCH", f"Order is for {order.exchange} but the snapshot is {inst.exchange}.")
    if order.exchange not in pol.allowed_exchanges:
        c.block("POLICY_EXCHANGE", f"{order.exchange} is outside the configured scope.", POLICY)
    if order.product not in pol.allowed_products:
        c.block("POLICY_PRODUCT", f"Product {order.product} is outside the configured scope.", POLICY)
    if order.via_api and not broker.tag_valid(order.tag):
        c.block("TAG_INVALID", f"Order tag must be 1-{broker.TAG_MAX_LEN} alphanumeric characters.",
                Cite(("KITE/ORDERS",), Status.BROKER_OFFICIAL))
    if inst.as_of != d:
        c.block("STALE_SNAPSHOT", f"Instrument snapshot is for {inst.as_of}, order is on {d}. Surveillance, bands "
                "and eligibility change daily.", UNKNOWN_INPUT, snapshot=inst.snapshot_id)
    if d < CHECKED:
        c.warn("CURRENT_BROKER_RULES_APPLIED_TO_PAST", f"Broker rules observed on {CHECKED} are applied to {d}; "
               "treat the result as a current-rule counterfactual.", POLICY)
    if order.quantity > QTY_ALERT:
        c.warn("QUANTITY_ALERT", f"Quantity above {QTY_ALERT} triggers an exchange capital-adequacy alert.",
               Cite(("NSE/CMTR/73927",), Status.PRIMARY))

    # ---- 2. Series / instrument status ----------------------------------------------------
    series = None
    try:
        series = instruments.series_rule(inst.exchange, inst.series)
        if not series.in_scope:
            c.block("SERIES_OUT_OF_SCOPE", f"{inst.exchange} series/group {inst.series} is outside scope "
                    f"({series.note or 'not main-board equity'}).", series.cite)
        else:
            c.ok("SERIES_CLASSIFIED", f"{inst.exchange} {inst.series}: "
                 f"{'trade-for-trade' if series.trade_for_trade else 'rolling settlement'}.", series.cite)
    except RuleUnknown as e:
        c.block("SERIES_UNKNOWN", str(e), UNKNOWN_INPUT)

    for flag, code, label in (
        (inst.suspended, "SUSPENDED", "suspended"),
        (inst.special_preopen_today, "SPECIAL_PREOPEN_OUT_OF_SCOPE", "in a special pre-open (IPO/relisting) today"),
        (inst.in_periodic_call_auction, "CALL_AUCTION_OUT_OF_SCOPE", "traded only in periodic call auctions"),
    ):
        if flag is None:
            c.block(f"{code}_STATUS_UNKNOWN", f"Whether the security is {label} is unknown.", UNKNOWN_INPUT)
        elif flag:
            c.block(code, f"Security is {label}.", Cite(("NSE/CMTR/73927", "PROJECT/POLICY"), Status.PRIMARY))

    restr = instruments.Restrictions()
    if inst.surveillance is None:
        c.block("SURVEILLANCE_UNKNOWN", "Surveillance lists (GSM/ASM/ESM/IBC) were not loaded for this date.",
                UNKNOWN_INPUT)
    else:
        try:
            restr = instruments.restrictions_for(inst.surveillance, d)
            if restr.labels:
                c.warn("UNDER_SURVEILLANCE", "Under " + ", ".join(restr.labels) + ".",
                       restr.cites[0] if restr.cites else None)
        except RuleUnknown as e:
            c.block("SURVEILLANCE_RULE_UNKNOWN", str(e), UNKNOWN_INPUT)
    t2t = bool((series and series.trade_for_trade) or restr.trade_for_trade)
    if restr.trade_for_trade and series is not None and not series.trade_for_trade:
        c.warn("T2T_SERIES_INCONSISTENT", f"Surveillance stage implies trade-for-trade but series is {inst.series}; "
               "treating as trade-for-trade.", restr.cites[0] if restr.cites else None)
    if restr.call_auction_only:
        c.block("CALL_AUCTION_OUT_OF_SCOPE", "Stage requires periodic call auction trading.",
                restr.cites[0] if restr.cites else None)

    # ---- 3. Calendar and session ------------------------------------------------------------
    session: SessionKind | None = None
    try:
        session = sessions.session_at(order.submitted_at, order.exchange, inst.has_derivatives, calendar)
    except RuleUnknown as e:
        c.block("SESSION_UNKNOWN", str(e), UNKNOWN_INPUT)
    if session is SessionKind.NON_TRADING_DAY:
        c.block("MARKET_HOLIDAY", f"{d} ({d:%A}) is not a trading day on {order.exchange}.",
                Cite(("NSE/CMTR/73927",), Status.PRIMARY))
    elif session is not None:
        accepted = sessions.ACCEPTED_ORDER_TYPES.get(session, frozenset())
        if not accepted:
            c.block("SESSION_NOT_ACCEPTING_ORDERS", f"At {local:%H:%M:%S} IST the session is {session}; the exchange "
                    "is not accepting new orders.", sessions.SESSION_CITES["cas" if "CAS" in session else "continuous"])
        elif order.order_type not in accepted:
            c.block("ORDER_TYPE_NOT_ALLOWED_IN_SESSION", f"{order.order_type} orders are not accepted in {session}.",
                    sessions.SESSION_CITES["preopen_v2" if "PRE_OPEN" in session else "cas"])
        else:
            c.ok("SESSION_OPEN", f"{session} accepts {order.order_type} orders.")
        if session in sessions.AUCTION_SESSIONS:
            if order.order_type is OrderType.MARKET and pol.limit_only_in_auctions:
                c.block("POLICY_LIMIT_ONLY_IN_AUCTION", "Policy: only limit orders in call auctions.", POLICY)
            if order.validity is not Validity.DAY:
                c.block("VALIDITY_NOT_ALLOWED_IN_AUCTION", f"{order.validity} validity is not allowed in auctions.",
                        sessions.SESSION_CITES["preopen_v2"])
        if restr.once_a_week:
            try:
                if not calendar.is_first_trading_day_of_week(order.exchange, d):
                    c.block("ONCE_A_WEEK_TRADING", f"Stage permits trading only on the first trading day of the "
                            f"week; {d} ({d:%A}) is not.", restr.cites[0])
            except RuleUnknown as e:
                c.block("SESSION_UNKNOWN", str(e), UNKNOWN_INPUT)

    # ---- 4. Product and side rules ----------------------------------------------------------
    if order.side is Side.BUY and ((series and series.broker_blocks_fresh_buy) or restr.broker_blocks_fresh_buy):
        c.block("BROKER_FRESH_BUY_BLOCKED", "Zerodha blocks fresh buys in this security (ASD/credit restriction); "
                "existing holdings can still be sold.",
                Cite(("ZERODHA/GSM2", "ZERODHA/SURV-INDICATORS"), Status.BROKER_OFFICIAL))

    if order.product is Product.MIS:
        _check_mis(c, order, inst, position, series, restr, t2t, pol, d, local)
    elif order.product is Product.MTF:
        if order.side is Side.BUY:
            _check_mtf_buy(c, order, inst, account, restr, t2t)
        else:
            avail = position.mtf_qty - position.pending_sell_qty
            if order.quantity > avail:
                c.block("INSUFFICIENT_SELLABLE_QTY", f"MTF sell of {order.quantity} exceeds MTF holdings available "
                        f"({avail}).", POLICY, available=avail)
    elif order.side is Side.SELL:
        _check_cnc_sell(c, order, position, series, t2t, pol, calendar, d)

    # ---- 5. Price, tick and band -----------------------------------------------------------
    effective = _check_prices(c, order, inst, restr, session, pol, d)

    blocked = any(i.outcome is Outcome.BLOCK for i in c.items)
    return Decision(accepted=not blocked, checks=tuple(c.items), effective_limit_price=None if blocked else effective,
                    session=str(session) if session else "")


# ------------------------------------------------------------------------------------------------


def _check_mis(c: _Collector, order: OrderRequest, inst: InstrumentSnapshot, position: PositionState,
               series: instruments.SeriesRule | None, restr: instruments.Restrictions, t2t: bool, pol: Policy, d: date, local: datetime) -> None:
    if t2t:
        c.block("T2T_NO_INTRADAY", "Trade-for-trade securities must be delivered; intraday (MIS) is not possible.",
                Cite(("NSE/CMTR/73927", "ZERODHA/T2T"), Status.PRIMARY))
    if (series and series.broker_blocks_mis) or restr.broker_blocks_mis:
        c.block("BROKER_MIS_BLOCKED", "Zerodha blocks MIS for this security's category.",
                Cite(("ZERODHA/MIS-BLOCKS",), Status.BROKER_OFFICIAL))
    if inst.mis_eligible is None:
        c.block("MIS_ELIGIBILITY_UNKNOWN", "Broker intraday eligibility list not loaded.", UNKNOWN_INPUT)
    elif not inst.mis_eligible:
        c.block("MIS_NOT_ELIGIBLE", "Security is not on the broker's intraday list.",
                Cite(("ZERODHA/MIS-BLOCKS",), Status.BROKER_OFFICIAL))
    try:
        cutoff = broker.mis_cutoff(d, inst.has_derivatives)
        if local.time() >= cutoff:
            c.block("MIS_CUTOFF_PASSED", f"MIS orders are not accepted after {cutoff:%H:%M} IST "
                    f"(auto square-off).", broker.MIS_CUTOFF_CITE)
    except RuleUnknown as e:
        c.block("MIS_CUTOFF_UNKNOWN", str(e), broker.MIS_CUTOFF_CITE)
    if order.side is Side.SELL:
        long_qty = max(position.mis_net_qty, 0)
        if order.quantity > long_qty and not pol.allow_short_selling:
            c.block("POLICY_NO_SHORT_SELLING", f"Selling {order.quantity} with intraday long {long_qty} would open a "
                    "short position; short selling is disabled.", POLICY)


def _check_mtf_buy(c: _Collector, order: OrderRequest, inst: InstrumentSnapshot, account: AccountState,
                   restr: instruments.Restrictions, t2t: bool) -> None:
    if account.resident_individual is None:
        c.block("MTF_ACCOUNT_ELIGIBILITY_UNKNOWN", "Account MTF eligibility (resident individual) unknown.",
                UNKNOWN_INPUT)
    elif not account.resident_individual:
        c.block("MTF_ACCOUNT_INELIGIBLE", "NRIs, minors and custodial participants are not eligible for MTF.",
                mtf.MTF_CITE)
    if account.ddpi_enabled is None:
        c.block("MTF_DDPI_UNKNOWN", "Whether DDPI/POA is enabled is unknown.", UNKNOWN_INPUT)
    elif not account.ddpi_enabled:
        c.block("MTF_DDPI_REQUIRED", "MTF requires DDPI/POA to be enabled.", mtf.MTF_CITE)
    if restr.broker_blocks_mtf:
        c.block("MTF_BLOCKED_BY_SURVEILLANCE", "Surveillance stage requires 100% margin or forbids pledging, so MTF "
                "funding is unavailable.", restr.cites[0] if restr.cites else None)
    if t2t:
        c.block("MTF_T2T", "Trade-for-trade securities are treated as MTF-ineligible.",
                Cite(("ZERODHA/MTF-FAQ",), Status.ASSUMPTION))
    if inst.mtf_eligible is None:
        c.block("MTF_ELIGIBILITY_UNKNOWN", "Broker's approved MTF list not loaded.", UNKNOWN_INPUT)
    elif not inst.mtf_eligible:
        c.block("MTF_NOT_APPROVED", "Security is not on the broker's approved MTF list.", mtf.MTF_CITE)
    if inst.var_pct is None or inst.elm_pct is None or inst.has_derivatives is None:
        c.block("MTF_MARGIN_INPUTS_UNKNOWN", "VaR, ELM and F&O status are required to compute MTF margin.",
                UNKNOWN_INPUT)
        return
    margin = mtf.mtf_margin_pct(inst.var_pct, inst.elm_pct, inst.has_derivatives)
    if margin >= 100:
        c.block("MTF_NOTHING_TO_FUND", f"MTF margin is {margin}% of value; nothing would be funded.", mtf.MTF_CITE)
    else:
        c.ok("MTF_MARGIN", f"Client must fund {margin}% of the purchase value.", mtf.MTF_CITE, margin_pct=margin)
    ref = order.price if order.price is not None else inst.ltp
    if ref is not None:
        value = ref * order.quantity
        cap = mtf.mtf_stock_cap(inst.in_nifty500)
        if account.mtf_stock_exposure_inr + value > cap:
            c.block("MTF_STOCK_CAP", f"MTF exposure in this stock would exceed Rs {cap}.", mtf.MTF_CITE)
        if account.mtf_total_exposure_inr + value > mtf.MTF_ACCOUNT_CAP:
            c.block("MTF_ACCOUNT_CAP", f"Total MTF exposure would exceed Rs {mtf.MTF_ACCOUNT_CAP}.", mtf.MTF_CITE)


T2T_NEXT_DAY_CITE = Cite(("ZERODHA/T2T", "ZERODHA/RMS-XT"), Status.CONFLICTING,
                         "Zerodha's T2T article says T2T buys can be sold on T+1; its RMS article says selling before "
                         "the shares reach demat is rejected and BTST is blocked. Treated as not sellable until "
                         "credited.")
BTST_CITE = Cite(("ZERODHA/BTST-SUMMARY", "ZERODHA/SHORT-DELIVERY"), Status.SECONDARY,
                 "T1 (BTST) holdings cannot be sold on a settlement holiday. If the original seller short-delivers, "
                 "the BTST sale is auctioned/closed out (up to +20% of close) with penalties.")


def _check_cnc_sell(c: _Collector, order: OrderRequest, position: PositionState,
                    series: instruments.SeriesRule | None, t2t: bool, pol: Policy, calendar: MarketCalendar,
                    d: date) -> None:
    settlement_day: bool | None
    try:
        settlement_day = calendar.is_settlement_day(order.exchange, d)
    except RuleUnknown:
        settlement_day = None
    btst_ok = (not t2t and not (series and series.broker_blocks_btst) and settlement_day is True)
    t2t_t1_ok = t2t and pol.allow_unverified_t2t_next_day_sale and settlement_day is True
    same_day_ok = not t2t
    sellable = (position.settled_qty
                + (position.t1_qty if (btst_ok or t2t_t1_ok) else 0)
                + (position.bought_today_qty if same_day_ok else 0)
                - position.pending_sell_qty)
    if order.quantity > sellable:
        c.block("INSUFFICIENT_SELLABLE_QTY", f"CNC sell of {order.quantity} exceeds sellable quantity {sellable}. "
                "Naked short selling is not permitted.", Cite(("NSE/CMTR/73927",), Status.PRIMARY),
                sellable=sellable, settled=position.settled_qty, t1=position.t1_qty,
                bought_today=position.bought_today_qty, pending=position.pending_sell_qty)
        if t2t and position.bought_today_qty:
            c.block("T2T_NO_SAME_DAY_SELL", "Trade-for-trade shares bought today cannot be sold today.",
                    Cite(("ZERODHA/T2T", "NSE/CMTR/73927"), Status.BROKER_OFFICIAL))
        if t2t and position.t1_qty and not t2t_t1_ok:
            c.block("T2T_NEXT_DAY_SALE_UNVERIFIED", "Trade-for-trade shares not yet credited to demat are not "
                    "counted as sellable.", T2T_NEXT_DAY_CITE)
        if not t2t and position.t1_qty and not btst_ok:
            reason = ("today is a settlement holiday" if settlement_day is False
                      else "the BSE group blocks BTST" if series and series.broker_blocks_btst
                      else "the settlement calendar is unknown")
            c.block("BTST_NOT_ALLOWED", f"T1 holdings cannot be sold now because {reason}.", BTST_CITE)
        return
    uses = order.quantity - max(position.settled_qty - position.pending_sell_qty, 0)
    if uses > 0 and btst_ok and position.t1_qty:
        c.warn("BTST_SHORT_DELIVERY_RISK", "Sale relies on T1 shares not yet in demat; a short delivery by the "
               "original seller leads to auction/close-out at your cost.", BTST_CITE)
    if uses > position.t1_qty * (1 if btst_ok else 0) and same_day_ok and position.bought_today_qty:
        c.warn("INTRADAY_REVERSAL_OF_DELIVERY", "Selling shares bought today nets the trade intraday; intraday "
               "charges apply instead of delivery charges.", Cite(("ZERODHA/CHARGES",), Status.ASSUMPTION))


def _check_prices(c: _Collector, order: OrderRequest, inst: InstrumentSnapshot, restr: instruments.Restrictions,
                  session: SessionKind | None, pol: Policy, d: date) -> Decimal | None:
    # Tick size
    tick: Decimal | None = inst.tick_size
    if inst.tick_reference_price is not None and inst.exchange is Exchange.NSE:
        try:
            derived = ticks.tick_size(inst.tick_reference_price, d)
            if tick is None:
                tick = derived
            elif tick != derived:
                c.warn("TICK_SOURCE_MISMATCH", f"Security-file tick {tick} differs from schedule tick {derived}; "
                       "using the security file.", ticks.regime_for(d).cite)
        except RuleUnknown as e:
            if tick is None:
                c.block("TICK_SIZE_UNKNOWN", str(e), UNKNOWN_INPUT)
                return None
    if tick is None:
        c.block("TICK_SIZE_UNKNOWN", "Tick size unknown: load the exchange security file or the reference close.",
                UNKNOWN_INPUT)
        return None

    # Band
    if inst.base_price is None:
        c.block("BASE_PRICE_UNKNOWN", "Base price (previous/adjusted close) unknown.", UNKNOWN_INPUT)
        return None
    band: bands.Band | None = None
    if inst.has_derivatives is True and restr.max_band_pct is None:
        pct = inst.dynamic_band_pct
        if pct is None:
            pct = D("10")
            c.warn("DYNAMIC_BAND_ASSUMED", "F&O stock: using the initial 10% operating range; intraday flexing state "
                   "was not supplied.", bands.BAND_CITE)
        band = bands.static_band(inst.base_price, pct, tick)
    elif inst.has_derivatives is None:
        c.block("FNO_STATUS_UNKNOWN", "Whether the stock has derivatives is unknown, so its band type is unknown.",
                UNKNOWN_INPUT)
        return None
    else:
        pct = inst.price_band_pct
        if pct is None:
            pct = restr.max_band_pct
            if pct is None:
                c.block("PRICE_BAND_UNKNOWN", "Static price band not supplied.", UNKNOWN_INPUT)
                return None
            c.warn("PRICE_BAND_FROM_SURVEILLANCE", f"Band not supplied; using the surveillance maximum {pct}%.",
                   restr.cites[0] if restr.cites else None)
        if restr.max_band_pct is not None and pct > restr.max_band_pct:
            c.block("SURVEILLANCE_BAND_CONFLICT", f"Supplied band {pct}% exceeds the surveillance maximum "
                    f"{restr.max_band_pct}%; the snapshot is inconsistent.", restr.cites[0] if restr.cites else None)
            return None
        band = bands.static_band(inst.base_price, pct, tick, no_upward_movement=restr.no_upward_movement)
    if session in (SessionKind.CAS_ALL, SessionKind.CAS_LIMIT_ONLY):
        if inst.cas_reference_price is None:
            c.block("CAS_REFERENCE_UNKNOWN", "CAS reference price (VWAP 15:00-15:15) not supplied.", UNKNOWN_INPUT)
            return None
        cb = bands.cas_band(inst.cas_reference_price, tick)
        band = bands.Band(lower=max(band.lower, cb.lower), upper=min(band.upper, cb.upper))
    if restr.no_upward_movement:
        c.warn("NO_UPWARD_MOVEMENT", f"Stage allows no price above the base price {inst.base_price}.",
               restr.cites[0] if restr.cites else None)

    def in_band(name: str, p: Decimal | None) -> bool:
        if p is None:
            c.block(f"{name.upper()}_MISSING", f"{name} is required for {order.order_type} orders.")
            return False
        if p <= 0:
            c.block(f"{name.upper()}_INVALID", f"{name} must be positive.")
            return False
        good = True
        if not ticks.is_on_tick(p, tick):
            c.block("PRICE_NOT_ON_TICK", f"{name} {p} is not a multiple of tick {tick}.", ticks.regime_for(d).cite
                    if inst.exchange is Exchange.NSE else None, tick=tick)
            good = False
        if not (band.lower <= p <= band.upper):
            c.block("PRICE_OUTSIDE_BAND", f"{name} {p} is outside the permitted range {band.lower}-{band.upper}.",
                    bands.CAS_BAND_CITE if session and "CAS" in session else bands.BAND_CITE,
                    lower=band.lower, upper=band.upper)
            good = False
        return good

    ot = order.order_type
    if ot is OrderType.LIMIT:
        in_band("price", order.price)
        return order.price
    if ot is OrderType.SL:
        ok_p = in_band("price", order.price)
        ok_t = in_band("trigger_price", order.trigger_price)
        if ok_p and ok_t:
            p, t = order.price, order.trigger_price
            if (order.side is Side.BUY and t > p) or (order.side is Side.SELL and t < p):
                c.block("SL_TRIGGER_DIRECTION", "Buy SL needs trigger <= limit; sell SL needs trigger >= limit.",
                        Cite(("KITE/ORDERS",), Status.ASSUMPTION))
            gap = bands.sl_limit_gap_allowed(t)
            if abs(p - t) > gap:
                c.block("SL_TRIGGER_LIMIT_GAP", f"|limit - trigger| = {abs(p - t)} exceeds the allowed {gap}.",
                        bands.SL_GAP_CITE)
        return order.price

    # MARKET and SL-M
    if ot is OrderType.SL_M:
        in_band("trigger_price", order.trigger_price)
    if order.via_api:
        mp = order.market_protection_pct
        if mp is None or not broker.market_protection_valid(mp):
            c.block("MARKET_PROTECTION_REQUIRED", "API market and SL-M orders need market_protection of -1 or "
                    "between 0 (exclusive) and 100; 0 or missing is rejected.", broker.MARKET_PROTECTION_CITE)
            return None
        if mp == D("-1") and pol.require_explicit_market_protection:
            c.block("POLICY_EXPLICIT_PROTECTION", "Policy: use an explicit protection %, not broker 'auto' (-1), "
                    "whose band is not documented.", POLICY)
            return None
        if mp > pol.max_market_protection_pct:
            c.block("POLICY_PROTECTION_TOO_WIDE", f"Protection {mp}% exceeds policy maximum "
                    f"{pol.max_market_protection_pct}%.", POLICY)
            return None
    if session is SessionKind.POST_CLOSE:
        if inst.ltp is None:
            c.block("MARKET_ORDER_NO_TRADE_TODAY", "Post-close session is open only to securities traded today.",
                    Cite(("NSE/CMTR/73927",), Status.PRIMARY))
        return None  # executes at the day's closing price
    if ot is OrderType.SL_M:
        return None  # protection applies at trigger time against the then-LTP
    if inst.ltp is None:
        c.block("MARKET_ORDER_NO_TRADE_TODAY", "Market orders are rejected when the security has not traded today.",
                bands.MPP_CITE)
        return None
    mpp = bands.mpp_limits(inst.ltp)
    if order.via_api and order.market_protection_pct is not None:
        f = order.market_protection_pct / 100
        if order.side is Side.BUY:
            raw = ticks.floor_to_tick(inst.ltp * (1 + f), tick)
            eff = min(raw, band.upper, ticks.floor_to_tick(mpp.upper, tick))
        else:
            raw = ticks.ceil_to_tick(inst.ltp * (1 - f), tick)
            eff = max(raw, band.lower, ticks.ceil_to_tick(mpp.lower, tick))
        c.ok("MARKET_PROTECTED", f"API market order becomes a protected limit at {eff}.",
             broker.MARKET_PROTECTION_CITE, protected_limit=eff)
        return eff
    return None
