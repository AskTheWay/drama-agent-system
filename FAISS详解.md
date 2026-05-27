# FAISS 详解 — 从原理到本系统实现

## 一、FAISS 是什么

FAISS（Facebook AI Similarity Search）是 Meta 开源的**向量相似度搜索算法库**。

它解决一个核心问题：**在海量高维向量中，快速找到与目标向量最相似的 top-k 个向量**。

```
输入: 查询向量 [0.12, -0.34, 0.56, ..., 0.78]  (1024 维)
输出: 最相似的 3 个向量 + 相似度分数
  → 向量 #1 (相似度 0.87)
  → 向量 #3 (相似度 0.76)
  → 向量 #5 (相似度 0.71)
```

---

## 二、本系统中 FAISS 的完整工作流

### 2.1 数据流向

```
SQLite (hot_references 表)
    │
    │  读取所有爆款素材
    ▼
Python 拼接文本
    │  title + hook_text + asr_text + tags
    ▼
阿里云 Embedding API
    │  文本 → 1024 维浮点向量
    ▼
FAISS IndexFlatIP
    │  向量归一化 → 加入索引
    ▼
faiss.write_index() → 磁盘文件 (faiss_index.index)
json.dump()          → 磁盘文件 (faiss_index.meta)
```

### 2.2 索引构建过程（代码逐行解析）

```python
# 第一步: 从 SQLite 读取所有爆款素材
db = SessionLocal()
refs = db.query(HotRef).all()
# refs = [HotRef(id=1, title="赘婿逆袭", ...), HotRef(id=2, ...), ...]

# 第二步: 对每条素材，拼接关键文本，调用 Embedding API
vectors = []
self.metadata = []

for ref in refs:
    # 拼接文本: "赘婿逆袭：百亿遗产继承 三年赘婿被人看不起... [赘婿, 逆袭, 遗产, 打脸]"
    text = f"{ref.title} {ref.hook_text} {ref.asr_text} {' '.join(ref.tags or [])}"

    # 调用阿里云 API，文本 → 1024 维向量
    vec = self._get_embedding(text)
    # vec = [0.0123, -0.0456, 0.0789, ..., -0.0321]  (1024 个浮点数)

    vectors.append(vec)

    # 保存元数据（与向量数组下标对齐）
    self.metadata.append({
        "id": ref.id,
        "title": ref.title,
        "category": ref.category,
        # ...
    })

# 第三步: 构建 FAISS 索引
vectors_np = np.array(vectors, dtype="float32")
# vectors_np.shape = (6, 1024)  → 6 条素材，每条 1024 维

faiss.normalize_L2(vectors_np)
# L2 归一化: 每个向量除以自身的 L2 范数
# 归一化后，内积 = 余弦相似度
# 原始向量 [3, 4] → 归一化 [0.6, 0.8]  (L2范数=5, 3/5=0.6, 4/5=0.8)

self.index = faiss.IndexFlatIP(1024)
# IndexFlatIP = 暴力搜索 + 内积(Inner Product)
# IP = Inner Product，配合 L2 归一化 = 余弦相似度
# Flat = 不压缩、不聚类，逐一计算

self.index.add(vectors_np)
# 把 6 个 1024 维向量加入索引
# 内部存储: 一个 (6, 1024) 的 float32 数组

# 第四步: 持久化到磁盘
faiss.write_index(self.index, "data/faiss_index.index")
# 写入二进制文件，包含索引类型 + 向量数据

with open("data/faiss_index.meta", "w") as f:
    json.dump(self.metadata, f)
# 元数据单独存 JSON，与向量数组下标一一对应
```

### 2.3 索引结构图

```
faiss_index.index 文件内容:
┌─────────────────────────────────────────────────────┐
│ 索引头: IndexFlatIP, dim=1024, metric=InnerProduct  │
├─────────────────────────────────────────────────────┤
│ 向量 #0: [0.0123, -0.0456, 0.0789, ..., -0.0321]  │  ← 赘婿逆袭
│ 向量 #1: [0.0234, -0.0567, 0.0890, ..., -0.0432]  │  ← 战神归来
│ 向量 #2: [0.0345, -0.0678, 0.0901, ..., -0.0543]  │  ← 龙王令
│ 向量 #3: [0.0456, -0.0789, 0.0112, ..., -0.0654]  │  ← 重生千金
│ 向量 #4: [0.0567, -0.0890, 0.0223, ..., -0.0765]  │  ← 闪婚总裁
│ 向量 #5: [0.0678, -0.0901, 0.0334, ..., -0.0876]  │  ← 穿越医妃
└─────────────────────────────────────────────────────┘

faiss_index.meta 文件内容:
[
  {"id": 1, "title": "赘婿逆袭", "category": "男频", ...},  ← 下标 0
  {"id": 2, "title": "战神归来", "category": "男频", ...},  ← 下标 1
  {"id": 3, "title": "龙王令",   "category": "男频", ...},  ← 下标 2
  {"id": 4, "title": "重生千金", "category": "女频", ...},  ← 下标 3
  {"id": 5, "title": "闪婚总裁", "category": "女频", ...},  ← 下标 4
  {"id": 6, "title": "穿越医妃", "category": "女频", ...},  ← 下标 5
]

对应关系: metadata[i] 就是 vectors_np[i] 的业务数据
```

---

## 三、搜索过程（代码逐行解析）

### 3.1 查询流程

```python
def search(self, query, category=None, sub_category=None, top_k=3):

    # Step 1: 元数据预过滤（在 Python 内存中）
    candidates = list(range(len(self.metadata)))
    # candidates = [0, 1, 2, 3, 4, 5]  → 全部下标

    if category:
        candidates = [i for i in candidates if self.metadata[i]["category"] == category]
        # category="男频" → candidates = [0, 1, 2]

    if sub_category:
        candidates = [i for i in candidates if self.metadata[i]["sub_category"] == sub_category]
        # sub_category="逆袭" → candidates = [0]

    # Step 2: 查询文本 → 向量
    query_vec = self._get_embedding(query)
    # "逆袭打脸" → [0.111, -0.222, 0.333, ..., -0.444]  (1024 维)
    query_vec = np.array([query_vec], dtype="float32")  # shape: (1, 1024)
    faiss.normalize_L2(query_vec)  # 归一化

    # Step 3: FAISS 向量搜索
    if len(candidates) <= top_k:
        # 候选集比 top_k 还小，直接返回
        results = [self.metadata[i] for i in candidates]
    else:
        # 在候选集内搜索
        selector = faiss.IDSelectorArray(candidates)
        # IDSelectorArray([0, 1, 2]) → 只允许在下标 0, 1, 2 中搜索

        params = faiss.SearchParameters()
        params.sel = selector
        # 把 selector 绑到搜索参数上

        scores, indices = self.index.search(query_vec, top_k, params=params)
        # search(query_vec, k=3, params=selector)
        # 返回:
        #   scores  = [[0.87, 0.76, 0.71]]  → 3 个相似度分数
        #   indices = [[0, 2, 1]]            → 3 个下标

        # Step 4: 组装结果
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and idx in candidates:
                item = {**self.metadata[idx], "similarity": float(score)}
                results.append(item)

    # Step 5: 按业务分数排序（数据飞轮权重）
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results[:top_k]
```

### 3.2 搜索过程图解

```
查询: "逆袭打脸" + category="男频"

Step 1: 元数据预过滤
  全部下标: [0, 1, 2, 3, 4, 5]
  category="男频": [0, 1, 2]
  → 候选集 = [0, 1, 2]

Step 2: 查询向量化
  "逆袭打脸" → Embedding API → [0.111, -0.222, ...] → L2归一化

Step 3: FAISS 暴力搜索（在候选集内）
  计算查询向量与候选集每个向量的内积:

  下标 0 (赘婿逆袭): 内积 = 0.87  ← 最相似
  下标 2 (龙王令):    内积 = 0.76
  下标 1 (战神归来):  内积 = 0.71

Step 4: 组装结果
  [
    {"title": "赘婿逆袭", "similarity": 0.87, "score": 92.0},
    {"title": "龙王令",   "similarity": 0.76, "score": 85.0},
    {"title": "战神归来", "similarity": 0.71, "score": 88.0},
  ]

Step 5: 按 score 排序
  赘婿逆袭 (score=92.0) → 第 1
  战神归来 (score=88.0) → 第 2
  龙王令   (score=85.0) → 第 3
```

---

## 四、核心算法原理

### 4.1 余弦相似度

```
余弦相似度 = cos(θ) = (A · B) / (|A| × |B|)

A = [0.6, 0.8]    (归一化后, |A| = 1)
B = [0.8, 0.6]    (归一化后, |B| = 1)

cos(θ) = (0.6×0.8 + 0.8×0.6) / (1 × 1) = 0.96

归一化后: 内积 = 余弦相似度
  A · B = 0.6×0.8 + 0.8×0.6 = 0.96 = cos(θ)
```

这就是为什么代码先 `faiss.normalize_L2()` 再用 `IndexFlatIP`（内积）：
- L2 归一化把向量长度缩放到 1
- 内积 = 余弦相似度（因为分母 |A|×|B| = 1）

### 4.2 IndexFlatIP 的"暴力"含义

```
Flat = 不压缩、不聚类、不近似
IP   = Inner Product (内积)

搜索时: 逐一计算查询向量与所有向量的内积

  查询向量 Q  vs  向量 #0 → 内积 0.87
  查询向量 Q  vs  向量 #1 → 内积 0.71
  查询向量 Q  vs  向量 #2 → 内积 0.76
  查询向量 Q  vs  向量 #3 → 内积 0.55
  查询向量 Q  vs  向量 #4 → 内积 0.62
  查询向量 Q  vs  向量 #5 → 内积 0.48

排序取 top-3: 0.87, 0.76, 0.71 → 下标 0, 2, 1

时间复杂度: O(n × d)  (n=向量数, d=维度)
6 条 × 1024 维 = 毫秒级
100 万条 × 1024 维 = 秒级（需要换索引类型）
```

### 4.3 FAISS 索引类型对比

| 索引类型 | 原理 | 搜索速度 | 精度 | 内存 | 适用场景 |
|----------|------|---------|------|------|---------|
| **IndexFlatIP** | 暴力逐一计算 | 最慢 | 100% 精确 | 低 | 本系统 (6条) |
| IndexIVFFlat | 先聚类再搜索 | 快 | 高 | 中 | 百万级 |
| IndexIVFPQ | 聚类+乘积量化 | 最快 | 有损 | 最低 | 亿级 |
| IndexHNSW | 图索引 | 很快 | 很高 | 高 | 高召回率 |

本系统选 IndexFlatIP 的原因:
1. 数据量极小 (6 条)，暴力搜索毫秒级
2. 精度最高，没有近似误差
3. 不需要训练，构建即用

---

## 五、FAISS 的局限性

### 5.1 不支持 CRUD

```python
# 只能追加，不能修改或删除
index.add(new_vectors)       # ✅ 追加
index.remove_ids(ids)        # ⚠️ 仅 IndexFlat 支持，且效率低
# index.update(id, new_vec)  # ❌ 不支持

# 修改一条数据的实际操作:
# 1. 重建整个索引
all_vectors = get_all_vectors()
index = faiss.IndexFlatIP(1024)
index.add(all_vectors)

# 2. 或者用 IDMap 包装（但性能差）
```

### 5.2 元数据与向量分离

```
FAISS 只存向量，不存业务数据:

FAISS 索引文件:           元数据 JSON 文件:
┌──────────────────┐      ┌──────────────────┐
│ [0.012, -0.045]  │ ───→ │ {"id":1,"title"} │
│ [0.023, -0.056]  │ ───→ │ {"id":2,"title"} │
│ [0.034, -0.067]  │ ───→ │ {"id":3,"title"} │
└──────────────────┘      └──────────────────┘

必须手动保持两者同步:
- 加数据: index.add() + metadata.append()
- 存盘: write_index() + json.dump()
- 加载: read_index() + json.load()
- 如果其中一个文件损坏或不同步 → 数据不一致
```

### 5.3 不支持过滤查询

```python
# FAISS 不能直接做: "找 category=男频 且 最相似的向量"

# 只能两步走:
# Step 1: Python 过滤出候选集
candidates = [i for i in range(n) if metadata[i]["category"] == "男频"]

# Step 2: 在候选集内搜索
selector = faiss.IDSelectorArray(candidates)
scores, indices = index.search(query_vec, k, params={sel: selector})

# 问题: 数据量大时，Step 1 的 Python 遍历很慢
# ES 用 bitset 做 filter，O(1) 命中
```

---

## 六、本系统的完整数据流图

```
                    ┌─────────────────────────────┐
                    │       爆款素材入库            │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  SQLite: hot_references 表   │
                    │  存储全部结构化字段            │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  拼接文本:                    │
                    │  title + hook_text +          │
                    │  asr_text + tags              │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  阿里云 Embedding API         │
                    │  文本 → 1024 维向量           │
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
    ┌─────────▼─────────┐ ┌───────▼───────┐ ┌──────────▼──────────┐
    │  FAISS IndexFlatIP │ │  元数据 JSON   │ │  SQLite (原数据)     │
    │  向量数组 (6×1024) │ │  6 条元数据    │ │  6 条完整记录        │
    │  write_index()     │ │  json.dump()   │ │  自动持久化          │
    └─────────┬─────────┘ └───────┬───────┘ └─────────────────────┘
              │                    │
              │  search()          │  metadata[i]
              │                    │
    ┌─────────▼────────────────────▼───────────┐
    │            Python 代码协调                 │
    │  1. metadata 过滤候选集                   │
    │  2. FAISS 搜索 top-k                     │
    │  3. 组装 metadata + similarity            │
    │  4. 按 score 排序                         │
    └──────────────────────────────────────────┘
```

对比 ES 的数据流:

```
                    ┌─────────────────────────────┐
                    │       爆款素材入库            │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  ES: drama_hot_references    │
                    │  结构化字段 + 向量 + 全文索引  │
                    │  一次写入，自动管理            │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  ES 查询引擎 (一次搞定)       │
                    │  filter(结构化) +             │
                    │  match(全文) + knn(向量)      │
                    └─────────────────────────────┘
```
