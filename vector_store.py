"""
向量知识库 — FAISS + 阿里云 Embedding
实现 "元数据预过滤 + 语义向量检索" 双模 RAG
"""

import os
import json
import numpy as np
import faiss
import httpx
from models import SessionLocal, HotRef
from logger import get_logger
from config import DASHSCOPE_API_KEY
from metrics import embedding_calls, embedding_errors, vector_searches, faiss_index_size

logger = get_logger(__name__)
EMBEDDING_DIM = 1024
INDEX_PATH = os.path.join(os.path.dirname(__file__), "data", "faiss_index")


class VectorStore:
    """向量知识库 — 爆款 Reference 检索引擎"""

    def __init__(self):
        self.index = None
        self.metadata = []  # 与向量对齐的元数据
        self.degraded = False  # 构建期降级标志：索引是否由随机向量构建（控制是否持久化）
        self._persisted = False  # 磁盘上是否存在持久化索引（控制 update_scores 是否落盘）
        self._load_or_build()

    def _get_embedding(self, text: str, mark_degraded: bool = False) -> list[float]:
        """调用阿里云百炼 embedding API。
        mark_degraded=True（构建索引时）：失败置 degraded 标志，控制索引不持久化；
        查询期失败只影响本次相似度计算，不改变持久化语义。
        """
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "text-embedding-v3",
            "input": {"texts": [text]},
            "parameters": {"dimension": EMBEDDING_DIM},
        }
        try:
            embedding_calls.inc()
            resp = httpx.post(
                "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["output"]["embeddings"][0]["embedding"]
        except Exception as e:
            embedding_errors.inc()
            if mark_degraded:
                self.degraded = True
            logger.warning(f"Embedding API 失败: {e}，使用随机向量降级" + ("（索引将不持久化）" if mark_degraded else ""))
            return list(np.random.rand(EMBEDDING_DIM).astype(float))

    def _load_or_build(self):
        """加载已有索引或从数据库构建。
        注意：上次若以降级（随机向量）构建，索引文件不会存在，下次启动会自动重建。
        """
        index_file = f"{INDEX_PATH}.index"
        meta_file = f"{INDEX_PATH}.meta"

        if os.path.exists(index_file) and os.path.exists(meta_file):
            self.index = faiss.read_index(index_file)
            with open(meta_file, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
            self._persisted = True
            faiss_index_size.set(self.index.ntotal)
            logger.info(f"已加载 {self.index.ntotal} 条向量")
        else:
            self.build_index()

    def build_index(self):
        """从数据库构建向量索引（embedding 不可用时降级构建但不持久化）"""
        with SessionLocal() as db:
            refs = db.query(HotRef).all()

            if not refs:
                logger.info("无数据，跳过构建")
                return

            vectors = []
            self.metadata = []
            self.degraded = False

            for ref in refs:
                # 拼接关键文本生成向量
                text = f"{ref.title} {ref.hook_text} {ref.asr_text} {' '.join(ref.tags or [])}"
                vec = self._get_embedding(text, mark_degraded=True)
                vectors.append(vec)
                self.metadata.append({
                    "id": ref.id,
                    "title": ref.title,
                    "category": ref.category,
                    "sub_category": ref.sub_category,
                    "hook_text": ref.hook_text,
                    "hook_type": ref.hook_type,
                    "tags": ref.tags or [],
                    "score": ref.score,
                    "ctr": ref.ctr,
                    "retention_3s": ref.retention_3s,
                    "completion_rate": ref.completion_rate,
                })

        # 构建 FAISS 索引
        vectors_np = np.array(vectors, dtype="float32")
        faiss.normalize_L2(vectors_np)
        self.index = faiss.IndexFlatIP(EMBEDDING_DIM)  # 余弦相似度
        self.index.add(vectors_np)

        if self.degraded:
            # 随机向量的索引对语义检索毫无意义，绝不持久化——
            # 否则磁盘上会留下"永久噪声索引"，Key 恢复后也无法自愈
            logger.error(
                "索引以随机向量降级构建，本次不持久化；"
                "Embedding API 恢复后重启服务将自动重建真实索引"
            )
        else:
            # 持久化
            os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
            faiss.write_index(self.index, f"{INDEX_PATH}.index")
            with open(f"{INDEX_PATH}.meta", "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False)
            self._persisted = True
            logger.info(f"构建完成，{len(vectors)} 条向量已索引并持久化")

        faiss_index_size.set(len(vectors))

    def update_scores(self, id2score: dict[int, float]):
        """数据飞轮：feedback 更新 DB 分数后，同步内存元数据并落盘，
        保证下次检索排序（按 score 降序）用到最新分数。
        注：落盘条件是磁盘上存在持久化索引——查询期偶发的 embedding 失败
        不应禁用分数落盘（否则飞轮效果跨重启丢失）。"""
        changed = 0
        for m in self.metadata:
            if m.get("id") in id2score:
                m["score"] = id2score[m["id"]]
                changed += 1
        if changed and self._persisted:
            os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
            with open(f"{INDEX_PATH}.meta", "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False)
        logger.info(f"[数据飞轮] 已同步 {changed} 条素材的最新得分到检索元数据")

    def _filter_candidates(self, category: str = None, sub_category: str = None) -> list[int]:
        """元数据预过滤（硬规则）。
        过滤结果为空时回退全量候选集（避免赛道判断失误导致空手而归），并记录警告。
        """
        candidates = list(range(len(self.metadata)))
        if category:
            candidates = [i for i in candidates if self.metadata[i]["category"] == category]
        if sub_category:
            candidates = [i for i in candidates if self.metadata[i]["sub_category"] == sub_category]
        if not candidates and self.metadata:
            logger.warning(
                f"元数据预过滤无匹配（category={category}, sub_category={sub_category}），"
                "回退全量候选集——注意此时返回结果可能与请求赛道不符"
            )
            return list(range(len(self.metadata)))
        return candidates

    def _search_small(self, query_vec, candidates: list[int]) -> list[dict]:
        """候选集小时，直接计算相似度"""
        results = []
        for i in candidates:
            item = {**self.metadata[i]}
            vec = np.array([self.index.reconstruct(i)], dtype="float32")
            item["similarity"] = float(np.dot(query_vec[0], vec[0]))
            results.append(item)
        return results

    def _search_faiss(self, query_vec, candidates: list[int], top_k: int) -> list[dict]:
        """候选集大时，用 FAISS 检索"""
        selector = faiss.IDSelectorArray(candidates)
        params = faiss.SearchParameters()
        params.sel = selector
        scores, indices = self.index.search(query_vec, min(top_k * 2, len(candidates)), params=params)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and idx in candidates:
                results.append({**self.metadata[idx], "similarity": float(score)})
                if len(results) >= top_k:
                    break
        return results

    def search(self, query: str, category: str = None, sub_category: str = None,
               top_k: int = 3) -> list[dict]:
        """双模 RAG 检索：元数据预过滤 + 语义向量检索"""
        if self.index is None or self.index.ntotal == 0:
            return []

        vector_searches.inc()
        candidates = self._filter_candidates(category, sub_category)
        query_vec = np.array([self._get_embedding(query)], dtype="float32")
        faiss.normalize_L2(query_vec)

        if len(candidates) <= top_k:
            results = self._search_small(query_vec, candidates)
        else:
            results = self._search_faiss(query_vec, candidates, top_k)

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:top_k]


# 全局实例
store = None

def get_vector_store():
    global store
    if store is None:
        store = VectorStore()
    return store
