from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import json
import re

from dorisops.cluster import ClusterConfig


SHOW_WHITELIST = (
    "SHOW FRONTENDS",
    "SHOW BACKENDS",
    "SHOW COMPUTE GROUPS",
)

HTTP_PATH_WHITELIST = (
    "/api/health",
    "/metrics",
    "/api/profile",
    "/api/query_profile",
    "/status",  # MetaService brpc status page (cloud only at call site)
)

FORBIDDEN_SQL = re.compile(
    r"\b(SET|ALTER|DROP|CREATE|INSERT|UPDATE|DELETE|TRUNCATE|GRANT|REVOKE|"
    r"LOAD|EXPORT|BACKUP|RESTORE|KILL|ADMIN)\b",
    re.IGNORECASE,
)


class InspectError(RuntimeError):
    """Inspect failed without inventing cluster facts."""


class MysqlTransport(Protocol):
    def query(self, sql: str) -> str: ...


class HttpTransport(Protocol):
    def get(self, url: str) -> tuple[int, str]: ...


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str
    skipped: bool = False


@dataclass
class InspectReport:
    cluster: str
    mode: str
    level: str
    probes: list[ProbeResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, probe: ProbeResult) -> None:
        self.probes.append(probe)

    def to_text(self) -> str:
        lines = [
            f"cluster: {self.cluster}",
            f"mode: {self.mode}",
            f"level: {self.level}",
            "",
        ]
        for probe in self.probes:
            if probe.skipped:
                mark = "SKIP"
            elif probe.ok:
                mark = "OK"
            else:
                mark = "FAIL"
            lines.append(f"[{mark}] {probe.name}: {probe.detail}")
        if self.notes:
            lines.append("")
            lines.extend(self.notes)
        return "\n".join(lines) + "\n"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise InspectError(f"http redirect refused: {code} {newurl}")


class StdlibHttpTransport:
    def get(self, url: str) -> tuple[int, str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise InspectError(f"http scheme not allowed: {parsed.scheme or 'none'}")
        assert_readonly_http_path(parsed.path)
        req = Request(url, method="GET")
        opener = build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=5) as resp:
                body = resp.read(65536).decode("utf-8", errors="replace")
                return int(resp.status), body
        except InspectError:
            raise
        except URLError as exc:
            raise InspectError(f"http failed: {exc}") from exc


class PymysqlTransport:
    def __init__(self, cfg: ClusterConfig) -> None:
        try:
            import pymysql
        except ImportError as exc:
            raise InspectError(
                "pymysql is required for L1 inspect. "
                "Install with: pip install 'dorisops[inspect]'"
            ) from exc
        try:
            self._conn = pymysql.connect(
                host=cfg.mysql_host,
                port=cfg.mysql_port,
                user=cfg.mysql_user,
                password=cfg.mysql_password,
                connect_timeout=5,
                read_timeout=10,
                charset="utf8mb4",
            )
        except Exception as exc:
            raise InspectError(f"mysql connect failed: {exc}") from exc

    def query(self, sql: str) -> str:
        assert_readonly_sql(sql)
        with self._conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            headers = [d[0] for d in (cur.description or [])]
        lines = ["\t".join(headers)] if headers else []
        for row in rows:
            lines.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(lines)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PymysqlTransport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def assert_readonly_sql(sql: str) -> None:
    stripped = sql.strip().rstrip(";")
    if FORBIDDEN_SQL.search(stripped):
        raise InspectError(f"refused non-readonly SQL: {sql}")
    upper = re.sub(r"\s+", " ", stripped.upper())
    if upper not in SHOW_WHITELIST:
        raise InspectError(f"SQL not in inspect whitelist: {sql}")


def assert_readonly_http_path(path: str) -> None:
    clean = path.split("?", 1)[0]
    if clean not in HTTP_PATH_WHITELIST:
        raise InspectError(f"HTTP path not in inspect whitelist: {path}")


L0_OPEN_HINT = (
    "Open an L0 diagnosis case without cluster credentials:\n"
    '  dorisops case open --alert "paste alert here" --mode integrated'
)


def l0_report(reason: str, *, cluster: str = "(none)", mode: str = "unknown") -> InspectReport:
    report = InspectReport(cluster=cluster, mode=mode, level="L0")
    report.notes.append(reason)
    report.notes.append("L1 inspect needs --cluster ./cluster.yaml with real read-only credentials.")
    report.notes.append(L0_OPEN_HINT)
    return report


def inspect_cluster(
    cfg: ClusterConfig,
    *,
    mysql: MysqlTransport | None = None,
    http: HttpTransport | None = None,
    query_id: str | None = None,
) -> InspectReport:
    if not cfg.credentials_ready():
        return l0_report(
            "cluster.yaml still has CHANGE_ME / placeholder credentials; "
            "refusing to connect. Fill mysql_user and mysql_password then retry.",
            cluster=cfg.name,
            mode=cfg.mode,
        )

    report = InspectReport(cluster=cfg.name, mode=cfg.mode, level="L1")
    owned_mysql = mysql is None
    try:
        mysql = mysql or PymysqlTransport(cfg)
        http = http or StdlibHttpTransport()
    except InspectError as exc:
        if "pymysql is required" in str(exc):
            return l0_report(str(exc), cluster=cfg.name, mode=cfg.mode)
        report.add(ProbeResult(name="connect", ok=False, detail=str(exc)))
        report.notes.append("L1 inspect is read-only whitelist only; no SET/ALTER/SSH.")
        return report

    try:
        return _run_probes(report, cfg, mysql, http, query_id)
    finally:
        if owned_mysql and hasattr(mysql, "close"):
            try:
                mysql.close()  # type: ignore[union-attr]
            except Exception:
                pass


def _run_probes(
    report: InspectReport,
    cfg: ClusterConfig,
    mysql: MysqlTransport,
    http: HttpTransport,
    query_id: str | None,
) -> InspectReport:
    fe_text = _probe_show(report, mysql, "SHOW FRONTENDS")
    if fe_text:
        seen = _bool_column(fe_text, "iscloudmode")
        if seen is True and cfg.mode != "cloud":
            report.notes.append(
                "SHOW FRONTENDS IsCloudMode=true; cluster.yaml mode is " + cfg.mode
            )
        elif seen is False and cfg.mode != "integrated":
            report.notes.append(
                "SHOW FRONTENDS IsCloudMode=false; cluster.yaml mode is " + cfg.mode
            )
    _probe_show(report, mysql, "SHOW BACKENDS")
    if cfg.mode == "cloud":
        _probe_show(report, mysql, "SHOW COMPUTE GROUPS")
    else:
        report.add(_refuse_integrated("SHOW COMPUTE GROUPS"))

    if cfg.fe_http_url:
        _probe_http(report, http, cfg.fe_http_url, "/api/health", "FE /api/health")
        _probe_http(report, http, cfg.fe_http_url, "/metrics", "FE /metrics")
    else:
        report.add(
            ProbeResult(name="FE HTTP", ok=True, skipped=True, detail="fe.http_url empty")
        )

    if cfg.backend_http_urls:
        _probe_http(
            report,
            http,
            cfg.backend_http_urls[0],
            "/api/health",
            "BE /api/health",
        )
    else:
        report.add(
            ProbeResult(name="BE HTTP", ok=True, skipped=True, detail="no backends.http_url")
        )

    _probe_ms_status(report, cfg, http)
    _probe_file_cache(report, cfg, http)

    if query_id and cfg.fe_http_url:
        q = quote(query_id, safe="")
        _probe_http(
            report,
            http,
            cfg.fe_http_url,
            f"/api/profile?query_id={q}",
            "FE /api/profile",
        )
    elif query_id:
        report.add(
            ProbeResult(
                name="FE /api/profile",
                ok=True,
                skipped=True,
                detail="fe.http_url empty; cannot fetch profile",
            )
        )

    report.notes.append("L1 inspect is read-only whitelist only; no SET/ALTER/SSH.")
    return report


def _refuse_integrated(tool: str) -> ProbeResult:
    return ProbeResult(
        name=tool,
        ok=True,
        skipped=True,
        detail="当前是 integrated，拒绝 " + tool,
    )


def _probe_ms_status(report: InspectReport, cfg: ClusterConfig, http: HttpTransport) -> None:
    if cfg.mode != "cloud":
        report.add(_refuse_integrated("MS /status"))
        return
    if not cfg.ms_http_url:
        report.add(
            ProbeResult(
                name="MS /status",
                ok=True,
                skipped=True,
                detail=(
                    "未配置 meta_service.http_url；待人执行 "
                    "curl http://$MS_PORT/status（brpc 默认 5000）。不假装已探过。"
                ),
            )
        )
        report.notes.append(
            "cloud: MetaService HTTP 待人执行（cluster.yaml 未配 meta_service.http_url）"
        )
        return
    path = "/status"
    assert_readonly_http_path(path)
    url = cfg.ms_http_url.rstrip("/") + path
    try:
        status, body = http.get(url)
    except Exception as exc:
        report.add(ProbeResult(name="MS /status", ok=False, detail=str(exc)))
        return
    ok = 200 <= status < 300
    lowered = body.lower()
    if "metaservice" in lowered or "meta_service" in lowered:
        marker = "page names MetaService"
    else:
        marker = "MetaService not in page (do not invent role)"
    snippet = body.strip().replace("\n", " ")[:80]
    report.add(ProbeResult(name="MS /status", ok=ok, detail=f"HTTP {status}; {marker}; {snippet}"))


def _probe_file_cache(report: InspectReport, cfg: ClusterConfig, http: HttpTransport) -> None:
    if cfg.mode != "cloud":
        report.add(_refuse_integrated("BE file_cache metrics"))
        return
    if not cfg.backend_http_urls:
        report.add(
            ProbeResult(
                name="BE file_cache metrics",
                ok=True,
                skipped=True,
                detail=(
                    "未配置 backends.http_url；待人执行 "
                    "curl BE:8040/metrics | grep file_cache。不假装已探过。"
                ),
            )
        )
        report.notes.append(
            "cloud: BE file_cache metrics 待人执行（cluster.yaml 未配 backends.http_url）"
        )
        return
    path = "/metrics"
    assert_readonly_http_path(path)
    url = cfg.backend_http_urls[0].rstrip("/") + path
    try:
        status, body = http.get(url)
    except Exception as exc:
        report.add(ProbeResult(name="BE file_cache metrics", ok=False, detail=str(exc)))
        return
    if not (200 <= status < 300):
        report.add(
            ProbeResult(
                name="BE file_cache metrics",
                ok=False,
                detail=f"HTTP {status}",
            )
        )
        return
    lines = [
        ln
        for ln in body.splitlines()
        if "file_cache" in ln.lower() and not ln.lstrip().startswith("#")
    ]
    if not lines:
        report.add(
            ProbeResult(
                name="BE file_cache metrics",
                ok=True,
                detail=f"HTTP {status}; no file_cache lines in /metrics (do not invent hit rate)",
            )
        )
        return
    preview = lines[0].strip()[:100]
    report.add(
        ProbeResult(
            name="BE file_cache metrics",
            ok=True,
            detail=f"HTTP {status}; {len(lines)} file_cache line(s); e.g. {preview}",
        )
    )


def _probe_show(report: InspectReport, mysql: MysqlTransport, sql: str) -> str | None:
    try:
        text = mysql.query(sql)
    except Exception as exc:
        report.add(ProbeResult(name=sql, ok=False, detail=str(exc)))
        return None
    alive = _alive_summary(text)
    report.add(ProbeResult(name=sql, ok=True, detail=alive or f"{len(text.splitlines())} line(s)"))
    return text


def _probe_http(
    report: InspectReport,
    http: HttpTransport,
    base: str,
    path: str,
    name: str,
) -> None:
    assert_readonly_http_path(path)
    url = base.rstrip("/") + path
    try:
        status, body = http.get(url)
    except Exception as exc:
        report.add(ProbeResult(name=name, ok=False, detail=str(exc)))
        return
    ok = 200 <= status < 300
    snippet = body.strip().replace("\n", " ")[:120]
    report.add(ProbeResult(name=name, ok=ok, detail=f"HTTP {status} {snippet}"))


def _alive_summary(text: str) -> str:
    counts = _bool_counts(text, "alive")
    if counts is None:
        return ""
    true_n, false_n = counts
    return f"Alive true={true_n} false={false_n}"


def _bool_column(text: str, name: str) -> bool | None:
    counts = _bool_counts(text, name)
    if counts is None:
        return None
    true_n, false_n = counts
    if true_n and not false_n:
        return True
    if false_n and not true_n:
        return False
    return None


def _bool_counts(text: str, name: str) -> tuple[int, int] | None:
    header_line = text.splitlines()[0] if text.strip() else ""
    cols = [c.strip().lower() for c in re.split(r"[\t,|]", header_line)]
    idx = next((i for i, c in enumerate(cols) if c == name), None)
    if idx is None:
        return None
    true_n = false_n = 0
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        parts = re.split(r"[\t,|]", line)
        if idx >= len(parts):
            continue
        val = parts[idx].strip().lower()
        if val in {"true", "1", "yes"}:
            true_n += 1
        elif val in {"false", "0", "no"}:
            false_n += 1
    if true_n + false_n == 0:
        return None
    return true_n, false_n


def report_to_json(report: InspectReport) -> str:
    return json.dumps(
        {
            "cluster": report.cluster,
            "mode": report.mode,
            "level": report.level,
            "probes": [
                {
                    "name": p.name,
                    "ok": p.ok,
                    "skipped": p.skipped,
                    "detail": p.detail,
                }
                for p in report.probes
            ],
            "notes": report.notes,
        },
        ensure_ascii=False,
        indent=2,
    )
