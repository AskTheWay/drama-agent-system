# Prometheus + Grafana 完整指南

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  应用层                  采集层              存储层        展示层     │
│                                                                     │
│  ┌──────────────┐       ┌────────────┐    ┌─────────┐  ┌─────────┐│
│  │ Drama Agent  │       │ Prometheus │    │ 本地存储 │  │ Grafana ││
│  │              │       │            │    │         │  │         ││
│  │ metrics.py   │◄─────►│ 每15秒抓取 │───►│ chunks  │─►│ 面板展示 ││
│  │ .inc()       │ GET   │ /metrics   │    │ wal     │  │ 折线图  ││
│  │ .observe()   │       │            │    │         │  │ 仪表盘  ││
│  │              │       │ PromQL引擎 │◄───│ 保留15天│  │         ││
│  └──────────────┘       └────────────┘    └─────────┘  └─────────┘│
│      端口 8080              端口 9090        容器内         端口 3000│
│      /metrics              /api/v1/query   /prometheus/            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 二、各组件职责

| 组件 | 职责 | 技术 | 位置 |
|------|------|------|------|
| metrics.py | 定义指标 | prometheus_client | 应用代码 |
| main.py 中间件 | 采集 HTTP 指标 | FastAPI middleware | 应用代码 |
| /metrics 端点 | 暴露指标数据 | make_asgi_app() | localhost:8080/metrics |
| Prometheus | 定时抓取 + 存储 + 查询 | 时序数据库 | localhost:9090 |
| prometheus.yml | 配置抓取目标和间隔 | YAML | 项目目录 |
| Grafana | 可视化展示 | Web UI | localhost:3000 |
| Dashboard JSON | 面板配置 | JSON | 项目目录 |

## 三、数据流全链路

### Step 1: 指标产生（Python 内存）

```python
# metrics.py — 定义指标（注册到 prometheus_client 全局 registry）
http_requests = Counter("http_requests_total", "HTTP 请求总数", ["method", "path"])

# main.py 中间件 — 每次请求自动更新
http_requests.labels("POST", "/api/analyze").inc()
node_latency.labels("analyze").observe(1.5)
```

```
指标值存在 Python 进程内存中:
  registry = {
    "http_requests_total{method=POST,path=/api/analyze}": 5,
    "workflow_node_duration_seconds_sum{node=analyze}": 3.2,
    "faiss_index_size": 6,
  }
```

### Step 2: 指标暴露（/metrics 端点）

```python
# main.py
metrics_app = make_asgi_app()     # 创建 ASGI 应用
app.mount("/metrics", metrics_app) # 挂载到 /metrics 路径
```

```
本质: make_asgi_app() 遍历内存中所有 Counter/Histogram/Gauge
      序列化为 Prometheus 文本格式返回

访问 http://localhost:8080/metrics 返回:

# HELP http_requests_total HTTP 请求总数
# TYPE http_requests_total counter
http_requests_total{method="POST",path="/api/analyze"} 5.0

# HELP faiss_index_size FAISS 向量库大小
# TYPE faiss_index_size gauge
faiss_index_size 6.0
```

### Step 3: 数据采集（Prometheus）

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "drama-agent"
    static_configs:
      - targets: ["host.docker.internal:8080"]
```

```
Prometheus 每 15 秒:
  HTTP GET http://host.docker.internal:8080/metrics
  → 解析文本
  → 写入本地存储
```

### Step 4: 数据存储（Prometheus 本地）

```
容器内路径: /prometheus/

/prometheus/
├── chunks_head/       ← 时序数据块（压缩存储）
├── wal/               ← 预写日志（防崩溃丢失）
├── queries.active     ← 当前活跃查询
└── lock               ← 锁文件

时序数据模型:
  指标名{标签} → [(时间戳1, 值1), (时间戳2, 值2), ...]

  http_requests_total{method="POST", path="/api/analyze"}:
    (T+0s,  0)    ← 初始值
    (T+15s, 3)    ← 第 1 次采集
    (T+30s, 7)    ← 第 2 次采集
    (T+45s, 12)   ← 第 3 次采集

默认保留 15 天
```

### Step 5: 数据查询（PromQL）

```
查询: rate(http_requests_total[1m])
含义: 最近 1 分钟内 counter 的增长速率

执行过程:
  1. 找到 http_requests_total 的所有时间序列
  2. 取最近 1 分钟的数据点
  3. 计算: (最新值 - 最早值) / 时间间隔
  4. 返回: 0.067 (每秒 0.067 次)
```

### Step 6: 可视化展示（Grafana）

```
Dashboard JSON = 面板配置（不含数据）

{
  "panels": [
    {
      "title": "HTTP 请求 QPS",
      "targets": [
        { "expr": "rate(http_requests_total[1m])" }
      ],
      "refresh": "10s"
    }
  ]
}
```

```
Grafana 每 10 秒:
  1. 读取面板配置中的 PromQL 查询
  2. 向 Prometheus 发送 HTTP 请求
  3. Prometheus 执行 PromQL，返回结果
  4. Grafana 渲染为折线图/仪表盘/直方图
```

## 四、指标类型详解

### 4.1 Counter（计数器）

```python
http_requests = Counter("http_requests_total", "HTTP 请求总数", ["method", "path"])
```

```
特点: 只增不减，重启归零
用途: 统计请求次数、错误次数、调用次数

http_requests_total{method="GET", path="/api/analyze"}
  t=0: 0
  t=1: 3    ← .inc()
  t=2: 7    ← .inc()
  t=3: 7    ← 没有请求，不变
  t=4: 10   ← .inc()

常用查询:
  rate(http_requests_total[1m])           → 每秒请求数
  increase(http_requests_total[5m])       → 5 分钟内增加量
  sum(http_requests_total) by (method)    → 按方法汇总
```

### 4.2 Histogram（直方图）

```python
node_latency = Histogram("workflow_node_duration_seconds", "节点耗时",
                         ["node"], buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120])
```

```
特点: 自动分桶统计，可计算分位数
用途: 统计延迟分布、大小分布

node_latency.labels("analyze").observe(1.5)
  → 1.5 落入 le=5 桶（1.5 < 5）
  → 同时落入 le=10, le=30, le=60, le=120 桶

自动产生 3 个指标:
  workflow_node_duration_seconds_bucket{le="5", node="analyze"}  = 1
  workflow_node_duration_seconds_sum{node="analyze"}             = 1.5
  workflow_node_duration_seconds_count{node="analyze"}           = 1

常用查询:
  histogram_quantile(0.5, ...)  → P50 延迟
  histogram_quantile(0.99, ...) → P99 延迟
```

### 4.3 Gauge（仪表盘）

```python
faiss_index_size = Gauge("faiss_index_size", "FAISS 向量库大小")
```

```
特点: 可增可减，反映当前值
用途: 温度、内存使用、队列长度

faiss_index_size
  t=0: 6     ← .set(6)
  t=1: 10    ← .set(10)
  t=2: 8     ← .set(8) 可以减小

常用查询:
  faiss_index_size                    → 当前值
  avg_over_time(faiss_index_size[5m]) → 5 分钟平均值
```

## 五、Dashboard JSON 详解

```
Dashboard JSON 不包含任何数据！
它只是一份"图纸"，定义了:
  - 有哪些面板（10 个图表）
  - 每个面板用什么 PromQL 查询
  - 用什么图表类型（折线图/仪表盘/直方图）
  - 刷新间隔（10 秒）
  - 时间范围（最近 30 分钟）

导入 JSON = 告诉 Grafana "怎么画图"
数据来源 = Grafana 实时向 Prometheus 查询
```

## 六、为什么能看实时和历史

```
Prometheus 持续采集，数据一直在本地:

时间轴:  ──────────────────────────────────────────►
采集:    ·   ·   ·   ·   ·   ·   ·   ·   ·   ·   ·
         0s  15s 30s 45s 60s 75s 90s ...           (每 15 秒)
存储:    [─────────────────────────────────────────] 保留 15 天

Grafana 查 "过去 30 分钟":
  → PromQL: rate(http_requests_total[30m])
  → Prometheus 从本地存储读取过去 30 分钟的所有数据点
  → 返回给 Grafana
  → 渲染为折线图（X 轴=时间，Y 轴=值）

所以: 实时数据 = 最近几个采集点
      历史数据 = 存储中的旧数据点
      全在 Prometheus 本地存储中
```

## 七、配置文件关系

```
docker-compose.yml
  ├─ 启动 Prometheus 容器
  │    └─ 挂载 prometheus.yml → /etc/prometheus/prometheus.yml
  └─ 启动 Grafana 容器
       └─ 挂载 grafana_dashboard.json → /var/lib/grafana/dashboards/

prometheus.yml
  └─ 告诉 Prometheus: scrape_interval=15s, targets=["host.docker.internal:8080"]

grafana_dashboard.json
  └─ 告诉 Grafana: 10 个面板，每个面板的 PromQL 查询和图表类型

metrics.py
  └─ 告诉 prometheus_client: 有哪些指标，名称、类型、标签

各业务模块
  └─ 调用 .inc() / .observe() 更新指标值
```

## 八、端口和地址

```
localhost:8080           → Drama Agent 应用
localhost:8080/metrics   → 指标端点（prometheus_client 生成）
localhost:9090           → Prometheus UI（查询和管理）
localhost:3000           → Grafana UI（可视化面板）

Docker 内部网络:
  prometheus:9090        → Prometheus（Grafana 用这个地址连接）
```

## 九、本项目监控指标

| 面板 | 类型 | PromQL 查询 | 含义 |
|------|------|-------------|------|
| HTTP 请求 QPS | 折线图 | `sum(rate(http_requests_total[1m])) by (path)` | 每条 API 的每秒请求数 |
| HTTP 延迟 P50/P99 | 折线图 | `histogram_quantile(0.5/0.99, ...)` | 请求延迟分位数 |
| 节点耗时 | 折线图 | `histogram_quantile(0.5/0.99, ...)` by node | 各节点执行时间 |
| 节点执行次数 | 统计值 | `sum(workflow_node_total) by (node)` | 每个节点调用次数 |
| LLM 调用成功率 | 仪表盘 | `1 - errors/calls` | LLM 成功比例 |
| 质量评分分布 | 直方图 | `sum(workflow_quality_score_bucket) by (le)` | 评分分布 |
| 回溯重试次数 | 统计值 | `sum(workflow_retry_total)` | 回溯总次数 |
| Embedding 成功率 | 仪表盘 | `1 - errors/calls` | Embedding 成功比例 |
| 向量检索 QPS | 折线图 | `rate(vector_search_total[1m])` | 每秒检索次数 |
| FAISS 索引大小 | 统计值 | `faiss_index_size` | 向量库数据量 |
