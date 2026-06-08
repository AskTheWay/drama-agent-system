"""
Prometheus 指标定义
所有模块从这里导入指标实例
"""

from prometheus_client import Counter, Histogram, Gauge

# ========== HTTP 请求层 ==========
http_requests = Counter(
    "http_requests_total", "HTTP 请求总数",
    ["method", "path", "status"],
)
http_latency = Histogram(
    "http_request_duration_seconds", "HTTP 请求延迟",
    ["method", "path"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

# ========== 工作流节点层 ==========
node_executions = Counter(
    "workflow_node_total", "节点执行次数",
    ["node"],
)
node_latency = Histogram(
    "workflow_node_duration_seconds", "节点耗时",
    ["node"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120],
)
quality_score = Histogram(
    "workflow_quality_score", "质量评分分布",
    buckets=[10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
)
retry_total = Counter(
    "workflow_retry_total", "回溯重试次数",
)

# ========== LLM 调用层 ==========
llm_calls = Counter(
    "llm_calls_total", "LLM 调用次数",
    ["node"],
)
llm_errors = Counter(
    "llm_errors_total", "LLM 调用失败次数",
    ["node"],
)

# ========== 向量检索层 ==========
embedding_calls = Counter(
    "embedding_calls_total", "Embedding API 调用次数",
)
embedding_errors = Counter(
    "embedding_errors_total", "Embedding API 失败次数",
)
vector_searches = Counter(
    "vector_search_total", "向量检索次数",
)
faiss_index_size = Gauge(
    "faiss_index_size", "FAISS 向量库大小",
)

# ========== 数据飞轮 ==========
feedback_total = Counter(
    "feedback_total", "数据飞轮反馈次数",
)
