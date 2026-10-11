"""상담 답 품질 비교 도구(tools/quality) -- 질문 묶음 모양과 빨간불 규칙만 본다(네트워크 없음)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("quality_compare", ROOT / "tools" / "quality" / "compare.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def test_question_set_shape():
    qs = C.load_questions("all", None)
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids))
    assert sum(1 for q in qs if q["id"].startswith("E")) == 55
    assert sum(1 for q in qs if q["id"].startswith("R")) >= 30
    assert all(q["criterion"].strip() for q in qs)
    assert len(C.load_questions("pr", None)) == 20
    shards = [C.load_questions("all", "%d/3" % i) for i in (1, 2, 3)]
    assert sorted(q["id"] for s in shards for q in s) == sorted(ids)
    assert any(q["text"] == "개발자용 PC를 가장 저렴하게 추천해줘" for q in qs)


def test_long_question_expands_to_requested_length():
    q = next(q for q in C.load_questions("all", None) if q["id"] == "E16")
    assert len(C.expand(q)) >= 20000


def test_model_follows_repo_setting(monkeypatch):
    monkeypatch.delenv("QUALITY_MODEL", raising=False)
    assert C.repo_model().startswith("claude-")


def _combine(tmp_path, verdicts, gate=True):
    d = tmp_path / "s1"
    d.mkdir()
    rows = [{"id": "R%02d" % i, "group": "g", "question": "q", "criterion": "c", "ours": "a",
             "generic": "b", "verdict": v, "reason": "r"} for i, v in enumerate(verdicts, 1)]
    (d / "rows.json").write_text(json.dumps({"base": "x", "model": "m", "rows": rows}), encoding="utf-8")
    args = type("A", (), {"dirs": [str(d)], "report": str(tmp_path / "r.md"), "summary": None,
                          "gate": gate, "require_judge": False})
    return C.cmd_combine(args)


def test_gate_red_on_any_worse(tmp_path):
    assert _combine(tmp_path, [C.SAME, C.BETTER, C.WORSE]) == 1


def test_gate_green_without_worse_and_unmeasured_not_counted_as_loss(tmp_path):
    assert _combine(tmp_path, [C.SAME, C.BETTER, C.UNMEASURED]) == 0
