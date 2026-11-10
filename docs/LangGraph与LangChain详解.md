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
# agent_workflow.py:73-95
class WorkflowState(TypedDict):
    # 输入
    asr_text: str                    # ASR 转写文本
    filename: str                    # 文件名
    frame_descriptions: list         # 帧描述列表

    # 节点输出
    analysis: dict                   # 节点1 输出：视频分析
    strategy: dict                   # 节点2 输出：策略检索
    plan: dict                       # 节点3 输出：剪辑方案

    # 质量控制
    quality_score: float             # 质量评分
    retry_count: int                 # 重试次数
    max_retries: int                 # 最大重试

    # 人工介入
    human_feedback: str              # 人工反馈
    human_approved: bool             # 是否通过

    # 流程控制
    current_node: str                # 当前节点
    status: str                      # 运行状态

    # 执行日志
    steps: list                      # 步骤详情
```

### 2.2 TypedDict 的意义

```python
# 普通 dict — 没有类型约束，key 可以随意写
state = {"asr_text": "xxx", "typo_key": 123}  # 不报错

# TypedDict — 编译时检查，key 和类型必须匹配
state: WorkflowState = {"asr_text": "xxx", "typo_key": 123}  # 类型警告
```

**对 LangGraph 的意义：**
- `StateGraph(WorkflowState)` 告诉 LangGraph 状态的完整结构
- 每个节点 return 时，LangGraph 自动 merge 到全局状态
- 节点之间通过 state 字段名传递数据，TypedDict 保证字段名正确

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
# agent_workflow.py:169
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

# 2. ChatOpenAI — LLM 调用（OpenAI 兼容接口）
llm = ChatOpenAI(
    base_url="https://token-plan-cn.xiaomimimo.com/v1",
    model="claude-sonnet-4-6",
    api_key="...",
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
# 质量检查后的路由
def route_after_quality(state: WorkflowState) -> str:
    score = state.get("quality_score", 0)
    retry = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if score >= 70 or retry >= max_retries:
        return "human_review"  # 达标或重试耗尽 → 人工审核
    return "retrieve"          # 不达标 → 回溯重试

# 注册条件边
graph.add_conditional_edges("quality_check", route_after_quality, {
    "retrieve": "retry_increment",
    "human_review": "human_review",
})
```

### 4.2 回溯循环

```python
# 图结构：quality_check → retry_increment → retrieve → quality_check → ...
graph.add_edge("retry_increment", "retrieve")  # 回溯边
graph.add_conditional_edges("quality_check", route_after_quality, {
    "retrieve": "retry_increment",  # 不达标 → 回溯
    "human_review": "human_review", # 达标 → 继续
})
```

### 4.3 人工介入（Human-in-the-Loop）

```python
# 暂停：human_review 节点设置 status="paused"
def node_human_review(state):
    return {**state, "status": "paused", "need_human_review": True}

# 恢复：外部注入 human_approved 和 human_feedback
def resume_workflow(state, approved, feedback=""):
    state["human_approved"] = approved
    state["human_feedback"] = feedback
    if approved:
        result = node_generate(state)     # 通过 → 生成
    else:
        result = node_retrieve(state)     # 打回 → 重新检索
    return result
```

---

## 五、对比总结

| 维度 | LangChain | LangGraph |
|------|-----------|-----------|
| **定位** | LLM 调用工具库 | Agent 编排框架 |
| **核心对象** | ChatOpenAI, PromptTemplate | StateGraph, TypedDict |
| **状态管理** | 无（每次调用独立） | TypedDict 全局状态，自动 merge |
| **流程控制** | 线性 Chain | 条件路由、循环、回溯 |
| **人工介入** | 无原生支持 | interrupt/resume 原生支持 |
| **代码位置** | 节点函数内部 | 节点之间的编排 |
| **类比** | 函数调用 | 状态机/工作流引擎 |

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
│    "retry_count": 0, "steps": []                            │
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
       │  评分: hook/category/strategy...      │
       │                                       │
       │  输出 → state["quality_score"] = 45   │
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
       │  node_human_review (LangGraph 暂停)   │
       │  state["status"] = "paused"           │
       │  等待 API /api/resume 注入决策        │
       └───────────────────┬───────────────────┘
                           │
       ┌───────────────────▼───────────────────┐
       │  node_generate (LangChain 执行)       │
       │  chain = prompt | llm | JsonParser    │
       │  result = chain.invoke(...)           │
       │                                       │
       │  输出 → state["plan"] = result        │
       └───────────────────┬───────────────────┘
                           │
                           ▼
                        END
```
