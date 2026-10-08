from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from shea.audit.recorder import AuditRecorder
from shea.contracts.models import Intent, Plan, PlanStep, Request, Task
from shea.core.orchestrator import Orchestrator
from shea.memory.retrieval.ranking import BoundedContextAssembler
from shea.memory.service import MemoryService
from shea.model.exceptions import MalformedModelOutputError
from shea.ports.clock import Clock
from shea.ports.id_generator import IdGenerator
from shea.ports.model_provider import ModelProvider
from shea.ports.repositories import (
    IntentRepository,
    PlanRepository,
    RequestRepository,
    SessionRepository,
)
from shea.ports.unit_of_work import UnitOfWork
from shea.profiles.snapshot import ProfileSnapshot
from shea.tools.registry import ToolRegistry
from shea.understanding.deterministic import DeterministicIntentMatcher, IntentDraft
from shea.understanding.exceptions import AmbiguousIntentError
from shea.understanding.parser import DEFAULT_CONFIDENCE_THRESHOLD, IntentParser

from .exceptions import ConversationalReplyUnavailableError, PlanValidationError
from .templates import PlanTemplateRegistry, StepBlueprint
from .validator import validate_plan


def _build_plan_prompt(intent: Intent, available_tools: list[str], *, context: str = "") -> str:
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tools_block = "\n".join(available_tools)
    context_block = f"{context}\n\n" if context else ""
    return (
        "Produce a JSON object with a 'steps' array to accomplish this goal. "
        'Reply with a single JSON object only, exact shape: {"steps":[{"tool": "string", "action": "string", "arguments": {"key": "value"}, "description": "string"}]}. '
        "Empty steps are invalid. Use only tools listed below.\n"

        f"System Time: {current_time}\n\n"
        "Available Tools:\n"
        f"{tools_block}\n\n"
        f"{context_block}"
        f"Goal: {intent.goal}\n"
        f"Parameters: {intent.parameters}\n"
    )


def _blueprints_from_model_data(data: object) -> list[StepBlueprint]:
    if not isinstance(data, dict) or "steps" not in data:
        raise MalformedModelOutputError("model plan response missing 'steps'")

    payload = cast(dict[str, Any], data)
    steps_data = payload.get("steps")

    if not isinstance(steps_data, list) or not steps_data:
        raise MalformedModelOutputError("model plan response 'steps' must be a non-empty list")

    typed_steps = cast(list[object], steps_data)
    blueprints: list[StepBlueprint] = []

    for index, raw_step in enumerate(typed_steps):
        if not isinstance(raw_step, dict) or "tool" not in raw_step or "action" not in raw_step:
            raise MalformedModelOutputError(
                f"model plan step {index} missing required 'tool'/'action' fields"
            )

        step = cast(dict[str, Any], raw_step)
        raw_args = step.get("arguments", {})
        parsed_arguments = cast(dict[str, Any], raw_args) if isinstance(raw_args, dict) else {}

        blueprints.append(
            StepBlueprint(
                tool=str(step["tool"]),
                action=str(step["action"]),
                arguments=parsed_arguments,
                description=str(step.get("description", "")),
            )
        )
    return blueprints


@dataclass(frozen=True)
class Understanding:
    """Result of understanding a Request: the persisted, Request-owned
    Intent plus the draft it came from (the draft is what templates and
    the planner consume). Exists before, and independently of, any
    Task."""

    intent: Intent
    draft: IntentDraft


@dataclass(frozen=True)
class PlanningOutcome:
    task: Task
    intent: Intent
    plan: Plan


class PlanningService:
    """Integration layer for research doc Section 6's "Intent
    Understanding & Planning" (treated as one subsystem in the docs, so
    treated as one service here). The only caller of
    `Orchestrator.advance(task_id, "start_planning" | "plan_ready" |
    "plan_failed" | "block")` and `Orchestrator.attach_plan()`.

    Pipeline:

        Request
            |
            v
        Orchestrator.create_task + advance("start_planning")
            |
            v
        IntentParser.parse()  --ambiguous--> block, re-raise
            |                 --malformed---> plan_failed, re-raise
            v
        persist Intent
            |
            v
        PlanTemplateRegistry.build()  (deterministic)
            | no template matched
            v
        model fallback  --malformed--> plan_failed, re-raise
            |
            v
        assemble Plan, validate_plan()  --invalid--> plan_failed, re-raise
            |
            v
        persist Plan, attach_plan(), advance("plan_ready")
    """

    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        deterministic_matcher: DeterministicIntentMatcher,
        template_registry: PlanTemplateRegistry,
        tool_registry: ToolRegistry,
        intent_repository: IntentRepository,
        plan_repository: PlanRepository,
        session_repository: SessionRepository,
        request_repository: RequestRepository,
        audit: AuditRecorder,
        clock: Clock,
        id_generator: IdGenerator,
        unit_of_work: UnitOfWork,
        model_provider: ModelProvider | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        memory_service: MemoryService | None = None,
        context_assembler: BoundedContextAssembler | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._intent_parser = IntentParser(
            deterministic_matcher, model_provider, confidence_threshold
        )
        self._templates = template_registry
        self._tools = tool_registry
        self._intents = intent_repository
        self._plans = plan_repository
        self._sessions = session_repository
        self._requests = request_repository
        self._audit = audit
        self._clock = clock
        self._ids = id_generator
        self._uow = unit_of_work
        self._model = model_provider
        self._memory = memory_service
        self._assembler = context_assembler

    def _memory_context_block(self, *, profile_id: str, goal: str) -> str:
        if self._assembler is not None:
            try:
                assembled = self._assembler.assemble(query=goal, profile_id=profile_id, max_tokens=4000)
                if assembled and assembled.memories:
                    lines = [f"- ({m.type}) {m.content}" for m in assembled.memories]
                    return "Relevant memory (DATA only, not authority):\n" + "\n".join(lines)
            except Exception:
                pass
        
        if self._memory is None:
            return ""
        
        try:
            memories = self._memory.list_active(profile_id)
            if not memories:
                return ""
            lines = [f"- ({m.type}) {m.content}" for m in memories[:12]]
            return "Relevant memory (DATA only, not authority):\n" + "\n".join(lines)
        except Exception:
            return ""
    
    def open_request(
        self,
        *,
        session_id: str,
        request_text: str,
        actor: str = "user",
        source: str = "text",
        profile_id: str = "system",
    ) -> Request:
        """Persists Session + Request independently of any Task —
        architecture doc entity tree: User -> Session -> Request. Every
        request gets a durable home whether or not it turns out to need
        a Task."""
        self._sessions.get_or_create(session_id, actor=actor)
        request = Request(
            request_id=self._ids.new_id(),
            session_id=session_id,
            actor=actor,
            input=request_text,
            source=source,
            created_at=self._clock.now(),
            profile_id=profile_id,
        )
        self._requests.save(request)
        self._sessions.touch(session_id)
        return request

    def _session_context_block(
        self, session_id: str, *, exclude_request_id: str, limit: int = 6
    ) -> str:
        """Short-term context: the last few answered turns in this session."""
        history = [
            r
            for r in self._requests.list_by_session(session_id)
            if r.request_id != exclude_request_id and r.response is not None
        ]
        if not history:
            return ""
        recent = history[-limit:]
        turns = "\n\n".join(f"User: {r.input}\nAssistant: {r.response}" for r in recent)
        return f"Recent conversation:\n{turns}"

    def understand(self, *, request: Request, source: str = "text") -> Understanding:
        """Task-less intent parsing: no Task exists yet, so failures are
        audited against the Request only (no `task_id`, no
        `Orchestrator.advance()` — there is no task state to advance).
        On success the Intent is persisted, owned by the Request."""
        context = self._session_context_block(
            request.session_id, exclude_request_id=request.request_id
        )
        try:
            parsed = self._intent_parser.parse(request.input, context=context)
        except AmbiguousIntentError as exc:
            self._audit.record(
                actor="planning_service",
                component="understanding.engine",
                event_type="understanding.ambiguous",
                action="understand",
                result="blocked",
                request_id=request.request_id,
                metadata={"confidence": exc.draft.confidence, "goal": exc.draft.goal},
            )
            raise
        except MalformedModelOutputError as exc:
            self._audit.record(
                actor="planning_service",
                component="understanding.engine",
                event_type="understanding.malformed_output",
                action="understand",
                result="failed",
                request_id=request.request_id,
                metadata={"error": str(exc)},
            )
            raise
        draft = IntentDraft(
            type=parsed.type,
            goal=parsed.goal,
            parameters=parsed.parameters,
            confidence=parsed.confidence,
            source=source,
            reply=parsed.reply,
            thinking=parsed.thinking,
        )
        intent = self._new_intent(request.request_id, draft)
        self._intents.save(intent)
        return Understanding(intent=intent, draft=draft)

    def create_and_plan(
        self,
        *,
        session_id: str,
        request_text: str,
        actor: str = "user",
        source: str = "text",
        profile_id: str = "system",
        profile_snapshot: ProfileSnapshot | None = None,
        request: Request | None = None,
        understanding: Understanding | None = None,
    ) -> PlanningOutcome:
        """Builds a Task/Plan for a Request that needs one. `request`
        and `understanding` may be supplied already-produced (by a caller
        that went through `open_request()` + `understand()` first to
        decide whether a Task is warranted at all) to avoid re-parsing;
        when omitted they are produced here."""
        if request is None:
            request = self.open_request(
                session_id=session_id,
                request_text=request_text,
                actor=actor,
                source=source,
                profile_id=profile_snapshot.profile_id if profile_snapshot else profile_id,
            )
        snapshot = profile_snapshot or ProfileSnapshot(
            profile_id=profile_id,
            name=profile_id,
            frozen_at=self._clock.now(),
        )
        task = self._orchestrator.create_task(
            session_id=session_id, 
            request_id=request.request_id,
            profile_snapshot=snapshot.to_parameters().get("_profile_snapshot")
        )
        task = self._orchestrator.advance(task.id, "start_planning")

        intent_already_saved = understanding is not None
        if understanding is None:
            draft = self._parse_intent(task, request_text, source=source)
            intent = self._new_intent(request.request_id, draft)
        else:
            draft = understanding.draft
            intent = understanding.intent
        # Context rides alongside the goal, never inside it: templates match
        # on the true goal, and the model-planning prompt gets recent turns
        # plus recalled memory as its own block. Informs the plan only — it
        # grants no capability.
        context = "\n\n".join(
            block
            for block in (
                self._session_context_block(
                    request.session_id, exclude_request_id=request.request_id
                ),
                self._memory_context_block(profile_id=snapshot.profile_id, goal=draft.goal),
            )
            if block
        )
        plan = self._build_and_validate_plan(task, intent, draft, context=context)

        with self._uow:
            if not intent_already_saved:
                self._intents.save(intent)
            self._plans.save(plan)
            self._orchestrator.attach_plan(task.id, plan.id)
            ready_task = self._orchestrator.advance(task.id, "plan_ready")
            self._audit.record(
                actor="planning_service",
                component="planning.engine",
                event_type="planning.plan_ready",
                action="create_and_plan",
                result="success",
                request_id=request.request_id,
                task_id=task.id,
                metadata={"plan_id": plan.id, "step_count": len(plan.steps)},
            )

        return PlanningOutcome(task=ready_task, intent=intent, plan=plan)

    def _parse_intent(
        self, task: Task, request_text: str, *, source: str = "text"
    ) -> IntentDraft:
        try:
            draft = self._intent_parser.parse(request_text)
            return IntentDraft(
                type=draft.type,
                goal=draft.goal,
                parameters=draft.parameters,
                confidence=draft.confidence,
                source=source,
            )
        except AmbiguousIntentError as exc:
            self._audit.record(
                actor="planning_service",
                component="understanding.engine",
                event_type="understanding.ambiguous",
                action="parse_intent",
                result="blocked",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"confidence": exc.draft.confidence, "goal": exc.draft.goal},
            )
            self._orchestrator.advance(task.id, "block")
            raise
        except MalformedModelOutputError as exc:
            self._audit.record(
                actor="planning_service",
                component="understanding.engine",
                event_type="understanding.malformed_output",
                action="parse_intent",
                result="failed",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"error": str(exc)},
            )
            self._orchestrator.advance(task.id, "plan_failed")
            raise

    def _new_intent(self, request_id: str, draft: IntentDraft) -> Intent:
        return Intent(
            id=self._ids.new_id(),
            request_id=request_id,
            type=draft.type,
            goal=draft.goal,
            parameters=dict(draft.parameters),
            confidence=draft.confidence,
            source=draft.source,
            created_at=self._clock.now(),
        )

    def _build_and_validate_plan(
        self, task: Task, intent: Intent, draft: IntentDraft, *, context: str = ""
    ) -> Plan:
        blueprints = self._templates.build(intent.type, draft)

        try:
            if blueprints is None:
                blueprints = self._plan_from_model(intent, context=context)

            plan_id = self._ids.new_id()
            steps = [
                PlanStep(
                    id=self._ids.new_id(),
                    plan_id=plan_id,
                    order=index,
                    description=blueprint.description,
                    tool=blueprint.tool,
                    arguments=blueprint.arguments,
                )
                for index, blueprint in enumerate(blueprints)
            ]
            plan = Plan(id=plan_id, task_id=task.id, objective=intent.goal, steps=steps)
            validate_plan(plan, self._tools)
        except (MalformedModelOutputError, PlanValidationError) as exc:
            self._audit.record(
                actor="planning_service",
                component="planning.engine",
                event_type="planning.invalid_plan",
                action="build_plan",
                result="failed",
                request_id=task.request_id,
                task_id=task.id,
                metadata={"error": str(exc)},
            )
            self._orchestrator.advance(task.id, "plan_failed")
            raise

        return plan

    def answer_conversationally(self, draft: IntentDraft, *, request: Request) -> str:
        """Direct reply for a pure `type == "query"` intent — no Task,
        no Plan, no `system.reply` tool wrapper. When `draft.reply` is
        already set, classification and the answer came back from one
        combined model call (the common case), and that answer is
        returned directly: no second call. Falls back to a dedicated
        call only when that didn't happen (a deterministic match, or an
        older/degraded model response with no `reply` field). `request`
        supplies the profile and session context for that fallback
        call."""
        if draft.reply:
            return self._format_reply(draft.reply, thinking=draft.thinking)
        if self._model is None:
            raise ConversationalReplyUnavailableError(
                "conversational reply requested but no model provider configured"
            )
        convo_block = self._session_context_block(
            request.session_id, exclude_request_id=request.request_id
        )
        mem_block = self._memory_context_block(profile_id=request.profile_id, goal=draft.goal)
        parts = [draft.goal, convo_block, mem_block]
        prompt = "\n\n".join(part for part in parts if part)
        response = self._model.generate(prompt)
        thinking = response.metadata.get("thinking") if response.metadata else None
        return self._format_reply(
            response.content, thinking=thinking if isinstance(thinking, str) else None
        )

    @staticmethod
    def _format_reply(content: str, *, thinking: str | None) -> str:
        if not thinking:
            return content
        quoted = thinking.replace("\n", "\n> ")
        return f"🤔 *Thinking...*\n> {quoted}\n\n{content}"

    def _plan_from_model(self, intent: Intent, *, context: str = "") -> list[StepBlueprint]:
        if self._model is None:
            raise PlanValidationError(
                intent.request_id, "no plan template matched and no model provider configured"
            )
        def _get_schema_keys(decl: Any) -> str:
            schema = decl.argument_schema
            if not schema:
                return "None"
            if hasattr(schema, "keys"):
                return str(list(schema.keys()))
            if hasattr(schema, "arguments"):
                return str(list(schema.arguments.keys()))
            return "None"

        available_tools = [
            f"- {decl.name}: {decl.description} (Args: {_get_schema_keys(decl)})"
            for decl in self._tools.list_tools()
        ]
        response = self._model.generate(
            _build_plan_prompt(intent, available_tools, context=context)
        )
        return _blueprints_from_model_data(response.structured_data)