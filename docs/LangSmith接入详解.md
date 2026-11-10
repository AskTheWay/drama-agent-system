# LangSmith 接入详解

## 一、接入方式

**零代码接入** — 只需设置环境变量，不改任何业务代码。

```
LangChain 库内部自动检测环境变量:
  LANGSMITH_TRACING=true  → 开启上报
  LANGSMITH_API_KEY=xxx   → 认证身份
  LANGSMITH_PROJECT=xxx   → 归类项目
  LANGSMITH_ENDPOINT=xxx  → 上报地址

检测到这些变量后，所有 LangChain 调用自动上报到 LangSmith
```

## 二、修改了什么

### 2.1 文件改动

| 文件 | 改动 | 说明 |
|------|------|------|
| `.env` | 新增 4 行 | LangSmith 环境变量 |
| `.env.example` | 新增 4 行 | 配置模板 |
| `config.py` | 无改动 | 已有 _load_env() 自动加载 |
| `agent_workflow.py` | 无改动 | LangChain 自动上报 |
| `main.py` | 无改动 | — |

### 2.2 .env 新增内容

```bash
# LangSmith 可观测性
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_your_langsmith_api_key
LANGSMITH_PROJECT=drama-agent
```

### 2.3 为什么不需要改代码

```
config.py 中已有环境变量加载机制:

  def _load_env():
      for line in f:
          key, value = line.split("=", 1)
          os.environ.setdefault(key.strip(), value.strip())

  _load_env()  ← 启动时自动执行

.env 中的 LANGSMITH_* 变量被加载到 os.environ
LangChain 库内部读取 os.environ 自动开启 tracing
```

## 三、连接原理

### 3.1 配置加载链路

```
应用启动
  │
  ▼
config.py._load_env()
  │ 读取 .env 文件
  │ 设置 os.environ["LANGSMITH_TRACING"] = "true"
  │ 设置 os.environ["LANGSMITH_API_KEY"] = "lsv2_pt_..."
  │ 设置 os.environ["LANGSMITH_PROJECT"] = "drama-agent"
  │ 设置 os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
  │
  ▼
LangChain 库检测环境变量
  │ 发现 LANGSMITH_TRACING=true
  │ 创建 LangSmithClient(api_key=..., endpoint=...)
  │
  ▼
每次 LLM 调用时自动上报
```

### 3.2 上报链路

```
agent_workflow.py 中的 LLM 调用:

  chain = ANALYSIS_PROMPT | llm | JsonOutputParser()
  result = chain.invoke({...})
       │
       ├─ ANALYSIS_PROMPT.invoke()  ← 自动上报到 LangSmith
       ├─ llm.invoke()              ← 自动上报到 LangSmith
       └─ JsonOutputParser.parse()  ← 自动上报到 LangSmith
       │
       ▼
  LangSmithClient 发送 HTTP POST:
  POST https://api.smith.langchain.com/api/v1/runs
  Headers:
    x-api-key: lsv2_pt_your_key...
  Body:
    {
      "name": "ChatOpenAI",
      "inputs": {"messages": [...]},
      "outputs": {"content": "..."},
      "run_type": "llm",
      "project_name": "drama-agent",
      "start_time": "2026-06-07T10:00:00Z",
      "end_time": "2026-06-07T10:00:01.5Z"
    }
       │
       ▼
  LangSmith 服务器 (smith.langchain.com)
  │ 存储到数据库
  │ 在 Web UI 中展示
```

### 3.3 连接关系

```
┌──────────────────────┐         HTTPS POST          ┌──────────────────────┐
│    Drama Agent       │ ──────────────────────────►  │    LangSmith         │
│    (localhost:8080)  │                              │    (smith.langchain. │
│                      │                              │     com)             │
│  LangChain 库        │  ◄────────────────────────── │                      │
│  自动检测环境变量     │    返回 run_id               │    存储 + 展示        │
│  自动上报每次调用     │                              │                      │
└──────────────────────┘                              └──────────────────────┘

认证: LANGSMITH_API_KEY (HTTP Header)
项目: LANGSMITH_PROJECT (请求体中)
地址: LANGSMITH_ENDPOINT (请求 URL)
开关: LANGSMITH_TRACING (是否启用)
```

## 四、LangSmith 能看到什么

### 4.1 每次 LLM 调用

```
Run: ChatOpenAI
├─ Input:
│    system: "你是一位资深短剧投流素材分析师..."
│    user: "素材：test.mp4\nASR：三年赘婿...\n帧描述：..."
├─ Output:
│    {"category": "男频", "sub_category": "逆袭", "hook_analysis": {...}}
├─ Metadata:
│    model: mimo-v2.5-pro
│    tokens: input=500, output=200
│    latency: 1.5s
│    project: drama-agent
└─ Status: success
```

### 4.2 完整工作流链路

```
Run: run_workflow
├─ node_analyze
│    └─ ChatOpenAI (1.5s, 700 tokens)
├─ node_retrieve
│    ├─ VectorStore.search (0.2s)
│    └─ ChatOpenAI (1.2s, 600 tokens)
├─ node_quality_check
│    └─ score=45, route=retrieve
├─ (回溯重试)
│    ├─ node_retrieve
│    │    └─ ChatOpenAI (1.1s, 580 tokens)
│    └─ node_quality_check
│         └─ score=70, route=human_review
├─ node_human_review
│    └─ paused, approved=true
└─ node_generate
     └─ ChatOpenAI (2.3s, 900 tokens)
```

### 4.3 可用功能

| 功能 | 说明 |
|------|------|
| Traces | 查看每次工作流的完整执行链路 |
| Runs | 查看每次 LLM 调用的输入/输出 |
| Playground | 在线调试 Prompt |
| Datasets | 构建测试数据集 |
| Evaluations | 评估 LLM 输出质量 |
| Feedback | 人工标注反馈 |

## 五、与 Prometheus+Grafana 的区别

```
Prometheus+Grafana → 系统层面监控
  QPS、延迟、错误率、节点耗时
  数值型指标，时序数据

LangSmith → LLM 层面监控
  Prompt 内容、LLM 输出、Token 消耗、执行链路
  文本型数据，调用追踪

两者互补，不冲突
```

## 六、数据流对比

```
Prometheus 路径:
  应用 → metrics.py → /metrics → Prometheus → Grafana
  监控: HTTP 请求、节点耗时、系统指标

LangSmith 路径:
  应用 → LangChain 库 → HTTPS POST → smith.langchain.com → Web UI
  监控: LLM 调用、Prompt、输出、Token

两个路径独立，互不影响
```
