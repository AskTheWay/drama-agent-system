"""
FastAPI 后端 — 短剧投流素材智能剪辑 Agent 系统
"""

import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from prometheus_client import make_asgi_app
from pydantic import BaseModel
from typing import Optional
import os

from models import init_db, SessionLocal, HotRef, MaterialAnalysis, EditPlan
from mock_data import seed_data
from agent_workflow import run_workflow, run_workflow_with_interrupt, resume_workflow
from vector_store import get_vector_store
from metrics import http_requests, http_latency, feedback_total

# ========== 启动/关闭（lifespan，替代已废弃的 on_event） ==========


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：建表、灌种子数据、预热向量库
    init_db()
    seed_data()
    get_vector_store()
    yield
    # 关闭：无资源需要释放


app = FastAPI(title="短剧智能剪辑 Agent 系统", lifespan=lifespan)

# 挂载 /metrics 端点
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# 挂载静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ========== 全局异常处理：统一返回 JSON 错误（而非 Starlette 纯文本 500） ==========


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误: {type(exc).__name__}: {exc}"},
    )


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """采集 HTTP 请求指标"""
    t0 = time.time()
    try:
        response = await call_next(request)
    except Exception:
        # 异常冒泡到全局 handler 前也要计数，避免指标缺口
        http_requests.labels(request.method, request.url.path, "500").inc()
        raise
    duration = time.time() - t0
    path = request.url.path
    # 排除静态文件和 metrics 自身；未匹配路由（404/扫描）合并为 other，防止标签基数爆炸
    if not path.startswith("/static") and not path.startswith("/metrics"):
        label_path = path if request.scope.get("route") else "other"
        http_requests.labels(request.method, label_path, str(response.status_code)).inc()
        http_latency.labels(request.method, label_path).observe(duration)
    return response


# ========== 页面路由 ==========


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


# ========== API 路由 ==========


@app.get("/api/references")
def list_references(category: Optional[str] = None):
    """获取爆款素材列表"""
    with SessionLocal() as db:
        query = db.query(HotRef)
        if category:
            query = query.filter(HotRef.category == category)
        refs = query.order_by(HotRef.score.desc()).all()
        return [{
            "id": r.id, "title": r.title, "category": r.category,
            "sub_category": r.sub_category, "hook_text": r.hook_text,
            "hook_type": r.hook_type, "ctr": r.ctr,
            "retention_3s": r.retention_3s, "completion_rate": r.completion_rate,
            "score": r.score, "tags": r.tags,
        } for r in refs]


@app.get("/api/stats")
def get_stats():
    """全局统计（真实总数，不受列表接口的 limit=20 截断影响）"""
    with SessionLocal() as db:
        refs_count = db.query(HotRef).count()
        analyses_count = db.query(MaterialAnalysis).count()
        plans = db.query(EditPlan.quality_score).all()
        plans_count = len(plans)
        avg_score = (sum(p[0] or 0 for p in plans) / plans_count) if plans_count else 0
        return {
            "references": refs_count,
            "analyses": analyses_count,
            "plans": plans_count,
            "avg_quality_score": round(avg_score, 1),
        }


class AnalyzeRequest(BaseModel):
    asr_text: str
    filename: str = "untitled.txt"
    frame_descriptions: Optional[list] = None
    video_path: Optional[str] = None  # 服务器本地视频路径（学习演示用），传入则走多模态处理链路


@app.post("/api/analyze")
def analyze_material(req: AnalyzeRequest):
    """运行完整 Agent 工作流（自动模式，跳过人工审核）"""
    result = run_workflow(
        asr_text=req.asr_text,
        filename=req.filename,
        frame_descriptions=req.frame_descriptions,
        video_path=req.video_path,
    )
    return result


@app.post("/api/analyze_interrupt")
def analyze_with_interrupt(req: AnalyzeRequest):
    """运行工作流到人工审核点后暂停"""
    result = run_workflow_with_interrupt(
        asr_text=req.asr_text,
        filename=req.filename,
        frame_descriptions=req.frame_descriptions,
        video_path=req.video_path,
    )
    return result


class ResumeRequest(BaseModel):
    state: dict
    approved: bool
    feedback: str = ""


@app.post("/api/resume")
def resume_after_review(req: ResumeRequest):
    """人工审核后恢复工作流"""
    result = resume_workflow(
        state=req.state,
        approved=req.approved,
        feedback=req.feedback,
    )
    return result


@app.get("/api/analyses")
def list_analyses():
    """获取历史分析记录"""
    with SessionLocal() as db:
        items = db.query(MaterialAnalysis).order_by(MaterialAnalysis.id.desc()).limit(20).all()
        return [{
            "id": a.id, "filename": a.filename, "category": a.category,
            "sub_category": a.sub_category, "hook_analysis": a.hook_analysis,
            "key_features": a.key_features,
        } for a in items]


@app.get("/api/plans")
def list_plans():
    """获取历史剪辑方案"""
    with SessionLocal() as db:
        items = db.query(EditPlan).order_by(EditPlan.id.desc()).limit(20).all()
        return [{
            "id": p.id, "material_id": p.material_id,
            "plan_json": p.plan_json, "quality_score": p.quality_score,
            "status": p.status, "created_at": str(p.created_at),
        } for p in items]


@app.post("/api/search")
def search_references(query: str, category: Optional[str] = None,
                      sub_category: Optional[str] = None):
    """向量检索爆款策略"""
    vs = get_vector_store()
    results = vs.search(query=query, category=category,
                        sub_category=sub_category, top_k=5)
    return results


class FeedbackRequest(BaseModel):
    plan_id: int
    score: float


@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    """数据飞轮：投流效果回传，调整知识库权重。
    更新 DB 分数后同步检索元数据，保证「高分策略优先被召回」真正生效。
    """
    if not 0 <= req.score <= 100:
        raise HTTPException(status_code=422, detail="score 需在 0-100 之间")
    feedback_total.inc()
    with SessionLocal() as db:
        plan = db.get(EditPlan, req.plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail=f"plan_id={req.plan_id} 不存在")
        refs = plan.strategy_refs or []
        updated = {}
        for ref_id in refs:
            ref = db.get(HotRef, ref_id)
            if ref:
                # 加权移动平均更新得分
                ref.score = ref.score * 0.8 + req.score * 0.2
                updated[ref.id] = ref.score
        db.commit()

    # 数据飞轮闭环：同步内存元数据 + 落盘，下次检索排序即用新分数
    if updated:
        get_vector_store().update_scores(updated)
    return {"status": "ok", "message": f"权重已更新（{len(updated)} 条素材），下次检索生效", "updated_scores": updated}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
