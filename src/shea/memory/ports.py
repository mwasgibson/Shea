from __future__ import annotations

from typing import Protocol

from .contracts import ContextWindow, Memory, RetrievalResult


class MemoryStore(Protocol):
    """Durable relational storage for Memory metadata and content."""

    def save(self, memory: Memory) -> None:
        """Persist or update the memory."""
        ...

    def get(self, memory_id: str) -> Memory | None:
        """Retrieve a specific memory by ID."""
        ...

    def delete(self, memory_id: str) -> None:
        """Hard delete a memory from the store."""
        ...

    def get_active(self, profile_id: str) -> list[Memory]:
        """Return all non-expired, non-deleted memories for a profile."""
        ...


class VectorStore(Protocol):
    """Semantic embedding storage for memories."""

    def upsert(self, memory_id: str, content: str, metadata: dict[str, str]) -> None:
        """Embed and store the memory content."""
        ...

    def search(self, query: str, limit: int = 10, **filters: str) -> list[tuple[str, float]]:
        """Semantic search returning (memory_id, score) pairs."""
        ...

    def delete(self, memory_id: str) -> None:
        """Remove the memory from the semantic index."""
        ...


class MemoryRetriever(Protocol):
    """Service boundary for context retrieval."""

    def retrieve(self, query: str, profile_id: str, limit: int = 5) -> list[RetrievalResult]:
        """Perform two-stage hybrid retrieval for the query."""
        ...


class ContextAssembler(Protocol):
    """Assembles retrieved memories into a bounded context window."""

    def assemble(self, query: str, profile_id: str, max_tokens: int) -> ContextWindow:
        """Build the context window for a given request."""
        ...