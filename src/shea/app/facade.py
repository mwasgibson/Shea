from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shea.app.interaction.service import InteractionResult
    from shea.bootstrap import SheaRuntime
    from shea.contracts.models import Task


class SheaApp:
    """Narrow public facade for the Shea Agent Runtime.
    
    Hides internal services (Decision, Recovery, Verification, Memory, etc.)
    and provides a strict boundary for external applications embedding Shea.
    """

    def __init__(self, runtime: SheaRuntime) -> None:
        self._runtime = runtime

    def reconcile(self) -> None:
        """Complete application-plane and stranded-task reconciliations."""
        self._runtime.reconcile_app_plane()
        self._runtime.reconcile_stranded_tasks()

    def chat(self, text: str, session_id: str = "default", run: bool = True, explicit_user_ack: bool = True) -> InteractionResult:
        """Submit a user request for planning and execution."""
        return self._runtime.interaction_service.handle_text(
            text,
            session_id=session_id,
            explicit_user_ack=explicit_user_ack,
            run=run,
        )

    def cancel_task(self, task_id: str) -> Task:
        """Cancel an ongoing task, enforcing the concurrency cancellation model."""
        return self._runtime.orchestrator.cancel_task(task_id, reason="Cancelled via App Facade")
