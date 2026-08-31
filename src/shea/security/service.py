from __future__ import annotations

from shea.audit.recorder import AuditRecorder
from shea.contracts.enums import TaskState
from shea.contracts.models import Task, ToolRequest
from shea.core.orchestrator import Orchestrator

from .exceptions import SecurityViolationError
from .gate import SecurityGate
from .injection import InjectionScanResult, PromptInjectionDetector


class TaskNotRunningForSecurityCheckError(Exception):
    def __init__(self, task_id: str, actual_state: TaskState) -> None:
        self.task_id = task_id
        self.actual_state = actual_state
        super().__init__(
            f"Task {task_id!r} is not RUNNING (currently {actual_state.value!r}); "
            "security enforcement runs immediately before execution."
        )


class SecurityService:
    """The only caller of `Orchestrator.advance(task_id, "security_halt")`.
    Sits between DecisionService (authorization) and ExecutionService
    (the actual tool call), matching the Architecture doc's "SECURITY
    ENFORCEMENT PLANE" positioned between Capabilities/Tools and
    OS/Internet.

    `enforce()` is a hard pre-execution gate: a violation halts the task
    permanently — SECURITY_HALT has no outgoing transitions (technical
    doc Appendix A) — rather than failing it. A request containing an
    SSRF or path-traversal attempt isn't "try again," it's "something is
    wrong enough to stop."

    `scan_output()` is deliberately softer: it records a security event
    for a detected prompt-injection pattern in untrusted tool output but
    does not itself halt the task. Per research doc Section 11.6, the
    content is data, not authority — audit is what makes that fact
    durable, not an automatic hard stop on this component's say-so alone.
    """

    def __init__(
        self,
        *,
        gate: SecurityGate,
        injection_detector: PromptInjectionDetector,
        orchestrator: Orchestrator,
        audit: AuditRecorder,
    ) -> None:
        self._gate = gate
        self._injection_detector = injection_detector
        self._orchestrator = orchestrator
        self._audit = audit

    def enforce(self, task: Task, request: ToolRequest) -> None:
        if task.state is not TaskState.RUNNING:
            raise TaskNotRunningForSecurityCheckError(task.id, task.state)

        try:
            self._gate.check_request(request)
        except SecurityViolationError as exc:
            self._audit.record(
                actor="security_service",
                component="security.gate",
                event_type="security.violation",
                action="enforce",
                result="blocked",
                request_id=task.request_id,
                task_id=task.id,
                metadata={
                    "tool": request.tool,
                    "category": exc.category,
                    "reason": exc.reason,
                    "severity": "HIGH",
                },
            )
            self._orchestrator.advance(task.id, "security_halt")
            raise

        self._audit.record(
            actor="security_service",
            component="security.gate",
            event_type="security.request_cleared",
            action="enforce",
            result="allowed",
            request_id=task.request_id,
            task_id=task.id,
            metadata={"tool": request.tool},
        )

    def scan_output(self, task: Task, tool_name: str, data: object) -> InjectionScanResult:
        text = data if isinstance(data, str) else str(data)
        result = self._injection_detector.scan(text)

        if result.flagged:
            self._audit.record(
                actor="security_service",
                component="security.injection_detection",
                event_type="security.prompt_injection_detected",
                action="scan_output",
                result="flagged",
                request_id=task.request_id,
                task_id=task.id,
                metadata={
                    "tool": tool_name,
                    "matched_phrases": list(result.matched_phrases),
                    "severity": "MEDIUM",
                },
            )

        return result