from __future__ import annotations

from shea.memory.contracts import ContextWindow, RetrievalResult
from shea.memory.ports import ContextAssembler, MemoryRetriever, MemoryStore, VectorStore
from shea.ports.clock import Clock


class HybridMemoryRetriever(MemoryRetriever):
    """Two-stage retrieval fusion: semantic search + exact match filtering."""

    def __init__(self, vector_store: VectorStore, memory_store: MemoryStore) -> None:
        self._vector_store = vector_store
        self._memory_store = memory_store

    def retrieve(self, query: str, profile_id: str, limit: int = 5) -> list[RetrievalResult]:
        # 1. Retrieve candidate IDs via semantic search from vector store
        # Passing profile_id as a filter if Chroma supports it, or we could filter post-retrieval
        vector_results = self._vector_store.search(query, limit=limit * 2, profile_id=profile_id)
        
        results: list[RetrievalResult] = []
        
        # 2. Re-hydrate metadata from reliable structured store and fuse
        for memory_id, similarity_score in vector_results:
            memory = self._memory_store.get(memory_id)
            if memory is None or memory.profile_id != profile_id:
                continue
                
            # Here we could blend similarity_score with memory.confidence or recency
            final_score = similarity_score * memory.confidence
            results.append(RetrievalResult(memory=memory, score=final_score))
            
        # Sort descending by final score
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]


class BoundedContextAssembler(ContextAssembler):
    """Assembles retrieved memories into a bounded context window."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def assemble(self, query: str, profile_id: str, max_tokens: int) -> ContextWindow:
        # Placeholder for assembling logic.
        # In a full implementation, this would:
        # 1. Fetch system prompt tokens.
        # 2. Call Retriever for relevant memories.
        # 3. Fit memories into remaining max_tokens (using a tokenizer).
        
        return ContextWindow(
            system_prompt="You are Shea, a secure agent.",
            memories=[],
            available_tokens=max_tokens
        )