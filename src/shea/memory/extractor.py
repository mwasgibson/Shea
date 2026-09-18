from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from shea.events.bus import EventBus
from shea.events.contracts import Event
from shea.memory.contracts import Memory, MemoryStatus, MemoryType, Sensitivity
from shea.memory.service import MemoryService
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.model_provider import ModelProvider
from shea.ports.repositories import IntentRepository, ToolExecutionRepository

logger = logging.getLogger(__name__)


class MemoryExtractor:
    """Listens for task completion events and extracts important facts/preferences using an LLM."""

    def __init__(
        self,
        event_bus: EventBus,
        memory_service: MemoryService,
        clock: Clock,
        id_generator: IdGenerator,
        intent_repository: IntentRepository,
        tool_execution_repository: ToolExecutionRepository,
        model_provider: ModelProvider,
    ) -> None:
        self._bus = event_bus
        self._memory_service = memory_service
        self._clock = clock
        self._ids = id_generator
        self._intent_repo = intent_repository
        self._tool_repo = tool_execution_repository
        self._model = model_provider
        
        # Subscribe to task state changes
        self._bus.subscribe("task.state_changed", self._on_task_state_changed, handler_priority=10)

    def _on_task_state_changed(self, event: Event) -> None:
        payload = event.payload
        to_state = payload.get("to_state")
        task_id = payload.get("task_id")
        
        if to_state == "COMPLETED" and task_id:
            logger.info(f"Task {task_id} completed. Initiating LLM memory extraction...")
            self._extract_from_task(task_id, event.correlation_id)

    def _extract_from_task(self, task_id: str, request_id: str | None) -> None:
        intent = self._intent_repo.get_by_task(task_id)
        if not intent:
            return

        executions = self._tool_repo.list_by_task(task_id)
        
        # Build prompt to extract memories
        transcript = f"User Goal: {intent.goal}\n"
        transcript += f"Intent Type: {intent.type}\n\n"
        for ex in executions:
            transcript += f"Tool: {ex.tool} Action: {ex.action} Success: {ex.success}\n"
            if ex.data:
                transcript += f"Result: {ex.data}\n"
                
        prompt = f"""Analyze the following task transcript and extract any persistent facts or user preferences.
A PREFERENCE is something the user explicitly wants or prefers (e.g. "I like dark mode", "always use JSON").
A FACT is a concrete objective reality established during the task.

Transcript:
{transcript}

Return the extracted memories as a JSON object with a single key "memories" containing a list of objects with "type" (PREFERENCE or FACT) and "content" (the extracted string).
If there is nothing persistent to remember, return {{"memories": []}}.
"""
        
        response = self._model.generate(prompt)
        
        try:
            data: dict[str, Any]
            if response.structured_data:
                data = response.structured_data
            else:
                # Naive json parsing fallback
                text = response.content
                start = text.find('{')
                end = text.rfind('}')
                if start != -1 and end != -1:
                    data = json.loads(text[start:end+1])
                else:
                    data = {"memories": []}
                    
            extracted = data.get("memories", [])
        except Exception as e:
            logger.error(f"Failed to parse memory extraction: {e}")
            return
            
        profile_id = intent.parameters.get("profile_id", "default_user")

        for item in extracted:
            content = item.get("content")
            mem_type_str = item.get("type", "FACT").upper()
            if not content:
                continue
                
            try:
                mem_type = MemoryType(mem_type_str)
            except ValueError:
                mem_type = MemoryType.FACT
                
            self._process_extracted_memory(content, mem_type, profile_id, task_id, request_id)

    def _process_extracted_memory(self, content: str, mem_type: MemoryType, profile_id: str, task_id: str, request_id: str | None) -> None:
        # Search for semantically similar memories to detect duplicates or conflicts
        similar_results = self._memory_service.retrieve(content, profile_id=profile_id, limit=3)
        
        # Only care about highly similar memories
        candidates = [r.memory for r in similar_results if r.score > 0.8]
        
        for old_mem in candidates:
            if old_mem.type != mem_type:
                continue
                
            # Ask LLM if they conflict or duplicate
            conflict_prompt = f"""Given the old memory and the new extracted memory, determine the relationship.
Old Memory: {old_mem.content}
New Memory: {content}

Return a JSON object with a single key "resolution" that is one of:
- "DUPLICATE": The new memory is semantically identical to the old one.
- "UPDATE": The new memory contradicts or supersedes the old memory (e.g. preference changed).
- "DISTINCT": They are different and both should be kept.
"""
            resp = self._model.generate(conflict_prompt)
            resolution = "DISTINCT"
            
            if resp.structured_data:
                resolution = resp.structured_data.get("resolution", "DISTINCT")
            else:
                if "DUPLICATE" in resp.content.upper():
                    resolution = "DUPLICATE"
                elif "UPDATE" in resp.content.upper():
                    resolution = "UPDATE"
                    
            if resolution == "DUPLICATE":
                logger.info(f"Memory '{content}' is a duplicate of {old_mem.id}. Bumping timestamp.")
                updated_mem = replace(old_mem, updated_at=self._clock.now())
                self._memory_service.store(updated_mem)
                return
                
            elif resolution == "UPDATE":
                logger.info(f"Memory '{content}' updates {old_mem.id}. Expiring old memory.")
                expired_mem = replace(old_mem, status=MemoryStatus.EXPIRED, updated_at=self._clock.now())
                self._memory_service.store(expired_mem)
                # Keep going to insert the new memory below
                break
                
        # If we got here, it's either DISTINCT or an UPDATE of an old one. Store new memory.
        new_memory = Memory(
            id=self._ids.new_id(),
            profile_id=profile_id,
            type=mem_type,
            content=content,
            source="llm_extraction",
            provenance=request_id or task_id,
            created_at=self._clock.now(),
            confidence=0.9,
            sensitivity=Sensitivity.INTERNAL,
            status=MemoryStatus.ACTIVE
        )
        self._memory_service.store(new_memory)
        logger.info(f"Stored new memory {new_memory.id}: '{content}'")
