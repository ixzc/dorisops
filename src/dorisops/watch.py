from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
import json
import os
import sys
import tempfile
import time

from dorisops.case import utc_now
from dorisops.inspect import HttpTransport, InspectReport, MysqlTransport
from dorisops.service import inspect_from_path

SNAPSHOT_NAME = "inspect-latest.json"
MIN_INTERVAL = 30
SNAPSHOT_NOTICE = "这是只读巡检快照，不是 Grafana，也不是实时订阅。"


def snapshot_path(store: Path) -> Path:
    return store / SNAPSHOT_NAME


def save_snapshot(store: Path, report: InspectReport, code: int, source: str) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": utc_now(),
        "exit_code": code,
        "source": source,
        "notice": SNAPSHOT_NOTICE,
        **report.to_dict(),
    }
    path = snapshot_path(store)
    fd, tmp_name = tempfile.mkstemp(prefix="inspect-latest.", suffix=".tmp", dir=str(store))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def load_snapshot(store: Path) -> dict[str, Any] | None:
    path = snapshot_path(store)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def run_once(
    cluster: Path | None,
    store: Path,
    *,
    query_id: str | None = None,
    mysql: MysqlTransport | None = None,
    http: HttpTransport | None = None,
    source: str = "cli",
) -> tuple[InspectReport, int, Path]:
    report, code = inspect_from_path(cluster, query_id=query_id, mysql=mysql, http=http)
    path = save_snapshot(store, report, code, source)
    return report, code, path


def watch_loop(
    cluster: Path | None,
    store: Path,
    interval: int,
    *,
    query_id: str | None = None,
    mysql: MysqlTransport | None = None,
    http: HttpTransport | None = None,
    loops: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if interval < MIN_INTERVAL:
        raise ValueError(f"watch interval must be >= {MIN_INTERVAL} seconds")
    remaining = loops
    last_code = 2
    try:
        while remaining is None or remaining > 0:
            report, last_code, path = run_once(
                cluster, store, query_id=query_id, mysql=mysql, http=http, source="watch"
            )
            sys.stdout.write(report.to_text())
            sys.stdout.write(f"-- watch tick saved {path} --\n")
            sys.stdout.flush()
            if remaining is not None:
                remaining -= 1
                if remaining == 0:
                    break
            sleep(interval)
    except KeyboardInterrupt:
        sys.stderr.write("\nstopping watch\n")
    return last_code
