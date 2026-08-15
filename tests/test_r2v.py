"""R2V 工作流 / 评级 prompt / 预处理命令 纯函数单测（守护踩过的坑）。"""
from pathlib import Path

from scripts.preprocess import build_preprocess_cmd
from scripts.r2v import build_rating_prompt, build_workflow, default_action_desc


def test_rating_prompt_has_picture_and_video():
    p = build_rating_prompt()
    assert "<Picture 1>" in p
    assert "<Video 1>" in p


def test_rating_prompt_forbids_standing_still():
    # 回归：曾写成 "stands centered" / "centered in frame" 导致动作丢失（score 45/55）
    p = build_rating_prompt("walk_toward").lower()
    assert "stands centered" not in p
    assert "centered in frame" not in p
    assert "must not stand still" in p
    assert "tracking backward" in p  # 相机跟随运动，避免静态构图
    assert "walk" in p


def test_rating_prompt_uses_verified_scene_and_camera():
    # 回归1：防止改回中性灰贫瘠场景（贫瘠场景触发静态肖像模式，动作迁移退化）
    p = build_rating_prompt("walk_toward")
    low = p.lower()
    assert "neutral grey" not in low
    assert "seamless background" not in low
    assert "rainy night" in low
    assert "convenience store" in low  # 验证过的黄金场景（雨夜便利店，85 分可复现）
    # 回归2：机位措辞必须「走向并越过镜头 + 镜头后拉跟拍」，禁止诱导推镜的词
    # （one-point perspective / receding / vanishing point 曾把走路压没，实测 42 分）
    assert "toward and past the camera" in low
    assert "tracking backward" in low
    for bad in ("one-point perspective", "receding", "vanishing point"):
        assert bad not in low


def test_build_rating_prompt_unknown_primitive_raises():
    import pytest
    with pytest.raises(ValueError):
        build_rating_prompt("nonexistent_primitive")


def test_walk_toward_matches_golden_template():
    # walk_toward 必须与黄金模板（assets/r2v_prompt_v2.txt，85 分）逐字等价
    golden = Path(__file__).resolve().parent.parent / "assets" / "r2v_prompt_v2.txt"
    g = golden.read_text(encoding="utf-8")
    p = build_rating_prompt("walk_toward")
    # <Picture 1> 身份段、integrated、soundscape 三段逐字一致
    for seg in (
        "<Picture 1> is the character identity reference. The character in this shot is Achi",
        "Achi walks continuously toward and past the camera with the same natural walking gait "
        "cycle shown in <Video 1>, his legs stepping in a steady rhythm, the camera slowly "
        "tracking backward to follow him",
        "overall_soundscape: gentle steady rain falling, distant soft city ambience",
    ):
        assert seg in g, f"黄金模板未含该段: {seg[:50]}"
        assert seg in p, f"组装 prompt 未含该段: {seg[:50]}"


def test_default_action_desc_known_type():
    assert default_action_desc("walk") is not None
    assert "gait" in default_action_desc("walk")
    assert default_action_desc("unknown_type") is None


def test_workflow_uses_r2v_node_not_i2v():
    wf = build_workflow("p", "char.png", Path("frames"), 1, "pref")
    classes = {v["class_type"] for v in wf.values()}
    assert "MiniMaxH3ReferenceToVideo" in classes
    assert "MiniMaxH3ImageToVideo" not in classes


def test_workflow_flat_dotted_keys():
    # 坑2：autogrow 输入是扁平点号键 ref_images.ref_image_0 / ref_videos.ref_video_0
    wf = build_workflow("p", "char.png", Path("frames"), 1, "pref")
    n9 = wf["9"]["inputs"]
    assert n9["ref_images.ref_image_0"] == ["1", 0]
    assert n9["ref_videos.ref_video_0"] == ["2", 0]


def test_workflow_kjnodes_required_params():
    # 坑1：LoadImagesFromFolderKJ 标 optional 实为必填的 image_load_cap / start_index
    wf = build_workflow("p", "char.png", Path("frames"), 1, "pref")
    n2 = wf["2"]["inputs"]
    assert n2["image_load_cap"] == 0
    assert n2["start_index"] == 0


def test_preprocess_cmd_shape():
    cmd = build_preprocess_cmd(Path("a.mp4"), Path("b.mp4"), duration=4.0, fps=24,
                               width=1344, height=768)
    assert cmd[0] == "ffmpeg"
    assert "-vf" in cmd
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1344:768:force_original_aspect_ratio=decrease" in vf
    assert "pad=1344:768" in vf
    assert "fps=24" in vf


def test_preprocess_cmd_crop_deocclusion():
    cmd = build_preprocess_cmd(Path("a.mp4"), Path("b.mp4"), crop="1600:900:0:100")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("crop=1600:900:0:100,")
