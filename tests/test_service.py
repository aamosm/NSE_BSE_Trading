"""Scheduler: due windows, circuit breakers, auth state, pause control, single instance, idempotent decisions."""
import json
from datetime import date, datetime, timedelta

import pytest

from marketlab import login, service
from marketlab.common import IST, atomic_json
from marketlab.kite import AuthenticationRequired
from marketlab.rules import MarketCalendar
from marketlab.store import Store

CAL = MarketCalendar()


def at(d, h, m=0):
    return datetime(2026, 11, d, h, m, tzinfo=IST)


def names(jobs):
    return sorted(n for n, _ in jobs)


@pytest.mark.parametrize("when, expected", [
    (at(5, 8, 0), ["feeds", "prepare", "public_daily", "public_eod"]),  # Thu morning: catch up Wed files
    (at(5, 10, 0), ["broker", "feeds", "public_daily"]),
    (at(5, 19, 30), ["broker", "feeds", "public_daily", "public_eod"]),
    (at(7, 10, 0), ["feeds", "public_daily"]),  # Saturday: no broker session
    (at(8, 14, 30), ["broker", "feeds", "public_daily"]),  # Muhurat session (opens 14:05)
    (at(8, 12, 0), ["feeds", "public_daily"]),  # before Muhurat pre-open minus 30 min
    (at(5, 23, 40), ["backup", "broker", "feeds", "public_daily", "public_eod"]),
])
def test_due_windows_follow_the_exchange_calendar(when, expected):
    assert names(service.due_jobs(when, CAL, {})) == expected


def test_eod_target_is_the_latest_completed_session():
    jobs = dict(service.due_jobs(at(9, 7, 0), CAL, {}))  # Monday morning after the Sunday Muhurat session
    assert jobs["public_eod"]["day"] == date(2026, 11, 8)


def test_jobs_respect_their_cadence():
    last = {"broker": at(5, 10, 0).isoformat(), "feeds": at(5, 9, 50).isoformat(),
            "public_daily:2026-11-05": at(5, 7, 0).isoformat()}
    assert names(service.due_jobs(at(5, 10, 3), CAL, last)) == []
    assert names(service.due_jobs(at(5, 10, 5), CAL, last)) == ["broker"]


def ctx(tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    return service.Context(root, tmp_path / "market", ["NSE:AAA"], calendar=CAL, pause=0)


def login_now(root, when):
    atomic_json(root / login.SESSION_FILE, {"api_key": "k", "access_token": "t", "login_at": when.isoformat(),
                                            "expires_at": login.next_expiry(when).isoformat()})


def ok_job(c, a):
    return "OK"


def test_failure_opens_a_breaker_and_skips_until_it_closes(tmp_path):
    c = ctx(tmp_path)
    login_now(c.root, at(5, 9, 0))
    calls = []

    def failing(cx, a):
        calls.append(a["key"])
        raise service.JobFailed("SOURCE_FAILED:nse_bhavcopy")

    jobs = {**{k: ok_job for k in service.JOBS}, "public_daily": failing}
    st = service.tick(c, at(5, 10, 0), jobs)
    assert st["state"] == "DEGRADED" and st["jobs"]["public_daily"]["error"] == "SOURCE_FAILED:nse_bhavcopy"
    assert st["breakers"]["exchange_files"]["failures"] == 1
    st = service.tick(c, at(5, 10, 10), jobs)
    assert st["jobs"]["public_daily"]["result"] == "SKIPPED_BREAKER_OPEN" and len(calls) == 1
    service.tick(c, at(5, 10, 16), jobs)  # 15-minute back-off elapsed: retried, fails again, doubled back-off
    assert len(calls) == 2 and st["breakers"]["exchange_files"]["failures"] == 2
    assert json.loads((c.root / service.STATE_FILE).read_text())["live_orders"] is False


def test_expired_or_invalidated_session_means_auth_required_but_public_jobs_continue(tmp_path):
    c = ctx(tmp_path)
    ran = []
    jobs = {k: (lambda cx, a, k=k: ran.append(k) or "OK") for k in service.JOBS}
    jobs["broker"] = service.job_broker
    st = service.tick(c, at(5, 10, 0), jobs)
    assert st["state"] == "AUTH_REQUIRED" and st["jobs"]["broker"]["result"] == "SKIPPED_AUTH_REQUIRED"
    assert "feeds" in ran and "public_daily" in ran

    login_now(c.root, at(5, 10, 1))

    def invalidated(cx, a):
        raise AuthenticationRequired("token rejected")
    jobs["broker"] = invalidated
    st = service.tick(c, at(5, 10, 6), jobs)
    assert st["state"] == "AUTH_REQUIRED" and st["session"]["invalidated"] is True
    login_now(c.root, at(5, 10, 20))  # a newer login clears the invalidation
    jobs["broker"] = ok_job
    st = service.tick(c, at(5, 10, 21), jobs)
    assert st["state"] == "RUNNING" and "invalidated" not in st["session"]


def test_pause_only_affects_analysis(tmp_path):
    c = ctx(tmp_path)
    login_now(c.root, at(5, 8, 0))
    service.set_paused(c.root, True, at(5, 8, 1))
    st = service.tick(c, at(5, 10, 0), {k: ok_job for k in service.JOBS})
    assert st["analysis"] == "PAUSED" and st["state"] == "RUNNING"
    service.set_paused(c.root, False)
    assert service.tick(c, at(5, 10, 5), {k: ok_job for k in service.JOBS})["analysis"] == "ACTIVE"


def test_decision_record_is_idempotent_across_restarts(tmp_path):
    c = ctx(tmp_path)
    service.record_decision(c, date(2026, 11, 5), "WAIT", ["MODEL_NOT_VALIDATED"], ["NSE:AAA"])
    service.record_decision(c, date(2026, 11, 5), "WAIT", ["MODEL_NOT_VALIDATED"], ["NSE:AAA"])
    db = Store(c.root / "evidence.sqlite3")
    rows = db.as_of("paper_decision", "2026-11-05", at(6, 0))
    db.close()
    assert len(rows) == 1 and rows[0]["payload"]["simulated"] is True
    assert "not passed paper-trading validation" in rows[0]["payload"]["explanation"]


def test_second_scheduler_is_refused(tmp_path):
    lock = tmp_path / "service.lock"
    with service.single_instance(lock):
        with pytest.raises(RuntimeError, match="already holds the lock"):
            with service.single_instance(lock):
                pass
    with service.single_instance(lock):  # released after the first one exits
        pass


def test_no_alert_or_heartbeat_without_https_configuration(tmp_path, monkeypatch):
    c = ctx(tmp_path)
    (c.root / ".env").write_text("MARKETLAB_ALERT_URL=http://insecure.example/x\n")
    monkeypatch.setattr(service, "build_opener", lambda *a: pytest.fail("no network call expected"))
    st = service.tick(c, at(5, 10, 0), {k: ok_job for k in service.JOBS})
    assert "last_alert" not in st and "heartbeat" not in st


def test_alert_on_state_change_carries_fixed_text_only(tmp_path, monkeypatch):
    c = ctx(tmp_path)
    (c.root / ".env").write_text("MARKETLAB_ALERT_URL=https://ntfy.example/topic\n")
    sent = []

    class Opener:
        def open(self, req, timeout):
            sent.append(req.data.decode())

            class R:
                def close(self):
                    pass
            return R()
    monkeypatch.setattr(service, "build_opener", lambda *a: Opener())
    service.tick(c, at(5, 10, 0), {k: ok_job for k in service.JOBS})  # no session -> AUTH_REQUIRED
    service.tick(c, at(5, 10, 1), {k: ok_job for k in service.JOBS})  # unchanged -> no repeat
    assert sent == [service.ALERT_TEXT["AUTH_REQUIRED"]]
