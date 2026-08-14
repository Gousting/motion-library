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
    p = build_rating_prompt(default_action_desc("walk"))
    assert "stands centered" not in p.lower()
    assert "centered in frame" not in p.lower()
    assert "must not stand still" in p.lower()
    assert "tracking backward" in p.lower()  # 相机跟随运动，避免静态构图
    assert "walk" in p.lower()


def test_rating_prompt_embeds_action_desc():
    p = build_rating_prompt("walks continuously with a natural gait cycle")
    assert "walks continuously" in p


def test_rating_prompt_uses_rich_scene_not_neutral_grey():
    # 回归：防止有人改回中性灰贫瘠场景（贫瘠场景触发静态肖像模式，动作迁移退化）
    p = build_rating_prompt(default_action_desc("walk"))
    assert "neutral grey" not in p.lower()
    assert "seamless background" not in p.lower()
    assert "rainy night" in p.lower()
    assert "one-point perspective" in p.lower()
    assert "sidewalk" in p.lower()


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
