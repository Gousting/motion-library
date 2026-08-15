"""VLM 三项审查：char_locked / motion_natural / spatial_stable + 总分。

评级标准化：只审查动作迁移质量，不评画面美感——因为评级的是「动作模板的可用性」，
不是出片好看程度。场景固定为标准丰富场景（雨夜便利店门口）。
"""
from __future__ import annotations

import base64
import io
import json
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image

# VLM 审查的三项判断（与 schemas.R2V_CHECK_KEYS 一致）
REVIEW_PROMPT = (
    "你是一名 AI 视频生成质量审查员。我会先给你 1 张角色定妆参考图（锁定角色身份用），"
    "随后给你从一段 AI 生成视频抽出的若干帧（按时间顺序）。这段视频是在「雨夜便利店门口」的"
    "标准丰富场景下生成的，用于评级动作模板的可用性，请只审查动作迁移质量、不评画面美感。严格审查：\n"
    "1) character_locked：画面中的角色是否与参考图保持同一人（东方面孔、黑短发、细框眼镜、深灰大衣），"
    "还是变成了参考动作视频里的人；\n"
    "2) motion_natural：是否复刻了参考动作（自然流畅的肢体运动），还是僵着不动只推镜；\n"
    "3) spatial_stable：运镜是否舒服，背景（雨夜便利店门口）是否稳定不漂移、不扭曲。\n"
    "只返回一个 JSON 对象（不要 markdown 代码块、不要额外文字），字段严格如下：\n"
    '{"score": <0-100 整数>, '
    '"character_locked": <true/false>, "character_comment": "<角色锁定说明>", '
    '"motion_natural": <true/false>, "motion_comment": "<动作自然度说明>", '
    '"spatial_stable": <true/false>, "spatial_comment": "<空间/运镜稳定性说明>", '
    '"opinion": "<一句话结论>"}'
)


def frame_to_b64(img: Image.Image, target_kb: int = 80) -> str:
    """把帧压成 JPEG base64（目标 ~80KB），控制 token 与超时。"""
    img = img.convert("RGB")
    img.thumbnail((768, 768))
    quality = 78
    for _ in range(6):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        if len(buf.getvalue()) <= target_kb * 1024:
            break
        quality -= 12
    return base64.b64encode(buf.getvalue()).decode()


def extract_frames(video: Path, n: int = 4) -> list[Image.Image]:
    """从视频均匀抽 n 帧（按时间顺序）。"""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        dur = float(probe.stdout.strip() or 0.0) or 5.0
    except ValueError:
        dur = 5.0
    ts = [dur * (i + 0.5) / n for i in range(n)]
    frames = []
    for t in ts:
        out = video.with_suffix(".tmp.jpg")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
             "-frames:v", "1", "-q:v", "3", "-y", str(out)],
            capture_output=True, check=True,
        )
        frames.append(Image.open(out).convert("RGB"))
        out.unlink(missing_ok=True)
    return frames


def chat(messages: list, base_url: str, api_key: str, model: str, attempts: int = 4) -> str:
    """调 OpenAI 兼容 chat/completions，带重试。"""
    last = ""
    for i in range(attempts):
        try:
            r = requests.post(
                f"{base_url}/chat/completions",
                json={"model": model, "messages": messages},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=180,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            last = f"{r.status_code}: {r.text[:300]}"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:300]
        time.sleep(4 + i * 3)
    raise RuntimeError(f"VLM 调用失败: {last}")


def parse_json(raw: str) -> dict:
    """稳健解析 VLM 返回的 JSON（容忍 ```json 代码块 / 前后噪声）。"""
    cleaned = raw.strip().strip("`")
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            return json.loads(raw[start:end + 1])
        return {"parse_error": True, "raw": raw}


def review_motion(
    video: Path,
    ref_image: Path,
    base_url: str,
    api_key: str,
    model: str,
    n_frames: int = 4,
) -> dict:
    """审查 R2V 结果：返回 {score, character_locked, motion_natural, spatial_stable, ...}。

    把角色参考图放最前，随后是生成视频抽出的 n 帧（按时间顺序）。
    """
    frames = extract_frames(video, n_frames)
    ref_img = Image.open(ref_image)
    content = [{"type": "text", "text": REVIEW_PROMPT}]
    content.append({
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{frame_to_b64(ref_img)}"},
    })
    for fr in frames:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{frame_to_b64(fr)}"},
        })
    raw = chat([{"role": "user", "content": content}], base_url, api_key, model)
    review = parse_json(raw)
    review["raw"] = raw
    return review


def main(argv=None) -> int:
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from scripts.config import load_config, get_vlm_api_key

    ap = argparse.ArgumentParser(description="VLM 三项审查（char_locked/motion_natural/spatial_stable）")
    ap.add_argument("--video", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    cfg = load_config()
    vlm = cfg.get("vlm", {})
    review = review_motion(
        Path(args.video), Path(args.ref),
        vlm.get("base_url", "https://opencode.ai/zen/go/v1"),
        get_vlm_api_key(cfg),
        vlm.get("model", "qwen3.8-max"),
    )
    print(json.dumps(review, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
