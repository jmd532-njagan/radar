"""
Hybrid search over a project's active SOP, entirely in memory.

A project's SOP is tens of chunks, so no search index is worth running: the chunks and their
stored embeddings are loaded once per process and scored in numpy. Two rankings — BM25 on
words (exact names like PL_Staging or TRG_WEEKLY_TWICE) and cosine on bge-base embeddings
(meaning) — are merged with reciprocal rank fusion. There is no boost for chunks naming the
pipeline asked about: on the SOP eval (evals/sop_retrieval.py) it lifted pipeline lists above
the section that answered the question. The cache is keyed by the active document id, checked on
every search, so a new upload is picked up by every worker.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import SOP_SEARCH_RESULTS
from db import sop
from db.models import SopDocument
from llm.embeddings import embed_texts_async

_RRF_K = 60
_TOKEN = re.compile(r"[a-z0-9_]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def passage(heading_path: str, text: str) -> str:
    """What gets embedded: the section path gives a chunk its context."""
    return f"{heading_path}\n{text}"


@dataclass(frozen=True)
class _Index:
    document_id: int
    sections: list[str]
    texts: list[str]
    vectors: np.ndarray
    docs: list[Counter]
    df: Counter
    avg_len: float

    def bm25(self, query: list[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
        n, scores = len(self.docs), np.zeros(len(self.docs))
        for term in set(query):
            idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
            for i, doc in enumerate(self.docs):
                tf = doc[term]
                if tf:
                    length = sum(doc.values())
                    scores[i] += (
                        idf
                        * tf
                        * (k1 + 1)
                        / (tf + k1 * (1 - b + b * length / self.avg_len))
                    )
        return scores


_cache: dict[str, _Index] = {}


async def _index(db: AsyncSession, project: str) -> _Index | None:
    document_id = await db.scalar(
        select(SopDocument.id).where(
            SopDocument.project == project, SopDocument.status == "active"
        )
    )
    if document_id is None:
        return None
    cached = _cache.get(project)
    if cached and cached.document_id == document_id:
        return cached
    rows = await sop.chunks(db, document_id)
    if not rows:
        return None
    _cache[project] = index = build_index(document_id, rows)
    return index


def build_index(document_id: int, rows: Sequence) -> _Index:
    """rows: SopChunk-like (heading_path, text, embedding), in document order."""
    docs = [Counter(_tokens(passage(r.heading_path, r.text))) for r in rows]
    return _Index(
        document_id=document_id,
        sections=[r.heading_path for r in rows],
        texts=[r.text for r in rows],
        vectors=np.array([r.embedding for r in rows], dtype=np.float32),
        docs=docs,
        df=Counter(t for d in docs for t in d),
        avg_len=sum(sum(d.values()) for d in docs) / len(docs),
    )


def _rrf(*rankings: np.ndarray) -> np.ndarray:
    fused = np.zeros(len(rankings[0]))
    for scores in rankings:
        for rank, i in enumerate(np.argsort(-scores)):
            fused[i] += 1 / (_RRF_K + rank + 1)
    return fused


async def search(
    db: AsyncSession,
    project: str,
    query: str,
    k: int = SOP_SEARCH_RESULTS,
) -> list[dict]:
    """The k most relevant SOP sections for the query, best first: [{"section", "text"}]."""
    index = await _index(db, project)
    if index is None or not query.strip():
        return []
    query_vector = (await embed_texts_async([query], query=True))[0]
    return [
        {"section": index.sections[i], "text": index.texts[i]}
        for i in rank(index, query, query_vector)[:k]
    ]


def rank(index: _Index, query: str, query_vector: np.ndarray) -> np.ndarray:
    """Chunk positions, best first."""
    return np.argsort(-_rrf(index.bm25(_tokens(query)), index.vectors @ query_vector))
