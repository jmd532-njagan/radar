"""
The shared local embedding model, loaded once per process:
BAAI/bge-base-en-v1.5 (768-dim, 512-token input): every embedding — ADF tool search
  (platform_tools/adf/tool_search_tool.py), prompt-injection detection (llm/injection_detection.py)
  and SOP retrieval (llm/sop/). Replaced all-MiniLM-L6-v2, whose 256-token window cut
  off SOP chunks. Values tuned on MiniLM's score range are provisional until re-measured
  (xyz/sop's/evals.txt lists them). No reranker: on the SOP test questions it never changed the
  top hit and cost ~9 s per search on CPU (evals.txt).

Lazy, not at import time — every test and script importing tool_search_tool imports this
module; an eager load would put a model load (and a network fetch on a cold cache) on every
test run whether or not it embeds anything. main.py warms it at startup instead.
"""

import asyncio
import logging
from functools import cache

import numpy as np
from sentence_transformers import SentenceTransformer

from config.settings import EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# bge's instruction for short search queries matched against passages; the passages, and
# symmetric comparisons like injection detection, get no prefix.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@cache
def _embedder() -> SentenceTransformer:
    logger.info("Loading local embedding model %s", EMBEDDING_MODEL)
    return SentenceTransformer(EMBEDDING_MODEL)


def embed_texts(texts: list[str], query: bool = False) -> np.ndarray:
    """L2-normalized embeddings. query=True for a search query matched against passages.
    Synchronous and CPU-bound: from async code use embed_texts_async, which runs it off the
    event loop (it runs on every chat turn)."""
    if query:
        texts = [_QUERY_PREFIX + t for t in texts]
    return _embedder().encode(texts, convert_to_numpy=True, normalize_embeddings=True)


async def embed_texts_async(texts: list[str], query: bool = False) -> np.ndarray:
    return await asyncio.to_thread(embed_texts, texts, query)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """a, b already L2-normalized (embed_texts uses normalize_embeddings=True), so this is just
    the dot product — no need to divide by norms again."""
    return float(np.dot(a, b))
