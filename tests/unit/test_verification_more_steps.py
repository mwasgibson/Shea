from __future__ import annotations

from typing import Any

from shea.contracts.enums import TaskState


def test_verify_default_completes_task(verification_service: Any, verifying_task: Any) -> None:
    result = verification_service.verify(verifying_task)
    assert result.verification.verified is True
    assert result.task.state is TaskState.COMPLETED


def test_verify_more_steps_returns_to_ready(verification_service: Any, verifying_task: Any) -> None:
    result = verification_service.verify(verifying_task, more_steps=True)
    assert result.verification.verified is True
    assert result.task.state is TaskState.READY