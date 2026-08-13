# motion-library — R2V 动作模板资产库

动作库 = R2V 参考生视频的「动作模板」资产管理，与 image-gen 的风格 registry 对称：

- **风格锁画面质感**（image-gen 的 style registry）
- **动作锁运动形态**（本项目的 motion library）

两者都是素材资产 + 索引规范，不是复杂代码。

## 核心结论（R2V 验证，2026-08-13）

动作迁移质量取决于参考视频的动作清晰度：

| 参考视频 | R2V 评分 | 结果 |
| --- | --- | --- |
| 全景背影走路 | 62 | 动作丢失（僵立只推镜），弃用 |
| 腿部步态特写（黑底） | 88 | 动作自然复刻，入库 |

同一模型同一 prompt，差距只在参考视频「动作信号是否清晰」。所以动作模板要沉淀成资产，
**入库前必须先跑 R2V 验证实测迁移质量，不凭肉眼感觉定级**。

## 目录结构

```
motion-library/
├── index.yaml                 # 总索引（动作列表 + 元数据摘要，检索入口）
├── README.md                  # 本文件（入库规范 + 验收标准 + 与 ai-video-pipeline 的关系）
├── config.yaml                # ComfyUI / R2V 模型 / VLM / 评级阈值配置（密钥占位符）
├── assets/
│   └── test_character.png     # 固定测试角色图（评级标准参照，阿迟东方面孔定妆图）
├── scripts/
│   ├── ingest.py              # 入库脚本（预处理 → R2V 验证 → VLM 三项 → 评级 → 写 meta + index）
│   ├── preprocess.py          # ffmpeg 预处理（裁 3-5s / 24fps / 1344x768 / 去遮挡）
│   ├── r2v.py                 # ComfyUI R2V 调用（MiniMaxH3ReferenceToVideo，只调 HTTP API）
│   ├── vlm_review.py          # VLM 三项审查（char_locked / motion_natural / spatial_stable）
│   ├── rating.py              # 评级映射（score→grade 纯函数）+ index 登记逻辑
│   ├── schemas.py             # meta.yaml 字段规范 + 完整性校验
│   └── config.py              # config.yaml + .env 加载
├── walk/
│   └── walk_slow_legs_001/    # 种子条目（腿部步态特写，88 分已验证）
│       ├── template.mp4       # 动作模板（预处理后，入库本体）
│       ├── source.mp4         # 原始素材（可商用凭证；reuse 类型可为空）
│       └── meta.yaml          # 完整元数据
└── tests/                     # pytest 单测
```

`hand/` `flip/` 等其它动作目录随用随建。

## 元数据规范（meta.yaml）

每条动作的完整元数据放在条目目录下的 `meta.yaml`（yaml 格式，字段对齐方案书）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | ✓ | 动作唯一标识，如 `walk_slow_legs_001`（ai-video-pipeline 出片时传此 ID） |
| `action_type` | string | ✓ | 主分类：`walk` / `turn` / `sit` / `hand` / `flip` / ... |
| `sub_action` | string | ✓ | 子动作描述，如 `slow_walk` |
| `camera` | string | ✓ | 景别：`full` / `medium` / `closeup` |
| `body_part` | string | ✓ | 部位：`full_body` / `half_body` / `legs` / `hands` / `face` |
| `clarity_grade` | string | ✓ | 清晰度评级 `A` / `B` / `C`（自动评级写入，见下） |
| `duration_sec` | float | ✓ | 模板时长（秒） |
| `resolution` | string | ✓ | 分辨率，如 `"1344x768"` |
| `fps` | int | ✓ | 帧率（24） |
| `source_type` | string | ✓ | 来源类型：`stock` / `selfshot` / `reuse` |
| `source_url` | string | ✓ | 可商用凭证 URL（reuse 为「源自验证产物」） |
| `license` | string | ✓ | 许可：`pexels-free` / `self-shot` / `derived` |
| `style_pollution` | bool | ✓ | 是否带画风污染（复用现有视频必须标） |
| `r2v_verified` | bool | ✓ | 是否已通过 R2V 验证 |
| `r2v_score` | int | ✓ | R2V 实测迁移评分（0-100） |
| `r2v_checks` | dict | ✓ | VLM 三项判断：`char_locked` / `motion_natural` / `spatial_stable`（均 bool） |

示例：

```yaml
id: walk_slow_legs_001
action_type: walk
sub_action: slow_walk
camera: closeup
body_part: legs
clarity_grade: A
duration_sec: 4.0
resolution: "1344x768"
fps: 24
source_type: stock
source_url: "https://..."
license: pexels-free
style_pollution: false
r2v_verified: true
r2v_score: 88
r2v_checks:
  char_locked: true
  motion_natural: true
  spatial_stable: true
```

`index.yaml` 是检索入口：按 `action_type` 分组的条目摘要（`id` + `camera` + `clarity_grade` + `r2v_score` + 路径），
完整字段只看各条目的 `meta.yaml`。

## 清晰度评级 A / B / C

| 等级 | 画面特征 | R2V 评分 | 处理 |
| --- | --- | --- | --- |
| A | 肢体特写、无遮挡、背景干净（如黑底步态特写） | ≥ 80 | 入库，正常使用 |
| B | 中景或轻微遮挡 | 70-79 | 入库，标注风险 |
| C | 全景 / 背影 | < 70 | **弃用，不入库不写 meta** |

评级标准化（保证不同动作模板之间可比）：评级时场景固定为**中性场景**（简洁室内、中性灰背景），
用**固定测试角色图**（`assets/test_character.png`），VLM 只审查三项动作迁移质量
（`char_locked` / `motion_natural` / `spatial_stable`），**不评画面美感**——评级的是「动作模板的可用性」，
不是出片好看程度。场景固定中性，避免复杂场景（如雨夜便利店）的生成质量干扰动作评分。

自动评级 = R2V 评分 + VLM 三项判断 → A / B / C：

- `score >= 80` → A 级；若三项判断任一为 false（动作迁移不干净）→ 降级 B 标注风险
- `70 <= score < 80` → B 级（标注风险）
- `score < 70` → C 级弃用

## 入库验收流程

```
候选视频 → 预处理(裁 3-5s/24fps/1344x768/去遮挡) → R2V 验证(中性场景 + 固定角色图)
        → VLM 三项审查(char_locked/motion_natural/spatial_stable + 总分)
        → 自动评级(A/B/C) → [C 弃用退出] → [A/B 写 meta.yaml + 登记 index.yaml + 落盘]
```

命令：

```bash
python scripts/ingest.py --video <候选视频> --action-type walk --camera closeup --body-part legs \
    --source-type stock --source-url <url> --license pexels-free [--style-pollution]
```

- 评级脚本调 ComfyUI HTTP API（`MiniMaxH3ReferenceToVideo` 节点 + ref2va 权重），**不直接读写权重文件**
  （权重物理位置对脚本透明，跟 image-gen 调 Z-Image 一个道理）。
- `score < 70` 的动作弃用不入库（打印「弃用」并退出）。
- 已在别处跑过 R2V 验证的动作可用 `--verified-score` / `--verified-checks` 复用验证结果重新入库。

## 来源策略

- **Pexels / Pixabay 主来源**：可商用，`license=pexels-free`，`source_url` 记录凭证。
- **真人自拍关键动作**：难找的特定动作（如手部翻转）自拍补充，`license=self-shot`。
- **现有视频复用**：复用已有产物必须标 `style_pollution`（是否带画风污染）。

## 与 ai-video-pipeline 的关系

ai-video-pipeline 出片时「风格名 + 动作 ID」一起传：

- 风格名 → image-gen 的 style registry（锁画面质感）
- 动作 ID → 本项目的 motion library（锁运动形态）

## 配置与密钥

`config.yaml` 入库，但 **api_key 一律用占位符**；真实密钥放项目根目录 `.env`（已 `.gitignore` 排除，永不提交）：

```bash
# .env（不入库）
MOTIONLIB_VLM_API_KEY=sk-xxxx   # VLM 审查模型密钥
```

加载优先级：`config.yaml` → `.env` → 进程环境变量（最高）。

## 环境要求

- Python 3.11+，依赖 `requests`、`PyYAML`、`Pillow`（`pip install requests pyyaml pillow`）
- 宿主机 ComfyUI 运行于 `127.0.0.1:8188`（`config.yaml` 可改），已装 `MiniMaxH3ReferenceToVideo` 节点与 ref2va 权重
- ffmpeg / ffprobe 在 PATH
