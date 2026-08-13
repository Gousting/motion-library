"""meta.yaml 元数据字段规范与完整性校验（对齐方案书）。

每条动作的 ``meta.yaml`` 字段固定，本模块是唯一权威（single source of truth）：
- ``REQUIRED_FIELDS`` / 各类型字段列表：定义哪些字段必填、什么类型。
- ``ALLOWED_*``：枚举字段的合法取值。
- ``validate_meta(meta) -> list[str]``：返回错误列表，空列表 = 通过。
"""

from __future__ import annotations

# ---- 字段分类（全部 17 个字段，见 README「元数据规范」表）----
STR_FIELDS: tuple[str, ...] = (
    "id",
    "action_type",
    "sub_action",
    "camera",
    "body_part",
    "clarity_grade",
    "resolution",
    "source_type",
    "source_url",
    "license",
)
BOOL_FIELDS: tuple[str, ...] = ("style_pollution", "r2v_verified")
INT_FIELDS: tuple[str, ...] = ("r2v_score", "fps")
FLOAT_FIELDS: tuple[str, ...] = ("duration_sec",)

REQUIRED_FIELDS: tuple[str, ...] = (
    STR_FIELDS + BOOL_FIELDS + INT_FIELDS + FLOAT_FIELDS
)

# ---- VLM 三项判断（r2v_checks 子字段）----
R2V_CHECK_KEYS: tuple[str, ...] = ("char_locked", "motion_natural", "spatial_stable")

# ---- 枚举字段合法取值 ----
ALLOWED_GRADES: frozenset[str] = frozenset({"A", "B", "C"})
ALLOWED_CAMERA: frozenset[str] = frozenset({"full", "medium", "closeup"})
ALLOWED_BODY_PART: frozenset[str] = frozenset(
    {"full_body", "half_body", "legs", "hands", "face"}
)
ALLOWED_SOURCE_TYPE: frozenset[str] = frozenset({"stock", "selfshot", "reuse"})
ALLOWED_LICENSE: frozenset[str] = frozenset({"pexels-free", "self-shot", "derived"})

# action_type 主分类：开放扩展，仅列出已知分类作为参考
KNOWN_ACTION_TYPES: frozenset[str] = frozenset(
    {"walk", "turn", "sit", "hand", "flip", "run", "jump", "gesture", "dance"}
)


def validate_meta(meta: dict) -> list[str]:
    """校验一条 meta.yaml 数据，返回错误信息列表（空 = 通过）。

    覆盖：必填字段缺失、字段类型错误、枚举字段越界、r2v_checks 三项缺项、
    r2v_score 越界、id 非法。字段名来自 ``meta`` 的顶层键。
    """
    errors: list[str] = []

    # 1. 必填字段缺失
    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    for f in missing:
        errors.append(f"缺少必填字段: {f}")

    # 2. 类型校验（字段存在时才查类型，缺失字段已在上面报过）
    for f in STR_FIELDS:
        if f in meta and not isinstance(meta[f], str):
            errors.append(f"字段 {f} 应为字符串，实际 {type(meta[f]).__name__}")
    for f in BOOL_FIELDS:
        if f in meta and not isinstance(meta[f], bool):
            errors.append(f"字段 {f} 应为布尔，实际 {type(meta[f]).__name__}")
    for f in INT_FIELDS:
        if f in meta and not isinstance(meta[f], int):
            errors.append(f"字段 {f} 应为整数，实际 {type(meta[f]).__name__}")
    for f in FLOAT_FIELDS:
        if f in meta and isinstance(meta[f], bool):
            errors.append(f"字段 {f} 应为数值，实际 bool")
        elif f in meta and not isinstance(meta[f], (int, float)):
            errors.append(f"字段 {f} 应为数值，实际 {type(meta[f]).__name__}")

    # 3. 枚举字段越界
    if isinstance(meta.get("clarity_grade"), str) and meta["clarity_grade"] not in ALLOWED_GRADES:
        errors.append(f"clarity_grade 非法: {meta['clarity_grade']!r}（合法 {sorted(ALLOWED_GRADES)}）")
    if isinstance(meta.get("camera"), str) and meta["camera"] not in ALLOWED_CAMERA:
        errors.append(f"camera 非法: {meta['camera']!r}（合法 {sorted(ALLOWED_CAMERA)}）")
    if isinstance(meta.get("body_part"), str) and meta["body_part"] not in ALLOWED_BODY_PART:
        errors.append(f"body_part 非法: {meta['body_part']!r}（合法 {sorted(ALLOWED_BODY_PART)}）")
    if isinstance(meta.get("source_type"), str) and meta["source_type"] not in ALLOWED_SOURCE_TYPE:
        errors.append(f"source_type 非法: {meta['source_type']!r}（合法 {sorted(ALLOWED_SOURCE_TYPE)}）")
    if isinstance(meta.get("license"), str) and meta["license"] not in ALLOWED_LICENSE:
        errors.append(f"license 非法: {meta['license']!r}（合法 {sorted(ALLOWED_LICENSE)}）")

    # 4. r2v_score 越界（0-100）
    score = meta.get("r2v_score")
    if isinstance(score, int) and not (0 <= score <= 100):
        errors.append(f"r2v_score 越界: {score}（应在 0-100）")

    # 5. r2v_checks 三项完整性
    checks = meta.get("r2v_checks")
    if not isinstance(checks, dict):
        errors.append("缺少 r2v_checks 或类型错误（应为 dict，含 char_locked/motion_natural/spatial_stable）")
    else:
        for k in R2V_CHECK_KEYS:
            if k not in checks:
                errors.append(f"r2v_checks 缺少子字段: {k}")
            elif not isinstance(checks[k], bool):
                errors.append(f"r2v_checks.{k} 应为布尔，实际 {type(checks[k]).__name__}")

    # 6. id 格式（非空、无空格、建议 snake_case，但不强制）
    if isinstance(meta.get("id"), str):
        if not meta["id"]:
            errors.append("id 不能为空")
        elif any(c.isspace() for c in meta["id"]):
            errors.append(f"id 不能含空白字符: {meta['id']!r}")

    return errors
