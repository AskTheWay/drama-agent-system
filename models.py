"""
数据模型 — SQLAlchemy ORM + Pydantic Schema
"""

import json as _json
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, create_engine
from sqlalchemy.types import TypeDecorator
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class JSON(TypeDecorator):
    """自定义 JSON 列，存储时保留中文（不转义为 \\uXXXX）"""
    impl = Text

    def process_bind_param(self, value, dialect):
        if value is not None:
            return _json.dumps(value, ensure_ascii=False)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return _json.loads(value)
        return value

Base = declarative_base()

# ========== 数据库模型 ==========

class HotRef(Base):
    """爆款素材 Reference 表"""
    __tablename__ = "hot_references"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    category = Column(String(50))          # 主赛道：男频/女频
    sub_category = Column(String(50))      # 二级题材：逆袭/甜宠/复仇...
    hook_text = Column(Text)               # 黄金3秒钩子文案
    hook_type = Column(String(50))         # 钩子类型：悬念/冲突/反转
    emotion_curve = Column(JSON)           # 情绪曲线数据点
    beat_points = Column(JSON)             # 音画卡点时间列表
    ctr = Column(Float)                    # 点击率
    retention_3s = Column(Float)           # 3秒停留率
    completion_rate = Column(Float)        # 完播率
    score = Column(Float, default=0)       # 综合得分（数据飞轮权重）
    tags = Column(JSON)                    # 标签列表
    created_at = Column(DateTime, default=datetime.now)
    asr_text = Column(Text)               # ASR 转写文本
    frame_descriptions = Column(JSON)      # 帧级画面描述


class MaterialAnalysis(Base):
    """素材分析结果表"""
    __tablename__ = "material_analysis"

    id = Column(Integer, primary_key=True)
    filename = Column(String(200))
    asr_text = Column(Text)
    frame_descriptions = Column(JSON)
    hook_analysis = Column(JSON)           # 钩子分析
    emotion_curve = Column(JSON)
    category = Column(String(50))
    sub_category = Column(String(50))
    key_features = Column(JSON)            # 提取的关键特征
    created_at = Column(DateTime, default=datetime.now)


class EditPlan(Base):
    """剪辑方案表"""
    __tablename__ = "edit_plans"

    id = Column(Integer, primary_key=True)
    material_id = Column(Integer)
    plan_json = Column(JSON)               # 完整剪辑方案
    strategy_refs = Column(JSON)           # 引用的爆款策略ID
    quality_score = Column(Float)          # 方案质量评分
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=datetime.now)


# ========== Pydantic Schema（结构化输出） ==========

class HookAnalysis(BaseModel):
    """钩子分析 Schema"""
    hook_text: str
    hook_type: str           # 悬念/冲突/反转/利益
    effectiveness: float     # 预估效果 0-1
    timestamp: str           # 时间戳

class EmotionPoint(BaseModel):
    """情绪曲线数据点"""
    time: str
    intensity: float         # 情绪强度 0-1
    label: str               # 平静/紧张/高潮/释放

class FrameDesc(BaseModel):
    """帧级画面描述"""
    timestamp: str
    scene: str
    action: str
    visual_hook: str         # 视觉钩子

class BeatPoint(BaseModel):
    """音画卡点"""
    time: str
    type: str                # 音乐节拍/画面切换/文案出现/特效
    intensity: float
    description: str

class EditSegment(BaseModel):
    """剪辑片段 — 核心结构化输出"""
    segment_id: int
    start_time: str
    end_time: str
    duration: str
    scene_description: str
    camera_movement: str     # 运镜方式
    bgm_cue: str            # BGM 卡点说明
    text_overlay: str        # 字幕/文案
    transition: str          # 转场效果
    conversion_hook: str     # 转化引导话术
    emotion_target: str      # 目标情绪

class EditPlanSchema(BaseModel):
    """完整剪辑方案 JSON Schema — 强制结构化输出"""
    plan_id: str
    title: str
    target_duration: str
    category: str
    sub_category: str
    hook_analysis: HookAnalysis
    emotion_curve: list[EmotionPoint]
    segments: list[EditSegment]
    beat_points: list[BeatPoint]
    strategy_summary: str    # 策略摘要
    estimated_ctr: float
    estimated_retention: float
    created_at: str


# ========== 数据库连接 ==========

import os
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "app.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
