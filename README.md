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
│   ├── test_character.png     # 固定测试角色图（评级标准参照，阿迟东方面孔定妆图）
│   └── r2v_prompt_v2.txt      # 黄金评级 prompt（雨夜便利店，实测 85 分，原语模板对齐基准）
├── scripts/
│   ├── ingest.py              # 入库脚本（预处理 → R2V 验证 → VLM 三项 → 评级 → 写 meta + index）
│   ├── fetch_stock.py         # 素材自动获取（Pixabay video API，按原语下载候选，不做入库验证）
│   ├── preprocess.py          # ffmpeg 预处理（裁 3-5s / 24fps / 1344x768 / 去遮挡）
│   ├── r2v.py                 # ComfyUI R2V 调用（只调 HTTP API）+ PRIMITIVE_TEMPLATES 原语模板表
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

评级标准化（保证不同动作模板之间可比）：评级时 prompt 由**原语模板**（见下节）组装，场景固定为
**雨夜便利店黄金场景**（`assets/r2v_prompt_v2.txt`，实测 85 分可复现），用**固定测试角色图**
（`assets/test_character.png`），VLM 只审查三项动作迁移质量（`char_locked` / `motion_natural` /
`spatial_stable`），**不评画面美感**——评级的是「动作模板的可用性」，不是出片好看程度。

自动评级 = R2V 评分 + VLM 三项判断 → A / B / C：

- `score >= 80` → A 级；若三项判断任一为 false（动作迁移不干净）→ 降级 B 标注风险
- `70 <= score < 80` → B 级（标注风险）
- `score < 70` → C 级弃用

> **已知限制（更新，2026-08-14）**：评级场景已从「中性灰」升级为「标准丰富场景」（雨夜城市街道）。
> 此前中性场景评级对动作迁移偏保守：同一动作模板、同一测试角色图、同一种子（原 88 分验证所用），
> 仅把场景从「雨夜便利店」换成「简洁室内中性灰背景」后，动作迁移质量显著下降（5 次实测 45-55 分，
> `motion_natural=false`，角色僵立只推镜），而 `char_locked` / `spatial_stable` 仍为 true。
> 根因：中性灰场景 prompt 太贫瘠，模型没有上下文「合理化」动作，进入静态肖像模式。
> 第二期重新标定：换成「雨夜城市街道」标准丰富场景后，同种子同参数实测仍为 42 分、
> `motion_natural=false`（角色僵立只推镜），说明光改场景不足以恢复动作迁移，该问题尚未完全解决。
> 种子 `walk_slow_legs_001` 的 `r2v_score=88` 仍来自之前「雨夜便利店」场景验证（详见 report 第二期）。
>
> **已解决（三期，2026-08-15）**：根因定位——不是场景不够丰富，是机位措辞诱导推镜：
> 「one-point perspective / sidewalk receding into the distance」让模型做推镜、把走路压没（42 分）。
> 评级 prompt 已按黄金模板（`assets/r2v_prompt_v2.txt`，实测 85 分可复现、跨场景复用成立）修正为
> 「走向并越过镜头 + 镜头后拉跟拍」，并建立下方原语模板表，评级 prompt 禁止任何诱导推镜措辞。

## 动作原语（PRIMITIVE_TEMPLATES）

评级/生成 prompt 不再手写，由 `scripts/r2v.py` 的原语模板表组装：`build_rating_prompt(primitive_id)`
按黄金模板结构（`<Picture 1>` 身份锁 + `<Video 1>` 动作锁 + integrated 场景机位 + 声景两段）输出。

| primitive_id | 动作 | 机位 | 场景道具 |
| --- | --- | --- | --- |
| `walk_toward` | 走向并越过镜头，步态循环 | 镜头后拉跟拍 | 无 |
| `walk_away` | 背对镜头走远 | 几乎静止、极缓跟随 | 无 |
| `run_toward` | 跑向并越过镜头 | 镜头后拉跟拍 | 无 |
| `turn` | 原地转身 180° | 中景静止 | 无 |
| `sit` | 自然坐下 | 静止 | 长椅 |
| `stand` | 自然起身 | 静止 | 长椅 |
| `reach_grab` | 伸手拿取物体 | 静止/轻微缓慢推近 | 桌子+物件 |
| `open_door` | 开门并迈过 | 静止 | 门 |
| `wave` | 挥手 | 近景静止 | 无 |
| `nod` | 点头 | 近景静止 | 无 |
| `head_turn` | 转头看向一侧 | 近景静止 | 无 |

**黄金模板说明（机位措辞是关键）**：两轮实验结论——决定动作成败的不是场景丰富度，是 prompt 里的
机位措辞：必须「走向并越过镜头（toward and past the camera）+ 镜头后拉跟拍（camera slowly
tracking backward）」。`walk_toward` 的 motion/camera 一字照抄黄金模板（实测 85 分），其余原语
沿用同句式仿写。评级 prompt 严禁 `one-point perspective` / `receding into the distance` /
`vanishing point` 等诱导推镜措辞（曾把走路压没，实测 42 分，有回归测试守护）。

## 素材自动获取（fetch_stock.py）

按原语从 Pixabay 下载候选动作素材（**只下载 + 打清单，不做入库验证**——入库要逐个跑 R2V 评级）：

```bash
python scripts/fetch_stock.py --primitive walk_toward --limit 5 --out work/raw/
# → 按 config.yaml stock.search_terms 的搜索词调 Pixabay video API
# → 下载候选 mp4 到 work/raw/walk_toward/，打印清单（id + 时长 + 分辨率 + 尺寸）
```

- 搜索词映射在 `config.yaml` 的 `stock.search_terms`（按原语可调，务必落到「肢体/全身动作」而非「场景风景」）。
- 候选下载落在 `work/`（已 gitignore），拿到满意的素材后再走 `ingest.py` 入库流程。

**Pixabay key 配置**：`config.yaml` 的 `stock.api_key` 只是占位符，真实密钥放项目根目录 `.env`
（已 gitignore，永不提交）：

```bash
# .env（不入库）
MOTIONLIB_PIXABAY_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxx
```

未配置时运行 `fetch_stock.py` 会清晰报错「请先在 .env 设 MOTIONLIB_PIXABAY_API_KEY」。
Pixabay 素材可商用，入库时 `source_type=stock`、`license=pexels-free`、`source_url` 记录凭证。

## 入库验收流程

```
候选视频 → 预处理(裁 3-5s/24fps/1344x768/去遮挡) → R2V 验证(标准丰富场景 + 固定角色图)
        → VLM 三项审查(char_locked/motion_natural/spatial_stable + 总分)
        → 自动评级(A/B/C) → [C 弃用退出] → [A/B 写 meta.yaml + 登记 index.yaml + 落盘]
```

命令：

```bash
python scripts/ingest.py --video <候选视频> --action-type walk --camera closeup --body-part legs \
    --source-type stock --source-url <url> --license pexels-free [--primitive walk_toward] [--style-pollution]
```

- `--primitive` 指定评级用的原语模板；缺省按 action-type 映射（walk→walk_toward、run→run_toward、
  turn→turn、sit→sit，见 `scripts/r2v.py` 的 `ACTION_TYPE_TO_PRIMITIVE`）。

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
MOTIONLIB_VLM_API_KEY=sk-xxxx          # VLM 审查模型密钥
MOTIONLIB_PIXABAY_API_KEY=xxxxxxxxxx   # Pixabay 素材源密钥（fetch_stock.py 用）
```

加载优先级：`config.yaml` → `.env` → 进程环境变量（最高）。

## 环境要求

- Python 3.11+，依赖 `requests`、`PyYAML`、`Pillow`（`pip install requests pyyaml pillow`）
- 宿主机 ComfyUI 运行于 `127.0.0.1:8188`（`config.yaml` 可改），已装 `MiniMaxH3ReferenceToVideo` 节点与 ref2va 权重
- ffmpeg / ffprobe 在 PATH
