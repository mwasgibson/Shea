from __future__ import annotations

import argparse
from collections.abc import Sequence

from shea.bootstrap import build_runtime


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Start the Shea runtime.")
    parser.add_argument(
        "--db",
        default="shea.db",
        help="SQLite database path (default: shea.db)",
    )
    args = parser.parse_args(argv)

    build_runtime(args.db)
    print("shea ready; app-plane reconcile done")


if __name__ == "__main__":
    main()