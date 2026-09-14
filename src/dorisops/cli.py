from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dorisops import __version__
from dorisops.case import default_store, open_case, save_case
from dorisops.playbook import PlaybookError, load_all, match
from dorisops.render import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dorisops")
    parser.add_argument("--version", action="version", version=f"dorisops {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    case_p = sub.add_parser("case", help="L0 diagnosis cases")
    case_sub = case_p.add_subparsers(dest="case_cmd", required=True)

    open_p = case_sub.add_parser("open", help="Open a case from alert text (no cluster I/O)")
    open_p.add_argument("--alert", required=True, help="Raw alert text")
    open_p.add_argument(
        "--mode",
        choices=("integrated", "cloud"),
        required=True,
        help="integrated = shared-nothing; cloud = storage-compute separation",
    )
    open_p.add_argument(
        "--store",
        type=Path,
        default=None,
        help="Directory for case JSON (default: $DORISOPS_HOME/cases or ~/.dorisops/cases)",
    )
    open_p.add_argument(
        "--playbook-dir",
        action="append",
        type=Path,
        default=[],
        help="Extra playbook directory (repeatable). Built-in pack always loads.",
    )

    args = parser.parse_args(argv)
    if args.cmd == "case" and args.case_cmd == "open":
        return _cmd_open(args)
    parser.error("unknown command")
    return 2


def _cmd_open(args: argparse.Namespace) -> int:
    try:
        books = load_all(list(args.playbook_dir))
    except PlaybookError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    book = match(args.alert, args.mode, books)
    case = open_case(args.alert, args.mode, book)
    path = save_case(case, args.store or default_store())
    sys.stdout.write(render(case))
    sys.stdout.write(f"saved: {path}\n")
    return 0 if book else 2


if __name__ == "__main__":
    raise SystemExit(main())
