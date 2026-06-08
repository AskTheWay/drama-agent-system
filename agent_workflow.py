"""
LangGraph Agent 工作流 — 三节点 + 人工介入 + 回溯重生成
节点1: 原视频深度理解 (analyze)
节点2: 爆款策略检索 (retrieve)
质量检查 (quality_check) — 不合格回溯到节点2
人工审核 (human_review) — 人工介入点
节点3: 剪辑方案生成 (generate)
"""

import json
import os
import time
from datetime import datetime
from typing import TypedDict, Annotated, Literal
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from models import (
    EditPlanSchema, HookAnalysis, EmotionPoint, FrameDesc,
    BeatPoint, EditSegment, SessionLocal, MaterialAnalysis, EditPlan,
    HotRef
)
from vector_store import get_vector_store
from video_processor import process_video, extract_frames, analyze_frames_batch
from logger import get_logger, flow_logger
from metrics import (
    node_executions, node_latency, quality_score as quality_score_hist,
    retry_total, llm_calls, llm_errors,
)
import config

logger = get_logger(__name__)


def _build_schema(state: dict) -> dict:
    """构建 state 的数据 schema"""
    schema = {}
    for key, val in state.items():
        if key == "steps":
            schema[key] = f"list[{len(val)}]"
        elif isinstance(val, dict):
            schema[key] = f"dict{list(val.keys())}"
        elif isinstance(val, str):
            schema[key] = f"str({len(val)}字)"
        elif isinstance(val, list):
            schema[key] = f"list[{len(val)}]"
        else:
            schema[key] = f"{type(val).__name__}({val})"
    return schema


def _truncate_val(key: str, val):
    """截断大字段，避免日志爆炸"""
    if key == "steps":
        return f"[{len(val)} steps]"
    if isinstance(val, str) and len(val) > 500:
        return val[:500] + f"...({len(val)}字)"
    if isinstance(val, (dict, list)):
        try:
            s = json.dumps(val, ensure_ascii=False)
            return val if len(s) < 2000 else f"[{type(val).__name__} {len(s)}字节]"
        except Exception:
            return str(val)[:200]
    return val


def _log_flow(node: str, state: dict):
    """记录节点间数据流转"""
    logger.info(f"[数据流转] {node} → {_build_schema(state)}")
    flow_data = {k: _truncate_val(k, v) for k, v in state.items()}
    flow_logger.debug(f"[{node}] {json.dumps(flow_data, ensure_ascii=False, default=str)}")


# ========== 状态定义 ==========

class WorkflowState(TypedDict):
    """工作流全局状态"""
    # 输入
    asr_text: str
    filename: str
    frame_descriptions: list

    # 节点1 输出
    analysis: dict

    # 节点2 输出
    strategy: dict

    # 节点3 输出
    plan: dict

    # 质量控制
    quality_score: float
    retry_count: int           # 回溯重试次数
    max_retries: int           # 最大重试次数

    # 人工介入
    human_feedback: str        # 人工反馈意见
    human_approved: bool       # 人工是否通过
    need_human_review: bool    # 是否需要人工审核

    # 流程控制
    current_node: str          # 当前所在节点
    status: str                # pending / running / paused / completed / failed

    # 执行日志
    steps: list                # 每步执行详情


# ========== 执行日志工具 ==========

def _record_step(state: WorkflowState, node: str, desc: str,
                 input_summary: dict, output_summary: dict, duration_ms: float) -> list:
    """记录一个节点的执行详情"""
    steps = list(state.get("steps") or [])
    steps.append({
        "node": node,
        "desc": desc,
        "input": input_summary,
        "output": output_summary,
        "duration_ms": round(duration_ms, 0),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })
    return steps


# ========== LLM 配置 ==========

def get_llm():
    return ChatOpenAI(
        model=config.LLM_MODEL,
        base_url=config.LLM_BASE_URL,
        api_key=config.LLM_API_KEY,
        extra_body={"thinking": {"type": "disabled"}},
        temperature=0.7,
    )


# ========== 节点1：原视频深度理解 ==========

ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是一位资深短剧投流素材分析师。深度理解素材，提取关键特征。

返回 JSON：
1. hook_analysis: 钩子分析（hook_text, hook_type, effectiveness, timestamp）
2. emotion_curve: 情绪曲线（time, intensity, label）
3. category: 主赛道（男频/女频）
4. sub_category: 二级题材
5. key_features: 关键特征列表（至少5个）
6. beat_points: 音画卡点

只返回 JSON，不要其他文字。"""),
    ("user", """素材：{filename}
ASR：{asr_text}
帧描述：{frame_descriptions}"""),
])


def node_analyze(state: WorkflowState) -> WorkflowState:
    """节点1：原视频深度理解"""
    logger.info("[节点1] 原视频深度理解...")
    node_executions.labels("analyze").inc()
    t0 = time.time()
    asr_text = state["asr_text"]
    filename = state["filename"]
    frame_descriptions = state.get("frame_descriptions") or [
        {"timestamp": "0s", "scene": "开场画面", "action": "主角出场", "visual_hook": "特写镜头"},
        {"timestamp": "3s", "scene": "冲突场景", "action": "对峙", "visual_hook": "快切剪辑"},
        {"timestamp": "10s", "scene": "高潮画面", "action": "反转", "visual_hook": "慢动作+特效"},
    ]

    llm = get_llm()
    chain = ANALYSIS_PROMPT | llm | JsonOutputParser()

    try:
        llm_calls.labels("analyze").inc()
        result = chain.invoke({
            "filename": filename,
            "asr_text": asr_text,
            "frame_descriptions": json.dumps(frame_descriptions, ensure_ascii=False),
        })
    except Exception as e:
        llm_errors.labels("analyze").inc()
        logger.warning(f"[节点1] LLM 失败，使用模拟: {e}")
        result = _mock_analysis(asr_text)

    # 存 DB
    db = SessionLocal()
    analysis = MaterialAnalysis(
        filename=filename, asr_text=asr_text,
        frame_descriptions=frame_descriptions,
        hook_analysis=result.get("hook_analysis", {}),
        emotion_curve=result.get("emotion_curve", []),
        category=result.get("category", "男频"),
        sub_category=result.get("sub_category", "逆袭"),
        key_features=result.get("key_features", []),
    )
    db.add(analysis)
    db.commit()
    result["analysis_id"] = analysis.id
    db.close()

    duration = (time.time() - t0) * 1000
    node_latency.labels("analyze").observe(duration / 1000)
    steps = _record_step(state, "analyze", "原视频深度理解",
        {"filename": filename, "asr_text": asr_text[:100] + "...", "frame_count": len(frame_descriptions)},
        {"category": result.get("category"), "sub_category": result.get("sub_category"),
         "hook_text": result.get("hook_analysis", {}).get("hook_text", ""),
         "key_features": result.get("key_features", []),
         "emotion_curve_count": len(result.get("emotion_curve", []))},
        duration)

    logger.info(f"[节点1] 完成，赛道={result.get('category')}/{result.get('sub_category')}")
    new_state = {**state, "analysis": result, "steps": steps, "current_node": "retrieve", "status": "running"}
    _log_flow("analyze", new_state)
    return new_state


# ========== 节点2：爆款策略检索 ==========

RETRIEVAL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是短剧投流策略专家。基于素材分析检索匹配策略。

返回 JSON：
1. matched_strategies: 匹配策略列表
2. strategy_summary: 策略总结（100字）
3. recommended_hook: 推荐钩子
4. recommended_emotion_flow: 推荐情绪节奏
5. key_learnings: 关键学习点

只返回 JSON。"""),
    ("user", """赛道：{category}/{sub_category}
钩子：{hook_text}
特征：{key_features}

检索结果：
{retrieved_refs}"""),
])


def node_retrieve(state: WorkflowState) -> WorkflowState:
    """节点2：爆款策略检索（双模 RAG）"""
    logger.info("[节点2] 爆款策略检索...")
    node_executions.labels("retrieve").inc()
    t0 = time.time()
    analysis = state["analysis"]
    category = analysis.get("category", "")
    sub_category = analysis.get("sub_category", "")
    hook_text = analysis.get("hook_analysis", {}).get("hook_text", "")
    key_features = analysis.get("key_features", [])

    query = f"{hook_text} {' '.join(key_features[:3])}"
    vs = get_vector_store()
    retrieved = vs.search(query=query, category=category, sub_category=sub_category, top_k=3)
    if not retrieved:
        retrieved = vs.search(query=query, top_k=3)

    llm = get_llm()
    chain = RETRIEVAL_PROMPT | llm | JsonOutputParser()

    # 如果有人工反馈，加入检索条件
    human_feedback = state.get("human_feedback", "")
    if human_feedback:
        query = f"{query} 人工反馈：{human_feedback}"

    try:
        llm_calls.labels("retrieve").inc()
        result = chain.invoke({
            "category": category, "sub_category": sub_category,
            "hook_text": hook_text,
            "key_features": json.dumps(key_features, ensure_ascii=False),
            "retrieved_refs": json.dumps(retrieved, ensure_ascii=False, indent=2),
        })
    except Exception as e:
        llm_errors.labels("retrieve").inc()
        logger.warning(f"[节点2] LLM 失败，使用模拟: {e}")
        result = _mock_retrieval(retrieved)

    result["retrieved_refs"] = retrieved
    duration = (time.time() - t0) * 1000
    node_latency.labels("retrieve").observe(duration / 1000)
    steps = _record_step(state, "retrieve", "爆款策略检索 (双模 RAG)",
        {"query": query, "category": category, "sub_category": sub_category},
        {"matched_count": len(retrieved),
         "retrieved_titles": [r.get("title", "") for r in retrieved],
         "strategy_summary": result.get("strategy_summary", "")},
        duration)

    logger.info(f"[节点2] 检索到 {len(retrieved)} 条策略")
    new_state = {**state, "strategy": result, "steps": steps, "current_node": "quality_check", "status": "running"}
    _log_flow("retrieve", new_state)
    return new_state


# ========== 质量检查节点 ==========

def node_quality_check(state: WorkflowState) -> WorkflowState:
    """质量检查：评估分析和检索结果，决定是否需要回溯"""
    logger.info("[质量检查] 评估中...")
    node_executions.labels("quality_check").inc()
    t0 = time.time()
    analysis = state["analysis"]
    strategy = state["strategy"]
    retry_count = state.get("retry_count", 0)

    # 评分规则
    score = 60.0
    issues = []

    # 检查分析结果
    hook = analysis.get("hook_analysis", {})
    try:
        effectiveness = float(hook.get("effectiveness", 0))
    except (ValueError, TypeError):
        effectiveness = 0
    if effectiveness < 0.5:
        score -= 15
        issues.append("钩子效果预估过低")

    if not analysis.get("category"):
        score -= 20
        issues.append("赛道未判断")

    key_features = analysis.get("key_features", [])
    if isinstance(key_features, str):
        key_features = [f.strip() for f in key_features.split(",") if f.strip()]
    if len(key_features) < 3:
        score -= 10
        issues.append("关键特征不足")

    # 检查检索结果
    if len(strategy.get("retrieved_refs", [])) == 0:
        score -= 20
        issues.append("无匹配策略")

    if not strategy.get("strategy_summary"):
        score -= 10
        issues.append("策略总结为空")

    score = max(0, min(100, score))
    quality_score_hist.observe(score)
    duration = (time.time() - t0) * 1000
    node_latency.labels("quality_check").observe(duration / 1000)

    route = "human_review" if score >= 70 or retry_count >= state.get("max_retries", 2) else "retrieve"
    steps = _record_step(state, "quality_check", "质量检查",
        {"retry_count": retry_count, "max_retries": state.get("max_retries", 2)},
        {"score": score, "issues": issues, "route": route},
        duration)

    logger.info(f"[质量检查] 得分={score}, 问题={issues}, 重试次数={retry_count}")
    new_state = {**state, "quality_score": score, "steps": steps, "current_node": "quality_check", "status": "running"}
    _log_flow("quality_check", new_state)
    return new_state


def route_after_quality(state: WorkflowState) -> Literal["retrieve", "human_review"]:
    """质量检查后的路由：不合格回溯到检索，合格进入人工审核"""
    score = state.get("quality_score", 0)
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if score < 70 and retry_count < max_retries:
        retry_total.inc()
        logger.warning(f"[路由] 质量不达标({score}<70)，回溯到检索节点，重试 {retry_count + 1}/{max_retries}")
        return "retrieve"
    else:
        if score < 70:
            logger.warning("[路由] 质量不达标但已达最大重试次数，强制进入人工审核")
        else:
            logger.info(f"[路由] 质量达标({score}>=70)，进入人工审核")
        return "human_review"


def node_retry_increment(state: WorkflowState) -> WorkflowState:
    """回溯时递增重试计数"""
    return {**state, "retry_count": state.get("retry_count", 0) + 1}


# ========== 人工审核节点 ==========

def node_human_review(state: WorkflowState) -> WorkflowState:
    """人工审核：暂停工作流，等待人工反馈"""
    logger.info("[人工审核] 等待人工介入...")
    node_executions.labels("human_review").inc()
    steps = _record_step(state, "human_review", "人工审核（暂停等待）",
        {"quality_score": state.get("quality_score"), "retry_count": state.get("retry_count")},
        {"action": "暂停，等待人工通过/打回"},
        0)
    new_state = {**state, "steps": steps, "current_node": "human_review", "status": "paused", "need_human_review": True}
    _log_flow("human_review", new_state)
    return new_state


def route_after_human(state: WorkflowState) -> Literal["generate", "retrieve"]:
    """人工审核后的路由：通过则生成，打回则重新检索"""
    approved = state.get("human_approved", False)
    feedback = state.get("human_feedback", "")

    if approved:
        logger.info("[路由] 人工审核通过，进入方案生成")
        return "generate"
    else:
        logger.warning(f"[路由] 人工打回，反馈='{feedback}'，回溯到检索节点")
        return "retrieve"


# ========== 节点3：剪辑方案生成 ==========

GENERATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是专业剪辑方案设计师。生成结构化剪辑方案。

严格返回 JSON Schema：
{{
  "plan_id": "唯一ID",
  "title": "方案标题",
  "target_duration": "时长",
  "category": "赛道",
  "sub_category": "题材",
  "hook_analysis": {{"hook_text":"","hook_type":"","effectiveness":0.0,"timestamp":""}},
  "emotion_curve": [{{"time":"","intensity":0.0,"label":""}}],
  "segments": [{{
    "segment_id":1,"start_time":"","end_time":"","duration":"",
    "scene_description":"","camera_movement":"","bgm_cue":"",
    "text_overlay":"","transition":"","conversion_hook":"","emotion_target":""
  }}],
  "beat_points": [{{"time":"","type":"","intensity":0.0,"description":""}}],
  "strategy_summary":"",
  "estimated_ctr":0.0,
  "estimated_retention":0.0,
  "created_at":""
}}

只返回 JSON。"""),
    ("user", """素材分析：
{analysis}

爆款策略：
{strategy}

{feedback_hint}

生成4-6个片段，总时长20-30秒。"""),
])


def node_generate(state: WorkflowState) -> WorkflowState:
    """节点3：剪辑方案生成（JSON Schema 强制输出）"""
    logger.info("[节点3] 剪辑方案生成...")
    node_executions.labels("generate").inc()
    t0 = time.time()
    analysis = state.get("analysis", {})
    strategy = state.get("strategy", {})
    human_feedback = state.get("human_feedback", "")

    # 防御：如果 analysis 或 strategy 为空，使用兜底数据
    if not analysis:
        logger.warning("[节点3] analysis 为空，使用兜底数据")
        analysis = _mock_analysis(state.get("asr_text", ""))
    if not strategy:
        logger.warning("[节点3] strategy 为空，使用兜底数据")
        strategy = _mock_retrieval([])

    feedback_hint = ""
    if human_feedback:
        feedback_hint = f"人工反馈要求：{human_feedback}\n请根据反馈调整方案。"

    llm = get_llm()
    chain = GENERATION_PROMPT | llm | JsonOutputParser()

    try:
        llm_calls.labels("generate").inc()
        result = chain.invoke({
            "analysis": json.dumps({
                "hook_analysis": analysis.get("hook_analysis"),
                "emotion_curve": analysis.get("emotion_curve"),
                "category": analysis.get("category"),
                "sub_category": analysis.get("sub_category"),
                "key_features": analysis.get("key_features"),
            }, ensure_ascii=False),
            "strategy": json.dumps({
                "strategy_summary": strategy.get("strategy_summary"),
                "recommended_hook": strategy.get("recommended_hook"),
                "recommended_emotion_flow": strategy.get("recommended_emotion_flow"),
                "key_learnings": strategy.get("key_learnings"),
            }, ensure_ascii=False),
            "feedback_hint": feedback_hint,
        })
    except Exception as e:
        llm_errors.labels("generate").inc()
        logger.warning(f"[节点3] LLM 失败，使用模拟: {e}")
        result = _mock_plan(analysis, strategy)

    # 存 DB
    quality_score = _calc_quality(result)
    db = SessionLocal()
    plan = EditPlan(
        material_id=analysis.get("analysis_id"),
        plan_json=result,
        strategy_refs=[r.get("id") for r in strategy.get("retrieved_refs", [])],
        quality_score=quality_score,
        status="human_approved" if state.get("human_approved") else "draft",
    )
    db.add(plan)
    db.commit()
    result["db_plan_id"] = plan.id
    db.close()

    duration = (time.time() - t0) * 1000
    node_latency.labels("generate").observe(duration / 1000)
    steps = _record_step(state, "generate", "剪辑方案生成",
        {"category": analysis.get("category"), "sub_category": analysis.get("sub_category"),
         "strategy_summary": strategy.get("strategy_summary", "")[:50],
         "human_feedback": human_feedback or "无"},
        {"plan_id": result.get("plan_id"), "title": result.get("title"),
         "segment_count": len(result.get("segments", [])),
         "estimated_ctr": result.get("estimated_ctr"),
         "estimated_retention": result.get("estimated_retention"),
         "quality_score": quality_score},
        duration)

    logger.info(f"[节点3] 完成，质量={quality_score}, CTR={result.get('estimated_ctr')}")
    new_state = {**state, "plan": result, "quality_score": quality_score, "steps": steps, "current_node": "completed", "status": "completed"}
    _log_flow("generate", new_state)
    return new_state


# ========== 图构建 ==========

def build_graph():
    """构建 LangGraph 状态图"""
    graph = StateGraph(WorkflowState)

    # 添加节点
    graph.add_node("analyze", node_analyze)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("quality_check", node_quality_check)
    graph.add_node("retry_increment", node_retry_increment)
    graph.add_node("human_review", node_human_review)
    graph.add_node("generate", node_generate)

    # 入口
    graph.set_entry_point("analyze")

    # 边：analyze → retrieve
    graph.add_edge("analyze", "retrieve")

    # 边：retrieve → quality_check
    graph.add_edge("retrieve", "quality_check")

    # 条件边：quality_check → retrieve（回溯）或 human_review
    graph.add_conditional_edges("quality_check", route_after_quality, {
        "retrieve": "retry_increment",
        "human_review": "human_review",
    })

    # 边：retry_increment → retrieve（回溯重试）
    graph.add_edge("retry_increment", "retrieve")

    # 条件边：human_review → generate（通过）或 retrieve（打回）
    graph.add_conditional_edges("human_review", route_after_human, {
        "generate": "generate",
        "retrieve": "retrieve",
    })

    # 边：generate → END
    graph.add_edge("generate", END)

    return graph.compile()


# ========== 工作流入口 ==========

# 全局图实例
_app = None

def get_app():
    global _app
    if _app is None:
        _app = build_graph()
    return _app


def run_workflow(asr_text: str, filename: str, frame_descriptions: list = None,
                 video_path: str = None) -> dict:
    """运行完整工作流（自动模式，不暂停）"""
    if video_path and os.path.exists(video_path):
        video_result = process_video(video_path, asr_text)
        asr_text = video_result["asr_text"]
        frame_descriptions = video_result["frame_descriptions"]

    initial_state: WorkflowState = {
        "asr_text": asr_text,
        "filename": filename,
        "frame_descriptions": frame_descriptions or [],
        "analysis": {},
        "strategy": {},
        "plan": {},
        "quality_score": 0,
        "retry_count": 0,
        "max_retries": 2,
        "human_feedback": "",
        "human_approved": True,    # 自动模式默认通过
        "need_human_review": False,
        "current_node": "",
        "status": "running",
        "steps": [],
    }

    app = get_app()
    final_state = app.invoke(initial_state)
    return {
        "analysis": final_state.get("analysis", {}),
        "strategy": final_state.get("strategy", {}),
        "plan": final_state.get("plan", {}),
        "quality_score": final_state.get("quality_score", 0),
        "retry_count": final_state.get("retry_count", 0),
        "steps": final_state.get("steps", []),
    }


def run_workflow_with_interrupt(asr_text: str, filename: str,
                                frame_descriptions: list = None) -> dict:
    """运行工作流到人工审核点后暂停，返回中间状态"""
    initial_state: WorkflowState = {
        "asr_text": asr_text,
        "filename": filename,
        "frame_descriptions": frame_descriptions or [],
        "analysis": {},
        "strategy": {},
        "plan": {},
        "quality_score": 0,
        "retry_count": 0,
        "max_retries": 2,
        "human_feedback": "",
        "human_approved": False,
        "need_human_review": False,
        "current_node": "",
        "status": "running",
        "steps": [],
    }

    app = get_app()
    # 用 stream 执行，在 human_review 节点暂停
    events = {}
    for event in app.stream(initial_state):
        for node, output in event.items():
            events[node] = output
            logger.info(f"[执行] 节点 {node} 完成")
            # 在 human_review 节点暂停
            if node == "human_review" and output.get("status") == "paused":
                return {
                    "status": "paused",
                    "paused_at": "human_review",
                    "state": output,
                    "steps": output.get("steps", []),
                    "events": events,
                }

    # 如果没暂停就完成了
    final = events.get("generate", {})
    return {
        "status": "completed",
        "state": final,
        "steps": final.get("steps", []),
        "events": events,
    }


def resume_workflow(state: WorkflowState, approved: bool, feedback: str = "") -> dict:
    """恢复暂停的工作流：带入人工反馈继续执行
    不重新运行整个图，而是直接从当前状态继续执行后续节点。
    """
    state["human_approved"] = approved
    state["human_feedback"] = feedback
    state["status"] = "running"

    if approved:
        # 通过 → 直接执行生成节点
        logger.info("[恢复] 人工审核通过，执行方案生成...")
        logger.debug(f"[恢复] 当前 analysis keys: {list(state.get('analysis', {}).keys())}")
        logger.debug(f"[恢复] 当前 strategy keys: {list(state.get('strategy', {}).keys())}")
        result_state = node_generate(state)
    else:
        # 打回 → 重新检索 + 质量检查 + 生成
        logger.warning(f"[恢复] 人工打回，反馈='{feedback}'，重新检索...")
        state["retry_count"] = state.get("retry_count", 0) + 1
        state = node_retrieve(state)
        state = node_quality_check(state)
        result_state = node_generate(state)

    plan = result_state.get("plan", {})
    logger.debug(f"[恢复] 完成，plan keys: {list(plan.keys()) if plan else 'EMPTY'}")
    return {
        "analysis": result_state.get("analysis", {}),
        "strategy": result_state.get("strategy", {}),
        "plan": plan,
        "quality_score": result_state.get("quality_score", 0),
        "retry_count": result_state.get("retry_count", 0),
        "steps": result_state.get("steps", []),
    }


# ========== Mock 数据 ==========

def _mock_analysis(asr_text, **_):
    return {
        "hook_analysis": {"hook_text": asr_text[:30] + "...", "hook_type": "悬念", "effectiveness": 0.75, "timestamp": "0-3s"},
        "emotion_curve": [
            {"time": "0s", "intensity": 0.3, "label": "平静"},
            {"time": "3s", "intensity": 0.7, "label": "紧张"},
            {"time": "10s", "intensity": 0.9, "label": "高潮"},
            {"time": "15s", "intensity": 0.5, "label": "释放"},
        ],
        "frame_descriptions": [
            {"timestamp": "0s", "scene": "开场", "action": "主角出场", "visual_hook": "特写"},
            {"timestamp": "5s", "scene": "冲突", "action": "对峙", "visual_hook": "快切"},
        ],
        "category": "男频", "sub_category": "逆袭",
        "key_features": ["悬念钩子", "快速冲突", "反转高潮", "情绪起伏", "视觉冲击"],
        "beat_points": [
            {"time": "0.5s", "type": "文案出现", "intensity": 0.8, "description": "钩子文案"},
            {"time": "10s", "type": "画面切换", "intensity": 1.0, "description": "高潮快切"},
        ],
    }


def _mock_retrieval(retrieved):
    return {
        "matched_strategies": [
            {"title": r["title"], "similarity": r.get("similarity", 0.8), "reusable_points": ["钩子结构", "情绪节奏"]}
            for r in retrieved
        ],
        "strategy_summary": "采用悬念式钩子开场，快速建立冲突，通过反转推动高潮，配合音画卡点强化情绪冲击。",
        "recommended_hook": "悬念+反差型钩子，前3秒抛出核心矛盾",
        "recommended_emotion_flow": "平静→紧张→铺垫→高潮→释放",
        "key_learnings": ["钩子文案要制造信息差", "情绪曲线要有明显起伏", "反转点放在15s左右"],
    }


def _mock_plan(analysis, strategy):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "plan_id": f"plan_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "title": f"优化版_{analysis.get('category', '')}_{analysis.get('sub_category', '')}素材",
        "target_duration": "25s",
        "category": analysis.get("category", "男频"),
        "sub_category": analysis.get("sub_category", "逆袭"),
        "hook_analysis": {
            "hook_text": analysis.get("hook_analysis", {}).get("hook_text", "悬念开场"),
            "hook_type": "悬念", "effectiveness": 0.85, "timestamp": "0-3s",
        },
        "emotion_curve": [
            {"time": "0s", "intensity": 0.3, "label": "平静"},
            {"time": "3s", "intensity": 0.7, "label": "紧张"},
            {"time": "8s", "intensity": 0.5, "label": "铺垫"},
            {"time": "15s", "intensity": 0.95, "label": "高潮"},
            {"time": "20s", "intensity": 0.6, "label": "释放"},
            {"time": "25s", "intensity": 0.4, "label": "收尾"},
        ],
        "segments": [
            {"segment_id": 1, "start_time": "0s", "end_time": "3s", "duration": "3s", "scene_description": "悬念开场：主角低谷状态", "camera_movement": "特写推进", "bgm_cue": "低沉弦乐", "text_overlay": "三年了...", "transition": "硬切", "conversion_hook": "想知道后来？", "emotion_target": "好奇"},
            {"segment_id": 2, "start_time": "3s", "end_time": "8s", "duration": "5s", "scene_description": "冲突升级", "camera_movement": "正反打快切", "bgm_cue": "紧张渐强", "text_overlay": "废物", "transition": "闪白", "conversion_hook": "", "emotion_target": "愤怒"},
            {"segment_id": 3, "start_time": "8s", "end_time": "13s", "duration": "5s", "scene_description": "转折铺垫", "camera_movement": "环绕推镜", "bgm_cue": "鼓点渐密", "text_overlay": "电话响起", "transition": "模糊", "conversion_hook": "", "emotion_target": "期待"},
            {"segment_id": 4, "start_time": "13s", "end_time": "18s", "duration": "5s", "scene_description": "高潮反转", "camera_movement": "升格慢动作", "bgm_cue": "重拍落点", "text_overlay": "全场震惊", "transition": "快闪", "conversion_hook": "点击看完整版", "emotion_target": "爽感"},
            {"segment_id": 5, "start_time": "18s", "end_time": "25s", "duration": "7s", "scene_description": "收尾引导", "camera_movement": "缓推特写", "bgm_cue": "余韵收尾", "text_overlay": "点击观看→", "transition": "渐隐", "conversion_hook": "免费看全集", "emotion_target": "意犹未尽"},
        ],
        "beat_points": [
            {"time": "0.5s", "type": "文案出现", "intensity": 0.8, "description": "钩子字幕"},
            {"time": "3s", "type": "音乐节拍", "intensity": 0.7, "description": "鼓点进入"},
            {"time": "15s", "type": "画面切换", "intensity": 1.0, "description": "高潮快切"},
        ],
        "strategy_summary": strategy.get("strategy_summary", "悬念开场+快速冲突+反转高潮"),
        "estimated_ctr": 0.048,
        "estimated_retention": 0.83,
        "created_at": now,
    }


def _calc_quality(plan):
    score = 60.0
    segments = plan.get("segments", [])
    if len(segments) >= 4: score += 10
    if plan.get("hook_analysis", {}).get("effectiveness", 0) > 0.7: score += 10
    if len(plan.get("beat_points", [])) >= 3: score += 10
    if plan.get("estimated_ctr", 0) > 0.04: score += 10
    return min(score, 100)
