from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from apps.voice_agent.extractor import fold_vi
from shared.config import REPO_ROOT, get_settings

STOPWORDS = {
    "va", "la", "cua", "cho", "a", "thi", "co", "khong", "o", "luc", "khi",
    "nha", "hang", "toi", "anh", "chi", "em", "duoc", "mot", "cac", "the",
}


@dataclass
class KnowledgeChunk:
    source: str
    title: str
    text: str

    def speakable(self, limit: int = 280) -> str:
        cleaned = re.sub(r"[#*_`]", "", self.text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1].rsplit(" ", 1)[0] + "."


class KnowledgeRetriever:
    """Lexical RAG over internal markdown; optional Chroma if enabled."""

    def __init__(
        self,
        knowledge_dir: str | Path | None = None,
        *,
        use_chroma: bool = False,
        chroma_path: str | None = None,
        openai_api_key: str = "",
    ) -> None:
        settings = get_settings()
        self.knowledge_dir = Path(knowledge_dir or settings.knowledge_dir)
        if not self.knowledge_dir.is_absolute():
            self.knowledge_dir = REPO_ROOT / self.knowledge_dir
        self.use_chroma = use_chroma
        self.chroma_path = chroma_path or settings.chroma_path
        self.openai_api_key = openai_api_key or settings.openai_api_key
        self.chunks: list[KnowledgeChunk] = []
        self._collection = None

    def ingest(self) -> list[KnowledgeChunk]:
        self.chunks = []
        if not self.knowledge_dir.exists():
            return self.chunks
        for path in sorted(self.knowledge_dir.glob("*.md")):
            self.chunks.extend(_chunk_markdown(path))
        if self.use_chroma:
            self._ingest_chroma()
        return self.chunks

    def retrieve(self, query: str, k: int = 3, min_score: float = 0.5) -> list[KnowledgeChunk]:
        if not self.chunks:
            self.ingest()
        if self._collection is not None:
            chroma_hits = self._retrieve_chroma(query, k)
            if chroma_hits:
                return chroma_hits
        scored: list[tuple[float, KnowledgeChunk]] = []
        q_tokens = _tokens(query)
        for chunk in self.chunks:
            score = _overlap_score(q_tokens, chunk)
            if score >= min_score:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:k]]

    def _ingest_chroma(self) -> None:
        try:
            import chromadb
        except ImportError:
            self._collection = None
            return
        try:
            client = chromadb.PersistentClient(path=str(self.chroma_path))
            kwargs: dict = {"name": "restaurant_knowledge"}
            if self.openai_api_key:
                try:
                    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

                    kwargs["embedding_function"] = OpenAIEmbeddingFunction(
                        api_key=self.openai_api_key,
                        model_name="text-embedding-3-small",
                    )
                except Exception:
                    pass
            collection = client.get_or_create_collection(**kwargs)
            if self.chunks:
                collection.upsert(
                    ids=[f"{c.source}-{i}" for i, c in enumerate(self.chunks)],
                    documents=[f"{c.title}\n{c.text}" for c in self.chunks],
                    metadatas=[{"source": c.source, "title": c.title} for c in self.chunks],
                )
            self._collection = collection
        except Exception:
            self._collection = None

    def _retrieve_chroma(self, query: str, k: int) -> list[KnowledgeChunk]:
        if self._collection is None:
            return []
        result = self._collection.query(query_texts=[query], n_results=k)
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        hits: list[KnowledgeChunk] = []
        for doc, meta in zip(docs, metas):
            hits.append(
                KnowledgeChunk(
                    source=str((meta or {}).get("source") or ""),
                    title=str((meta or {}).get("title") or ""),
                    text=doc,
                )
            )
        return hits


def _chunk_markdown(path: Path) -> list[KnowledgeChunk]:
    raw = path.read_text(encoding="utf-8")
    parts = re.split(r"\n(?=#{1,3} )", raw)
    chunks: list[KnowledgeChunk] = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        title_match = re.match(r"^#{1,3}\s+(.+)", text)
        title = title_match.group(1).strip() if title_match else path.stem
        chunks.append(KnowledgeChunk(source=path.name, title=title, text=text))
    return chunks


def _tokens(text: str) -> set[str]:
    folded = fold_vi(text)
    words = re.findall(r"[a-z0-9]+", folded)
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def _overlap_score(q_tokens: set[str], chunk: KnowledgeChunk) -> float:
    doc_tokens = _tokens(chunk.title + " " + chunk.text)
    if not q_tokens or not doc_tokens:
        return 0.0
    overlap = q_tokens & doc_tokens
    score = len(overlap)
    title_tokens = _tokens(chunk.title)
    score += 1.5 * len(q_tokens & title_tokens)
    blob = fold_vi(chunk.text)
    for token in q_tokens:
        if len(token) >= 4 and token in blob:
            score += 0.25
    return score
