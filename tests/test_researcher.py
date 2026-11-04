"""Research service: budget caps, provider contract, evidence validation, templates, queue and replay.

Offline: the provider is faked with responses in the documented Agent API shape. Every expected number
is worked by hand in the comment.
"""
import json
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from marketlab.common import IST
from marketlab.researcher import evidence, jobs, templates
from marketlab.researcher.budget import BudgetExceeded, Ledger, Limits, Policy, worst_case_usd
from marketlab.researcher.provider import (
    ArchivedProvider, NullProvider, ProviderError, ProviderRequest, http_error_label, parse_response,
)

T = datetime(2026, 11, 5, 7, 0, tzinfo=IST)
MODEL = "example/model"
PRICES = {MODEL: (D("0.10"), D("0.50"))}  # a sample price table; real tables are recorded with their source


@pytest.fixture(autouse=True)
def _sample_prices(monkeypatch):
    """The runner reserves from budget.MODEL_PRICES, which is empty until a provider is enabled."""
    from marketlab.researcher import budget
    monkeypatch.setitem(budget.MODEL_PRICES, MODEL, PRICES[MODEL])


# ---- budget ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("limits, expected", [
    # 4 steps: input 4*3000 + (3000+1500)*(4*5/2) = 57,000 -> $0.0057; output 4*1500 = 6,000 -> $0.003;
    # 4 fast searches $0.004; total $0.0127
    (Limits(1500, 4, 3000, 3000, 8), D("0.0127")),
    # 5 steps: input 17,500 + 4,500*15 = 85,000 -> $0.0085; output 7,500 -> $0.00375; searches $0.005 -> 0.01725 -> 0.0173
    (Limits(1500, 5, 3500, 3000, 8), D("0.0173")),
    # 8 standard searches: input 32,000 + 6,000*36 = 248,000 -> $0.0248; output 16,000 -> $0.008; $0.02 -> 0.0528
    (Limits(2000, 8, 4000, 4000, 10, "web"), D("0.0528")),
])
def test_worst_case_reservation_is_hand_computable(limits, expected):
    assert worst_case_usd(MODEL, limits, PRICES) == expected


def test_every_job_kind_fits_its_cap_at_the_sample_prices():
    pol = Policy()
    for kind, kp in jobs.KINDS.items():
        assert worst_case_usd(MODEL, kp.limits, PRICES) <= pol.per_job_usd[kind], kind


def test_unknown_model_price_is_refused():
    with pytest.raises(ValueError, match="No verified price"):
        worst_case_usd("someone/unpriced", Limits(10, 1, 10, 10, 1))


def ledger(tmp_path, **kw):
    return Ledger(tmp_path / "ledger.sqlite3", Policy(**kw) if kw else Policy())


def test_caps_are_enforced_before_any_call(tmp_path):
    lg = ledger(tmp_path, monthly_usd=D("0.10"), daily_usd=D("0.05"))
    with pytest.raises(BudgetExceeded) as e:
        lg.reserve("j0", "overnight_update", D("0.04"), T)  # above the per-job cap of 0.03
    assert e.value.label == "JOB_CAP"
    r1 = lg.reserve("j1", "overnight_update", D("0.03"), T)
    with pytest.raises(BudgetExceeded) as e:
        lg.reserve("j2", "overnight_update", D("0.03"), T)  # 0.03 + 0.03 > daily 0.05
    assert e.value.label == "DAILY_CAP"
    lg.settle(r1, D("0.004"), T)  # actual cost replaces the reservation
    assert lg.spent(T)["day"] == D("0.004")
    lg.reserve("j3", "overnight_update", D("0.03"), T)
    next_day = T + timedelta(days=1)
    lg.reserve("j4", "overnight_update", D("0.03"), next_day)
    lg.reserve("j5", "overnight_update", D("0.03"), next_day + timedelta(days=1))
    with pytest.raises(BudgetExceeded) as e:  # month: 0.004 + 0.03 + 0.03 + 0.03 = 0.094; +0.03 > 0.10
        lg.reserve("j6", "overnight_update", D("0.03"), next_day + timedelta(days=2))
    assert e.value.label == "MONTHLY_CAP"
    lg.close()


def test_release_unknown_cost_and_overrun(tmp_path):
    lg = ledger(tmp_path)
    r = lg.reserve("a", "smoke", D("0.01"), T)
    lg.release(r, "429", T)
    assert lg.spent(T)["day"] == 0
    r = lg.reserve("b", "smoke", D("0.01"), T)
    assert lg.settle(r, None, T) == D("0.01")  # unknown cost: charged at the reservation
    r = lg.reserve("c", "smoke", D("0.001"), T)
    lg.settle(r, D("0.002"), T)  # provider cost above the reservation -> OVERRUN suspends the kind
    with pytest.raises(BudgetExceeded) as e:
        lg.reserve("d", "smoke", D("0.001"), T)
    assert e.value.label == "KIND_SUSPENDED"
    lg.resume("smoke", "reviewed: reservation bound corrected", T)
    lg.reserve("e", "smoke", D("0.001"), T)
    lg.close()


def test_daily_job_count_cap(tmp_path):
    lg = ledger(tmp_path)
    for i in range(2):
        lg.reserve(f"r{i}", "bounded_company_research", D("0.01"), T)
    with pytest.raises(BudgetExceeded) as e:
        lg.reserve("r3", "bounded_company_research", D("0.01"), T)
    assert e.value.label == "DAILY_COUNT"
    lg.close()


def test_policy_hard_ceiling(tmp_path):
    with pytest.raises(ValueError):
        Policy(monthly_usd=D("10.01"), daily_usd=D("1"))
    (tmp_path / "p.json").write_text(json.dumps({"monthly_usd": "8", "daily_usd": "0.60"}))
    assert Policy.load(tmp_path / "p.json").monthly_usd == D("8")


# ---- provider contract ------------------------------------------------------------------------------------

def raw_response(text, results=(), cost="0.0041", status="completed", citations=()):
    return json.dumps({
        "id": "resp_1", "object": "response", "created_at": 1, "status": status, "model": MODEL,
        "output": [{"type": "search_results", "queries": ["q"], "results": [
            {"id": i + 1, "url": u, "title": t, "snippet": s, "date": "2026-11-04", "source": "web"}
            for i, (u, t, s) in enumerate(results)]},
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": text,
                 "annotations": [{"type": "url_citation", "url": c, "title": "x", "start_index": 0, "end_index": 1}
                                 for c in citations]}]}],
        "usage": {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500,
                  "tool_calls_details": {"search_web": {"invocation": 1}},
                  "cost": {"currency": "USD", "input_cost": 0.00012, "output_cost": 0.00015, "total_cost": float(cost)}},
    }).encode()


def test_request_body_uses_documented_fields_only():
    req = ProviderRequest(model=MODEL, instructions="i", input="x", max_output_tokens=10, max_steps=2,
                          web_search={"search_type": "fast", "max_results": 3, "max_tokens": 100,
                                      "max_tokens_per_page": 50, "filters": {"search_domain_filter": ["nseindia.com"]}},
                          response_schema={"type": "object"})
    b = req.body()
    assert set(b) == {"model", "instructions", "input", "max_output_tokens", "max_steps", "store", "tools",
                      "response_format"}
    assert b["store"] is False and b["tools"][0]["type"] == "web_search"
    assert b["response_format"] == {"type": "json_schema", "json_schema": {"name": "evidence_v1",
                                                                         "schema": {"type": "object"}}}
    twin = ProviderRequest(model=MODEL, instructions="i", input="x", max_output_tokens=10, max_steps=2,
                           web_search=b["tools"][0] | {}, response_schema={"type": "object"})
    twin = ProviderRequest(model=twin.model, instructions="i", input="x", max_output_tokens=10, max_steps=2,
                           web_search={k: v for k, v in b["tools"][0].items() if k != "type"},
                           response_schema={"type": "object"})
    assert req.request_hash() == twin.request_hash() and len(req.request_hash()) == 64


def test_parse_response_reads_message_parts_search_results_and_cost():
    r = parse_response(raw_response('{"a": 1}', [("https://www.nseindia.com/x", "T", "S")],
                                    citations=["https://www.nseindia.com/x"]), want_json=True)
    assert r.parsed == {"a": 1} and r.cost_usd == D("0.0041") and r.status == "completed"
    assert r.search_results[0]["url"] == "https://www.nseindia.com/x" and r.citations[0]["url"].endswith("/x")
    assert r.tool_calls == {"search_web": {"invocation": 1}} and len(r.raw_sha256) == 64


def test_http_error_labels_are_fixed():
    assert http_error_label(401).label == "AUTH" and http_error_label(429, retry_after=3).retry_after == 3.0
    assert http_error_label(429, "overloaded").label == "OVERLOADED" and http_error_label(400).label == "BAD_REQUEST"
    assert http_error_label(503, retry_after=5).label == "OVERLOADED" and http_error_label(500).label == "SERVER"


def test_null_provider_sends_nothing():
    with pytest.raises(ProviderError) as e:
        NullProvider().run(ProviderRequest(model=MODEL, instructions="i", input="x", max_output_tokens=5, max_steps=1))
    assert e.value.label == "NOT_CONFIGURED"


# ---- evidence validation -------------------------------------------------------------------------------

ISIN = "INE000A01001"
URL = "https://www.nseindia.com/companies-listing/corporate-filings-announcements/abc"
PASSAGE = "The Board has declared an interim dividend of Rs 1 per equity share"
ALLOWED = {"EXCHANGE": ["nseindia.com", "bseindia.com"], "REGULATOR": ["sebi.gov.in"]}


def fact(**kw):
    f = {"event_type": "DIVIDEND", "summary": "Interim dividend Rs 1 per share; record date 6 Nov 2026.",
         "published_at": "2026-11-04T18:00:00+05:30", "period": "FY2027", "dates": [{"kind": "RECORD_DATE",
                                                                                      "date": "2026-11-06"}],
         "values": [{"field": "DIVIDEND_PER_SHARE", "amount": 1, "unit": "PER_SHARE_INR", "basis": "NOT_APPLICABLE"}],
         "sources": [{"url": URL, "passage": PASSAGE, "source_type": "EXCHANGE"}], "known_fact_id": None,
         "novelty": "NEW"}
    f.update(kw)
    return f


def doc(*facts, contradictions=()):
    return {"schema_version": "evidence.v1", "task_id": "job-1", "isin": ISIN, "facts": list(facts),
            "contradictions": list(contradictions), "unknown_fields": [], "no_new_evidence": not facts}


RESULT = parse_response(raw_response("{}", [(URL, "Dividend", PASSAGE + " on 4 Nov 2026.")]))


def assess(d, **kw):
    return evidence.assess(d, job_id="job-1", isin=ISIN, allowed=ALLOWED, result=kw.pop("result", RESULT),
                           received_at=datetime(2026, 11, 5, 7, 0, tzinfo=IST), **kw)


def test_valid_primary_fact_with_verified_passage_is_accepted():
    a = assess(doc(fact()))
    assert a.ok and len(a.accepted) == 1 and not a.candidates and not a.rejected
    f = a.accepted[0]
    assert f["novelty"] == "NEW" and f["passages_verified"] and f["independent_sources"] == 1


@pytest.mark.parametrize("change, reason", [
    ({"sources": [{"url": "https://www.nseindia.com/other", "passage": PASSAGE, "source_type": "EXCHANGE"}]},
     "CITATION_NOT_RETRIEVED"),
    ({"sources": [{"url": "https://evil.example/x", "passage": PASSAGE, "source_type": "EXCHANGE"}]},
     "DOMAIN_NOT_ALLOWED_FOR_EXCHANGE"),
    ({"sources": [{"url": "http://www.nseindia.com/x", "passage": PASSAGE, "source_type": "EXCHANGE"}]},
     "SOURCE_NOT_HTTPS"),
    ({"published_at": "2026-11-09T10:00:00+05:30"}, "PUBLISHED_AFTER_RECEIPT"),
    ({"published_at": "2026-11-04T18:00:00"}, "BAD_DATE_OR_TIME"),
    ({"dates": [{"kind": "RECORD_DATE", "date": "06/11/2026"}]}, "BAD_DATE_OR_TIME"),
    ({"sources": []}, "SOURCE_COUNT"),
])
def test_invalid_facts_are_rejected_with_reasons(change, reason):
    a = assess(doc(fact(**change)))
    assert a.ok and not a.accepted and reason in a.rejected[0][1]


def test_unverified_passage_or_news_only_is_a_candidate_not_a_fact():
    a = assess(doc(fact(sources=[{"url": URL, "passage": "A sentence that is not on the page at all.",
                                  "source_type": "EXCHANGE"}])))
    assert not a.accepted and len(a.candidates) == 1 and a.candidates[0]["passages_verified"] is False
    news = "https://economictimes.indiatimes.com/x"
    r = parse_response(raw_response("{}", [(news, "t", PASSAGE)]))
    a = evidence.assess(doc(fact(sources=[{"url": news, "passage": PASSAGE, "source_type": "NEWS"}])), job_id="job-1",
                        isin=ISIN, allowed={**ALLOWED, "NEWS": ["indiatimes.com"]}, result=r)
    assert not a.accepted and a.candidates[0]["primary_sources_only"] is False


def test_closed_schema_rejects_opinion_fields_and_wrong_task():
    bad = doc(fact())
    bad["facts"][0]["recommendation"] = "BUY"
    assert any("recommendation: not allowed" in e for e in assess(bad).errors)
    wrong = doc(fact())
    wrong["task_id"] = "other"
    assert assess(wrong).errors == ["TASK_OR_ISIN_MISMATCH"]
    assert assess("not json").errors == ["SCHEMA_PARSE_FAILED"]


def test_novelty_is_recomputed_from_identity_not_taken_from_the_model():
    f = fact(novelty="NEW")
    key, ekey = evidence.fact_identity(ISIN, f), evidence.event_identity(ISIN, f)
    same = assess(doc(f), known_facts=[{"fact_id": "k1", "fact_key": key, "event_key": ekey}])
    assert same.accepted[0]["novelty"] == "CONFIRMS_KNOWN" and same.accepted[0]["novelty_model"] == "NEW"
    changed = fact(values=[{"field": "DIVIDEND_PER_SHARE", "amount": 2, "unit": "PER_SHARE_INR",
                            "basis": "NOT_APPLICABLE"}])
    upd = assess(doc(changed), known_facts=[{"fact_id": "k1", "fact_key": key, "event_key": ekey}])
    assert upd.accepted[0]["novelty"] == "UPDATES_KNOWN"


def test_contradiction_must_reference_a_known_fact():
    c = {"known_fact_id": "nope", "field": "RECORD_DATE", "known_value": "2026-11-06",
         "reported_value": "2026-11-07", "sources": [{"url": URL, "passage": PASSAGE, "source_type": "EXCHANGE"}]}
    a = assess(doc(contradictions=[c]))
    assert not a.contradictions and "UNKNOWN_FACT_ID" in a.rejected[0][1]
    a = assess(doc(contradictions=[{**c, "known_fact_id": "k1"}]), known_facts=[{"fact_id": "k1"}])
    assert len(a.contradictions) == 1


def test_syndicated_copies_count_as_one_source():
    p = "Company X wins order worth Rs 500 crore from a state utility for supply of transformers"
    copies = [{"url": "https://www.publisher-a.com/n1", "passage": p}, {"url": "https://www.publisher-b.co.in/n9",
                                                                       "passage": p + "."}]
    assert evidence.independent_sources(copies) == 1
    assert evidence.independent_sources(copies + [{"url": "https://www.publisher-c.com/z",
                                                   "passage": "A different report of the order"}]) == 2


# ---- templates --------------------------------------------------------------------------------------

def make_job(kind="overnight_update", **kw):
    entity = {"isin": ISIN, "nse_symbol": "AAA", "bse_code": "500001", "name": "Aaa Limited", "aliases": ["AAA Ltd"]}
    return jobs.new_job(kind, entity, T - timedelta(days=1), T, ALLOWED, created_at=T, **kw)


def test_templates_carry_identifiers_window_sources_and_known_facts():
    job = make_job(known_facts=({"fact_id": "k1", "event_type": "DIVIDEND", "period": "FY2027",
                                 "dates": [{"kind": "RECORD_DATE", "date": "2026-11-06"}], "values": [],
                                 "url": URL, "published_at": "2026-11-04"},))
    instructions, text = templates.render(job)
    for needle in (ISIN, "AAA", "500001", "Aaa Limited", "AAA Ltd", "TIME WINDOW (IST)", "nseindia.com",
                   "sebi.gov.in", "k1: DIVIDEND", "REQUESTED FIELDS"):
        assert needle in text, needle
    assert "untrusted data" in instructions and "Never state or imply buy, sell, hold" in instructions
    assert set(templates.TEMPLATES) == set(jobs.KINDS)
    assert all("@" in t.template_id and len(t.sha256) == 64 for t in templates.TEMPLATES.values())


def test_unknown_requested_field_is_refused():
    with pytest.raises(ValueError):
        templates.render(make_job(requested_fields=("SECRET_SAUCE",)))


def test_jobs_refuse_account_fields_bad_isin_and_too_many_domains():
    entity = {"isin": ISIN, "name": "Aaa Limited", "holdings": 5}
    with pytest.raises(ValueError, match="Private account fields"):
        jobs.new_job("overnight_update", entity, T - timedelta(days=1), T, ALLOWED)
    with pytest.raises(ValueError, match="ISIN"):
        jobs.new_job("overnight_update", {"isin": "XX", "name": "n"}, T - timedelta(days=1), T, ALLOWED)
    with pytest.raises(ValueError, match="20 allowed domains"):
        jobs.new_job("overnight_update", {"isin": ISIN, "name": "n"}, T - timedelta(days=1), T,
                     {"NEWS": [f"d{i}.com" for i in range(21)]})


# ---- queue, runner, archive, replay ------------------------------------------------------------------

class FakeProvider:
    name = "fake"

    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def run(self, req, timeout=0):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def good_result(job_id="job-1"):
    d = doc(fact())
    d["task_id"] = job_id
    return parse_response(raw_response(json.dumps(d), [(URL, "Dividend", PASSAGE)]), want_json=True)


def setup(tmp_path):
    base = tmp_path / "research"
    return jobs.Queue(base / "q.sqlite3"), Ledger(base / "l.sqlite3"), jobs.Archive(base)


def test_queue_dedup_priority_and_expiry(tmp_path):
    q, lg, ar = setup(tmp_path)
    a = make_job("overnight_update")
    assert q.submit(a, T) == "QUEUED"
    dup = jobs.new_job("overnight_update", a.entity, a.window_start, a.window_end, ALLOWED, created_at=T)
    assert q.submit(dup, T) == "DUPLICATE"
    urgent = make_job("material_event_investigation", trigger={"url": URL, "title": "t"})
    q.submit(urgent, T)
    assert [j.kind for j in q.pending(T)] == ["material_event_investigation", "overnight_update"]
    assert q.pending(T + timedelta(hours=11))[0:1] == []  # both expired (3 h and 10 h TTL)
    assert q.state(a.job_id)[0] == "EXPIRED"
    for x in (q, lg, ar):
        x.close()


def test_runner_success_stores_facts_available_only_from_completion(tmp_path, monkeypatch):
    q, lg, ar = setup(tmp_path)
    job = make_job()
    q.submit(job, T)
    done_at = datetime(2026, 11, 5, 7, 5, tzinfo=IST)
    monkeypatch.setattr(jobs, "now", lambda: done_at)
    out = jobs.run_one(q, FakeProvider([good_result(job.job_id)]), lg, ar, at=T, model=MODEL)
    assert out["result"] == "DONE" and out["accepted"] == 1 and out["cost_usd"] == "0.0041"
    assert jobs.run_one(q, NullProvider(), lg, ar, at=T)["result"] == "NO_PROVIDER_CONFIGURED"
    assert ar.facts_as_of(ISIN, done_at - timedelta(seconds=1)) == []  # not usable before validation finished
    facts = ar.facts_as_of(ISIN, done_at)
    assert facts[0]["status"] == "ACCEPTED" and facts[0]["fact"]["fact_key"]
    assert lg.spent(done_at)["day"] == D("0.0041")
    for x in (q, lg, ar):
        x.close()


def test_rate_limit_is_released_and_retried_auth_is_final(tmp_path):
    q, lg, ar = setup(tmp_path)
    job = make_job()
    q.submit(job, T)
    prov = FakeProvider([ProviderError("RATE_LIMITED", retry_after=1), good_result(job.job_id)])
    out = jobs.run_one(q, prov, lg, ar, at=T, sleep=lambda s: None, model=MODEL)
    assert out["result"] == "DONE" and prov.calls == 2
    job2 = make_job(requested_fields=("REVENUE",))
    q.submit(job2, T)
    out = jobs.run_one(q, FakeProvider([ProviderError("AUTH", http_status=401)]), lg, ar, at=T, model=MODEL)
    assert out == {"result": "FAILED", "job_id": job2.job_id, "error": "AUTH"}
    for x in (q, lg, ar):
        x.close()


def test_budget_exhaustion_defers_and_private_data_is_never_sent(tmp_path):
    base = tmp_path / "research"
    q, ar = jobs.Queue(base / "q.sqlite3"), jobs.Archive(base)
    lg = Ledger(base / "l.sqlite3", Policy(monthly_usd=D("0.01"), daily_usd=D("0.01")))
    job = make_job()
    q.submit(job, T)
    prov = FakeProvider([])
    assert jobs.run_one(q, prov, lg, ar, at=T, model=MODEL)["reason"] == "DAILY_CAP" and prov.calls == 0
    assert q.state(job.job_id)[0] == "DEFERRED" and q.pending(T + timedelta(minutes=30)) == []
    leaked = make_job(requested_fields=("REVENUE",), known_facts=({"fact_id": "k", "event_type": "OTHER_MATERIAL",
                                                                   "url": "secret-client-AB1234"},))
    q2 = jobs.Queue(base / "q2.sqlite3")
    q2.submit(leaked, T)
    out = jobs.run_one(q2, prov, Ledger(base / "l2.sqlite3"), ar, private_values=["secret-client-AB1234"], at=T, model=MODEL)
    assert out["error"] == "PRIVATE_DATA_BLOCKED" and prov.calls == 0
    for x in (q, q2, lg, ar):
        x.close()


def test_deep_research_waits_for_off_hours(tmp_path):
    q, lg, ar = setup(tmp_path)
    q.submit(make_job("bounded_company_research"), T)
    in_session = datetime(2026, 11, 5, 11, 0, tzinfo=IST)
    assert jobs.run_one(q, FakeProvider([]), lg, ar, at=in_session, model=MODEL) == {"result": "IDLE"}
    for x in (q, lg, ar):
        x.close()


def test_validation_failure_is_recorded_not_stored(tmp_path):
    q, lg, ar = setup(tmp_path)
    job = make_job()
    q.submit(job, T)
    bad = parse_response(raw_response("not json", [(URL, "t", PASSAGE)]), want_json=True)
    out = jobs.run_one(q, FakeProvider([bad]), lg, ar, at=T, model=MODEL)
    assert out["result"] == "FAILED_VALIDATION" and out["errors"] == ["SCHEMA_PARSE_FAILED"]
    assert ar.facts_as_of(ISIN, datetime(2027, 1, 1, tzinfo=IST)) == []
    for x in (q, lg, ar):
        x.close()


def test_stale_running_job_fails_and_replay_never_calls_the_network(tmp_path, monkeypatch):
    q, lg, ar = setup(tmp_path)
    job = make_job()
    q.submit(job, T)
    q.event(job.job_id, "RUNNING", T)
    assert q.pending(T + timedelta(minutes=20)) == [] and q.state(job.job_id)[1]["error"] == "STALE_RUNNING"
    job2 = make_job(requested_fields=("REVENUE",))
    q.submit(job2, T)
    monkeypatch.setattr(jobs, "now", lambda: T)
    jobs.run_one(q, FakeProvider([good_result(job2.job_id)]), lg, ar, at=T, model=MODEL)
    req, _ = jobs.build_request(job2, MODEL)
    replay = ArchivedProvider(ar.lookup)
    assert replay.run(req).parsed["task_id"] == job2.job_id
    other, _ = jobs.build_request(make_job(requested_fields=("NET_PROFIT",)), MODEL)
    with pytest.raises(ProviderError) as e:
        replay.run(other)
    assert e.value.label == "NOT_ARCHIVED"
    for x in (q, lg, ar):
        x.close()
