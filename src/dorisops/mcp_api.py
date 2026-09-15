from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

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

TOOL_NAMES = (
    "case_open",
    "case_show",
    "case_reply",
    "case_refuse",
    "inspect_cluster",
)

L0_NO_INVENT = (
    "MCP: level is L0. Do not invent Alive, replica counts, or topology. "
    "Need a real cluster.yaml with read-only credentials, or use case_open for an L0 diagnosis case."
)


@dataclass
class McpSession:
    store: Path
    extra_dirs: list[Path] = field(default_factory=list)
    cluster: Path | None = None

    def case_open(self, alert: str, mode: str) -> str:
        try:
            case, path, matched = open_from_alert(
                alert, mode, self.store, self.extra_dirs
            )
        except (PlaybookError, ValueError) as exc:
            return f"error: {exc}"
        text = render(case) + f"saved: {path}\n"
        if not matched:
            text += (
                "\nPlaybook unmatched or mode mismatch. "
                "Do not invent cluster facts. Re-open with the other --mode if hinted.\n"
            )
        return text

    def case_show(self, case_id: str) -> str:
        try:
            return render(show_from_id(self.store, case_id.strip()))
        except CaseStoreError as exc:
            return f"error: {exc}"

    def case_reply(self, case_id: str, output: str) -> str:
        text = output
        if not text.strip():
            return "error: provide output (pasted command stdout). The server does not read arbitrary files."
        try:
            case = reply_from_text(
                self.store,
                case_id.strip(),
                text,
                self.extra_dirs,
                source="mcp",
            )
        except (CaseStoreError, PlaybookError, ValueError) as exc:
            return f"error: {exc}"
        return render(case)

    def case_refuse(self, case_id: str, reason: str) -> str:
        try:
            case = refuse_from_reason(self.store, case_id.strip(), reason)
        except (CaseStoreError, ValueError) as exc:
            return f"error: {exc}"
        return render(case)

    def inspect_cluster(self, cluster_path: str = "", query_id: str = "") -> str:
        raw = cluster_path.strip()
        path: Path | None
        if raw:
            path = Path(raw)
        elif self.cluster is not None:
            path = self.cluster
        else:
            path = None
        qid = query_id.strip() or None
        try:
            report, _code = inspect_from_path(path, query_id=qid)
        except (OSError, ValueError) as exc:
            return f"error: {exc}\n{L0_NO_INVENT}\n"
        text = report.to_text()
        if report.level == "L0":
            text += "\n" + L0_NO_INVENT + "\n"
        return text


def session_from_env(
    store: Path | None = None,
    extra_dirs: list[Path] | None = None,
    cluster: Path | None = None,
) -> McpSession:
    if cluster is None:
        env = os.environ.get("DORISOPS_CLUSTER", "").strip()
        cluster = Path(env) if env else None
    return McpSession(
        store=store or default_store(),
        extra_dirs=list(extra_dirs or []),
        cluster=cluster,
    )
