"""ComfyUI R2V 调用：MiniMaxH3ReferenceToVideo（ref2va）。

只调 ComfyUI HTTP API（``/upload/image``、``/prompt``、``/history``、``/view``），
**不直接读写权重文件**——权重物理位置对脚本透明，跟 image-gen 调 Z-Image 一个道理。

踩过的坑（已沉淀进工作流，勿删）：
- 节点用 ``MiniMaxH3ReferenceToVideo``（R2V），不是 ``MiniMaxH3ImageToVideo``（I2V）。
- ``LoadImagesFromFolderKJ`` 有个标 optional 实为必填的参数：``image_load_cap=0`` / ``start_index=0``。
- autogrow 的 ref_images/ref_videos 输入是扁平点号键：``ref_images.ref_image_0`` / ``ref_videos.ref_video_0``。
"""
from __future__ import annotations

import json
import random
import subprocess
import time
from pathlib import Path

import requests

# 模型文件（UNETLoader 等按名加载，与 config.yaml 的 r2v 段一致）
UNET_NAME = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
CLIP_NAME = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"

# 采样默认值（与 config.yaml 一致）
DEFAULT_STEPS = 25
DEFAULT_LENGTH = 124        # ≈5s@24fps
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768
DEFAULT_FPS = 24

POLL_INTERVAL = 10
POLL_TIMEOUT = 7200         # 2 小时（ref2va 首次加载权重 + 采样较慢）


def default_action_desc(action_type: str) -> str | None:
    """按主分类给一个动作描述（动词短语），用于评级场景 R2V prompt 的 motion 描述。

    R2V 动作迁移对 prompt 里的动作描述敏感（实测：写成 ``stands centered`` 会僵立只推镜）。
    已知主分类给显式动作，未知分类返回 None（用 build_rating_prompt 的通用默认）。
    """
    mapping = {
        "walk": "walks continuously toward and past the camera with a natural gait cycle, legs "
                "stepping forward in a steady rhythm, feet lifting and planting, body weight "
                "shifting from foot to foot",
        "run": "runs continuously with a natural stride, arms swinging, legs driving forward steadily",
        "turn": "turns around smoothly and continuously, shifting body weight from foot to foot",
        "sit": "sits down and stands back up naturally and continuously",
        "hand": "moves the hands naturally and continuously in the gesture shown in <Video 1>",
        "flip": "performs the flipping motion naturally and continuously",
        "jump": "jumps naturally and repeatedly, bending the knees and pushing off the ground",
        "gesture": "gestures naturally and continuously with the arms and hands",
        "dance": "dances naturally and continuously, moving the whole body in a steady rhythm",
    }
    return mapping.get(action_type)


def build_rating_prompt(action_desc: str | None = None) -> str:
    """构造「标准评级场景」（雨夜便利店门口）的 R2V ref 格式 prompt。

    评级标准化：场景固定为雨夜便利店门口——这是实测验证过的黄金场景（85 分可复现、
    跨场景复用成立），丰富到让模型有上下文「合理化」动作，又固定保证不同动作模板之间可比
    （此前中性灰太贫瘠，易触发静态肖像模式，动作迁移退化）。

    关键踩坑（两轮实验验证）：决定动作成败的是机位措辞——必须是
    「walks toward and past the camera + camera slowly tracking backward」；
    **禁止** one-point perspective / receding into the distance / vanishing point 之类
    诱导推镜的词（曾把走路压没，实测 42 分）。动作描述必须是显式的「持续运动」动词短语。
    ``<Picture 1>`` 锁角色身份，``<Video 1>`` 锁动作，显式分配职责。
    """
    if not action_desc:
        action_desc = "performs the motion from <Video 1> continuously and fluidly"
    return (
        "<Picture 1> is the character identity reference. The character in this shot is Achi, "
        "a lean young man in his late twenties with East Asian features, slightly messy black "
        "short hair with a few raindrops, thin-rimmed glasses, wearing a half-wet dark grey wool "
        "overcoat over a dark shirt, and a dark canvas messenger bag across his chest. His "
        "identity, face, hairstyle, glasses, and outfit must stay exactly consistent with "
        "<Picture 1>. He must NOT become the person appearing in <Video 1>.\n\n"
        "<Video 1> is the motion reference. The character performs the exact same motion shown in "
        f"<Video 1>: {action_desc}, continuously and naturally without stopping. The character "
        "must NOT stand still.\n\n"
        "integrated_multimodal_description: A rainy night in front of a glowing convenience store, "
        "Makoto Shinkai anime film style. Achi walks continuously toward and past the camera with "
        "the same natural walking gait cycle shown in <Video 1>, his legs stepping in a steady "
        "rhythm, the camera slowly tracking backward to follow him. Text-free glowing neon sign "
        "boards, puddles on the wet ground reflecting the warm neon lights, a layered gradient "
        "night sky, gentle raindrops falling. Beautiful detailed lighting, neon reflections on wet "
        "ground, layered gradient sky, bokeh, cinematic composition, Makoto Shinkai anime film "
        "style.\n\n"
        "overall_soundscape: gentle steady rain falling, distant soft city ambience, soft footsteps "
        "splashing lightly on the wet pavement, occasional faint distant traffic rumble.\n\n"
        "non_diegetic_music: N/A"
    )


def extract_frames(video: Path, folder: Path, fps: int = DEFAULT_FPS) -> int:
    """把动作视频拆成 24fps PNG 帧序列（ref_videos 输入为 IMAGE 帧序列），返回帧数。"""
    folder.mkdir(parents=True, exist_ok=True)
    for p in folder.glob("*.png"):
        p.unlink()
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video),
         "-vf", f"fps={fps}", "-q:v", "1",
         str(folder / "frame_%04d.png")],
        check=True, capture_output=True,
    )
    n = len(list(folder.glob("*.png")))
    if n == 0:
        raise RuntimeError(f"拆帧失败：{video}")
    return n


def upload_image(path: Path, comfy_url: str) -> str:
    """上传角色参考图到 ComfyUI，返回文件名（供 LoadImage 按名引用）。"""
    with path.open("rb") as f:
        files = {"image": (path.name, f, "image/png")}
        data = {"overwrite": "true"}
        r = requests.post(f"{comfy_url}/upload/image", files=files, data=data, timeout=60)
    r.raise_for_status()
    j = r.json()
    name = j.get("name")
    if not name:
        raise RuntimeError(f"upload 未返回 name: {j}")
    return name


def build_workflow(
    prompt: str,
    char_name: str,
    frames_folder: Path,
    seed: int,
    prefix: str,
    steps: int = DEFAULT_STEPS,
    length: int = DEFAULT_LENGTH,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    ref_image_size: str = "match",
) -> dict:
    """构造 R2V 工作流（纯函数，便于单测；结构沿用已验证的采样链路）。"""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": char_name}},
        "2": {"class_type": "LoadImagesFromFolderKJ",
              "inputs": {"folder": str(frames_folder).replace("\\", "/"),
                         "width": -1, "height": -1, "keep_aspect_ratio": "stretch",
                         "image_load_cap": 0, "start_index": 0, "include_subfolders": False}},
        "3": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET_NAME, "weight_dtype": "default"}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP_NAME, "type": "minimax"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "7": {"class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch", "inputs": {"model": ["3", 0]}},
        "8": {"class_type": "EasyCache", "inputs": {"model": ["7", 0], "reuse_threshold": 0.2,
                                                      "start_percent": 0.15, "end_percent": 0.95,
                                                      "verbose": False}},
        "9": {"class_type": "MiniMaxH3ReferenceToVideo",
              "inputs": {"clip": ["4", 0], "vae": ["5", 0], "audio_vae": ["6", 0],
                         "prompt": prompt, "width": width, "height": height, "length": length,
                         "ref_image_size": ref_image_size,
                         "ref_images.ref_image_0": ["1", 0],
                         "ref_videos.ref_video_0": ["2", 0]}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["8", 0], "conditioning": ["9", 0]}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "12": {"class_type": "BasicScheduler", "inputs": {"model": ["8", 0], "scheduler": "simple",
                                                            "steps": steps, "denoise": 1.0}},
        "13": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["11", 0], "guider": ["10", 0],
                                                                  "sampler": ["13", 0], "sigmas": ["12", 0],
                                                                  "latent_image": ["9", 1]}},
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["5", 0]}},
        "16": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["14", 0], "vae": ["6", 0]}},
        "17": {"class_type": "CreateVideo", "inputs": {"images": ["15", 0], "audio": ["16", 0], "fps": 24}},
        "18": {"class_type": "SaveVideo", "inputs": {"video": ["17", 0], "filename_prefix": prefix,
                                                       "format": "auto", "codec": "auto"}},
    }


def queue_workflow(wf: dict, comfy_url: str) -> str:
    r = requests.post(f"{comfy_url}/prompt", json={"prompt": wf}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"prompt 排队失败 {r.status_code}: {r.text[:800]}")
    j = r.json()
    pid = j.get("prompt_id")
    if not pid:
        raise RuntimeError(f"未返回 prompt_id: {j}")
    return pid


def poll_history(pid: str, comfy_url: str, timeout: int = POLL_TIMEOUT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{comfy_url}/history/{pid}", timeout=30)
        r.raise_for_status()
        j = r.json()
        if pid in j:
            status = j[pid].get("status", {})
            if status.get("completed"):
                return j[pid]
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI 执行出错: {json.dumps(status, ensure_ascii=False)[:1500]}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"轮询超时 {timeout}s (prompt_id={pid})")


def find_video_output(entry: dict) -> tuple[str, str, str]:
    """从 history 条目里找视频输出，返回 (filename, subfolder, type)。"""
    for node_id, node in entry.get("outputs", {}).items():
        for kind in ("gifs", "videos", "images"):
            for item in node.get(kind, []):
                fn = item.get("filename", "")
                if fn.lower().endswith((".mp4", ".webm")):
                    return fn, item.get("subfolder", ""), item.get("type", "output")
    raise RuntimeError(f"history 未找到视频输出: {json.dumps(entry, ensure_ascii=False)[:800]}")


def download_video(filename: str, subfolder: str, vtype: str, out: Path, comfy_url: str) -> None:
    params = {"filename": filename, "subfolder": subfolder, "type": vtype}
    r = requests.get(f"{comfy_url}/view", params=params, timeout=600)
    r.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)


def run_r2v(
    char_path: Path,
    motion_video: Path,
    out_path: Path,
    comfy_url: str,
    action_desc: str | None = None,
    seed: int | None = None,
    steps: int = DEFAULT_STEPS,
    length: int = DEFAULT_LENGTH,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    prefix: str = "motionlib_r2v",
) -> dict:
    """跑一次完整 R2V 生成，返回结果摘要 dict（含 seed / prompt_id / 输出文件等）。

    流程：拆帧 → 上传角色图 → 构建工作流 → 排队 → 轮询 → 下载 .mp4。
    """
    seed = seed if seed is not None else random.randint(0, int(1e9))
    prompt = build_rating_prompt(action_desc)

    t0 = time.time()
    frames_folder = out_path.parent / "motion_frames"
    nframes = extract_frames(motion_video, frames_folder, DEFAULT_FPS)

    char_name = upload_image(char_path, comfy_url)
    wf = build_workflow(prompt, char_name, frames_folder, seed, prefix,
                        steps=steps, length=length, width=width, height=height)
    pid = queue_workflow(wf, comfy_url)
    entry = poll_history(pid, comfy_url)
    fn, sub, vtype = find_video_output(entry)
    download_video(fn, sub, vtype, out_path, comfy_url)
    dt = time.time() - t0

    return {
        "seed": seed,
        "steps": steps,
        "length": length,
        "width": width,
        "height": height,
        "prompt_id": pid,
        "comfy_filename": fn,
        "subfolder": sub,
        "type": vtype,
        "elapsed_sec": round(dt, 1),
        "motion_frames": nframes,
        "prompt": prompt,
        "result_path": str(out_path),
    }
