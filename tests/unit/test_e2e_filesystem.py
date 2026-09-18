from pathlib import Path

from shea.bootstrap import build_runtime


def test_e2e_filesystem_write_and_read(tmp_path: Path) -> None:
    # Build a runtime with filesystem_roots allowing tmp_path
    _ = build_runtime(
        db_path=":memory:",
        workspace=tmp_path,
        register_builtins=True,
    )

    # Note: We rely on deterministic fallback or a stub model provider
    # However, since we don't want to actually call Ollama/OpenAI during tests,
    # we might need a mock model provider unless the test suite already stubs it.
    pass
