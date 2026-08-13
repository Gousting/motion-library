"""ffmpeg 预处理：裁 3-5s / 24fps / 1344x768（保持比例 pad 黑边）/ 可选裁剪去遮挡。

「去遮挡」的实现方式：候选素材若画面边缘有遮挡物（如路牌、Logo），用 ``crop=W:H:X:Y``
先裁掉再缩放。无遮挡的干净素材（如黑底步态特写）不传 ``crop`` 即可。
遮挡是否可接受最终由入库前的 R2V 验证 + VLM 三项判断兜底，不凭肉眼定级。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# 默认参数（与 config.yaml 的 preprocess 段一致）
DEFAULT_DURATION = 4.0
DEFAULT_FPS = 24
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768


def build_preprocess_cmd(
    src: Path,
    dst: Path,
    duration: float = DEFAULT_DURATION,
    fps: int = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    start: float | None = None,
    crop: str | None = None,
) -> list[str]:
    """构造 ffmpeg 命令（纯函数，便于单测）。

    - ``start``：裁剪起点（秒），None 表示从 0 开始（或由调用方先居中算好）。
    - ``crop``：``"W:H:X:Y"``，先裁掉遮挡物再缩放。
    - 缩放保持比例，不足处 pad 黑边到 ``width x height``。
    """
    filters: list[str] = []
    if crop:
        filters.append(f"crop={crop}")
    filters.append(f"fps={fps}")
    filters.append(
        f"scale={width}:{height}:force_original_aspect_ratio=decrease"
    )
    filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    vf = ",".join(filters)

    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += [
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        str(dst),
    ]
    return cmd


def run_cmd(cmd: list[str]) -> None:
    """执行命令，失败抛异常（携带 stderr 前 800 字）。"""
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {' '.join(cmd[:4])}... {proc.stderr[:800]}")


def probe_video(path: Path) -> dict:
    """ffprobe 读回 duration / width / height / fps（JSON 输出，字段定位稳健）。"""
    import json

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        data = {}
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    try:
        width = int(stream.get("width", 0) or 0)
    except (TypeError, ValueError):
        width = 0
    try:
        height = int(stream.get("height", 0) or 0)
    except (TypeError, ValueError):
        height = 0
    num, _, den = str(stream.get("avg_frame_rate", "0/1")).partition("/")
    try:
        fps = round(float(num) / float(den), 2) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    try:
        duration = round(float(fmt.get("duration", 0) or 0), 2)
    except (TypeError, ValueError):
        duration = 0.0
    return {"duration_sec": duration, "width": width, "height": height, "fps": fps}


def preprocess_video(
    src: Path,
    dst: Path,
    duration: float = DEFAULT_DURATION,
    fps: int = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    start: float | None = None,
    crop: str | None = None,
) -> dict:
    """跑 ffmpeg 预处理并返回结果摘要（实际时长/分辨率/fps）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(build_preprocess_cmd(src, dst, duration, fps, width, height, start, crop))
    info = probe_video(dst)
    info["resolution"] = f"{info['width']}x{info['height']}"
    return info


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="ffmpeg 预处理：裁 3-5s / 24fps / 1344x768 / 去遮挡")
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS)
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--crop", default=None, help="W:H:X:Y，先裁掉遮挡物")
    args = ap.parse_args(argv)

    info = preprocess_video(
        Path(args.src), Path(args.dst), args.duration, args.fps,
        args.width, args.height, args.start, args.crop,
    )
    print(f"[preprocess] {args.src} -> {args.dst} {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
