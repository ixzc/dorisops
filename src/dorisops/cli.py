from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dorisops import __version__
from dorisops.case import (
    CaseStoreError,
    default_store,
    load_case,
    open_case,
    save_case,
)
from dorisops.engine import refuse_case, reply_case
from dorisops.playbook import PlaybookError, load_all, match
from dorisops.render import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dorisops")
    parser.add_argument("--version", action="version", version=f"dorisops {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    case_p = sub.add_parser("case", help="L0 diagnosis cases")
    case_sub = case_p.add_subparsers(dest="case_cmd", required=True)

    open_p = case_sub.add_parser("open", help="Open a case from alert text (no cluster I/O)")
    _add_store(open_p)
    _add_playbook_dir(open_p)
    open_p.add_argument("--alert", required=True, help="Raw alert text")
    open_p.add_argument(
        "--mode",
        choices=("integrated", "cloud"),
        required=True,
        help="integrated = shared-nothing; cloud = storage-compute separation",
    )

    show_p = case_sub.add_parser("show", help="Show a case without querying the cluster")
    _add_store(show_p)
    show_p.add_argument("case_id")

    reply_p = case_sub.add_parser("reply", help="Paste command output; advance the decision tree")
    _add_store(reply_p)
    _add_playbook_dir(reply_p)
    reply_p.add_argument("case_id")
    reply_p.add_argument(
        "--output-file",
        type=Path,
        required=True,
        help="File you captured locally (program does not run the command)",
    )

    refuse_p = case_sub.add_parser("refuse", help="Record why a command pack cannot be run")
    _add_store(refuse_p)
    refuse_p.add_argument("case_id")
    refuse_p.add_argument("--reason", required=True, help="Why the pack was not executed")

    args = parser.parse_args(argv)
    if args.cmd != "case":
        parser.error("unknown command")
        return 2
    if args.case_cmd == "open":
        return _cmd_open(args)
    if args.case_cmd == "show":
        return _cmd_show(args)
    if args.case_cmd == "reply":
        return _cmd_reply(args)
    if args.case_cmd == "refuse":
        return _cmd_refuse(args)
    parser.error("unknown command")
    return 2


def _add_store(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        type=Path,
        default=None,
        help="Directory for case JSON (default: $DORISOPS_HOME/cases or ~/.dorisops/cases)",
    )


def _add_playbook_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--playbook-dir",
        action="append",
        type=Path,
        default=[],
        help="Extra playbook directory (repeatable). Built-in pack always loads.",
    )


def _store(args: argparse.Namespace) -> Path:
    return args.store or default_store()


def _load_books(args: argparse.Namespace):
    return load_all(list(getattr(args, "playbook_dir", []) or []))


def _cmd_open(args: argparse.Namespace) -> int:
    try:
        books = _load_books(args)
    except PlaybookError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    book = match(args.alert, args.mode, books)
    case = open_case(args.alert, args.mode, book)
    path = save_case(case, _store(args))
    sys.stdout.write(render(case))
    sys.stdout.write(f"saved: {path}\n")
    return 0 if book else 2


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        case = load_case(_store(args), args.case_id)
    except CaseStoreError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(render(case))
    return 0


def _cmd_reply(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        case = load_case(store, args.case_id)
        books = _load_books(args)
    except (CaseStoreError, PlaybookError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    path: Path = args.output_file
    if not path.is_file():
        sys.stderr.write(f"error: output file not found: {path}\n")
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    book = None
    if case.playbook_id:
        book = next((item for item in books if item.id == case.playbook_id), None)
    try:
        reply_case(case, text, str(path), book)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    saved = save_case(case, store, replace=True)
    sys.stdout.write(render(case))
    sys.stdout.write(f"saved: {saved}\n")
    return 0


def _cmd_refuse(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        case = load_case(store, args.case_id)
        refuse_case(case, args.reason)
    except (CaseStoreError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    saved = save_case(case, store, replace=True)
    sys.stdout.write(render(case))
    sys.stdout.write(f"saved: {saved}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
