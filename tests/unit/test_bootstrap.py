from __future__ import annotations

from pathlib import Path

from shea.bootstrap import build_runtime
from shea.contracts.enums import TaskState
from shea.contracts.models import ModelResponse
from shea.model.scripted import ScriptedModelProvider


def test_build_runtime_starts(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    runtime = build_runtime(tmp_path / "shea.db", workspace=workspace)

    assert runtime.reconcile_app_plane() == []
    names = {tool.name for tool in runtime.tool_registry.list_tools()}
    assert {"filesystem.read", "filesystem.write"} <= names
    runtime.conn.close()


def test_handle_text_write_note_plan_only(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    runtime = build_runtime(tmp_path / "shea.db", workspace=workspace)

    result = runtime.interaction_service.handle_text(
        "write a note",
        run=False,
    )
    assert result.error is None
    assert result.task.state is TaskState.READY
    assert result.planning.plan is not None
    assert len(result.planning.plan.steps) == 1
    assert result.planning.plan.steps[0].tool == "filesystem.write"
    runtime.conn.close()


def test_handle_text_write_note_executes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    runtime = build_runtime(
        tmp_path / "shea.db",
        workspace=workspace,
        allow_unsafe_execution=True,
    )

    result = runtime.interaction_service.handle_text(
        "write a note",
        explicit_user_ack=True,
        run=True,
    )
    assert result.error is None
    assert result.run is not None
    assert result.task.state is TaskState.COMPLETED
    assert result.run.stopped_early is False
    note = workspace / "note.txt"
    assert note.is_file()
    assert note.read_text(encoding="utf-8") == "hello from shea"
    runtime.conn.close()


def test_handle_text_conversational_query_skips_task(tmp_path: Path) -> None:
    """A pure `type == "query"` intent never becomes a Task — no Plan,
    no Decision, no Execution/Verification ceremony for a greeting."""
    workspace = tmp_path / "ws"
    provider = ScriptedModelProvider()
    # 1st call: intent classification. 2nd call: the direct reply.
    provider.queue_response(
        ModelResponse(
            content="",
            structured_data={
                "type": "query",
                "goal": "respond conversationally",
                "confidence": 1.0,
            },
        )
    )
    provider.queue_response(ModelResponse(content="Hey! How can I help?"))

    runtime = build_runtime(tmp_path / "shea.db", workspace=workspace, model_provider=provider)

    result = runtime.interaction_service.handle_text("hi there", run=True)

    assert result.error is None
    assert result.task is None
    assert result.message == "Hey! How can I help?"
    assert result.planning is None
    assert result.run is None
    runtime.conn.close()


def test_handle_text_conversational_query_persists_request(tmp_path: Path) -> None:
    """Even the task-less fast path leaves a durable Request/Session
    trail — the whole point is Request no longer needs a Task to have
    somewhere to live."""
    workspace = tmp_path / "ws"
    provider = ScriptedModelProvider()
    provider.queue_response(
        ModelResponse(
            content="",
            structured_data={"type": "query", "goal": "respond conversationally", "confidence": 1.0},
        )
    )
    provider.queue_response(ModelResponse(content="Sure thing."))

    runtime = build_runtime(tmp_path / "shea.db", workspace=workspace, model_provider=provider)

    runtime.interaction_service.handle_text("hi there", session_id="convo-1", run=True)

    requests = runtime.request_repository.list_by_session("convo-1")
    assert len(requests) == 1
    assert requests[0].input == "hi there"

    # The Intent is owned by the Request even though no Task ever existed.
    intent = runtime.intent_repository.get_by_request(requests[0].request_id)
    assert intent is not None
    assert intent.type == "query"
    runtime.conn.close()


def test_conversational_turn_is_remembered_under_the_requests_profile(tmp_path: Path) -> None:
    """End to end: chat (no Task) -> reply recorded -> memory extracted
    and stored under the profile the request was made with."""
    provider = ScriptedModelProvider()
    provider.queue_response(
        ModelResponse(
            content="",
            structured_data={"type": "query", "goal": "chat", "confidence": 1.0},
        )
    )
    provider.queue_response(ModelResponse(content="Got it, JSON from now on."))
    provider.queue_response(
        ModelResponse(
            content="",
            structured_data={
                "memories": [{"type": "PREFERENCE", "content": "user wants JSON answers"}]
            },
        )
    )
    runtime = build_runtime(tmp_path / "shea.db", workspace=tmp_path / "ws", model_provider=provider)

    result = runtime.interaction_service.handle_text(
        "from now on answer in JSON", profile_id="work", run=True
    )

    assert result.task is None
    request = runtime.request_repository.list_by_session("cli")[0]
    assert request.profile_id == "work"
    assert request.response == "Got it, JSON from now on."
    stored = runtime.memory_service.list_active("work")
    assert [m.content for m in stored] == ["user wants JSON answers"]
    assert stored[0].provenance == request.request_id
    runtime.conn.close()


def _queue_conversational_turn(provider: ScriptedModelProvider, reply: str) -> None:
    """Queue one full conversational turn: classify -> answer -> memory extraction."""
    provider.queue_response(
        ModelResponse(
            content="",
            structured_data={"type": "query", "goal": "chat", "confidence": 1.0},
        )
    )
    provider.queue_response(ModelResponse(content=reply))
    provider.queue_response(ModelResponse(content="", structured_data={"memories": []}))


def test_conversational_follow_up_sees_prior_turn(tmp_path: Path) -> None:
    """The second conversational turn should see the previous answer in context."""
    provider = ScriptedModelProvider()
    _queue_conversational_turn(provider, "Paris is the capital of France.")
    _queue_conversational_turn(provider, "About 2.1 million people.")

    runtime = build_runtime(tmp_path / "shea.db", workspace=tmp_path / "ws", model_provider=provider)

    first = runtime.interaction_service.handle_text("what's the capital of france", run=True)
    assert first.task is None

    second = runtime.interaction_service.handle_text("what's its population", run=True)
    assert second.task is None
    assert second.message == "About 2.1 million people."

    classify_prompt, answer_prompt, _extract_prompt = provider.calls[-3:]
    assert "capital of france" in answer_prompt
    assert "Paris is the capital of France." in answer_prompt
    assert "Paris is the capital of France." in classify_prompt
    runtime.conn.close()


def test_conversational_context_window_is_bounded(tmp_path: Path) -> None:
    provider = ScriptedModelProvider()
    for i in range(8):
        _queue_conversational_turn(provider, f"reply-{i}")

    runtime = build_runtime(tmp_path / "shea.db", workspace=tmp_path / "ws", model_provider=provider)
    for i in range(8):
        runtime.interaction_service.handle_text(f"turn {i}", run=True)

    _classify_prompt, answer_prompt, _extract_prompt = provider.calls[-3:]
    assert "turn 0" not in answer_prompt
    assert "turn 1" in answer_prompt
    runtime.conn.close()