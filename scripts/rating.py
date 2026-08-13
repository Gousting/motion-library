"""评级映射（纯函数）+ index.yaml 登记逻辑。

- ``score_to_grade``：score → clarity_grade 的纯阈值映射（任务书阈值，单测覆盖边界 79/80、69/70）。
- ``auto_grade``：结合 score + VLM 三项判断，输出最终评级与是否入库（弃用判断）。
- ``register_entry`` / ``load_index`` / ``save_index``：index.yaml 按 action_type 分组登记。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from scripts import schemas

# 评级阈值（与 config.yaml 的 rating 段一致；这里作为纯函数默认值，便于单测）
A_THRESHOLD = 80
B_THRESHOLD = 70


def score_to_grade(score: int) -> str:
    """score → clarity_grade 纯函数（任务书阈值）。

    - ``>= 80`` → ``A``
    - ``70-79`` → ``B``（标注风险）
    - ``< 70``   → ``C``（弃用）
    """
    if score >= A_THRESHOLD:
        return "A"
    if score >= B_THRESHOLD:
        return "B"
    return "C"


def auto_grade(score: int, checks: dict) -> tuple[str, bool]:
    """结合 R2V 评分 + VLM 三项判断 → ``(grade, accept)``。

    - ``score < 70`` → ``("C", False)``，弃用（不入库不写 meta）。
    - ``70 <= score < 80`` → ``("B", True)``，标注风险。
    - ``score >= 80`` 且三项全 true → ``("A", True)``。
    - ``score >= 80`` 但任一检查 false（动作迁移不干净）→ ``("B", True)``，降级标注风险。
    """
    if score < B_THRESHOLD:
        return "C", False
    grade = "A" if score >= A_THRESHOLD else "B"
    if grade == "A" and not all(bool(checks.get(k)) for k in schemas.R2V_CHECK_KEYS):
        grade = "B"
    return grade, True


def entry_summary(meta: dict, rel_path: str) -> dict:
    """从 meta.yaml 生成 index 条目摘要（id + camera + clarity_grade + r2v_score + 路径等）。"""
    return {
        "id": meta["id"],
        "sub_action": meta.get("sub_action", ""),
        "camera": meta["camera"],
        "body_part": meta["body_part"],
        "clarity_grade": meta["clarity_grade"],
        "r2v_score": meta["r2v_score"],
        "path": rel_path,
    }


_GRADE_RANK = {"A": 0, "B": 1, "C": 2}


def register_entry(index: dict, meta: dict, rel_path: str) -> dict:
    """按 action_type 分组登记（同 id 覆盖），返回更新后的 index 副本。

    纯函数：不落盘。分组内按 grade（A/B/C）再按 r2v_score 降序，方便检索最优动作。
    """
    action_type = meta["action_type"]
    summary = entry_summary(meta, rel_path)

    new_index = {"version": index.get("version", 1), "entries": {}}
    entries = index.get("entries", {}) or {}
    for at, group in entries.items():
        new_index["entries"][at] = [dict(e) for e in (group or []) if isinstance(e, dict)]

    group = new_index["entries"].setdefault(action_type, [])
    group = [e for e in group if e.get("id") != meta["id"]]
    group.append(summary)
    group.sort(key=lambda e: (_GRADE_RANK.get(e.get("clarity_grade"), 9), -int(e.get("r2v_score", 0))))
    new_index["entries"][action_type] = group

    # 分组按 action_type 名排序，稳定输出
    new_index["entries"] = dict(sorted(new_index["entries"].items()))
    return new_index


def load_index(path: Path) -> dict:
    """读取 index.yaml；不存在或损坏时返回空索引。"""
    if not path.exists():
        return {"version": 1, "entries": {}}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    return data


def save_index(index: dict, path: Path) -> None:
    """把 index 写回 yaml（保持字段顺序，中文不转义）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(index, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
