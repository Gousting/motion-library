"""评级映射边界单测（任务书硬要求：79/80、69/70）+ auto_grade + index 登记。"""
import pytest

from scripts.rating import auto_grade, register_entry, score_to_grade

ALL_TRUE = {"char_locked": True, "motion_natural": True, "spatial_stable": True}


@pytest.mark.parametrize(
    "score,expected",
    [
        (100, "A"),
        (80, "A"),   # 边界：>=80 → A
        (79, "B"),   # 边界：70-79 → B
        (70, "B"),   # 边界：>=70 → B
        (69, "C"),   # 边界：<70 → C
        (0, "C"),
    ],
)
def test_score_to_grade_boundaries(score, expected):
    assert score_to_grade(score) == expected


def test_auto_grade_a():
    assert auto_grade(88, ALL_TRUE) == ("A", True)


def test_auto_grade_a_downgrade_when_check_false():
    checks = dict(ALL_TRUE)
    checks["motion_natural"] = False
    # score>=80 但三项任一 false → 降级 B 标注风险
    assert auto_grade(88, checks) == ("B", True)


def test_auto_grade_b():
    assert auto_grade(75, ALL_TRUE) == ("B", True)


def test_auto_grade_c_reject():
    checks = {"char_locked": True, "motion_natural": False, "spatial_stable": True}
    assert auto_grade(60, checks) == ("C", False)


def _meta(id, action_type, grade, score):
    return {
        "id": id, "action_type": action_type, "sub_action": "slow_walk",
        "camera": "closeup", "body_part": "legs",
        "clarity_grade": grade, "r2v_score": score,
    }


def test_register_entry_groups_by_action_type():
    idx = register_entry({"version": 1, "entries": {}},
                         _meta("walk_slow_legs_001", "walk", "A", 88),
                         "walk/walk_slow_legs_001")
    assert "walk" in idx["entries"]
    e = idx["entries"]["walk"][0]
    assert e["id"] == "walk_slow_legs_001"
    assert e["r2v_score"] == 88
    assert e["path"] == "walk/walk_slow_legs_001"


def test_register_entry_overwrites_same_id():
    idx = {"version": 1, "entries": {
        "walk": [{"id": "x", "camera": "closeup", "body_part": "legs",
                  "clarity_grade": "B", "r2v_score": 70, "path": "walk/x"}],
    }}
    idx = register_entry(idx, _meta("x", "walk", "A", 90), "walk/x")
    assert len(idx["entries"]["walk"]) == 1
    assert idx["entries"]["walk"][0]["r2v_score"] == 90


def test_register_entry_sort_by_grade_then_score():
    idx = {"version": 1, "entries": {}}
    idx = register_entry(idx, _meta("a", "walk", "B", 75), "walk/a")
    idx = register_entry(idx, _meta("b", "walk", "A", 82), "walk/b")
    idx = register_entry(idx, _meta("c", "walk", "A", 90), "walk/c")
    order = [e["id"] for e in idx["entries"]["walk"]]
    assert order == ["c", "b", "a"]  # A(高) → A(低) → B
