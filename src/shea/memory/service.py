from __future__ import annotations

from shea.memory.contracts import Memory, RetrievalResult
from shea.memory.lifecycle.expiration import MemoryLifecycleEnforcer
from shea.memory.ports import ContextAssembler, MemoryRetriever, MemoryStore, VectorStore


class MemoryService:
    """Coordinates storage, retrieval, and lifecycle of memories.
    
    This facade is the primary entry point for the rest of the application
    to interact with the Memory subsystem.
    """

    def __init__(
        self,
        *,
        memory_store: MemoryStore,
        vector_store: VectorStore,
        retriever: MemoryRetriever,
        assembler: ContextAssembler,
        lifecycle: MemoryLifecycleEnforcer,
    ) -> None:
        self._memory_store = memory_store
        self._vector_store = vector_store
        self._retriever = retriever
        self._assembler = assembler
        self._lifecycle = lifecycle

    def store(self, memory: Memory) -> None:
        """Persist a memory to both structured and semantic stores."""
        # 1. Save to durable relational store
        self._memory_store.save(memory)
        
        # 2. Embed and store for semantic retrieval
        self._vector_store.upsert(
            memory_id=memory.id,
            content=memory.content,
            metadata={
                "profile_id": memory.profile_id,
                "type": memory.type.value,
                "source": memory.source,
                "sensitivity": memory.sensitivity.value,
            }
        )

    def retrieve(self, query: str, profile_id: str, limit: int = 5) -> list[RetrievalResult]:
        """Perform semantic search for relevant memories."""
        return self._retriever.retrieve(query, profile_id, limit)

    def list_active(self, profile_id: str) -> list[Memory]:
        """Return all active memories for a profile."""
        return self._memory_store.get_active(profile_id)

    def delete(self, memory_id: str) -> None:
        """Permanently delete a memory from all stores."""
        self._vector_store.delete(memory_id)
        self._memory_store.delete(memory_id)

    def run_maintenance(self) -> dict[str, int]:
        """Run TTL expiration and hard deletion sweeps."""
        expired = self._lifecycle.expire_memories()
        purged = self._lifecycle.purge_deleted_memories()
        return {"expired": expired, "purged": purged}