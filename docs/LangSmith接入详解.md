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

> 本项目中 `LANGSMITH_TRACING` 默认为 `false`（默认关闭），启用需手动改为 `true`，详见 2.2 节。

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
# LangSmith 可观测性（可选）
LANGSMITH_TRACING=false
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=drama-agent
```

> 注意：`LANGSMITH_TRACING` **默认为 `false`（默认关闭）**。
> LangSmith 属于可选的可观测性组件，且上报会把 Prompt/输出内容发往外部服务，
> 因此 `.env` / `.env.example` 中默认不开启。要启用需手动改为 `true` 并填入有效 key。

### 2.3 为什么不需要改代码

```
config.py 中已有环境变量加载机制:

  def _load_env():
      for line in f:
          key, value = line.split("=", 1)
          os.environ.setdefault(key.strip(), value.strip())

  _load_env()  ← 模块级调用：import config 时立即执行，
                  而不是等到启动某个函数时才执行

触发时机（import 链）:
  main.py → import agent_workflow → import config → _load_env() 执行
  即应用进程一启动，.env 中的 LANGSMITH_* 变量就已进入 os.environ

.env 中的 LANGSMITH_* 变量被加载到 os.environ
LangChain 库内部读取 os.environ 自动开启 tracing
```

## 三、连接原理

### 3.1 配置加载链路

以下链路以「已手动开启」（.env 中 `LANGSMITH_TRACING=true`）为前提：

```
应用启动
  │
  ▼
import config 时执行 config.py._load_env()
  │ 读取 .env 文件
  │ os.environ.setdefault("LANGSMITH_TRACING", "true")
  │   （setdefault：shell 中已导出的同名环境变量优先，不会被 .env 覆盖）
  │ os.environ.setdefault("LANGSMITH_API_KEY", "lsv2_pt_...")
  │ os.environ.setdefault("LANGSMITH_PROJECT", "drama-agent")
  │ os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
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

（以下为 LangSmith 页面上一条 run 记录的示例，token/延迟等为演示数据）

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

（演示数据。质量检查为 100 分制纯扣分：零问题 = 100 分直接通过；
低于 70 分回溯重试（最多 2 次），回溯路径为 quality_check → retry_increment → retrieve。
质量达标后：自动模式（run_workflow）跳过 human_review 直达 generate；
人工介入模式暂停在 human_review 等待审批）

```
Run: run_workflow（自动模式）
├─ node_analyze
│    └─ ChatOpenAI (1.5s, 700 tokens)
├─ node_retrieve
│    ├─ VectorStore.search (0.2s)
│    └─ ChatOpenAI (1.2s, 600 tokens)
├─ node_quality_check
│    └─ score=45, route=retrieve（45 < 70，回溯）
├─ node_retry_increment
│    └─ retry_count: 0 → 1（回溯留痕到执行步骤）
├─ node_retrieve（回溯重试）
│    └─ ChatOpenAI (1.1s, 580 tokens)
├─ node_quality_check
│    └─ score=72, route=generate（达标，自动模式跳过人工审核）
└─ node_generate
     └─ ChatOpenAI (2.3s, 900 tokens)

人工介入模式（run_workflow_with_interrupt）差异：
  质量达标后 route=human_review，工作流暂停等待审批；
  审批通过 → node_generate；打回 → 带「人工反馈」重新 node_retrieve
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

## 七、验证接入与常见问题

### 7.1 如何验证接入成功

1. 确认 `.env` 中 `LANGSMITH_TRACING=true` 且 `LANGSMITH_API_KEY` 为有效 key（`lsv2_pt_` 开头）；
2. 重启服务（环境变量在 import 时加载，改完 `.env` 必须重启进程才生效，见 7.3）；
3. 在前端提交一次素材分析，触发真实 LLM 调用；
4. 打开 [smith.langchain.com](https://smith.langchain.com) → 左侧 **Projects** 页：
   应能看到 `drama-agent` 项目（由 `LANGSMITH_PROJECT` 指定）出现新的 run 记录，
   点进去可看到 `ChatOpenAI` 的输入 Prompt 与输出 JSON。

只要 Projects 页有 run 记录在持续产生，即说明接入成功。

### 7.2 常见问题排查

| 现象 | 可能原因 | 处理方式 |
|------|----------|----------|
| Projects 页没有任何 run 记录 | `LANGSMITH_TRACING` 仍为 `false`（默认关闭） | 改为 `true` 并重启服务 |
| 没有记录，但工作流能跑通 | LLM 调用失败走了 mock 兜底，根本没有真实 LLM 调用 | 检查 `LLM_API_KEY`；前端执行步骤的徽章会标注「兜底演示数据」 |
| 上报报 401 / 认证失败 | `LANGSMITH_API_KEY` 无效或已过期 | 到 LangSmith 设置页重新生成 key（`lsv2_pt_` 开头） |
| 完全没有网络请求发出 | 代理/防火墙拦截 `api.smith.langchain.com` | 配置 `HTTPS_PROXY` 环境变量或更换网络环境 |
| key 被系统环境变量覆盖 | shell 已导出同名变量，`.env` 不生效 | `_load_env()` 用 `setdefault`，系统环境变量优先；检查 `os.environ` |

### 7.3 .env 的加载时机（易踩坑）

`.env` 由 `config.py` 的 `_load_env()` 加载，该函数是**模块级调用——`import config` 时立即执行**。
本项目 `main.py → import agent_workflow → import config`，因此进程启动的瞬间 `.env` 就已加载完毕。

推论：
- 修改 `.env` 后**必须重启服务**，运行中的进程不会重新读取；
- `_load_env()` 内部用的是 `os.environ.setdefault()`，shell 中已导出的同名环境变量优先级高于 `.env`。
