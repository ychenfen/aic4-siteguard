"""自动录制带字幕的演示视频：docs/video/筑安智检演示.mp4（约 75 秒，1920×1080，无声，字幕烧录在画面中）。

    pip install playwright && playwright install chromium   # 首次
    python scripts/record_video.py

流程：片头 → 回放演示页 30 秒并在关键时刻显示字幕 → 推进一张整改单至闭环 → 实验结果 → 片尾。
解说词与时间轴见 docs/video/解说词.md，可按字幕时间配音。
"""
from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "video" / "筑安智检演示.mp4"
DEMO = ROOT / "demo" / "index.html"
FIG = ROOT / "docs" / "paper" / "figures"
W, H = 1920, 1080

CARD_CSS = """
body{margin:0;width:1920px;height:1080px;background:#22323D;color:#F6F7F5;
font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif;display:flex;flex-direction:column;justify-content:center;
padding:0 160px;box-sizing:border-box;overflow:hidden}
.tape{position:absolute;left:0;top:0;width:100%;height:36px;
background:repeating-linear-gradient(-45deg,#F2C200 0 28px,#1A1F23 28px 56px)}
.k{color:#F2C200;font-size:32px;font-weight:500;margin:0 0 24px}
h1{font-family:'Noto Serif CJK SC',serif;font-size:140px;margin:0 0 24px;font-weight:900}
p{font-size:44px;color:#D5DCE0;margin:0 0 16px;line-height:1.4}
img{display:block;margin:24px 0 0;width:1500px;background:#fff;border-radius:8px;padding:16px}
"""

CAPTION_JS = """
(() => {
  const d = document.createElement('div');
  d.id = 'cap';
  d.style.cssText = 'position:fixed;left:50%;bottom:40px;transform:translateX(-50%);max-width:1600px;'+
    'background:rgba(20,28,34,.88);color:#fff;font:500 38px/1.45 "Noto Sans CJK SC",sans-serif;'+
    'padding:18px 36px;border-radius:10px;border-left:8px solid #F2C200;z-index:99;text-align:left;display:none';
  document.body.appendChild(d);
  window.__cap = (t) => { d.textContent = t; d.style.display = t ? 'block' : 'none'; };
})();
"""


def card(kicker: str, title: str, lines: list[str], img: Path | None = None, w: int = 1500) -> str:
    im = ""
    if img is not None:
        im = (f'<img style="width:{w}px" '
              f'src="data:image/png;base64,{base64.b64encode(img.read_bytes()).decode()}">')
    body = "".join(f"<p>{x}</p>" for x in lines)
    return (f"<html><head><meta charset='utf-8'><style>{CARD_CSS}</style></head><body><div class='tape'></div>"
            f"<div class='k'>{kicker}</div><h1>{title}</h1>{body}{im}</body></html>")


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                                  record_video_size={"width": W, "height": H}, color_scheme="light")
        pg = await ctx.new_page()

        # 片头 5 秒
        await pg.set_content(card("AIC4 · 人工智能+场景·建造 · 创新应用【青创学生组】", "筑安智检",
                                  ["施工现场安全隐患 AI 巡检与整改闭环系统", "演示：塔吊区监控 30 秒回放"]))
        await pg.wait_for_timeout(5000)

        # 背景与方法（静态卡片，便于 3～5 分钟的完整讲解）
        async def show(html: str, secs: float) -> None:
            await pg.set_content(html)
            await pg.wait_for_timeout(int(secs * 1000))

        await show(card("问题", "报不准 · 管不住",
                        ["2019 年全国房屋市政工程生产安全事故 773 起，其中高处坠落占 53.69%（住建部通报）",
                         "现有 AI 安全帽识别多为逐帧报警：误报成堆，安全员逐渐不再看告警",
                         "识别之后缺少整改流程：谁负责、几时整改、是否复查，都没有记录"]), 18)
        await show(card("方法", "三层架构",
                        ["感知：目标检测 → 人员—装备关联 → 多目标跟踪",
                         "决策：规则判定 → 双条件时序确认 → 片段去重与风险分级",
                         "应用：整改通知单 → 状态机闭环"],
                        FIG / "fig_architecture.png", w=1300), 22)
        await show(card("方法 · 双条件时序确认", "时长 且 占比",
                        ["持续时长达标，且窗口内命中帧占比不低于 0.7，才确认违规",
                         "零星误检串不成一段有效违规；真实违规中的少量漏判不影响确认"],
                        FIG / "fig_confirmation.png", w=1300), 22)

        # 演示页
        await pg.goto(DEMO.as_uri())
        await pg.add_style_tag(content="main{max-width:1500px!important;padding-top:8px!important} header{padding-block:10px 4px!important}")
        await pg.evaluate(CAPTION_JS)
        await pg.wait_for_timeout(800)
        cap = lambda t: pg.evaluate("t => window.__cap(t)", t)  # noqa: E731
        await cap("画面中绿色框为合规，橙色为违规待确认，红色为已确认隐患；黄色虚线是危险区")
        await pg.wait_for_timeout(3500)
        await pg.click("#play")
        # 回放 30 秒（5 fps 实时），按时刻切换字幕
        timeline = [
            (0.0, "工人 #2 未戴安全帽：违规持续 2 秒、且大部分帧都判定违规，才确认并生成整改单"),
            (2.6, "第 3 秒，合规的工人 #1 被误检了一帧“裸头”：只有一帧，不报警"),
            (5.5, "工人 #3 未穿反光背心，持续 3 秒后确认，等级“一般”"),
            (8.5, "工人 #2 没戴安全帽，正走向 1# 塔吊回转区……"),
            (10.4, "进入塔吊区 1 秒：安全帽违规早已确认，系统直接发出“重大”复合风险告警，要求立即停工"),
            (14.3, "工人 #3 在基坑临边停留 5 秒，确认“滞留”，等级“较大”"),
            (19.0, "同一段违规只报一次，不会刷屏"),
            (22.5, "画面右上方出现烟雾……"),
            (24.3, "烟雾持续 2 秒后确认，生成整改单，依据 GB 50720"),
            (27.0, "30 秒共生成 5 张整改单：重大 1、较大 3、一般 1"),
        ]
        t0 = asyncio.get_event_loop().time()
        for at, text in timeline:
            now = asyncio.get_event_loop().time() - t0
            if at > now:
                await asyncio.sleep(at - now)
            await cap(text)
        await asyncio.sleep(max(0, 31.5 - (asyncio.get_event_loop().time() - t0)))

        # 整改闭环
        await pg.locator("#feed button", has_text="复合风险").click()
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pg.evaluate("document.getElementById('cap').style.cssText += ';bottom:auto;top:40px'")
        await cap("点开“重大”整改通知单：写明规范依据、整改措施和期限")
        await pg.wait_for_timeout(3500)
        for text in ["安全员开始整改", "整改完成，提交复查", "复查通过，工单闭环；每一步都留有时间记录"]:
            await pg.click("#ticket button[data-a=next]")
            await cap(text)
            await pg.wait_for_timeout(2500)
        await pg.wait_for_timeout(1000)
        await cap("")

        # 去重与复合升级（静态卡片）
        await show(card("方法", "只报一次 · 高危升级",
                        ["一段连续违规只告警一次；持续超过 300 秒仍未消除，才再次提醒",
                         "同一人员同时确认“未戴安全帽”与“进入塔吊区”，升级为“重大”告警，要求立即停工"]), 15)

        # 实验结果
        await show(card("仿真评估：20 个场景、3.3 小时", "误报 −96.1%",
                        ["与“逐帧 + 固定冷却”相比：每小时 1685.4 次 → 65.1 次；召回率 0.859 → 0.962"],
                        FIG / "fig_strategy_compare.png"), 12)
        await show(card("仿真评估 · 参数敏感性", "确认时长决定权衡",
                        ["确认时长放大时误报迅速下降，但召回率与时延随之变差",
                         "默认配置处于拐点附近：误报约 67 次/小时，召回率 0.94，时延 2.9 秒"],
                        FIG / "fig_sweep.png", w=1300), 15)
        await show(card("仿真评估 · 鲁棒性", "检测器更差，告警仍可控",
                        ["检测误差强度 k=3 时，逐帧加冷却的误报升至每小时约 1 万次",
                         "本文方法仍保持在每小时约 40 次，精确率不低于 0.92"],
                        FIG / "fig_noise.png", w=1300), 15)

        # 局限与下一步
        await show(card("局限与计划", "诚实地说边界",
                        ["定量结论来自仿真，检测模型尚未在真实工地数据上训练",
                         "下一步：用 SHWD 数据集训练 YOLO，真实视频人工标注验证，合作工地试点"]), 20)

        # 片尾
        await show(card("筑安智检", "谢谢观看",
                        ["双条件时序确认 · 片段级去重 · 复合风险升级 · 规范驱动的整改闭环"]), 5)
        await ctx.close()
        await b.close()

    webm = next(tmp.glob("*.webm"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-preset", "slow",
                    "-crf", "26", "-pix_fmt", "yuv420p", "-r", "25", "-movflags", "+faststart", str(OUT)], check=True)
    shutil.rmtree(tmp)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
