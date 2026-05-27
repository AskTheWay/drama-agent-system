"""
FastAPI 后端 — 短剧投流素材智能剪辑 Agent 系统
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import os

from models import init_db, SessionLocal, HotRef, MaterialAnalysis, EditPlan
from mock_data import seed_data
from agent_workflow import run_workflow, run_workflow_with_interrupt, resume_workflow
from vector_store import get_vector_store

app = FastAPI(title="短剧智能剪辑 Agent 系统")

# 挂载静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ========== 启动初始化 ==========

@app.on_event("startup")
def startup():
    init_db()
    seed_data()
    # 预热向量库
    get_vector_store()


# ========== 页面路由 ==========

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


# ========== API 路由 ==========

@app.get("/api/references")
def list_references(category: Optional[str] = None):
    """获取爆款素材列表"""
    db = SessionLocal()
    query = db.query(HotRef)
    if category:
        query = query.filter(HotRef.category == category)
    refs = query.order_by(HotRef.score.desc()).all()
    db.close()
    return [{
        "id": r.id, "title": r.title, "category": r.category,
        "sub_category": r.sub_category, "hook_text": r.hook_text,
        "hook_type": r.hook_type, "ctr": r.ctr,
        "retention_3s": r.retention_3s, "completion_rate": r.completion_rate,
        "score": r.score, "tags": r.tags,
    } for r in refs]


class AnalyzeRequest(BaseModel):
    asr_text: str
    filename: str = "untitled.txt"
    frame_descriptions: Optional[list] = None

@app.post("/api/analyze")
def analyze_material(req: AnalyzeRequest):
    """运行完整 Agent 工作流（自动模式，跳过人工审核）"""
    result = run_workflow(
        asr_text=req.asr_text,
        filename=req.filename,
        frame_descriptions=req.frame_descriptions,
    )
    return result


@app.post("/api/analyze_interrupt")
def analyze_with_interrupt(req: AnalyzeRequest):
    """运行工作流到人工审核点后暂停"""
    result = run_workflow_with_interrupt(
        asr_text=req.asr_text,
        filename=req.filename,
        frame_descriptions=req.frame_descriptions,
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
    db = SessionLocal()
    items = db.query(MaterialAnalysis).order_by(MaterialAnalysis.id.desc()).limit(20).all()
    db.close()
    return [{
        "id": a.id, "filename": a.filename, "category": a.category,
        "sub_category": a.sub_category, "hook_analysis": a.hook_analysis,
        "key_features": a.key_features,
    } for a in items]


@app.get("/api/plans")
def list_plans():
    """获取历史剪辑方案"""
    db = SessionLocal()
    items = db.query(EditPlan).order_by(EditPlan.id.desc()).limit(20).all()
    db.close()
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
    """数据飞轮：投流效果回传，调整知识库权重"""
    db = SessionLocal()
    plan = db.query(EditPlan).get(req.plan_id)
    if plan and plan.plan_json:
        refs = plan.strategy_refs or []
        for ref_id in refs:
            ref = db.query(HotRef).get(ref_id)
            if ref:
                # 加权移动平均更新得分
                ref.score = ref.score * 0.8 + req.score * 0.2
        db.commit()
    db.close()
    return {"status": "ok", "message": "权重已更新"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
