#!/usr/bin/env python3
"""入库脚本（核心）：预处理 → R2V 验证 → VLM 三项审查 → 自动评级 → 写 meta + index。

CLI:
  # 全新候选（完整验证）
  python scripts/ingest.py --video <候选视频> --action-type walk --camera closeup \
      --body-part legs --source-type stock --source-url <url> --license pexels-free \
      [--sub-action slow_walk] [--style-pollution] [--seed N]

  # 复用已跑过 R2V 验证的动作（source_type=reuse，跳过 R2V+VLM）
  python scripts/ingest.py --video <已验证模板.mp4> --source-file <原始素材.mp4> \
      --action-type walk --sub-action slow_walk --camera closeup --body-part legs \
      --source-type reuse --source-url "源自验证产物" --license derived \
      --id walk_slow_legs_001 \
      --verified-score 88 --verified-checks char_locked=true,motion_natural=true,spatial_stable=true

流程：
  1. 调 preprocess：ffmpeg 裁 3-5s / 24fps / 1344x768（保持比例 pad 黑边）/ 去遮挡
  2. 调 ComfyUI R2V：ref_images=[assets/test_character.png]，ref_videos=[模板转帧]，
     原语模板组装的黄金评级 prompt（walk_toward 等 11 原语，机位措辞决定动作成败）
  3. 调 VLM 审查三项（char_locked / motion_natural / spatial_stable）+ 总分
  4. 自动评级：score>=80 A；70-79 B；<70 C（打印「弃用」并退出，不入库不写 meta）
  5. 写 meta.yaml + 登记 index.yaml + 落盘 template.mp4 / source.mp4
  6. 打印入库结果（id + grade + score + 三项判断）

退出码：0=入库成功；1=弃用（score<70）；2=错误。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml  # noqa: E402

from scripts import rating, schemas  # noqa: E402
from scripts.config import get_vlm_api_key, load_config  # noqa: E402
from scripts.preprocess import preprocess_video, probe_video  # noqa: E402
from scripts.r2v import ACTION_TYPE_TO_PRIMITIVE, PRIMITIVE_TEMPLATES, run_r2v  # noqa: E402
from scripts.vlm_review import review_motion  # noqa: E402


# ---- 纯函数（便于 pytest）----

def parse_verified_checks(s: str) -> dict[str, bool]:
    """解析 ``--verified-checks "char_locked=true,motion_natural=true,..."``。"""
    checks: dict[str, bool] = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        key, _, val = part.partition("=")
        checks[key.strip()] = val.strip().lower() in ("true", "1", "yes", "on")
    missing = [k for k in schemas.R2V_CHECK_KEYS if k not in checks]
    if missing:
        raise ValueError(f"--verified-checks 缺少三项判断: {missing}")
    return checks


def slug(s: str) -> str:
    """把子动作描述转成 id 安全片段（小写、非字母数字→下划线）。"""
    import re
    out = re.sub(r"[^a-zA-Z0-9]+", "_", s.strip().lower()).strip("_")
    return out or "default"


def generate_id(action_type: str, sub_action: str, body_part: str, existing_ids: set[str]) -> str:
    """按 ``{action_type}_{sub_action}_{body_part}_{NNN}`` 生成唯一 id。"""
    base = f"{slug(action_type)}_{slug(sub_action)}_{slug(body_part)}"
    n = 1
    while f"{base}_{n:03d}" in existing_ids:
        n += 1
    return f"{base}_{n:03d}"


def build_meta(
    id: str,
    action_type: str,
    sub_action: str,
    camera: str,
    body_part: str,
    clarity_grade: str,
    duration_sec: float,
    resolution: str,
    fps: int,
    source_type: str,
    source_url: str,
    license: str,
    style_pollution: bool,
    r2v_score: int,
    r2v_checks: dict,
    r2v_verified: bool = True,
) -> dict:
    """组装一条 meta.yaml 数据（纯函数）。"""
    return {
        "id": id,
        "action_type": action_type,
        "sub_action": sub_action,
        "camera": camera,
        "body_part": body_part,
        "clarity_grade": clarity_grade,
        "duration_sec": round(float(duration_sec), 2),
        "resolution": resolution,
        "fps": int(fps),
        "source_type": source_type,
        "source_url": source_url,
        "license": license,
        "style_pollution": bool(style_pollution),
        "r2v_verified": bool(r2v_verified),
        "r2v_score": int(r2v_score),
        "r2v_checks": {k: bool(r2v_checks.get(k)) for k in schemas.R2V_CHECK_KEYS},
    }


def collect_existing_ids(index: dict) -> set[str]:
    ids: set[str] = set()
    for group in (index.get("entries") or {}).values():
        for e in (group or []):
            if isinstance(e, dict) and e.get("id"):
                ids.add(e["id"])
    return ids


def _print_reject(score: int, checks: dict) -> None:
    print("=" * 60)
    print(f"[弃用] R2V 评分 {score} < 70，动作迁移不合格，不入库不写 meta。")
    print(f"  char_locked  = {bool(checks.get('char_locked'))}")
    print(f"  motion_natural = {bool(checks.get('motion_natural'))}")
    print(f"  spatial_stable = {bool(checks.get('spatial_stable'))}")
    print("  建议：换更清晰的动作参考（肢体特写、无遮挡、背景干净）重新验证。")
    print("=" * 60)


# ---- 主流程 ----

def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="动作模板入库（预处理 → R2V → VLM → 评级 → 落盘）")
    ap.add_argument("--video", required=True, help="候选视频（完整模式=原始素材；reuse 模式=已验证模板）")
    ap.add_argument("--action-type", required=True)
    ap.add_argument("--sub-action", default="default")
    ap.add_argument("--camera", required=True, choices=sorted(schemas.ALLOWED_CAMERA))
    ap.add_argument("--body-part", required=True, choices=sorted(schemas.ALLOWED_BODY_PART))
    ap.add_argument("--source-type", required=True, choices=sorted(schemas.ALLOWED_SOURCE_TYPE))
    ap.add_argument("--source-url", required=True)
    ap.add_argument("--license", required=True, choices=sorted(schemas.ALLOWED_LICENSE))
    ap.add_argument("--style-pollution", action="store_true", help="是否带画风污染（复用现有视频必标）")
    ap.add_argument("--id", default=None, help="动作唯一 id；缺省自动生成")
    ap.add_argument("--duration", type=float, default=None, help="裁剪时长（秒），缺省用 config")
    ap.add_argument("--start", type=float, default=None, help="裁剪起点（秒），缺省居中/0")
    ap.add_argument("--crop", default=None, help="去遮挡裁剪 W:H:X:Y")
    ap.add_argument("--seed", type=int, default=None, help="R2V 随机种子")
    ap.add_argument("--primitive", default=None,
                    help="原语模板 id（评级 prompt 用它组装），缺省按 action-type 映射")
    ap.add_argument("--action-desc", default=None,
                    help="[已弃用] 旧版自由动作描述；现由原语模板统一组装 prompt，此参数忽略")
    ap.add_argument("--source-file", default=None, help="原始素材（落盘为 source.mp4，reuse 模式可选）")
    ap.add_argument("--verified-score", type=int, default=None, help="复用已跑 R2V 的评分（reuse 模式）")
    ap.add_argument("--verified-checks", default=None,
                    help="复用已跑 R2V 的三项判断 char_locked=true,motion_natural=true,spatial_stable=true")
    args = ap.parse_args(argv)

    cfg = load_config()
    comfy_url = (cfg.get("comfyui") or {}).get("url", "http://127.0.0.1:8188")
    work_dir = PROJECT_ROOT / (cfg.get("output") or {}).get("work_dir", "work")
    test_character = PROJECT_ROOT / (cfg.get("assets") or {}).get("test_character", "assets/test_character.png")
    r2v_cfg = cfg.get("r2v") or {}
    pp_cfg = cfg.get("preprocess") or {}

    duration = args.duration if args.duration is not None else pp_cfg.get("duration_sec", 4.0)
    fps = int(pp_cfg.get("fps", 24))
    width = int(pp_cfg.get("width", 1344))
    height = int(pp_cfg.get("height", 768))
    start = args.start if args.start is not None else pp_cfg.get("trim_start")

    video = Path(args.video)
    source_file = Path(args.source_file) if args.source_file else None
    if not video.exists():
        print(f"[错误] 候选视频不存在: {video}", file=sys.stderr)
        return 2

    # 1) 确定 id 与条目目录
    index_path = PROJECT_ROOT / "index.yaml"
    index = rating.load_index(index_path)
    existing_ids = collect_existing_ids(index)
    action_id = args.id or generate_id(args.action_type, args.sub_action, args.body_part, existing_ids)
    if action_id in existing_ids:
        print(f"[错误] id 已存在: {action_id}", file=sys.stderr)
        return 2
    entry_dir = PROJECT_ROOT / args.action_type / action_id
    rel_path = f"{args.action_type}/{action_id}"

    reuse_mode = args.verified_score is not None

    # 2) 预处理 / 复用模板
    if reuse_mode:
        # reuse：--video 已是已验证模板，直接落盘；--source-file 可选为原始素材
        template_src = video
        info = probe_video(template_src)
    else:
        # 完整模式：ffmpeg 预处理原始素材 → 模板
        candidate_work = work_dir / action_id
        template_src = candidate_work / "template.mp4"
        info = preprocess_video(
            video, template_src, duration=duration, fps=fps, width=width, height=height,
            start=start, crop=args.crop,
        )
        print(f"[preprocess] {video.name} -> {template_src} {info}", flush=True)

    # 3) R2V 验证 + VLM 审查（reuse 模式跳过）
    if reuse_mode:
        score = args.verified_score
        checks = parse_verified_checks(args.verified_checks)
        r2v_result_path = None
    else:
        if not test_character.exists():
            print(f"[错误] 测试角色图缺失: {test_character}", file=sys.stderr)
            return 2
        candidate_work = work_dir / action_id
        r2v_result_path = candidate_work / "r2v_result.mp4"
        if args.action_desc:
            print("[提示] --action-desc 已弃用（现由原语模板组装 prompt），忽略该参数。", file=sys.stderr)
        primitive_id = args.primitive or ACTION_TYPE_TO_PRIMITIVE.get(args.action_type, "walk_toward")
        if primitive_id not in PRIMITIVE_TEMPLATES:
            print(f"[错误] 未知原语 {primitive_id!r}，可选: {', '.join(sorted(PRIMITIVE_TEMPLATES))}",
                  file=sys.stderr)
            return 2
        print(f"[r2v] 调 ComfyUI R2V（ref_images=测试角色图，ref_videos=模板转帧，原语={primitive_id}，"
              f"黄金评级场景）...", flush=True)
        run_r2v(
            char_path=test_character,
            motion_video=template_src,
            out_path=r2v_result_path,
            comfy_url=comfy_url,
            primitive_id=primitive_id,
            seed=args.seed,
            steps=int(r2v_cfg.get("steps", 25)),
            length=int(r2v_cfg.get("length", 124)),
            width=int(r2v_cfg.get("width", 1344)),
            height=int(r2v_cfg.get("height", 768)),
        )
        vlm = cfg.get("vlm") or {}
        print("[vlm] 三项审查（char_locked / motion_natural / spatial_stable）...", flush=True)
        review = review_motion(
            r2v_result_path, test_character,
            vlm.get("base_url", "https://opencode.ai/zen/go/v1"),
            get_vlm_api_key(cfg),
            vlm.get("model", "qwen3.8-max"),
        )
        score = int(review.get("score", 0) or 0)
        checks = {
            "char_locked": bool(review.get("character_locked")),
            "motion_natural": bool(review.get("motion_natural")),
            "spatial_stable": bool(review.get("spatial_stable")),
        }
        # 审查明细落盘 work/（gitignore），供溯源
        (candidate_work / "r2v_review.json").write_text(
            yaml.safe_dump(review, allow_unicode=True), encoding="utf-8")

    # 4) 自动评级
    grade, accept = rating.auto_grade(score, checks)
    if not accept:
        _print_reject(score, checks)
        return 1

    # 5) 写 meta + 落盘 template/source + 登记 index
    meta = build_meta(
        id=action_id,
        action_type=args.action_type,
        sub_action=args.sub_action,
        camera=args.camera,
        body_part=args.body_part,
        clarity_grade=grade,
        duration_sec=info.get("duration_sec", duration),
        resolution=info.get("resolution", f"{width}x{height}"),
        fps=int(info.get("fps", fps)),
        source_type=args.source_type,
        source_url=args.source_url,
        license=args.license,
        style_pollution=args.style_pollution,
        r2v_score=score,
        r2v_checks=checks,
    )
    errors = schemas.validate_meta(meta)
    if errors:
        for e in errors:
            print(f"[错误] meta 校验失败: {e}", file=sys.stderr)
        return 2

    entry_dir.mkdir(parents=True, exist_ok=True)
    template_dst = entry_dir / "template.mp4"
    shutil.copy2(template_src, template_dst)
    if source_file and source_file.exists():
        shutil.copy2(source_file, entry_dir / "source.mp4")
    elif not reuse_mode:
        shutil.copy2(video, entry_dir / "source.mp4")
    (entry_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")

    index = rating.register_entry(index, meta, rel_path)
    rating.save_index(index, index_path)

    # 6) 打印结果
    print("=" * 60)
    print(f"[入库] id={action_id}  grade={grade}  score={score}")
    print(f"  char_locked    = {meta['r2v_checks']['char_locked']}")
    print(f"  motion_natural = {meta['r2v_checks']['motion_natural']}")
    print(f"  spatial_stable = {meta['r2v_checks']['spatial_stable']}")
    print(f"  目录           = {rel_path}/")
    print(f"  模板           = {template_dst}")
    if r2v_result_path and r2v_result_path.exists():
        print(f"  R2V 结果       = {r2v_result_path}")
    print("=" * 60)
    return 0


def main(argv=None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 入库失败: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
