from __future__ import annotations

import argparse
import sys

from transprot.cli import run_self_check
from transprot.core.errors import ConfigurationError, SecretStoreError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TransProt 屏幕 OCR 与翻译工具。")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="执行环境自检，不启动桌面界面。",
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
                "未安装 PySide6。请先执行 `pip install -e .[desktop]`，"
                "或者使用 `python -m transprot --self-check` 检查当前环境。",
                file=sys.stderr,
            )
            return 1
        raise

    try:
        return launch_app()
    except (ConfigurationError, SecretStoreError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
