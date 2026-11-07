from marketlab.quant.universe import ScreenPolicy, research_universe, screen
from synthetic import make_panel


def test_research_universe_keeps_expensive_and_illiquid_securities(tmp_path):
    panel = make_panel(tmp_path / "panel.sqlite3", n=30, n_stocks=2)
    day = panel.sessions()[-1]
    research = research_universe(panel, day)
    execution = screen(panel, day, ScreenPolicy(v_min=10_000_000_000, price_max_fraction=.01),
                       sessions=panel.sessions())
    assert "INE000A01001" in research.isins
    assert "INE000A01001" not in execution.isins
    assert research.excluded == {}


def test_research_universe_does_not_require_rule_inputs(tmp_path):
    panel = make_panel(tmp_path / "panel.sqlite3", n=30, n_stocks=2)
    research = research_universe(panel, panel.sessions()[-1])
    assert research.unverified == []
    assert research.availability == "NONE"
