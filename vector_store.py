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

logger = get_logger(__name__)
EMBEDDING_DIM = 1024
INDEX_PATH = os.path.join(os.path.dirname(__file__), "data", "faiss_index")


class VectorStore:
    """向量知识库 — 爆款 Reference 检索引擎"""

    def __init__(self):
        self.index = None
        self.metadata = []  # 与向量对齐的元数据
        self._load_or_build()

    def _get_embedding(self, text: str) -> list[float]:
        """调用阿里云百炼 embedding API"""
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
            resp = httpx.post(
                "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["output"]["embeddings"][0]["embedding"]
        except Exception as e:
            logger.warning(f"Embedding API 失败: {e}，使用随机向量")
            return list(np.random.rand(EMBEDDING_DIM).astype(float))

    def _load_or_build(self):
        """加载已有索引或从数据库构建"""
        index_file = f"{INDEX_PATH}.index"
        meta_file = f"{INDEX_PATH}.meta"

        if os.path.exists(index_file) and os.path.exists(meta_file):
            self.index = faiss.read_index(index_file)
            with open(meta_file, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
            logger.info(f"已加载 {self.index.ntotal} 条向量")
        else:
            self.build_index()

    def build_index(self):
        """从数据库构建向量索引"""
        db = SessionLocal()
        refs = db.query(HotRef).all()

        if not refs:
            logger.info("无数据，跳过构建")
            db.close()
            return

        vectors = []
        self.metadata = []

        for ref in refs:
            # 拼接关键文本生成向量
            text = f"{ref.title} {ref.hook_text} {ref.asr_text} {' '.join(ref.tags or [])}"
            vec = self._get_embedding(text)
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

        # 持久化
        os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
        faiss.write_index(self.index, f"{INDEX_PATH}.index")
        with open(f"{INDEX_PATH}.meta", "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False)

        db.close()
        logger.info(f"构建完成，{len(vectors)} 条向量已索引")

    def _filter_candidates(self, category: str = None, sub_category: str = None) -> list[int]:
        """元数据预过滤（硬规则）"""
        candidates = list(range(len(self.metadata)))
        if category:
            candidates = [i for i in candidates if self.metadata[i]["category"] == category]
        if sub_category:
            candidates = [i for i in candidates if self.metadata[i]["sub_category"] == sub_category]
        return candidates or list(range(len(self.metadata)))

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

        candidates = self._filter_candidates(category, sub_category)
        query_vec = np.array([self._get_embedding(query)], dtype="float32")
        faiss.normalize_L2(query_vec)

        if len(candidates) <= top_k:
            results = self._search_small(query_vec, candidates)
        else:
            results = self._search_faiss(query_vec, candidates, top_k)

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:top_k]

    def add_reference(self, data: dict):
        """新增一条爆款 Reference（增量更新）"""
        text = f"{data['title']} {data['hook_text']} {data.get('asr_text', '')} {' '.join(data.get('tags', []))}"
        vec = self._get_embedding(text)
        vec_np = np.array([vec], dtype="float32")
        faiss.normalize_L2(vec_np)
        self.index.add(vec_np)
        self.metadata.append(data)

        # 持久化
        faiss.write_index(self.index, f"{INDEX_PATH}.index")
        with open(f"{INDEX_PATH}.meta", "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False)


# 全局实例
store = None

def get_vector_store():
    global store
    if store is None:
        store = VectorStore()
    return store
