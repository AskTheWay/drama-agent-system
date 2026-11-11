# 短剧投流素材智能剪辑 Agent 系统

基于 **LangGraph** 的短剧投流素材智能剪辑方案生成系统（学习项目）：输入一条短剧素材（ASR 文本 + 抽帧画面），Agent 工作流自动完成「原视频深度理解 → 爆款策略检索（双模 RAG） → 质量检查与回溯 → 人工审核 → 剪辑方案生成」，输出结构化（JSON Schema 校验）的高转化剪辑脚本，并通过投流效果回传持续校准知识库权重（数据飞轮）。

> **零 Key 可跑**：所有外部依赖（LLM / Embedding / MLLM / Whisper / OpenCV）均有内置兜底数据，不配置任何 API Key 也能完整体验全部流程——前端「执行步骤」中会标注每一步用的是真实模型还是兜底演示数据。

## 📸 运行效果

### Agent 工作流 — 素材输入

预设 4 种题材模板（男频·逆袭 / 女频·复仇 / 男频·战神 / 女频·甜宠）一键填充，工作流 5 节点状态实时可视化，核心术语悬浮即有解释：

![工作流输入](docs/images/01-workflow-input.png)

### 工作流运行中

节点状态渐变推进；质量检查 < 70 分自动回溯重试（结果区会显示回溯横幅）：

![工作流运行中](docs/images/02-workflow-running.png)

### 运行结果 — 三节点完整输出

**节点1** 原视频深度理解（钩子分析 / 赛道判断 / SVG 情绪曲线 / 关键特征）→ **节点2** 爆款策略检索（素材卡片展示相似度，按综合得分排序 + 策略总结）→ **节点3** 剪辑方案（秒级时间轴片段 / 运镜 / BGM 卡点 / 预估 CTR / Schema 校验状态）。每步执行详情标注数据来源：

![工作流结果](docs/images/03-workflow-result.png)

### 人工审核暂停（Human-in-the-Loop）

开启人工介入模式后，工作流在审核节点暂停，展示质量评分与检索策略，支持**通过生成**或**打回重新检索**（打回意见会参与检索条件）：

![人工审核暂停](docs/images/04-human-review-paused.png)

审核通过后继续执行至方案生成：

![审核后结果](docs/images/05-workflow-after-review.png)

### 爆款知识库

6 条爆款素材知识卡片（钩子文案 / CTR / 3秒停留率 / 完播率 / 综合得分），支持语义搜索（回车触发、携带赛道筛选）：

![爆款知识库](docs/images/06-knowledge-base.png)

### 历史记录 + 数据飞轮

历史分析记录与剪辑方案；每条方案可填写投流效果得分**回传**（数据飞轮入口），对应素材权重立即更新：

![历史记录](docs/images/07-history.png)

### 系统架构

技术架构总览页：

![系统架构](docs/images/08-architecture.png)

## 📚 延伸文档与学习路径

`docs/` 下配套 7 份技术详解，建议按以下顺序配合源码阅读：

| 顺序 | 文档 | 学什么 | 配合源码 |
|-----|------|--------|---------|
| ① | [系统总结](docs/系统总结.md) | 系统全貌、设计取舍、模块关系 | 全部 |
| ② | [LangGraph 与 LangChain 详解](docs/LangGraph与LangChain详解.md) | StateGraph / 条件边 / 回溯 / HITL 的框架原理 | `agent_workflow.py` |
| ③ | [FAISS 详解](docs/FAISS详解.md) | 向量检索原理、索引类型选型、余弦相似度实现 | `vector_store.py` |
| ④ | [日志系统详解](docs/日志系统详解.md) | 结构化日志、数据流转留档设计 | `logger.py` |
| ⑤ | [Prometheus + Grafana 完整指南](docs/Prometheus+Grafana完整指南.md) | 指标埋点、监控栈搭建、provisioning 机制 | `metrics.py`, `docker-compose.yml` |
| ⑥ | [LangSmith 接入详解](docs/LangSmith接入详解.md) | LLM 链路可观测性 | `config.py` |
| ⑦ | [面试 QA](docs/INTERVIEW_QA.md) | 本项目相关的高频面试题与回答思路 | 全部 |

## ✨ 核心特性

- **Agent 工作流编排** — LangGraph StateGraph，6 节点 + 条件边路由；质量评分（100 分制）< 70 时**回溯重试**（最多 2 次）
- **Human-in-the-Loop** — `analyze_interrupt` / `resume` 接口实现人工审核暂停/恢复；打回时审核意见会**真正参与重新检索**
- **双模 RAG 检索** — 元数据预过滤（赛道硬规则）+ FAISS 余弦相似度向量检索（软匹配）两层召回
- **JSON Schema 结构化输出** — LLM 输出经 Pydantic `EditPlanSchema` **真实校验**，不合规自动降级兜底
- **数据飞轮** — 投流效果回传按加权移动平均更新素材 score，**同步检索元数据落盘**，下次检索立即生效
- **优雅降级** — Embedding 失败时索引以随机向量降级构建但**绝不持久化**，Key 恢复后重启自动重建真实索引
- **全链路可观测** — 结构化日志（flow.log 节点数据流转）+ Prometheus 指标 + Grafana 看板（provisioning 开箱即用）
- **学习友好前端** — 每步执行标注数据来源（真实 LLM / 兜底演示）、SVG 情绪曲线、回溯重试可视化横幅、术语悬浮解释

## 🚀 快速开始

```bash
cd drama_agent_system

# 1. 安装核心依赖
pip install langchain langchain-openai fastapi uvicorn faiss-cpu httpx sqlalchemy prometheus-client

# 2.（可选）配置 API Key — 不配置也能跑，所有外部依赖有兜底数据
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY / DASHSCOPE_API_KEY

# 3. 启动服务
python -m uvicorn main:app --host 0.0.0.0 --port 8080

# 4. 浏览器访问
# http://localhost:8080
```

可选监控栈（Prometheus + Grafana，数据源与看板自动 provisioning）：

```bash
docker-compose up -d
# Prometheus: http://localhost:9090（targets 应显示 UP）
# Grafana:    http://localhost:3000 (admin/admin)，看板已自动加载，无需手动 Import
```

重新生成 README 截图（需先启动服务）：

```bash
pip install playwright
python scripts/take_screenshots.py   # 优先用系统 Edge，否则回退 Playwright Chromium
```

## 📁 项目结构

```
drama_agent_system/
├── main.py                  # FastAPI 后端（API 路由 + 指标采集 + 全局异常处理）
├── agent_workflow.py        # LangGraph 工作流（6节点 + 回溯 + 人工审核暂停/恢复）
├── vector_store.py          # 双模 RAG 检索引擎（元数据预过滤 + FAISS + 飞轮同步）
├── video_processor.py       # 多模态视频处理（OpenCV抽帧 + Whisper ASR + Qwen-VL）
├── models.py                # SQLAlchemy 表结构 + Pydantic 输出 Schema
├── mock_data.py             # 种子数据（6条爆款素材知识库）
├── metrics.py               # Prometheus 指标定义
├── logger.py                # 结构化日志 + 数据流转留档（flow.log）
├── config.py                # 配置（.env 加载，支持引号/注释）
├── static/index.html        # 前端（Bootstrap 5，4 Tab 页，SVG 图表）
├── scripts/
│   └── take_screenshots.py  # README 截图脚本（Playwright）
├── docs/                    # 延伸技术文档（见上方学习路径）+ 运行截图
│   └── images/
├── data/                    # 运行时数据（SQLite + FAISS 索引 + 日志，gitignore）
├── grafana/provisioning/    # Grafana 数据源/看板自动加载配置
├── docker-compose.yml       # Prometheus + Grafana 监控栈
├── prometheus.yml           # Prometheus 抓取配置
├── grafana_dashboard.json   # Grafana 看板模板
├── .env.example             # 环境变量模板
└── README.md
```

---

## 一、系统概述

### 1.1 业务背景
短剧投流素材迭代极快，人工拆解效率低，爆款基因难以稳定复制。本系统基于 Agent Workflow 构建智能剪辑方案生成系统，替代传统单点长 Prompt 模式，自动生成高转化潜力的结构化剪辑脚本。

### 1.2 技术栈
| 技术 | 用途 |
|------|------|
| LangGraph | Agent 工作流编排（StateGraph + 条件边） |
| LangChain | LLM 调用、Prompt 模板、JSON 解析 |
| LLM（OpenAI 兼容接口） | 分析/检索总结/生成推理（默认 mimo-v2.5-pro，可换任意兼容服务） |
| Qwen-VL（阿里云百炼） | 多模态帧画面理解 |
| Whisper | ASR 语音转文字 |
| FAISS | 向量检索（IndexFlatIP + L2 归一化 = 余弦相似度） |
| 阿里云 Embedding | 文本向量化（text-embedding-v3, 1024 维） |
| SQLite | 结构化数据存储（生产可替换 PostgreSQL） |
| FastAPI | 后端 API 服务 |
| Prometheus + Grafana | 指标监控与可视化 |
| Pydantic | JSON Schema 结构化输出校验 |

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                       前端 (static/index.html)               │
│  Bootstrap 5 + 原生 JS，4 个 Tab 页                          │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP API
┌───────────────────────────▼──────────────────────────────────┐
│                    FastAPI 后端 (main.py)                     │
│  路由 + lifespan 初始化 + Prometheus 指标中间件 + 全局异常    │
└──────┬──────────────────┬───────────────────┬────────────────┘
       │                  │                   │
       ▼                  ▼                   ▼
┌─────────────┐  ┌─────────────────┐  ┌────────────────┐
│ agent_       │  │ vector_store.py │  │ video_         │
│ workflow.py  │  │ 双模 RAG 检索   │  │ processor.py   │
│              │  │                 │  │ 视频处理       │
│ 节点1: 分析  │  │ 元数据预过滤    │  │ 帧抽取+MLLM   │
│ 节点2: 检索  │  │ + FAISS 向量检索│  │ ASR 转写       │
│ 节点3: 生成  │  │ + 飞轮 score 同步│ │                │
└──────┬──────┘  └────────┬────────┘  └───────┬────────┘
       │                  │                   │
       ▼                  ▼                   ▼
┌──────────────────────────────────────────────────────────────┐
│                        数据层                                 │
│  SQLite (data/app.db)    FAISS 文件 (data/faiss_index.*)     │
│  - hot_references        - faiss_index.index (向量索引)       │
│  - material_analysis     - faiss_index.meta (元数据 JSON)     │
│  - edit_plans            - data/frames/ (抽取的帧图片)        │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、核心功能详解

### 3.1 Agent 工作流（agent_workflow.py）

采用 **LangGraph StateGraph** 构建工作流，包含 6 个节点，支持**回溯重试**和**人工介入**。

#### 工作流拓扑

```
analyze → retrieve → quality_check ──┬→ human_review → generate → END   （人工介入模式）
                          │          │
                          │ <70分    │ 质量达标（自动模式直达生成）
                          ▼          └→ generate → END                  （自动模式）
                    retry_increment ──→ retrieve（回溯）
```

#### 状态定义（WorkflowState）

```python
class WorkflowState(TypedDict):
    # 输入
    asr_text: str
    filename: str
    frame_descriptions: list
    # 三节点输出
    analysis: dict             # 节点1：分析结果
    strategy: dict             # 节点2：检索结果
    plan: dict                 # 节点3：剪辑方案
    plan_score: float          # 方案质量分（与检查分分离）
    # 质量控制
    quality_score: float       # 质量检查评分
    retry_count: int           # 回溯重试次数
    max_retries: int           # 最大重试次数（默认2）
    # 人工介入
    human_feedback: str        # 人工反馈意见（打回时参与重新检索）
    human_approved: bool       # 人工是否通过（自动模式初始化为 True）
    need_human_review: bool    # 是否需要人工审核
    # 流程控制
    current_node: str
    status: str                # pending / running / paused / completed / failed
    steps: list                # 执行留档（每步输入输出摘要 + llm_mode 标注）
```

#### 节点说明

| 节点 | 函数 | 说明 |
|------|------|------|
| analyze | `node_analyze()` | 原视频深度理解（多模态分析） |
| retrieve | `node_retrieve()` | 爆款策略检索（双模 RAG，人工反馈参与查询） |
| quality_check | `node_quality_check()` | 质量评分，<70分触发回溯 |
| retry_increment | `node_retry_increment()` | 回溯重试计数（留痕到 steps） |
| human_review | `node_human_review()` | 人工审核暂停点（仅介入模式经过） |
| generate | `node_generate()` | 剪辑方案生成（EditPlanSchema 校验） |

#### 质量检查与回溯

**100 分制纯扣分**：零问题 = 100 分直接通过，不回溯。扣分规则：

| 检查项 | 扣分 |
|--------|------|
| 钩子效果预估 < 0.5 | -15 |
| 赛道未判断 | -20 |
| 关键特征不足 3 个 | -10 |
| 无匹配策略 | -20 |
| 策略总结为空 | -10 |

路由规则（`_route_after_quality_check`，条件边回调 `route_after_quality` 使用同一逻辑）：
- 得分 < 70 且重试次数 < 2 → 回溯到 retrieve 节点重新检索（重试时若有人工反馈，反馈会拼入检索查询）
- 达标或重试耗尽 → **自动模式**（`human_approved=True` 初始化）直达 generate 跳过审核；**人工介入模式**进入 human_review 暂停等待

#### 人工介入

系统提供两种运行模式：
1. **自动模式** (`run_workflow`): `human_approved=True` 初始化，质量达标后跳过人工审核直达生成
2. **人工介入模式** (`run_workflow_with_interrupt`): 在 human_review 节点暂停，返回中间状态

```python
# 自动模式
result = run_workflow(asr_text, filename)

# 人工介入模式
paused = run_workflow_with_interrupt(asr_text, filename)
# 用户审核后恢复：通过 or 打回（打回意见参与重新检索）
result = resume_workflow(paused["state"], approved=True, feedback="钩子需要更强")
```

> 实现说明：暂停/恢复**不是** LangGraph 原生 `interrupt()`/checkpointer 机制——`run_workflow_with_interrupt` 用 `app.stream()` 逐步迭代，检测到 human_review 节点输出 `status=="paused"` 后提前返回（丢弃 stream 生成器）实现暂停；`resume_workflow` 则从暂停状态直接顺序调用后续节点（通过 → `node_generate`；打回 → `node_retrieve` → `node_quality_check` → `node_generate`），避免重新执行 analyze。改为原生 interrupt/checkpointer 可作为进阶练习。

LangGraph 的条件边实现：
```python
# quality_check 后的路由（三种去向）
graph.add_conditional_edges("quality_check", route_after_quality, {
    "retrieve": "retry_increment",    # 回溯
    "human_review": "human_review",   # 介入模式进入审核
    "generate": "generate",           # 自动模式直达生成
})

# human_review 后的路由
graph.add_conditional_edges("human_review", route_after_human, {
    "generate": "generate",   # 通过→生成
    "retrieve": "retrieve",   # 打回→重新检索
})
```

#### 节点1：原视频深度理解 — `node_analyze()`

**输入**: ASR 文本 + 帧级画面描述（无帧描述时使用内置默认帧）
**输出**: 结构化分析结果（钩子分析、情绪曲线、赛道判断、关键特征）

```python
# 核心 Prompt（ChatPromptTemplate）
ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是一位资深短剧投流素材分析师。深度理解素材，提取关键特征。返回 JSON：..."),
    ("user", "素材：{filename}\nASR：{asr_text}\n帧描述：{frame_descriptions}"),
])

# 执行链（LCEL）：失败自动降级 _mock_analysis()，并在 steps 标注 llm_mode
chain = ANALYSIS_PROMPT | llm | JsonOutputParser()
```

**提取维度**:
| 维度 | 字段 | 说明 |
|------|------|------|
| 钩子分析 | hook_analysis | 文案、类型(悬念/冲突/反转/利益)、效果预估 |
| 情绪曲线 | emotion_curve | 多时间点的情绪强度(0-1)和标签 |
| 赛道判断 | category, sub_category | 男频/女频 + 逆袭/甜宠/复仇/战神/穿越 |
| 关键特征 | key_features | 至少 5 个特征标签 |
| 帧级描述 | frame_descriptions | 时间戳、场景、动作、视觉钩子 |
| 音画卡点 | beat_points | 时间、类型、强度、描述 |

**兜底机制**: LLM 调用失败时调用 `_mock_analysis()` 返回预设演示数据；分析结果存入 SQLite `material_analysis` 表。

---

#### 节点2：爆款策略检索 — `node_retrieve()`

**输入**: 节点1 的分析结果（+ 打回时的人工反馈）
**输出**: 匹配的爆款策略 + 策略总结

**检索流程**:

```
Step 1: 构造查询
  → hook_text + key_features 前3个
  → 有人工反馈时追加 "人工反馈：..."（让打回后的重试检索输入不同）

Step 2: 元数据预过滤（硬规则）
  → 按 category + sub_category 过滤候选集
  → 候选集为空时回退全量（记录 warning）

Step 3: 语义向量检索（软匹配）
  → 阿里云 Embedding API → 1024 维向量
  → FAISS IndexFlatIP 余弦相似度搜索
  → 候选集 ≤ top_k 时逐点内积，否则 IDSelectorArray 参数化检索

Step 4: 综合排序
  → 按 score 降序（score 由数据飞轮动态更新）
```

**双模检索核心代码**（与源码一致）:
```python
def search(self, query, category=None, sub_category=None, top_k=3):
    candidates = self._filter_candidates(category, sub_category)  # Step 2
    query_vec = np.array([self._get_embedding(query)], dtype="float32")
    faiss.normalize_L2(query_vec)

    if len(candidates) <= top_k:
        results = self._search_small(query_vec, candidates)   # 逐点内积
    else:
        results = self._search_faiss(query_vec, candidates, top_k)  # IDSelector 过滤检索

    results.sort(key=lambda x: x.get("score", 0), reverse=True)  # Step 4 飞轮排序
    return results[:top_k]

def _search_faiss(self, query_vec, candidates, top_k):
    selector = faiss.IDSelectorArray(candidates)
    params = faiss.SearchParameters()
    params.sel = selector
    scores, indices = self.index.search(query_vec, min(top_k * 2, len(candidates)), params=params)
    ...
```

**LLM 策略总结**: 检索完成后用 LLM 对匹配素材做策略总结（`RETRIEVAL_PROMPT` 含 `{human_feedback}` 变量，人工反馈也参与总结），失败时 `_mock_retrieval()` 兜底。

---

#### 节点3：剪辑方案生成 — `node_generate()`

**输入**: 节点1 分析结果 + 节点2 策略结果（+ 人工反馈提示）
**输出**: 完整结构化剪辑方案（EditPlanSchema 校验）

**结构化输出校验**: LLM 输出经 Pydantic 真实校验，不合规自动降级：
```python
result = chain.invoke({...})                     # LLM 输出
try:
    EditPlanSchema.model_validate(result)        # Pydantic 校验
    result["schema_validated"] = True            # 前端展示「Schema 校验通过」
except ValidationError:
    result = _mock_plan(analysis, strategy)      # 不合规 → 降级演示数据
```

**EditPlanSchema（models.py，Pydantic）**:
```python
class EditPlanSchema(BaseModel):
    plan_id: str
    title: str
    target_duration: str
    category: str
    sub_category: str
    hook_analysis: HookAnalysis          # 钩子分析
    emotion_curve: list[EmotionPoint]    # 情绪曲线
    segments: list[EditSegment]          # 剪辑片段列表
    beat_points: list[BeatPoint]         # 音画卡点
    strategy_summary: str                # 策略摘要
    estimated_ctr: float                 # 预估点击率
    estimated_retention: float           # 预估停留率
    created_at: str
```

**剪辑片段 Schema (EditSegment)**: `segment_id / start_time / end_time / duration / scene_description / camera_movement / bgm_cue / text_overlay / transition / conversion_hook / emotion_target` —— 精确到秒级时间轴、运镜、BGM 卡点、转化话术。

**方案评分**: `_calc_quality()` 计算 `plan_score`（方案质量分），与 `quality_score`（质量检查分）分离；方案存入 SQLite `edit_plans` 表（status: `auto` / `human_approved`）。

---

#### 工作流编排 — `run_workflow()`

真实实现（StateGraph 驱动，与源码一致）：

```python
def run_workflow(asr_text, filename, frame_descriptions=None, video_path=None):
    # 前置: 传了 video_path 则走多模态处理（抽帧 + ASR + MLLM 帧理解）
    if video_path and os.path.exists(video_path):
        video_result = process_video(video_path, asr_text)
        asr_text = video_result["asr_text"]
        frame_descriptions = video_result["frame_descriptions"]

    initial_state: WorkflowState = {
        "asr_text": asr_text, "filename": filename,
        "frame_descriptions": frame_descriptions or [],
        "analysis": {}, "strategy": {}, "plan": {},
        "plan_score": 0, "quality_score": 0,
        "retry_count": 0, "max_retries": 2,
        "human_feedback": "",
        "human_approved": True,        # 自动模式：质量达标后跳过人工审核
        "need_human_review": False,
        "current_node": "", "status": "running", "steps": [],
    }

    app = get_app()                     # graph.compile() 的全局缓存实例
    final_state = app.invoke(initial_state)   # LangGraph 驱动整张图
    return {"analysis": ..., "strategy": ..., "plan": ...,
            "quality_score": ..., "plan_score": ..., "steps": ...}
```

---

### 3.2 多模态视频处理（video_processor.py）

> 该链路当前通过 `POST /api/analyze` 的可选 `video_path` 字段（服务器本地路径，学习演示用）或直接调用 `run_workflow(video_path=...)` 触发。

#### 3.2.1 帧抽取 — `extract_frames()`

| 功能 | 实现 | 依赖 |
|------|------|------|
| 视频读取 | OpenCV `cv2.VideoCapture` | opencv-python |
| 抽帧策略 | 每秒 1 帧，最多 30 帧（fps 缺失时兜底为 1，避免死循环） | — |
| 输出格式 | JPG 文件 + Base64 编码 | — |
| 兜底 | opencv 未安装时返回 6 个模拟帧 | — |

#### 3.2.2 ASR 语音转写 — `transcribe_audio()`

| 功能 | 实现 | 依赖 |
|------|------|------|
| 语音识别 | OpenAI Whisper `base` 模型（全局缓存，避免重复加载） | openai-whisper |
| 语言 | 中文 | — |
| 兜底 | whisper 未安装时返回模拟文本 | — |

#### 3.2.3 MLLM 多模态理解 — `analyze_frame_with_mllm()`

| 功能 | 实现 | 依赖 |
|------|------|------|
| 模型 | 阿里云百炼 Qwen-VL-Plus | DashScope API |
| 输入 | 帧图片 Base64 + 分析 Prompt | — |
| 输出 | 场景/动作/视觉钩子/情绪/构图/色调（6 维度） | — |
| 兜底 | API 调用失败时返回模拟帧描述 | — |

---

### 3.3 双模 RAG 检索引擎（vector_store.py）

#### 3.3.1 向量化

| 项目 | 说明 |
|------|------|
| 模型 | 阿里云百炼 text-embedding-v3 |
| 维度 | 1024 |
| 向量化文本 | `title + hook_text + asr_text + tags` 拼接 |
| 兜底 | API 失败时生成随机向量（`degraded=True`），**索引不持久化** |

#### 3.3.2 索引构建与降级保护

```python
# FAISS 索引类型: IndexFlatIP（内积）+ L2 归一化 = 余弦相似度
vectors_np = np.array(vectors, dtype="float32")
faiss.normalize_L2(vectors_np)
self.index = faiss.IndexFlatIP(1024)
self.index.add(vectors_np)

if self.degraded:
    # 随机向量的索引毫无意义，绝不持久化——
    # 否则磁盘留下「永久噪声索引」，Key 恢复后也无法自愈
    logger.error("索引以随机向量降级构建，本次不持久化...")
else:
    faiss.write_index(self.index, f"{INDEX_PATH}.index")
```

| 项目 | 说明 |
|------|------|
| 索引类型 | FAISS IndexFlatIP（暴力搜索，精确） |
| 相似度 | 余弦相似度（L2 归一化 + 内积） |
| 持久化 | 仅在全部向量真实生成时落盘（.index + .meta） |
| 加载 | 启动时文件存在则加载，否则从 DB 重建（Key 恢复后自动重建真实索引） |
| 元数据 | 与向量对齐的 JSON 数组，单独存储（含 DB 主键 id） |

#### 3.3.3 FAISS vs 向量数据库

| 对比项 | FAISS | 向量数据库 (Milvus/Pinecone/Qdrant) |
|--------|-------|-----------------------------------|
| 本质 | 向量检索算法库 | 专用数据库 |
| 部署 | 嵌入式，import 即用 | 独立服务，需要部署 |
| 数据管理 | 手动管理文件 | CRUD、索引、分片、副本 |
| 查询能力 | 仅向量检索（+IDSelector 过滤） | 向量+标量混合查询 |
| 扩展性 | 单机，百万级 | 分布式，十亿级 |
| 适用场景 | Demo/小规模/嵌入式 | 生产环境大规模部署 |

本系统用 FAISS 是因为 demo 场景数据量小（6条），不需要独立部署。生产环境应替换为 Milvus/Qdrant 等。详见 [FAISS详解](docs/FAISS详解.md)。

#### 3.3.4 双模检索流程

```
查询输入（hook_text + key_features [+ 人工反馈]）
    │
    ▼
┌──────────────────────────────┐
│ 第一层：元数据预过滤（硬规则） │
│ - category (男频/女频)        │
│ - sub_category (逆袭/甜宠...) │
│ → 候选集缩小（空则回退全量+警告）│
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 第二层：语义向量检索（软匹配） │
│ - 查询文本 → Embedding        │
│ - FAISS 余弦相似度            │
│ → top_k 结果                 │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 排序：按 score 降序           │
│ score 由数据飞轮动态同步       │
└──────────────────────────────┘
```

---

### 3.4 数据库设计（models.py）

#### 表结构

**hot_references — 爆款素材知识库**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| title | String | 素材标题 |
| category | String | 主赛道：男频/女频 |
| sub_category | String | 二级题材：逆袭/甜宠/复仇/战神/穿越 |
| hook_text | Text | 黄金3秒钩子文案 |
| hook_type | String | 钩子类型：悬念/冲突/反转/利益 |
| emotion_curve | JSON | 情绪曲线数据点列表 |
| beat_points | JSON | 音画卡点时间列表 |
| ctr | Float | 点击率 |
| retention_3s | Float | 3秒停留率 |
| completion_rate | Float | 完播率 |
| score | Float | 综合得分（数据飞轮权重） |
| tags | JSON | 标签列表 |
| asr_text | Text | ASR 转写文本 |
| frame_descriptions | JSON | 帧级画面描述列表 |
| created_at | DateTime | 创建时间 |

**material_analysis — 素材分析结果**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| filename | String | 文件名 |
| asr_text | Text | ASR 文本 |
| frame_descriptions | JSON | 帧描述 |
| hook_analysis | JSON | 钩子分析结果 |
| emotion_curve | JSON | 情绪曲线 |
| category / sub_category | String | 赛道判断 |
| key_features | JSON | 关键特征列表 |
| created_at | DateTime | 创建时间 |

**edit_plans — 剪辑方案**
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| material_id | Integer FK | 关联分析记录 |
| plan_json | JSON | 完整剪辑方案 |
| strategy_refs | JSON | 引用的爆款策略 ID 列表 |
| quality_score | Float | 方案质量评分（plan_score） |
| status | String | 状态：auto（自动生成）/ human_approved（人工审核通过）/ human_rejected（人工打回后按反馈重生成） |
| created_at | DateTime | 创建时间 |

---

### 3.5 数据飞轮（main.py `/api/feedback`）

闭环真正生效——更新 DB 后**同步检索元数据并落盘**：

```
投流效果数据回传（前端「历史记录」页每条方案旁的回传控件）
    │
    ▼
POST /api/feedback  { plan_id: 1, score: 85.0 }   （plan 不存在返回 404，score 校验 0-100）
    │
    ▼
找到 plan 引用的 strategy_refs → 更新 SQLite score
score = score * 0.8 + new_score * 0.2  (加权移动平均)
    │
    ▼
VectorStore.update_scores()：同步内存元数据 + 重写 .meta 落盘
    │
    ▼
下次检索排序（按 score 降序）立即使用新分数 → 高分策略优先被召回
```

---

### 3.6 前端（static/index.html）

#### 页面结构

| Tab | 功能 | 说明 |
|-----|------|------|
| Agent 工作流 | 素材输入 + 工作流执行 + 结果展示 | 核心功能页 |
| 爆款知识库 | 浏览/搜索爆款素材 | 语义搜索（回车触发、携带赛道筛选、可清除） |
| 历史记录 | 查看历史分析和方案 + 效果回传 | 数据飞轮入口 |
| 系统架构 | 技术架构图 | ASCII 架构图展示 |

#### 学习导向设计

- **执行步骤面板**：每步展示输入/输出摘要 + **数据来源徽章**（真实 LLM / 兜底演示数据）+ 耗时
- **回溯可视化**：出现回溯重试时流程图下方显示橙色横幅（重试次数 + 原因）
- **术语 tooltip**：RAG / 人工介入 / 回溯机制等术语悬浮即有解释
- **SVG 情绪曲线**：面积图 + 数据点 + 悬浮详情（节点1 与方案两处）
- **统一错误处理**：所有请求经 `apiFetch()` 封装（网络错误 / HTTP 状态 / 业务错误 toast 提示）
- **HTML 转义**：所有后端文本注入前经 `esc()` 转义

#### 技术实现

- 前端框架: Bootstrap 5 + 原生 JavaScript（无构建步骤）
- API 调用: Fetch API（统一 `apiFetch` 封装）
- 统计数据: `/api/stats` 单接口返回真实总数（不受列表 limit 截断）

---

## 四、API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/references?category=男频` | 获取爆款素材列表（可按赛道筛选） |
| GET | `/api/stats` | 全局统计（素材/分析/方案总数 + 平均分） |
| POST | `/api/analyze` | 运行完整 Agent 工作流（自动模式；可选 `video_path` 触发多模态链路） |
| POST | `/api/analyze_interrupt` | 运行到人工审核点后暂停 |
| POST | `/api/resume` | 人工审核后恢复工作流（打回意见参与重新检索） |
| GET | `/api/analyses` | 获取历史分析记录（最近 20 条） |
| GET | `/api/plans` | 获取历史剪辑方案（最近 20 条） |
| POST | `/api/search?query=xxx&category=男频&sub_category=逆袭` | 语义向量检索爆款策略 |
| POST | `/api/feedback` | 投流效果回传（数据飞轮；404/422 校验） |
| GET | `/metrics` | Prometheus 指标端点 |

错误处理：全局异常处理器统一返回 JSON（`{"detail": "..."}`），前端 toast 展示。

---

## 五、依赖与兜底

| 依赖 | 用途 | 必需？ | 未安装/失败时 |
|------|------|--------|---------|
| langchain + langchain-openai | Agent 编排 + LLM 调用 | 是 | — |
| fastapi + uvicorn | Web 服务 | 是 | — |
| faiss-cpu | 向量检索 | 是 | — |
| httpx | API 调用 | 是 | — |
| sqlalchemy | ORM | 是 | — |
| prometheus-client | 指标采集 | 是 | — |
| LLM API（OpenAI 兼容） | 分析/总结/生成 | 否 | 各节点 `_mock_*()` 兜底数据 |
| 阿里云 Embedding API | 文本向量化 | 否 | 随机向量降级构建（索引不持久化） |
| 阿里云 Qwen-VL API | 帧画面理解 | 否 | `_mock_frame_desc()` |
| opencv-python | 帧抽取 | 否 | `_mock_frames()` |
| openai-whisper | ASR 转写 | 否 | `_mock_asr()` |

---

## 六、学习要点对照

每个核心机制对应的学习入口（面试/复习速查）：

| 概念 | 系统实现 | 入口文件 |
|---------|---------|------|
| LangGraph Agent 工作流 | StateGraph 6 节点 + 条件边三向路由 | agent_workflow.py |
| 人工介入 (Human-in-the-Loop) | human_review 节点 + interrupt/resume API | agent_workflow.py, main.py |
| 回溯重生成 (Backtracking) | quality_check < 70 → retry_increment → retrieve | agent_workflow.py |
| 多模态非结构化数据处理 | 帧级画面 + ASR + 6 维度帧理解 | video_processor.py |
| 元数据预过滤 + 语义向量检索 | 双模 RAG：category 过滤 + FAISS 检索 | vector_store.py |
| JSON Schema 结构化输出 | EditPlanSchema + Pydantic 真实校验 | models.py, agent_workflow.py |
| 数据飞轮 | /api/feedback → 加权更新 score → 同步检索元数据 | main.py, vector_store.py |
| 帧级画面抽取与理解 | OpenCV 抽帧 + Qwen-VL 分析 | video_processor.py |
| 黄金3秒钩子提取 | hook_analysis 字段 | agent_workflow.py |
| 情绪曲线 | emotion_curve 字段 + SVG 可视化 | models.py, static/index.html |
| 音画卡点规则 | beat_points 字段 | models.py |
| 可观测性 | 结构化日志 + Prometheus + Grafana provisioning | logger.py, metrics.py, grafana/ |
| 优雅降级设计 | 全链路 mock 兜底 + 降级索引不持久化 | 各模块 |
