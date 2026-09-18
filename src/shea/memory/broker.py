from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from shea.memory.contracts import (
    Memory,
    MemoryProposal,
    MemoryStatus,
    MemoryType,
    ResolutionOutcome,
    Sensitivity,
)
from shea.memory.service import MemoryService
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.model_provider import ModelProvider

logger = logging.getLogger(__name__)

class MemoryBroker:
    """Intermediate layer to enforce memory trust bounds, compute confidence,
    resolve conflicts, and assign lifecycle policies before persistence.
    """

    def __init__(
        self,
        memory_service: MemoryService,
        clock: Clock,
        id_generator: IdGenerator,
        model_provider: ModelProvider,
    ) -> None:
        self._memory_service = memory_service
        self._clock = clock
        self._ids = id_generator
        self._model = model_provider

    def propose(self, proposal: MemoryProposal) -> None:
        """Process a proposed memory through the trust pipeline."""
        logger.info(f"Processing memory proposal: {proposal.content[:50]}...")
        
        # 1. Sensitivity Analysis
        sensitivity = self._analyze_sensitivity(proposal.content)
        
        # 2. Confidence Scoring
        confidence = self._compute_confidence(proposal, sensitivity)

        # 3. Lifecycle Policy
        expires_at = self._compute_expiration(proposal.type)
        
        # 4. Conflict Analysis
        resolution, old_memory = self._resolve_conflicts(proposal)

        now = self._clock.now()

        # 5. Apply Resolution
        if resolution == ResolutionOutcome.DUPLICATE and old_memory:
            logger.info(f"Proposal is duplicate of {old_memory.id}. Bumping timestamp.")
            updated = replace(old_memory, updated_at=now)
            self._memory_service.store(updated)
            return

        if resolution == ResolutionOutcome.UPDATE and old_memory:
            logger.info(f"Proposal updates {old_memory.id}. Expiring old memory.")
            expired = replace(old_memory, status=MemoryStatus.EXPIRED, updated_at=now)
            self._memory_service.store(expired)
            # Continue to insert the new memory

        # 6. Commitment
        new_memory = Memory(
            id=self._ids.new_id(),
            profile_id=proposal.profile_id,
            type=proposal.type,
            content=proposal.content,
            source=proposal.source,
            provenance=proposal.request_id or proposal.task_id,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
            confidence=confidence,
            sensitivity=sensitivity,
            status=MemoryStatus.ACTIVE,
        )
        self._memory_service.store(new_memory)
        logger.info(f"Stored verified memory {new_memory.id}: '{new_memory.content[:50]}'")

    def _analyze_sensitivity(self, content: str) -> Sensitivity:
        """Identify high-risk data (secrets, tokens, PII) to upgrade sensitivity."""
        text = content.lower()
        if "bearer " in text or "sk-" in text or "password" in text or "secret" in text:
            return Sensitivity.RESTRICTED
        if "email" in text or "phone" in text or "address" in text:
            return Sensitivity.SENSITIVE
        # Default for agent reasoning
        return Sensitivity.INTERNAL

    def _compute_confidence(self, proposal: MemoryProposal, sensitivity: Sensitivity) -> float:
        """Determine base confidence. More sensitive data might require higher validation."""
        confidence = proposal.base_confidence
        # Example rule: High sensitivity from an LLM extraction loses some confidence
        if sensitivity in (Sensitivity.RESTRICTED, Sensitivity.SENSITIVE) and proposal.source == "llm_extraction":
            confidence -= 0.2
        return max(0.0, min(1.0, confidence))

    def _compute_expiration(self, mem_type: MemoryType) -> datetime | None:
        """Determine TTL based on memory type."""
        now = self._clock.now()
        if mem_type == MemoryType.FACT:
            return now + timedelta(days=90)
        elif mem_type == MemoryType.OBSERVATION:
            return now + timedelta(days=7)
        # PREFERENCE, SKILL, CONVERSATION (summaries) typically don't expire automatically
        return None

    def _resolve_conflicts(self, proposal: MemoryProposal) -> tuple[ResolutionOutcome, Memory | None]:
        """Search for semantic conflicts and use the model to resolve them deterministically."""
        similar = self._memory_service.retrieve(proposal.content, profile_id=proposal.profile_id, limit=3)
        candidates = [r.memory for r in similar if r.score > 0.8 and r.memory.type == proposal.type]
        
        for old_mem in candidates:
            conflict_prompt = (
                "Given the old memory and the new proposed memory, determine the relationship.\n"
                f"Old Memory: {old_mem.content}\n"
                f"New Memory: {proposal.content}\n\n"
                "Return a JSON object with a single key 'resolution' that is one of:\n"
                "- 'DUPLICATE': The new memory is semantically identical to the old one.\n"
                "- 'UPDATE': The new memory contradicts or supersedes the old memory (e.g. preference changed).\n"
                "- 'DISTINCT': They are different and both should be kept.\n"
            )
            
            resp = self._model.generate(conflict_prompt)
            resolution_str = "DISTINCT"
            
            if resp.structured_data:
                resolution_str = resp.structured_data.get("resolution", "DISTINCT")
            else:
                if "DUPLICATE" in resp.content.upper():
                    resolution_str = "DUPLICATE"
                elif "UPDATE" in resp.content.upper():
                    resolution_str = "UPDATE"
                    
            try:
                outcome = ResolutionOutcome(resolution_str)
            except ValueError:
                outcome = ResolutionOutcome.DISTINCT

            if outcome in (ResolutionOutcome.DUPLICATE, ResolutionOutcome.UPDATE):
                return outcome, old_mem

        return ResolutionOutcome.DISTINCT, None