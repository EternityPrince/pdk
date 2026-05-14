from __future__ import annotations

import sys

from .analytics import AnalyticsStore, analytics_disabled, command_log_database_path
from .commands import CLI_ERRORS, report_cli_error
from .model_loader import load_env_file
from .parser import build_parser


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        exit_code = args.func(args, sys.stdin, sys.stdout, sys.stderr)
    except CLI_ERRORS as exc:
        _record_command(args, "error", str(exc))
        report_cli_error(args, sys.stderr, exc)
        return 1
    except Exception as exc:
        _record_command(args, "error", exc.__class__.__name__)
        raise
    _record_command(args, "ok" if exit_code == 0 else "error", None if exit_code == 0 else str(exit_code))
    return exit_code


def _record_command(args, status: str, detail: str | None) -> None:
    if analytics_disabled():
        return
    try:
        AnalyticsStore(command_log_database_path(args)).record_command(args, status=status, detail=detail)
    except Exception:
        return


if __name__ == "__main__":
    raise SystemExit(main())
