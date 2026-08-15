#!/usr/bin/env python3
"""素材自动获取：按原语从 Pixabay video API 搜「肢体/全身动作」候选并下载。

CLI:
  python scripts/fetch_stock.py --primitive walk_toward --limit 5 --out work/raw/

流程：读取 config.yaml 的 stock 段（provider=pixabay / api_key 占位符 / search_terms）→
密钥由 .env ``MOTIONLIB_PIXABAY_API_KEY`` 覆盖 → 按原语搜索词调 Pixabay video API →
下载候选 mp4 到 ``<out>/<primitive_id>/`` → 打印候选清单（id + 时长 + 分辨率 + 尺寸）。

本脚本**只做候选素材下载 + 清单展示，不做入库验证**（入库是下一期拿到 key 后逐个跑 R2V 的事）。
退出码：0=成功；2=配置/网络错误。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402

from scripts.config import STOCK_API_KEY_ENV, get_stock_api_key, load_config  # noqa: E402
from scripts.r2v import PRIMITIVE_TEMPLATES  # noqa: E402

PIXABAY_VIDEOS_URL = "https://pixabay.com/api/videos/"

# 兜底搜索词（肢体/全身动作，非场景风景）；config.yaml stock.search_terms 可覆盖。
DEFAULT_SEARCH_TERMS: dict[str, str] = {
    "walk_toward": "walking legs feet",
    "walk_away": "walking away back view",
    "run_toward": "running legs",
    "turn": "turning around body",
    "sit": "sitting down bench",
    "stand": "standing up chair",
    "reach_grab": "reaching grabbing object hand",
    "open_door": "opening door",
    "wave": "waving hand greeting",
    "nod": "nodding head",
    "head_turn": "turning head look",
}

# 视频清晰度档位挑选顺序：优先 medium（尺寸/画质均衡），逐级回退。
VARIANT_ORDER = ("medium", "small", "tiny", "large")

# Pixabay 边缘节点会 RST 默认 python-requests UA，必须带浏览器 UA。
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (motion-library stock fetch)"}


def _get(url: str, params: dict | None = None, attempts: int = 3, **kw):
    """带重试的 GET（Pixabay 偶发连接重置）。"""
    import time
    last = ""
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=kw.pop("timeout", 60), **kw)
            return r
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(2 + i * 2)
    raise RuntimeError(f"请求失败（已重试 {attempts} 次）: {last[:300]}")


def get_search_term(cfg: dict, primitive_id: str) -> str:
    """取原语搜索词：config.yaml stock.search_terms 覆盖代码兜底。"""
    terms = dict(DEFAULT_SEARCH_TERMS)
    terms.update((cfg.get("stock") or {}).get("search_terms") or {})
    return terms.get(primitive_id, "")


def pick_variant(hit: dict) -> tuple[str, dict] | None:
    """从 Pixabay hit 的 videos 字典按 VARIANT_ORDER 挑一个可用档位，返回 (档位, 视频信息)。"""
    videos = hit.get("videos") or {}
    for name in VARIANT_ORDER:
        v = videos.get(name) or {}
        if v.get("url"):
            return name, v
    return None


def fetch_hits(api_key: str, query: str, limit: int, per_page: int) -> list[dict]:
    """调 Pixabay video API，返回至多 limit 个 hit。"""
    params = {"key": api_key, "q": query, "per_page": per_page, "safesearch": "true"}
    r = _get(PIXABAY_VIDEOS_URL, params=params)
    if r.status_code != 200:
        raise RuntimeError(f"Pixabay API 返回 {r.status_code}: {r.text[:300]}")
    hits = r.json().get("hits") or []
    return hits[:limit]


def download_candidates(hits: list[dict], out_dir: Path) -> list[dict]:
    """下载每个 hit 的候选 mp4 到 out_dir，返回候选清单（含 id/时长/分辨率/尺寸）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    listing: list[dict] = []
    for hit in hits:
        picked = pick_variant(hit)
        if picked is None:
            continue
        variant, v = picked
        url = v["url"]
        dest = out_dir / f"pixabay_{hit.get('id')}_{variant}.mp4"
        with requests.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        listing.append({
            "id": hit.get("id"),
            "page_url": hit.get("pageURL"),
            "file": str(dest),
            "variant": variant,
            "duration_sec": hit.get("duration"),
            "resolution": f'{v.get("width")}x{v.get("height")}',
            "size_mb": round((v.get("size") or dest.stat().st_size) / 1048576, 2),
            "tags": hit.get("tags"),
        })
    return listing


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按原语从 Pixabay 下载候选动作素材")
    ap.add_argument("--primitive", required=True, help=f"原语 id（{', '.join(sorted(PRIMITIVE_TEMPLATES))}）")
    ap.add_argument("--limit", type=int, default=5, help="候选数量（默认 5）")
    ap.add_argument("--out", default="work/raw", help="输出根目录（候选落到 <out>/<primitive_id>/）")
    args = ap.parse_args(argv)

    primitive_id = args.primitive
    if primitive_id not in PRIMITIVE_TEMPLATES:
        print(f"[错误] 未知原语 {primitive_id!r}，可选: {', '.join(sorted(PRIMITIVE_TEMPLATES))}",
              file=sys.stderr)
        return 2

    cfg = load_config()
    api_key = get_stock_api_key(cfg)
    if not api_key:
        print(f"[错误] 未配置 Pixabay 密钥：请先在 .env 设 {STOCK_API_KEY_ENV}"
              f"（config.yaml 的 stock.api_key 只是占位符）。", file=sys.stderr)
        return 2

    query = get_search_term(cfg, primitive_id)
    if not query:
        print(f"[错误] 原语 {primitive_id} 没有配置搜索词（config.yaml stock.search_terms）。",
              file=sys.stderr)
        return 2

    out_dir = Path(args.out) / primitive_id
    print(f"[fetch] primitive={primitive_id} query={query!r} limit={args.limit} out={out_dir}", flush=True)
    try:
        per_page = int((cfg.get("stock") or {}).get("per_page", 10))
        hits = fetch_hits(api_key, query, args.limit, max(per_page, args.limit))
        listing = download_candidates(hits, out_dir)
    except Exception as e:  # noqa: BLE001
        print(f"[错误] Pixabay 获取失败: {e}", file=sys.stderr)
        return 2

    if not listing:
        print(f"[提示] 无候选命中（query={query!r}）。可换搜索词或增大 --limit。")
        return 0

    print("=" * 80)
    print(f"候选清单（未做入库验证，下载仅供后续 R2V 评级）— {out_dir}")
    for c in listing:
        print(f"  id={c['id']:<10} 时长={c['duration_sec']}s  分辨率={c['resolution']:<11} "
              f"尺寸={c['size_mb']}MB  档={c['variant']}")
        print(f"      {c['page_url']}")
    print("=" * 80)
    return 0


def main(argv=None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[错误] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
