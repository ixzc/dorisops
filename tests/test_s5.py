from __future__ import annotations

from pathlib import Path

import pytest

from dorisops.cli import main
from dorisops.cluster import load_cluster_yaml
from dorisops.inspect import (
    InspectError,
    assert_readonly_http_path,
    assert_readonly_sql,
    inspect_cluster,
)
from dorisops.service import inspect_from_path

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "cluster.example.yaml"

READY_YAML = """\
name: lab
mode: integrated
fe:
  mysql_host: 127.0.0.1
  mysql_port: 9030
  mysql_user: reader
  mysql_password: secret
  http_url: http://127.0.0.1:8030
backends:
  - http_url: http://127.0.0.1:8040
"""

CLOUD_YAML = READY_YAML.replace("mode: integrated", "mode: cloud").replace("name: lab", "name: cloud-lab")

SHOW_FRONTENDS = "Name\tHost\tAlive\tIsCloudMode\nfe1\t127.0.0.1\ttrue\tfalse\n"
SHOW_BACKENDS = "BackendId\tHost\tAlive\n10001\t127.0.0.1\ttrue\n"
SHOW_BACKENDS_DEAD = "BackendId\tHost\tAlive\n10001\t127.0.0.1\tfalse\n"
SHOW_COMPUTE_GROUPS = "Name\tId\ndefault_cluster\t1\n"


class FakeMysql:
    def __init__(self, tables: dict[str, str]) -> None:
        self.tables = tables
        self.queries: list[str] = []

    def query(self, sql: str) -> str:
        assert_readonly_sql(sql)
        self.queries.append(sql)
        key = sql.strip().rstrip(";").upper()
        if key not in self.tables:
            raise InspectError(f"unexpected SQL: {sql}")
        return self.tables[key]


class FakeHttp:
    def __init__(self, responses: dict[str, tuple[int, str]]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url: str) -> tuple[int, str]:
        self.urls.append(url)
        if url not in self.responses:
            raise InspectError(f"unexpected url: {url}")
        return self.responses[url]


class Boom:
    def query(self, sql: str) -> str:
        raise AssertionError("must not connect")

    def get(self, url: str) -> tuple[int, str]:
        raise AssertionError("must not connect")


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _http() -> FakeHttp:
    return FakeHttp(
        {
            "http://127.0.0.1:8030/api/health": (200, '{"status":"OK"}'),
            "http://127.0.0.1:8030/metrics": (200, "doris_fe_query_total 1"),
            "http://127.0.0.1:8040/api/health": (200, "OK"),
            "http://127.0.0.1:8030/api/profile?query_id=q1": (200, "Query: q1"),
        }
    )


def test_inspect_without_cluster_is_l0(capsys) -> None:
    code = main(["inspect"])
    assert code == 2
    out = capsys.readouterr().out
    assert "level: L0" in out
    assert "no --cluster given" in out
    assert "case open" in out
    assert "Can't connect" not in out
    assert "Alive=false" not in out


def test_inspect_missing_file_is_l0(tmp_path: Path, capsys) -> None:
    code = main(["inspect", "--cluster", str(tmp_path / "missing.yaml")])
    assert code == 2
    out = capsys.readouterr().out
    assert "level: L0" in out
    assert "not found" in out
    assert "case open" in out


def test_inspect_example_placeholders_do_not_connect(capsys) -> None:
    code = main(["inspect", "--cluster", str(EXAMPLE)])
    assert code == 2
    out = capsys.readouterr().out
    assert "level: L0" in out
    assert "CHANGE_ME" in out
    assert "case open" in out
    assert "[OK] SHOW FRONTENDS" not in out


def test_subset_parser_reads_example() -> None:
    from dorisops.cluster import _parse_without_pyyaml

    data = _parse_without_pyyaml(EXAMPLE.read_text(encoding="utf-8"))
    assert data["name"] == "lab"
    assert data["mode"] == "integrated"
    assert data["fe"]["mysql_port"] == 9030
    assert data["fe"]["mysql_password"] == "CHANGE_ME"
    assert data["backends"][0]["http_url"] == "http://127.0.0.1:8040"


def test_placeholder_never_calls_transport(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", EXAMPLE.read_text(encoding="utf-8")))
    boom = Boom()
    report = inspect_cluster(cfg, mysql=boom, http=boom)
    assert report.level == "L0"
    assert report.probes == []


def test_inspect_mocked_alive(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", READY_YAML))
    assert cfg.credentials_ready()
    mysql = FakeMysql({"SHOW FRONTENDS": SHOW_FRONTENDS, "SHOW BACKENDS": SHOW_BACKENDS})
    http = _http()
    report, code = inspect_from_path(
        tmp_path / "cluster.yaml",
        mysql=mysql,
        http=http,
    )
    assert code == 0
    assert report.level == "L1"
    text = report.to_text()
    assert "Alive true=1 false=0" in text
    assert "mode: integrated" in text
    skipped = next(p for p in report.probes if p.name == "SHOW COMPUTE GROUPS")
    assert skipped.skipped is True
    assert "SHOW COMPUTE GROUPS" not in mysql.queries
    assert "http://127.0.0.1:8030/api/health" in http.urls
    assert "http://127.0.0.1:8040/api/health" in http.urls
    assert not any("/status" in url for url in http.urls)


def test_inspect_records_alive_false_from_output(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", READY_YAML))
    mysql = FakeMysql({"SHOW FRONTENDS": SHOW_FRONTENDS, "SHOW BACKENDS": SHOW_BACKENDS_DEAD})
    report = inspect_cluster(cfg, mysql=mysql, http=_http())
    be = next(p for p in report.probes if p.name == "SHOW BACKENDS")
    assert "Alive true=0 false=1" in be.detail


def test_cloud_runs_compute_groups(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", CLOUD_YAML))
    mysql = FakeMysql(
        {
            "SHOW FRONTENDS": SHOW_FRONTENDS.replace("false", "true"),
            "SHOW BACKENDS": SHOW_BACKENDS,
            "SHOW COMPUTE GROUPS": SHOW_COMPUTE_GROUPS,
        }
    )
    report = inspect_cluster(cfg, mysql=mysql, http=_http())
    assert "SHOW COMPUTE GROUPS" in mysql.queries
    cg = next(p for p in report.probes if p.name == "SHOW COMPUTE GROUPS")
    assert cg.ok and not cg.skipped
    assert not any("meta_service" in p.name.lower() or "/status" in p.name for p in report.probes)


def test_query_id_fetches_profile(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", READY_YAML))
    mysql = FakeMysql({"SHOW FRONTENDS": SHOW_FRONTENDS, "SHOW BACKENDS": SHOW_BACKENDS})
    http = _http()
    report = inspect_cluster(cfg, mysql=mysql, http=http, query_id="q1")
    assert "http://127.0.0.1:8030/api/profile?query_id=q1" in http.urls
    assert any(p.name == "FE /api/profile" and p.ok for p in report.probes)


def test_write_sql_refused() -> None:
    with pytest.raises(InspectError):
        assert_readonly_sql("SET GLOBAL enable_profile = true")
    with pytest.raises(InspectError):
        assert_readonly_sql("ALTER TABLE t ADD COLUMN c INT")
    with pytest.raises(InspectError):
        assert_readonly_sql("ADMIN REPAIR TABLE t")
    with pytest.raises(InspectError):
        assert_readonly_sql("SHOW TABLES")
    with pytest.raises(InspectError):
        assert_readonly_sql("SHOW FRONTENDS; DROP TABLE t")
    assert_readonly_sql("SHOW FRONTENDS")
    assert_readonly_sql("SHOW BACKENDS")
    assert_readonly_sql("SHOW COMPUTE GROUPS")


def test_http_whitelist() -> None:
    assert_readonly_http_path("/api/health")
    assert_readonly_http_path("/metrics")
    assert_readonly_http_path("/api/profile?query_id=abc")
    with pytest.raises(InspectError):
        assert_readonly_http_path("/api/bootstrap")
    with pytest.raises(InspectError):
        assert_readonly_http_path("/rest/v1/system")


def test_password_not_in_repr(tmp_path: Path) -> None:
    cfg = load_cluster_yaml(_write(tmp_path / "cluster.yaml", READY_YAML))
    assert "secret" not in repr(cfg)


def test_probe_failure_exit_1(tmp_path: Path) -> None:
    _write(tmp_path / "cluster.yaml", READY_YAML)
    mysql = FakeMysql({"SHOW FRONTENDS": SHOW_FRONTENDS, "SHOW BACKENDS": SHOW_BACKENDS})

    class FailHttp:
        def get(self, url: str) -> tuple[int, str]:
            raise InspectError("connection refused")

    report, code = inspect_from_path(tmp_path / "cluster.yaml", mysql=mysql, http=FailHttp())
    assert code == 1
    assert report.level == "L1"
    assert any(not p.ok and not p.skipped for p in report.probes)
