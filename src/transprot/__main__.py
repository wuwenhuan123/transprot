from __future__ import annotations

import argparse
import sys

from transprot.cli import run_self_check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TransProt screen OCR utility.")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Run environment diagnostics without launching the desktop UI.",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        run_self_check()
        return 0

    try:
        from transprot.app import launch_app
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            print(
                "PySide6 is not installed. Run `pip install -e .[desktop]` first, "
                "or use `python -m transprot --self-check` to inspect the environment.",
                file=sys.stderr,
            )
            return 1
        raise

    return launch_app()


if __name__ == "__main__":
    raise SystemExit(main())
