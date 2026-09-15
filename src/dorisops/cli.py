from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dorisops import __version__
from dorisops.case import CaseStoreError, default_store
from dorisops.playbook import PlaybookError
from dorisops.render import render
from dorisops.service import (
    inspect_from_path,
    open_from_alert,
    refuse_from_reason,
    reply_from_text,
    show_from_id,
)


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

    web_p = sub.add_parser("web", help="Local L0 browser UI (loopback only)")
    _add_store(web_p)
    _add_playbook_dir(web_p)
    web_p.add_argument(
        "--bind",
        default="127.0.0.1:8787",
        help="Loopback host:port (default 127.0.0.1:8787). Public binds are rejected.",
    )

    insp_p = sub.add_parser(
        "inspect",
        help="L1 read-only probe (downgrades to L0 without credentials)",
    )
    insp_p.add_argument(
        "--cluster",
        type=Path,
        default=None,
        help="cluster.yaml with read-only FE MySQL + HTTP. Omit to stay on L0.",
    )
    insp_p.add_argument(
        "--query-id",
        default=None,
        help="Optional. Fetch FE /api/profile for this query_id (read-only).",
    )

    mcp_p = sub.add_parser("mcp", help="Stdio MCP server for Cursor (read-only tools)")
    _add_store(mcp_p)
    _add_playbook_dir(mcp_p)
    mcp_p.add_argument(
        "--cluster",
        type=Path,
        default=None,
        help="Default cluster.yaml for inspect_cluster (or $DORISOPS_CLUSTER).",
    )

    args = parser.parse_args(argv)
    if args.cmd == "web":
        return _cmd_web(args)
    if args.cmd == "inspect":
        return _cmd_inspect(args)
    if args.cmd == "mcp":
        return _cmd_mcp(args)
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


def _dirs(args: argparse.Namespace) -> list[Path]:
    return list(getattr(args, "playbook_dir", []) or [])


def _cmd_open(args: argparse.Namespace) -> int:
    try:
        case, path, matched = open_from_alert(args.alert, args.mode, _store(args), _dirs(args))
    except (PlaybookError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(render(case))
    sys.stdout.write(f"saved: {path}\n")
    return 0 if matched else 2


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        case = show_from_id(_store(args), args.case_id)
    except CaseStoreError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(render(case))
    return 0


def _cmd_reply(args: argparse.Namespace) -> int:
    path: Path = args.output_file
    if not path.is_file():
        sys.stderr.write(f"error: output file not found: {path}\n")
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        case = reply_from_text(
            _store(args),
            args.case_id,
            text,
            _dirs(args),
            source=str(path),
        )
    except (CaseStoreError, PlaybookError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(render(case))
    sys.stdout.write(f"saved: {_store(args) / (case.id + '.json')}\n")
    return 0


def _cmd_refuse(args: argparse.Namespace) -> int:
    try:
        case = refuse_from_reason(_store(args), args.case_id, args.reason)
    except (CaseStoreError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(render(case))
    sys.stdout.write(f"saved: {_store(args) / (case.id + '.json')}\n")
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    from dorisops.web import parse_bind, serve

    try:
        host, port = parse_bind(args.bind)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    serve(host, port, _store(args), _dirs(args))
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    from dorisops.cluster import ClusterError
    from dorisops.inspect import InspectError

    try:
        report, code = inspect_from_path(args.cluster, query_id=args.query_id)
    except (ClusterError, InspectError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(report.to_text())
    return code


def _cmd_mcp(args: argparse.Namespace) -> int:
    import os

    from dorisops.mcp_api import session_from_env
    from dorisops.mcp_server import serve_stdio

    cluster = args.cluster
    if cluster is None:
        env = os.environ.get("DORISOPS_CLUSTER", "").strip()
        cluster = Path(env) if env else None
    session = session_from_env(_store(args), _dirs(args), cluster)
    try:
        serve_stdio(session)
    except ImportError as exc:
        sys.stderr.write(f"error: {exc}\nInstall with: pip install 'dorisops[mcp]'\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
