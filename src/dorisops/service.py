from __future__ import annotations

from pathlib import Path

from dorisops.case import (
    Case,
    CaseStoreError,
    list_cases,
    load_case,
    open_case,
    save_case,
)
from dorisops.cluster import ClusterConfig, ClusterError, load_cluster_yaml
from dorisops.engine import refuse_case, reply_case
from dorisops.inspect import InspectReport, MysqlTransport, HttpTransport, inspect_cluster, l0_report
from dorisops.playbook import PlaybookError, load_all, match_alert
from dorisops.render import export_report


def load_books(
    extra_dirs: list[Path] | None = None,
    sop_dirs: list[Path] | None = None,
) -> list:
    return load_all(list(extra_dirs or []), list(sop_dirs or []))


def open_from_alert(
    alert: str,
    mode: str,
    store: Path,
    extra_dirs: list[Path] | None = None,
    sop_dirs: list[Path] | None = None,
) -> tuple[Case, Path, bool]:
    text = alert.strip()
    if not text:
        raise ValueError("alert is empty")
    if mode not in {"integrated", "cloud"}:
        raise ValueError("mode must be integrated or cloud")
    hit = match_alert(text, mode, load_books(extra_dirs, sop_dirs))
    case = open_case(text, mode, hit.book, mismatch=hit.mismatch)
    path = save_case(case, store)
    return case, path, hit.book is not None


def show_from_id(store: Path, case_id: str) -> Case:
    return load_case(store, case_id)


def reply_from_text(
    store: Path,
    case_id: str,
    text: str,
    extra_dirs: list[Path] | None = None,
    source: str = "web",
    sop_dirs: list[Path] | None = None,
) -> Case:
    case = load_case(store, case_id)
    books = load_books(extra_dirs, sop_dirs)
    book = None
    if case.playbook_id and not case.mode_mismatch:
        book = next((item for item in books if item.id == case.playbook_id), None)
    reply_case(case, text, source, book)
    save_case(case, store, replace=True)
    return case


def refuse_from_reason(store: Path, case_id: str, reason: str) -> Case:
    case = load_case(store, case_id)
    refuse_case(case, reason)
    save_case(case, store, replace=True)
    return case


def cases_for_index(store: Path) -> list[Case]:
    return list_cases(store)


def export_from_id(store: Path, case_id: str, fmt: str = "md") -> str:
    return export_report(show_from_id(store, case_id), fmt)


def inspect_from_path(
    cluster: Path | None,
    *,
    query_id: str | None = None,
    mysql: MysqlTransport | None = None,
    http: HttpTransport | None = None,
) -> tuple[InspectReport, int]:
    if cluster is None:
        return l0_report("no --cluster given; staying on L0."), 2
    try:
        cfg = load_cluster_yaml(cluster)
    except ClusterError as exc:
        return l0_report(str(exc)), 2
    report = inspect_cluster(cfg, mysql=mysql, http=http, query_id=query_id)
    if report.level == "L0":
        return report, 2
    if any(not probe.ok and not probe.skipped for probe in report.probes):
        return report, 1
    return report, 0


__all__ = [
    "CaseStoreError",
    "ClusterConfig",
    "ClusterError",
    "PlaybookError",
    "cases_for_index",
    "export_from_id",
    "inspect_from_path",
    "open_from_alert",
    "refuse_from_reason",
    "reply_from_text",
    "show_from_id",
]
