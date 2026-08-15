"""fetch_stock：搜索词映射完整性 / 清晰度档位挑选 / 未配 key 清晰报错。"""
import scripts.config as cfg_mod
from scripts import fetch_stock
from scripts.config import get_stock_api_key, load_config
from scripts.r2v import PRIMITIVE_TEMPLATES


def test_search_term_mapping_covers_all_primitives():
    cfg = load_config()
    for pid in PRIMITIVE_TEMPLATES:
        term = fetch_stock.get_search_term(cfg, pid)
        assert term and isinstance(term, str), f"原语 {pid} 缺搜索词"


def test_default_search_terms_cover_all_primitives():
    # 代码兜底映射必须覆盖全部 11 原语（config.yaml 可覆盖但不能缺）
    assert set(fetch_stock.DEFAULT_SEARCH_TERMS) >= set(PRIMITIVE_TEMPLATES)


def test_search_terms_target_body_not_scenery():
    # 搜索词务必落到肢体/全身动作，不能是纯场景风景词
    for pid, term in fetch_stock.DEFAULT_SEARCH_TERMS.items():
        assert term.strip(), pid
        assert "landscape" not in term.lower()
        assert "scenery" not in term.lower()


def test_pick_variant_prefers_medium_then_fallback():
    hit = {"videos": {"large": {"url": "L"}, "medium": {"url": "M"}, "tiny": {"url": "T"}}}
    assert fetch_stock.pick_variant(hit)[0] == "medium"
    hit2 = {"videos": {"large": {"url": "L"}, "tiny": {"url": "T"}}}
    assert fetch_stock.pick_variant(hit2)[0] == "tiny"
    assert fetch_stock.pick_variant({"videos": {}}) is None


def test_placeholder_key_treated_as_unset():
    assert get_stock_api_key({"stock": {"api_key": "YOUR_PIXABAY_API_KEY"}}) == ""
    assert get_stock_api_key({"stock": {"api_key": ""}}) == ""
    assert get_stock_api_key({}) == ""


def test_missing_key_clear_error(monkeypatch, capsys):
    # 未配置 key 时必须清晰报错（指向 .env 的 MOTIONLIB_PIXABAY_API_KEY），不静默失败
    monkeypatch.setattr(cfg_mod, "ENV_PATH", cfg_mod.PROJECT_ROOT / ".env.nonexistent")
    monkeypatch.delenv(cfg_mod.STOCK_API_KEY_ENV, raising=False)
    rc = fetch_stock.run(["--primitive", "walk_toward", "--limit", "1"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "MOTIONLIB_PIXABAY_API_KEY" in err
    assert ".env" in err


def test_unknown_primitive_rejected(capsys):
    rc = fetch_stock.run(["--primitive", "bogus"])
    assert rc == 2
    assert "未知原语" in capsys.readouterr().err
