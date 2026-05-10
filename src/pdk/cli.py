from __future__ import annotations

import sys

from .commands import CLI_ERRORS, report_cli_error
from .parser import build_parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args, sys.stdin, sys.stdout, sys.stderr)
    except CLI_ERRORS as exc:
        report_cli_error(args, sys.stderr, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
