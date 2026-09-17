from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class MemoryType(StrEnum):
    """Classification of the memory content."""

    CONVERSATION = "CONVERSATION"  # Verbatim or summarized dialogue
    FACT = "FACT"                  # Verified objective reality
    PREFERENCE = "PREFERENCE"      # Explicit user preference or instruction
    SKILL = "SKILL"                # Learned capability or workflow pattern
    OBSERVATION = "OBSERVATION"    # Passive environmental observations


class MemoryStatus(StrEnum):
    """Lifecycle status of a memory."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class Sensitivity(StrEnum):
    """Privacy and security tiering for memories."""

    PUBLIC = "PUBLIC"              # Safe to share externally
    INTERNAL = "INTERNAL"          # Safe for agent internal reasoning
    SENSITIVE = "SENSITIVE"        # Requires explicit justification to use
    RESTRICTED = "RESTRICTED"      # High risk, e.g., secrets or auth tokens


@dataclass(frozen=True)
class Memory:
    """A discrete unit of retrieved context."""

    id: str
    profile_id: str
    type: MemoryType
    content: str
    source: str               # e.g., 'interaction', 'planning', 'verification'
    provenance: str           # The request_id, task_id, or interaction_id that produced it
    created_at: datetime
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    confidence: float = 1.0   # 0.0 to 1.0
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    status: MemoryStatus = MemoryStatus.ACTIVE


@dataclass(frozen=True)
class RetrievalResult:
    """A scored memory retrieved from the backing stores."""
    
    memory: Memory
    score: float  # typically 0.0 to 1.0, higher is better


@dataclass(frozen=True)
class ContextWindow:
    """The assembled context provided to the model."""
    
    system_prompt: str
    memories: list[Memory] = field(default_factory=list[Memory])
    available_tokens: int = 0