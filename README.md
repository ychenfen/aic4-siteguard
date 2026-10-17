# 筑安智检 SiteGuard

> AIC4 · 人工智能+场景·建造赛道 · 创新应用【青创学生组】参赛项目

施工现场安全隐患 **AI 巡检与整改闭环** 系统：接入工地现有监控摄像头，自动识别未戴安全帽、未穿反光背心、闯入塔吊/吊装警戒区、基坑临边滞留、明火烟雾等隐患，按《建筑施工安全检查标准》JGJ59 等规范自动定级，生成整改通知单，并跟踪“待整改 → 整改中 → 待复查 → 已闭环”全流程。

```
摄像头视频 ──► 目标检测(YOLO) ──► 人员-装备关联 ──► IoU 跟踪
                                                   │
   整改通知单 ◄── 片段去重/复合升级 ◄── 双条件时序确认 ◄── 规则判定(rules.json)
       │
       └──► 复查闭环 ──► 安全看板 / 统计
```

**核心方法**：违规须持续 ≥ T 秒**且**这段时间内命中帧占比 ≥ ρ 才确认（过滤单帧误检和零星误检）；一段连续违规只报一次；同一人同时有多项已确认违规时升级为重大隐患。

**仿真评估结果**（20 个场景、3.3 小时，`results/exp1_main.md`）：

| 策略 | 召回率 | 误报/小时 | 精确率 | 每事件告警数 |
|---|---|---|---|---|
| 逐帧报警 | 1.000 | 13073.4 | 0.790 | 77.08 |
| 逐帧 + 固定冷却 | 0.859 | 1685.4 | 0.403 | 2.06 |
| 仅时长确认（消融） | 0.964 | 287.4 | 0.771 | 1.57 |
| 双条件确认 + 固定冷却（消融） | 0.916 | 56.1 | 0.940 | 1.50 |
| **本文方法** | **0.962** | **65.1** | **0.938** | **1.59** |

## 快速开始

```bash
# 1. 离线演示（无需 GPU、无需联网、无第三方依赖）
python -m siteguard run samples/site_demo.json --out out/
#   out/tickets.md   整改通知单
#   out/tickets.json 结构化工单
#   out/summary.json 统计

# 2. 可视化演示页：直接用浏览器打开
open demo/index.html

# 3. 接真实视频（需自备在安全帽/反光衣数据集上训练的 YOLO 权重）
pip install ultralytics
python -m siteguard yolo --weights best.pt --source site.mp4 --zones zones.json

# 4. 复现论文实验与图表（约 1~2 分钟）
python scripts/run_experiments.py && python scripts/make_figures.py
python scripts/build_paper.py   # 生成 docs/paper/论文.docx（需要 pandoc、python-docx）

# 测试
pip install pytest && python -m pytest -q
```

演示数据：一路模拟塔吊区摄像头 30 秒回放，覆盖 5 类规则；其中第 3 秒故意放了一帧“裸头”误检，用来展示时序确认能过滤单帧误报。最终生成 5 张整改单（重大 1、较大 3、一般 1）。

## 目录

| 路径 | 说明 |
|---|---|
| `siteguard/association.py` | 把 person / helmet / head / vest 框按空间关系关联成“人员 + 佩戴状态” |
| `siteguard/tracker.py` | 轻量 IoU 跟踪，给人员稳定 ID |
| `siteguard/engine.py` | 规则判定、双条件时序确认、片段去重、复合风险升级 |
| `siteguard/rules.json` | 规则与规范依据（可按项目增删） |
| `siteguard/tickets.py` | 整改通知单生成与状态流转 |
| `siteguard/detectors.py` | YOLO 适配层 + 离线回放 |
| `siteguard/sim.py` / `evaluate.py` | 带真值的场景仿真器、检测器误差模型、评估指标与对比策略 |
| `results/` | 实验结果（CSV / Markdown） |
| `demo/` | 单文件可视化演示（`template.html` + 构建脚本内联数据 → `index.html`） |
| `scripts/` | 生成演示数据、构建演示页、跑实验、画图、生成论文 Word 版 |
| `docs/项目方案.md` | 初赛项目方案（简版） |
| `docs/paper/论文.md` / `论文.docx` | 完整参赛论文（摘要、相关工作、方法、实验、讨论、参考文献） |
| `docs/video/` | 带字幕的演示视频（约 65 秒）与配音解说词；`scripts/record_video.py` 可重新录制 |
| `docs/提交清单.md` | 初赛提交材料清单与提交前待办 |

修改规则或演示数据后，运行 `python scripts/make_sample.py && python scripts/build_demo.py` 重新生成演示页。

## 当前状态与待办

- [x] 规则引擎、工单闭环、离线演示、13 项单元测试
- [x] 仿真评估与消融实验、完整论文
- [ ] 用公开安全帽数据集（如 SHWD）+ 自采工地图片训练 YOLO 权重，补充真实视频演示
- [ ] 危险区多边形在画面上拖拽标定
- [ ] 整改照片上传 + 复查前后对比（可选：多模态模型辅助判断整改是否到位）
- [ ] 核对 `rules.json` 中各规范的检查项与条款编号
