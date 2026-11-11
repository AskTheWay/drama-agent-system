# LangGraph 与 LangChain 详解 — 本项目实践

## 一、核心区别

```
LangChain = 节点内部怎么调 LLM、怎么解析结果
LangGraph = 节点之间怎么传状态、怎么路由、怎么回溯
```

两者是**互补关系**，不是替代关系：

```
┌─────────────────────────────────────────────────────────┐
│                    LangGraph (编排层)                    │
│                                                         │
│  StateGraph + TypedDict + 条件路由 + 回溯 + 人工介入     │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ analyze  │→ │ retrieve │→ │ quality  │→ │generate │ │
│  │          │  │          │  │  check   │  │         │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
│       │             │             │              │      │
└───────┼─────────────┼─────────────┼──────────────┼──────┘
        │             │             │              │
        ▼             ▼             ▼              ▼
┌─────────────────────────────────────────────────────────┐
│                   LangChain (执行层)                     │
│                                                         │
│  ChatOpenAI + PromptTemplate + JsonOutputParser         │
│                                                         │
│  每个节点内部：构造 prompt → 调 LLM → 解析 JSON 输出     │
└─────────────────────────────────────────────────────────┘
```

---

## 二、TypedDict 在本项目中的作用

### 2.1 定义状态结构

```python
# agent_workflow.py — class WorkflowState
class WorkflowState(TypedDict):
    # 输入
    asr_text: str                    # ASR 转写文本
    filename: str                    # 文件名
    frame_descriptions: list         # 帧描述列表

    # 节点输出
    analysis: dict                   # 节点1 输出：视频分析
    strategy: dict                   # 节点2 输出：策略检索
    plan: dict                       # 节点3 输出：剪辑方案
    plan_score: float                # 方案质量分（_calc_quality 计算，与 quality_score 分离）

    # 质量控制
    quality_score: float             # 质量检查分（100 分制纯扣分）
    retry_count: int                 # 回溯重试次数
    max_retries: int                 # 最大重试次数

    # 人工介入
    human_feedback: str              # 人工反馈
    human_approved: bool             # 是否通过（自动模式初始化即 True）
    need_human_review: bool          # 是否需要人工审核

    # 流程控制
    current_node: str                # 当前节点
    status: str                      # 运行状态

    # 执行日志
    steps: list                      # 步骤详情（含每步 llm_mode 留痕）
```

### 2.2 TypedDict 的意义

```python
# 普通 dict — 没有类型约束，key 可以随意写
state = {"asr_text": "xxx", "typo_key": 123}  # 不报错

# TypedDict — 运行时行为完全相同，写错 key 照样不抛异常；
# 区别在于 mypy / pyright 等静态类型检查器（以及 IDE）能识别这个声明，
# 在「静态检查阶段」发现 key 拼写错误和类型不匹配
state: WorkflowState = {"asr_text": "xxx", "typo_key": 123}  # 静态检查器报类型警告
```

> **概念辨析**：Python 是动态类型语言，**没有「编译时类型检查」**这一环节。TypedDict 只是一个
> 结构声明（对人和静态检查器可见的"文档"），运行时不做任何校验。LangGraph 拿它也只是用来
> 声明 state 的结构，并不会在运行时校验字段。如果需要**运行时**强校验，要用 Pydantic——
> 例如本项目 `node_generate` 中用 `EditPlanSchema.model_validate()` 校验 LLM 输出，失败即降级 mock。

**对 LangGraph 的意义：**
- `StateGraph(WorkflowState)` 告诉 LangGraph 状态的完整结构
- 每个节点 return 时，LangGraph 自动 merge 到全局状态
- 节点之间通过 state 字段名传递数据；字段名是否写对由静态检查器把关，TypedDict 本身只是「结构声明 + 类型提示」

### 2.3 节点如何读写状态

```python
# 节点函数签名接收整个 state
def node_analyze(state: WorkflowState) -> WorkflowState:
    # 读取：从 state 中取需要的字段
    asr_text = state["asr_text"]
    filename = state["filename"]

    # 执行：调 LLM
    result = chain.invoke({...})

    # 写入：return 时只写变化的字段，LangGraph 自动 merge
    return {
        **state,           # 保留所有原字段
        "analysis": result, # 写入新字段
        "steps": steps,    # 更新步骤
    }
```

**merge 机制：**
```
节点输入 state:  {asr_text: "xxx", analysis: {}, strategy: {}, steps: []}
节点返回:        {**state, analysis: {hook: "...", category: "男频"}, steps: [step1]}
merge 后 state:  {asr_text: "xxx", analysis: {hook: "...", category: "男频"}, strategy: {}, steps: [step1]}
```

---

## 三、LangChain 在本项目中的使用

### 3.1 LCEL 管道（LangChain Expression Language）

```python
# agent_workflow.py — node_analyze 内部
chain = ANALYSIS_PROMPT | llm | JsonOutputParser()

# 等价于：
# 1. ANALYSIS_PROMPT.format(...)  → 构造消息列表
# 2. llm.invoke(messages)         → 调用 LLM API
# 3. JsonOutputParser().parse()   → 从 LLM 输出中提取 JSON
```

### 3.2 三个组件

```python
# 1. PromptTemplate — 模板化 prompt
ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是一位资深短剧投流素材分析师...返回 JSON..."),
    ("user", "素材：{filename}\nASR：{asr_text}\n帧描述：{frame_descriptions}"),
])

# 2. ChatOpenAI — LLM 调用（OpenAI 兼容接口），实际代码见 agent_workflow.py — get_llm()
llm = ChatOpenAI(
    base_url=config.LLM_BASE_URL,   # 默认 https://token-plan-cn.xiaomimimo.com/v1
    model=config.LLM_MODEL,         # 默认 mimo-v2.5-pro（.env / 环境变量可覆盖）
    api_key=config.LLM_API_KEY,
    extra_body={"thinking": {"type": "disabled"}},
    temperature=0.7,
)

# 3. JsonOutputParser — 从 LLM 输出中提取 JSON
parser = JsonOutputParser()
# LLM 输出: "```json\n{\"category\": \"男频\"}\n```"
# 解析后:   {"category": "男频"}
```

### 3.3 调用流程

```python
result = chain.invoke({
    "filename": "test.mp4",
    "asr_text": "三年赘婿被人看不起...",
    "frame_descriptions": "[{...}]",
})

# 内部流程：
# 1. PromptTemplate 填充变量 → 完整 prompt 文本
# 2. ChatOpenAI 发送 HTTP 请求 → LLM API 返回文本
# 3. JsonOutputParser 正则提取 → Python dict
```

---

## 四、LangGraph 的核心能力

### 4.1 条件路由

```python
# 质量检查后的路由（agent_workflow.py — route_after_quality，核心决策在 _route_after_quality_check）
def route_after_quality(state: WorkflowState) -> str:
    score = state.get("quality_score", 0)
    retry = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)
    auto_mode = state.get("human_approved", False)  # 自动模式初始化时即为 True

    if score < 70 and retry < max_retries:
        return "retrieve"          # 不达标且重试未耗尽 → 回溯重试
    return "generate" if auto_mode else "human_review"
    # 自动模式（run_workflow）：达标或重试耗尽 → 直达 generate，跳过人工审核
    # 人工介入模式（run_workflow_with_interrupt）：进入 human_review 暂停等待

# 注册条件边（agent_workflow.py — build_graph）
graph.add_conditional_edges("quality_check", route_after_quality, {
    "retrieve": "retry_increment",
    "human_review": "human_review",
    "generate": "generate",
})
```

### 4.2 回溯循环

```python
# 图结构：quality_check → retry_increment → retrieve → quality_check → ...
graph.add_edge("retry_increment", "retrieve")  # 回溯边
graph.add_conditional_edges("quality_check", route_after_quality, {
    "retrieve": "retry_increment",  # 不达标且未耗尽重试 → 回溯
    "human_review": "human_review", # 达标/耗尽重试且人工介入模式 → 人工审核
    "generate": "generate",         # 达标/耗尽重试且自动模式 → 直达生成
})
```

### 4.3 人工介入（Human-in-the-Loop）

```python
# 暂停：human_review 节点设置 status="paused"（agent_workflow.py — node_human_review）
def node_human_review(state):
    return {**state, "status": "paused", "need_human_review": True}

# 暂停的触发（agent_workflow.py — run_workflow_with_interrupt）：
# 用 app.stream() 逐节点迭代，检测到 human_review 输出 status=="paused" 后提前 return
for event in app.stream(initial_state):
    for node, output in event.items():
        if node == "human_review" and output.get("status") == "paused":
            return {"status": "paused", "state": output, ...}  # 丢弃 stream 生成器，提前返回

# 恢复：外部注入 human_approved 和 human_feedback（agent_workflow.py — resume_workflow）
def resume_workflow(state, approved, feedback=""):
    state["human_approved"] = approved
    state["human_feedback"] = feedback
    if approved:
        result = node_generate(state)      # 通过 → 直接生成
    else:
        # 打回 → 完整 4 步链路（不是只调 node_retrieve 一步）
        state["retry_count"] += 1          # 1. 重试计数 +1
        state = node_retrieve(state)       # 2. 人工反馈拼入检索 query，重新检索
        state = node_quality_check(state)  # 3. 重新质量检查
        result = node_generate(state)      # 4. 重新生成方案
    return result
```

> **与 LangGraph 原生机制的差异**：LangGraph 框架本身提供 `interrupt()` 函数 + checkpointer（检查点）
> 的原生人工介入机制，可以在图执行中途冻结状态、之后从检查点恢复。本项目出于学习目的用了更朴素的
> 实现：`run_workflow_with_interrupt` 用 `app.stream()` 迭代、检测到 human_review 节点输出
> `status=="paused"` 后提前返回（丢弃 stream 生成器）实现"伪暂停"；`resume_workflow` 则是**手工调用**
> 后续节点继续执行，并不重新运行整个图。代码中已加注释说明这一点。
> 原生 `interrupt()` / checkpointer 可作为进一步学习方向。

---

## 五、对比总结

| 维度 | LangChain | LangGraph |
|------|-----------|-----------|
| **定位** | LLM 调用工具库 | Agent 编排框架 |
| **核心对象** | ChatOpenAI, PromptTemplate | StateGraph, TypedDict |
| **状态管理** | 无（每次调用独立） | TypedDict 全局状态，自动 merge |
| **流程控制** | 线性 Chain | 条件路由、循环、回溯 |
| **人工介入** | 无原生支持 | interrupt()/checkpointer 原生支持 |
| **代码位置** | 节点函数内部 | 节点之间的编排 |
| **类比** | 函数调用 | 状态机/工作流引擎 |

> 注：上表「人工介入」一行对比的是**框架能力**（LangGraph 确实原生支持 interrupt()/checkpointer）。
> 本项目并未使用原生机制，而是用 stream 迭代 + 提前返回 + 手工 resume 实现的"伪暂停"，详见 §4.3。

**本项目的分工：**
- LangChain 负责每个节点内部的 "怎么问 LLM、怎么解析答案"
- LangGraph 负责节点之间的 "下一步走哪、出错怎么回溯、何时等人"

---

## 六、数据流全景图

```
用户输入 ASR 文本
       │
       ▼
┌─ LangGraph: StateGraph 初始化 ──────────────────────────────┐
│  initial_state = {                                          │
│    "asr_text": "...", "filename": "...",                    │
│    "analysis": {}, "strategy": {}, "plan": {},              │
│    "plan_score": 0, "retry_count": 0, "steps": [],          │
│    "human_approved": True(自动) / False(介入)               │
│  }                                                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
       ┌───────────────────▼───────────────────┐
       │  node_analyze (LangChain 执行)        │
       │  chain = prompt | llm | JsonParser    │
       │  result = chain.invoke(...)           │
       │                                       │
       │  输出 → state["analysis"] = result    │
       └───────────────────┬───────────────────┘
                           │
       ┌───────────────────▼───────────────────┐
       │  node_retrieve (LangChain + FAISS)    │
       │  vector_store.search(...) → 检索      │
       │  chain.invoke(...) → 策略生成         │
       │                                       │
       │  输出 → state["strategy"] = result    │
       └───────────────────┬───────────────────┘
                           │
       ┌───────────────────▼───────────────────┐
       │  node_quality_check (纯 Python)       │
       │  100 分制纯扣分（零问题 = 100 分）    │
       │                                       │
       │  输出 → state["quality_score"] = 45   │
       │  （45 为演示值：扣了钩子/赛道等项）   │
       └───────────────────┬───────────────────┘
                           │
       ┌───────────────────▼───────────────────┐
       │  route_after_quality (LangGraph 路由) │
       │  score=45 < 70 → return "retrieve"   │
       │  retry_count=0 < 2 → 回溯            │
       └───────────────────┬───────────────────┘
                           │
       ┌───────────────────▼───────────────────┐
       │  retry_increment → retrieve (回溯)    │
       │  重新检索，覆盖 state["strategy"]     │
       └───────────────────┬───────────────────┘
                           │
                          ... (循环直到 score>=70 或 retry>=2)
                           │
       ┌───────────────────▼───────────────────┐
       │  node_human_review (仅人工介入模式)   │
       │  state["status"] = "paused"           │
       │  自动模式跳过此节点直达 generate      │
       │  介入模式等待 /api/resume 注入决策    │
       └───────────────────┬───────────────────┘
                           │
       ┌───────────────────▼───────────────────┐
       │  node_generate (LangChain 执行)       │
       │  chain = prompt | llm | JsonParser    │
       │  EditPlanSchema 校验失败 → 降级 mock  │
       │                                       │
       │  输出 → state["plan"] = result        │
       │  同时写入 plan_score 并落库 DB        │
       └───────────────────┬───────────────────┘
                           │
                           ▼
                        END
```
