import importlib.util
from pathlib import Path

import pytest

from nycdistress.llm import client as cl
from nycdistress.llm.sandbox import DB, Sandbox

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("llm_eval", ROOT / "pipelines" / "llm_eval.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
needs_marts = pytest.mark.skipif(not DB.exists(), reason="marts.duckdb not built")


@needs_marts
def test_harness_mode_reports_perfect_wrong_and_detected_corruptions():
    out = ev.harness(Sandbox(), 12)
    assert "NOT model results" in out["mode"]
    t = out["text_to_sql"]
    assert t["stub-oracle"]["execution_accuracy"] == 1.0 and t["stub-wrong"]["execution_accuracy"] == 0.0
    b = out["biography"]
    assert b["template_fully_verified"] == 12 and b["numeric_corruptions_caught"] == b["numeric_corruptions_tried"] >= 10 and b["invented_ids_caught"] == 12


@needs_marts
def test_live_mode_refuses_without_a_key_and_never_invents_numbers(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cl, "load_dotenv", lambda *_a, **_k: [])
    with pytest.raises(SystemExit) as e:
        ev.live(Sandbox(), None, 3)
    assert "No ANTHROPIC_API_KEY" in str(e.value) and "nothing was invented" in str(e.value)
