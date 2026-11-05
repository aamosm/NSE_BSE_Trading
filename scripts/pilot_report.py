"""Build the pilot panel, the immutable manifest and the pilot report (coverage, labels, folds, traces, the
reconstructed Infosys Q4 FY25 case).

    python scripts/pilot_report.py data/pilot/nse_2025 2025-01-01 2025-07-31
Writes <root>/manifest.json once (exclusive create; later runs verify it) and a new report version each run:
report.json, report-2.json, ... Earlier versions are never replaced; each later one names what it supersedes."""
import json
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from marketlab import history, sources  # noqa: E402
from marketlab.common import IST  # noqa: E402
from marketlab.quant import allocate, evaluate, labels, pilot  # noqa: E402
from marketlab.quant import panel as qpanel  # noqa: E402
from marketlab.quant.universe import ScreenPolicy, rule_inputs_for  # noqa: E402

root = Path(sys.argv[1])
start, end = date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3])
market, docs = root / "market", root / "documents"
INFY = "INE009A01021"
BOARD = "https://nsearchives.nseindia.com/corporate/Infosys_14032025161835_SEIntimation_Q4FY25BM.pdf"
FILING = "https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_INDAS_85350_17042025233634_iXBRL_WEB.html"

man_path = root / "manifest.json"
if man_path.exists():
    man = json.loads(man_path.read_text(encoding="utf-8"))
    print("manifest exists; verification problems:", history.verify_manifest(market, man))
else:
    man = history.build_manifest(market, "nse_2025_pilot", start, end,
                                 extra={"documents": {u.rsplit("/", 1)[1]: history.fetch_document(docs, u) for u in (BOARD, FILING)},
                                        "probe_requests_note": "5 single probe requests on 5 Nov 2026 (bhavcopy 2025-04-17 and "
                                                               "2024-07-05, legacy 2024-07-05, REG1_IND and sec_list 2025-04-17) "
                                                               "preceded the collector's one request for the same files."})
    print("manifest sha256", history.write_once(man_path, man), "problems", history.verify_manifest(market, man))

cal = history.ObservedCalendar(market, start, end)
built = qpanel.build(market, root / "panel.sqlite3", after=start, calendar=cal)
pn = qpanel.Panel(root / "panel.sqlite3")
view = pn.view(end)
policy = allocate.Policy.for_capital(10_000)
spol = ScreenPolicy(W=10_000)
cov = pilot.coverage(view, cal, market, start, end, policy=spol, progress=print)
unis, sess, stored = cov.pop("_universes"), cov.pop("_sessions"), cov.pop("_stored")

# ---- corporate actions and the dividend probe (H-CA1) ------------------------------------------------------
acts = pilot.corporate_actions(view, start, end)
infy_factors = [a for a in acts if a["isin"] == INFY]
probe_day = date(2025, 5, 30)  # secondary source (review): ex-date of the Rs 22 final dividend; unverified officially
probe = pilot.base_price_on(view, INFY, probe_day) if probe_day in stored else None

# ---- the Infosys Q4 FY25 case --------------------------------------------------------------------------------
fields = pilot.filing_fields(history.read_document(docs, FILING))
D = date(2025, 4, 17)
k = sess.index(D)
entry = sess[k + 1]
u = unis[D]
ri = rule_inputs_for(market, entry, cal, "RECONSTRUCTED")
bar = next(b for b in view.bars(INFY, D, D))
q = pilot.size_at_cap(bar.close, policy)
trace_ok = pilot.mechanical_trace(view, sess, stored, INFY, D, q, 20, median_value=u.median_value.get(INFY, 0.0), end=end)
lab = labels.forward_return(view, INFY, D, 20, sessions=sess, panel_days=stored)
idx = view.index_levels("Nifty 50")
file_av = {sid: {k_: man["files"][sid][D.isoformat()][k_] for k_ in ("received_at", "server_last_modified",
                                                                    "reconstructed_available_at", "availability_basis", "sha256")}
           for sid in history.PILOT_SOURCES if D.isoformat() in man["files"].get(sid, {})}
filing_meta = man["documents"][FILING.rsplit("/", 1)[1]]
infosys = {
    "label": "RECONSTRUCTED_NO_FORECAST: no MarketLab forecast existed in April 2025; mechanics only",
    "schedule_known_beforehand": {"board_meeting_intimation": {"url": BOARD, "server_last_modified": man["documents"][BOARD.rsplit("/", 1)[1]]["server_last_modified"],
                                                               "prior_intimation_date_per_filing": fields["prior_intimation_date"]},
                                  "company_release_time_announcement": "NOT FETCHED (company website, not an exchange host); review cites "
                                                                       "an expected publication around 15:45 IST on 17 Apr"},
    "facts": {k_: fields[k_] for k_ in ("symbol", "isin", "basis", "audited", "period", "presentation_unit", "rounding_level",
                                        "board_meeting", "revenue_from_operations_inr", "revenue_from_operations_crore",
                                        "net_profit_inr", "profit_attributable_to_owners_inr", "basic_eps_inr")},
    "unit_checks": {"40925 crore": pilot.check_amount(fields, 40925, "crore"),
                    "409250000000 crore (mislabelled actuals)": pilot.check_amount(fields, 409250000000, "crore")},
    "filing_availability": {"url": FILING, "server_last_modified": filing_meta["server_last_modified"],
                            "received_at_this_system": filing_meta["received_at"],
                            "note": "board meeting ended 16:10 IST (per filing); the exchange's own dissemination time of the "
                                    "results announcement is not held (source question)"},
    "decision": {"decision_session": D.isoformat(), "earliest_usable_decision_time": "after 23:36 IST on 17 Apr 2025 "
                 "(integrated filing server time); before the next session's pre-open", "next_session_observed": entry.isoformat(),
                 "sessions_skipped": [d.isoformat() for d in cal.closed if D < d < entry] + ["weekend"],
                 "input_files": file_av},
    "eligibility": {"in_universe": INFY in u.isins, "excluded_reason": u.excluded.get(INFY), "unverified": u.unverified,
                    "rule_inputs_availability": u.availability, "rule_file_evidence": ri.get("evidence") if ri else None,
                    "series_next_session": (ri or {}).get("series", {}).get("INFY"),
                    "band_next_session": (ri or {}).get("band", {}).get("INFY", "absent"),
                    "surveillance_next_session": str((ri or {}).get("reg", {}).get("INFY")),
                    "median_value_20_crore": round(u.median_value.get(INFY, 0) / 1e7, 1)},
    "benchmark": {"name": "Nifty 50 price index (open to open)", "open_entry": idx.get(lab.entry_day, (None,))[0],
                  "open_exit": idx.get(lab.exit_day, (None,))[0]},
    "label_h20": {"status": lab.status, "reason": lab.reason, "entry_day": str(lab.entry_day), "exit_day": str(lab.exit_day),
                  "entry_open": lab.entry_open, "exit_open": lab.exit_open, "gross": lab.gross, "index_log": lab.index_log,
                  "excess_log": lab.excess, "basis": lab.basis},
    "actual_size": {"policy_cap": policy.cap_fraction * policy.W, "decision_close": bar.close, "q": q},
    "trace": {k_: trace_ok[k_] for k_ in ("trades", "open_positions", "net_rupees", "events")},
    "review_secondary_values": {"open_2025-04-21": 1410.0, "open_2025-05-20": 1570.0, "nifty_open_2025-04-21": 23949.15,
                                "nifty_open_2025-05-20": 24996.20, "close_2025-04-17": 1419.50},
}

# ---- blocked exits from the data: an ISIN replacement and a security that stopped trading ----------------------
found = {}
for d in sorted(unis):
    if unis[d].unverified:
        continue
    for isin in unis[d].isins:
        lb = labels.forward_return(view, isin, d, 20, sessions=sess, panel_days=stored)
        if lb.status == labels.EXCLUDED and lb.reason in ("IDENTITY_CHANGE", "NO_TRADE_AT_EXIT") and lb.reason not in found:
            found[lb.reason] = (d, isin)
blocked_traces = {}
for reason, (d, isin) in found.items():
    b = next(x for x in view.bars(isin, d, d))
    qq = max(1, pilot.size_at_cap(b.close, policy))
    t = pilot.mechanical_trace(view, sess, stored, isin, d, qq, 20, median_value=unis[d].median_value[isin], end=end)
    later = [x.day.isoformat() for x in view.bars(isin, d, end)]
    t |= {"label_reason": reason, "symbol": b.symbol, "bars_after_decision": {"count": len(later), "last": later[-1] if later else None},
          "discontinuities": {str(k_): v for k_, v in view.discontinuities(isin).items()}}
    blocked_traces[reason] = t
disc_all = view.discontinuities()
sym = dict(view.db.execute("SELECT isin, symbol FROM bars GROUP BY isin").fetchall())
ident = sorted((str(d), sym.get(i), i, v[0][2]) for i, dd in disc_all.items() for d, vs in dd.items() for v in [vs] if v[0][0] == "IDENTITY_END")
price = sorted((str(d), sym.get(i), i, round(k[1], 4), pilot.classify_factor(k[1]))
               for i, dd in disc_all.items() for d, vs in dd.items() for k in vs if k[0] == "PRICE_DISCONTINUITY")

transition = [history.format_transition(market, d) for d in (date(2024, 7, 3), date(2024, 7, 4), date(2024, 7, 5), date(2024, 7, 8))]
report = {"pilot_id": man["pilot_id"], "manifest_sha256": man["content_sha256"], "window": [start.isoformat(), end.isoformat()],
          "panel": built | {"content_hash": view.content_hash()}, "calendar": cal.report(), "coverage": cov,
          "corporate_actions": {"count": len(acts), "by_class": pilot._count(a["class"].split(" (")[0] for a in acts),
                                "split_or_bonus": [a for a in acts if a["class"].startswith("SPLIT_OR_BONUS")][:20],
                                "infy_factors": infy_factors, "infy_dividend_probe": probe},
          "discontinuities": {"finding": "PrvsClsgPric is not adjusted on 2025 split/bonus ex-dates; splits often issue a new ISIN",
                              "identity_changes": ident, "price_discontinuities": price,
                              "in_universe_previous_session": [x for x in price if any(
                                  x[2] in unis[dd].isins for dd in unis if dd < date.fromisoformat(x[0]) and (date.fromisoformat(x[0]) - dd).days <= 4)]},
          "format_transition": transition, "infosys_q4fy25": infosys, "blocked_traces": blocked_traces,
          "holdout": "not frozen; the pilot is diagnostic and opens no holdout"}
report = evaluate.jsonable(report)
n = 1
while (root / ("report.json" if n == 1 else f"report-{n}.json")).exists():
    n += 1
if n > 1:
    report["supersedes"] = {"version": n - 1, "reason": {2: "v1 read availability from already-derived manifest fields (showed "
                            "NO_SERVER_TIME for the Infosys inputs) and predated discontinuity detection: it counted labels "
                            "across unadjusted split/bonus ex-dates as resolved",
                            3: "v2 used a 0.80/1.25 discontinuity threshold, which also caught closes pinned at a 20% circuit"}.get(n, "rerun")}
out = root / ("report.json" if n == 1 else f"report-{n}.json")
print("report", out.name, "sha256", history.write_once(out, report))
print(json.dumps({"coverage": {k_: v for k_, v in cov.items() if k_ != "missing_sessions"},
                  "acts": report["corporate_actions"]["by_class"], "infy_probe": probe, "transition": transition,
                  "infosys": {k_: infosys[k_] for k_ in ("eligibility", "benchmark", "label_h20", "actual_size", "unit_checks")},
                  "trace_ok": trace_ok["trades"], "blocked": {k_: (str(v[0]), v[1]) for k_, v in found.items()},
                  "identity_changes": len(ident), "price_discontinuities": len(price)}, indent=1, default=str)[:6000])
pn.close()
