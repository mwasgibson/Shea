from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from shea.bootstrap import build_runtime


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Shea runtime")
    parser.add_argument("--db", default="shea.db", help="SQLite database path")
    parser.add_argument(
        "--workspace",
        default="./workspace",
        help="Allowed filesystem root for builtin tools",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("boot", help="Start runtime and reconcile only")

    run_p = sub.add_parser("run", help="Plan and execute a text request")
    run_p.add_argument("text", help="User request text")
    run_p.add_argument(
        "--no-execute",
        action="store_true",
        help="Plan only (leave task READY)",
    )
    run_p.add_argument("--session", default="cli")

    args = parser.parse_args(argv)
    Path(args.workspace).mkdir(parents=True, exist_ok=True)

    runtime = build_runtime(
        args.db,
        workspace=args.workspace,
        register_builtins=True,
    )

    if args.command is None or args.command == "boot":
        print("shea ready; app-plane reconcile done")
        return

    if args.command == "run":
        result = runtime.interaction_service.handle_text(
            args.text,
            session_id=args.session,
            explicit_user_ack=True,
            run=not args.no_execute,
        )
        print(f"task={result.task.id} state={result.task.state.value}")
        if result.error:
            print(f"error: {result.error}", file=sys.stderr)
            sys.exit(1)
        print(f"plan_steps={len(result.planning.plan.steps)}")
        if result.run is not None:
            print(
                f"completed_steps={result.run.completed_steps} "
                f"stopped_early={result.run.stopped_early}"
            )
        return

    parser.error(f"unknown command {args.command!r}")


if __name__ == "__main__":
    main()