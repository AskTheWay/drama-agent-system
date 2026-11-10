# -*- coding: utf-8 -*-
"""
截图脚本 — 用系统 Edge (playwright channel) 给 README 截运行界面图
运行前提: uvicorn main:app 已在 127.0.0.1:8080 启动
输出: docs/images/*.png
"""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)


def shot(page, name, full=False):
    """截图并打印落盘路径"""
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p), full_page=full)
    print(f"[ok] {p}")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        device_scale_factor=1.5,
        locale="zh-CN",
    )
    page = ctx.new_page()

    # ===== 1. 首页: Agent 工作流 Tab(默认, 输入区已预填模板) =====
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector("#btn-analyze", state="visible")
    time.sleep(1)  # 等 CDN 图标/字体
    shot(page, "01-workflow-input")

    # ===== 2. 运行中(节点动画 + loading) =====
    page.click("#btn-analyze")
    time.sleep(1.8)  # 节点1 active 动画 + loading 出现
    shot(page, "02-workflow-running")

    # ===== 3. 运行结果(自动模式: 节点1/2/3 结果全展示) =====
    page.wait_for_selector("#result-area", state="visible", timeout=120_000)
    time.sleep(1)  # 等渲染稳定
    shot(page, "03-workflow-result", full=True)

    # ===== 4. 人工介入模式: 暂停在 human_review 节点 =====
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector("#btn-analyze", state="visible")
    page.check("#mode-human-review")
    page.click("#btn-analyze")
    page.wait_for_selector("#human-review-panel", state="visible", timeout=120_000)
    time.sleep(0.8)
    shot(page, "04-human-review-paused", full=True)

    # 审核通过, 等最终结果出来(给历史记录页造数据)
    page.click("#human-review-panel .btn-success")
    page.wait_for_selector("#result-area", state="visible", timeout=120_000)
    time.sleep(0.5)
    shot(page, "05-workflow-after-review", full=True)

    # ===== 5. 爆款知识库 Tab =====
    page.click('[data-bs-target="#tab-knowledge"]')
    page.wait_for_selector("#refs-list .card", timeout=30_000)
    time.sleep(0.5)
    shot(page, "06-knowledge-base", full=True)

    # ===== 6. 历史记录 Tab =====
    page.click('[data-bs-target="#tab-history"]')
    time.sleep(1.5)  # 等历史接口返回
    shot(page, "07-history", full=True)

    # ===== 7. 系统架构 Tab =====
    page.click('[data-bs-target="#tab-architecture"]')
    time.sleep(0.5)
    shot(page, "08-architecture", full=True)

    browser.close()

print("done")
