"""index.yaml 登记逻辑单测（load/save roundtrip + 分组）。"""
from pathlib import Path

from scripts.rating import load_index, register_entry, save_index


def _meta(id, action_type, grade, score):
    return {
        "id": id, "action_type": action_type, "sub_action": "slow_walk",
        "camera": "closeup", "body_part": "legs",
        "clarity_grade": grade, "r2v_score": score,
    }


def test_register_then_roundtrip(tmp_path):
    path = tmp_path / "index.yaml"
    idx = register_entry(load_index(path), _meta("walk_slow_legs_001", "walk", "A", 88),
                         "walk/walk_slow_legs_001")
    save_index(idx, path)
    loaded = load_index(path)
    e = loaded["entries"]["walk"][0]
    assert e["id"] == "walk_slow_legs_001"
    assert e["clarity_grade"] == "A"
    assert e["r2v_score"] == 88
    assert e["path"] == "walk/walk_slow_legs_001"


def test_load_missing_file_returns_empty():
    idx = load_index(Path("/nonexistent_dir/index.yaml"))
    assert idx == {"version": 1, "entries": {}}


def test_load_corrupt_yaml_returns_empty(tmp_path):
    path = tmp_path / "index.yaml"
    path.write_text("::not valid yaml::\n\t- [", encoding="utf-8")
    idx = load_index(path)
    assert idx == {"version": 1, "entries": {}}


def test_register_multiple_action_types_grouped(tmp_path):
    path = tmp_path / "index.yaml"
    idx = register_entry(load_index(path), _meta("walk_001", "walk", "A", 88), "walk/walk_001")
    idx = register_entry(idx, _meta("turn_001", "turn", "B", 75), "turn/turn_001")
    save_index(idx, path)
    loaded = load_index(path)
    assert set(loaded["entries"].keys()) == {"walk", "turn"}
