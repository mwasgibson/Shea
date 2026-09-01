from __future__ import annotations

from shea.recovery.idempotency import IdempotencyKeyGenerator


def test_same_operation_produces_same_key() -> None:
    arguments = {
        "recipient": "[test@example.com](mailto:test@example.com)",
        "message": "hello",
    }
    first = IdempotencyKeyGenerator.generate(
        task_id="task-1",
        tool="email",
        action="send",
        arguments=arguments,
    )
    second = IdempotencyKeyGenerator.generate(
       task_id="task-1",
       tool="email",
       action="send",
       arguments=arguments,
    )
    assert first == second

def test_argument_order_does_not_change_key() -> None:
    first = IdempotencyKeyGenerator.generate(
        task_id="task-1",
        tool="email",
        action="send",
        arguments={
            "recipient": "[test@example.com](mailto:test@example.com)",
            "message": "hello",
        },
    )
    second = IdempotencyKeyGenerator.generate(
        task_id="task-1",
        tool="email",
        action="send",
        arguments={
            "message": "hello",
            "recipient": "[test@example.com](mailto:test@example.com)",
        },
    )
    assert first == second

def test_different_arguments_produce_different_keys() -> None:
    first = IdempotencyKeyGenerator.generate(
        task_id="task-1",
        tool="email",
        action="send",
        arguments={"recipient": "[a@example.com](mailto:a@example.com)"},
    )
    second = IdempotencyKeyGenerator.generate(
        task_id="task-1",
        tool="email",
        action="send",
        arguments={"recipient": "[b@example.com](mailto:b@example.com)"},
    )
    assert first != second

def test_different_actions_produce_different_keys() -> None:
    first = IdempotencyKeyGenerator.generate(
        task_id="task-1",
        tool="email",
        action="send",
        arguments={},
    )
    second = IdempotencyKeyGenerator.generate(
        task_id="task-1",
        tool="email",
        action="delete",
        arguments={},
    )
    assert first != second

def test_key_is_sha256_hex() -> None:
    key = IdempotencyKeyGenerator.generate(
        task_id="task-1",
        tool="test",
        action="run",
        arguments={},
    )
    assert len(key) == 64
    assert all(character in "0123456789abcdef" for character in key)