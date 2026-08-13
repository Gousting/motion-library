"""meta.yaml 字段完整性校验单测。"""
from scripts.schemas import REQUIRED_FIELDS, validate_meta


def _valid_meta(**overrides):
    meta = {
        "id": "walk_slow_legs_001",
        "action_type": "walk",
        "sub_action": "slow_walk",
        "camera": "closeup",
        "body_part": "legs",
        "clarity_grade": "A",
        "duration_sec": 4.0,
        "resolution": "1344x768",
        "fps": 24,
        "source_type": "reuse",
        "source_url": "https://pixabay.com/videos/walk-slow-legs-feet-shoes-47129/",
        "license": "derived",
        "style_pollution": False,
        "r2v_verified": True,
        "r2v_score": 88,
        "r2v_checks": {"char_locked": True, "motion_natural": True, "spatial_stable": True},
    }
    meta.update(overrides)
    return meta


def test_valid_meta_passes():
    assert validate_meta(_valid_meta()) == []


def test_field_count_is_16():
    # 方案书顶层字段共 16 个：15 标量 + r2v_checks（dict，含 3 子字段）。
    # 标量字段列表 REQUIRED_FIELDS = 15；r2v_checks 在 validate_meta 里单独校验。
    assert len(REQUIRED_FIELDS) == 15
    from scripts.schemas import R2V_CHECK_KEYS
    assert len(R2V_CHECK_KEYS) == 3


def test_missing_field_detected():
    m = _valid_meta()
    del m["r2v_score"]
    errs = validate_meta(m)
    assert any("r2v_score" in e for e in errs)


def test_missing_required_field_each_detected():
    m = _valid_meta()
    del m["source_type"]
    errs = validate_meta(m)
    assert any("source_type" in e for e in errs)


def test_bad_grade_detected():
    errs = validate_meta(_valid_meta(clarity_grade="Z"))
    assert any("clarity_grade" in e for e in errs)


def test_bad_camera_detected():
    errs = validate_meta(_valid_meta(camera="wide"))
    assert any("camera" in e for e in errs)


def test_bad_body_part_detected():
    errs = validate_meta(_valid_meta(body_part="torso"))
    assert any("body_part" in e for e in errs)


def test_bad_source_type_detected():
    errs = validate_meta(_valid_meta(source_type="ai"))
    assert any("source_type" in e for e in errs)


def test_score_out_of_range_detected():
    errs = validate_meta(_valid_meta(r2v_score=101))
    assert any("r2v_score" in e for e in errs)


def test_wrong_type_detected():
    errs = validate_meta(_valid_meta(r2v_score="88"))  # str 而非 int
    assert any("r2v_score" in e for e in errs)


def test_missing_check_subfield_detected():
    m = _valid_meta()
    del m["r2v_checks"]["spatial_stable"]
    errs = validate_meta(m)
    assert any("spatial_stable" in e for e in errs)


def test_id_no_whitespace():
    errs = validate_meta(_valid_meta(id="walk slow legs"))
    assert any("空白" in e for e in errs)
