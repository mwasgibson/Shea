from __future__ import annotations

import json
import logging
from typing import Any

from shea.events.bus import EventBus
from shea.events.contracts import Event
from shea.memory.broker import MemoryBroker
from shea.memory.contracts import MemoryProposal, MemoryType
from shea.ports.model_provider import ModelProvider
from shea.ports.repositories import IntentRepository, ToolExecutionRepository

logger = logging.getLogger(__name__)


class MemoryExtractor:
    """Listens for task completion events and extracts important facts/preferences using an LLM."""

    def __init__(
        self,
        event_bus: EventBus,
        memory_broker: MemoryBroker,
        intent_repository: IntentRepository,
        tool_execution_repository: ToolExecutionRepository,
        model_provider: ModelProvider,
    ) -> None:
        self._bus = event_bus
        self._broker = memory_broker
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
                
            proposal = MemoryProposal(
                profile_id=profile_id,
                type=mem_type,
                content=content,
                source="llm_extraction",
                task_id=task_id,
                request_id=request_id,
                base_confidence=0.8
            )
            self._broker.propose(proposal)