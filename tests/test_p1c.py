from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError

import pytest

from dorisops.cli import main
from dorisops.watch import MIN_INTERVAL, load_snapshot, snapshot_path, watch_loop
from dorisops.web import start_background

from test_s5 import EXAMPLE, FakeMysql, READY_YAML, SHOW_BACKENDS, SHOW_FRONTENDS, Boom, _http
from test_web import _OPENER, _get, _post


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_watch_interval_floor() -> None:
    assert MIN_INTERVAL == 30
    assert main(["inspect", "--watch", "--interval", "5"]) == 2
    with pytest.raises(ValueError, match="interval"):
        watch_loop(None, Path("."), 5, loops=1, sleep=lambda _s: None)


def test_watch_two_ticks_saves_snapshot(tmp_path: Path, capsys) -> None:
    cluster = _write(tmp_path / "cluster.yaml", READY_YAML)
    store = tmp_path / "cases"
    mysql = FakeMysql({"SHOW FRONTENDS": SHOW_FRONTENDS, "SHOW BACKENDS": SHOW_BACKENDS})
    http = _http()
    slept: list[int] = []
    code = watch_loop(
        cluster,
        store,
        interval=30,
        mysql=mysql,
        http=http,
        loops=2,
        sleep=slept.append,
    )
    capsys.readouterr()
    assert code == 0
    assert slept == [30]
    assert mysql.queries.count("SHOW FRONTENDS") == 2
    snap = load_snapshot(store)
    assert snap is not None
    assert snap["level"] == "L1"
    assert snap["source"] == "watch"
    assert "不是 Grafana" in snap["notice"]
    assert "Alive true=1 false=0" in snap["text"]
    assert all(q.startswith("SHOW ") for q in mysql.queries)
    assert snapshot_path(store).is_file()


def test_watch_placeholders_never_connect(tmp_path: Path) -> None:
    boom = Boom()
    code = watch_loop(
        EXAMPLE,
        tmp_path / "cases",
        interval=30,
        mysql=boom,
        http=boom,
        loops=1,
        sleep=lambda _s: None,
    )
    assert code == 2
    snap = load_snapshot(tmp_path / "cases")
    assert snap is not None
    assert snap["level"] == "L0"
    assert "CHANGE_ME" in snap["text"]
    assert "Alive true=" not in snap["text"]
    assert "已查询集群" not in snap["text"]


def test_web_hides_probe_without_cluster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DORISOPS_CLUSTER", str(tmp_path / "cluster.yaml"))
    _write(tmp_path / "cluster.yaml", READY_YAML)
    httpd, thread = start_background("127.0.0.1", 0, tmp_path / "cases")
    host, port = httpd.server_address[:2]
    try:
        html = _get(f"http://{host}:{port}/")
        assert "探活（只读）" not in html
        assert "没有去查集群" in html
        with pytest.raises(HTTPError) as err:
            _post(f"http://{host}:{port}/inspect", {})
        assert err.value.code == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_web_probe_block_is_readonly(tmp_path: Path) -> None:
    cluster = _write(tmp_path / "cluster.yaml", READY_YAML)
    store = tmp_path / "cases"
    mysql = FakeMysql({"SHOW FRONTENDS": SHOW_FRONTENDS, "SHOW BACKENDS": SHOW_BACKENDS})
    http = _http()
    httpd, thread = start_background(
        "127.0.0.1", 0, store, cluster=cluster, mysql=mysql, http=http
    )
    host, port = httpd.server_address[:2]
    url = f"http://{host}:{port}"
    try:
        index = _get(url + "/")
        assert "探活（只读）" in index
        assert "尚未探活" in index
        assert "不会 SET、ALTER" in index
        _post(url + "/inspect", {})
        html = _get(url + "/")
        assert "Alive true=1 false=0" in html
        assert "不是 Grafana" in html
        assert all(q.startswith("SHOW ") for q in mysql.queries)
        snap = load_snapshot(store)
        assert snap is not None
        assert snap["source"] == "web"
        assert snap["level"] == "L1"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_web_probe_placeholders_stay_l0(tmp_path: Path) -> None:
    boom = Boom()
    store = tmp_path / "cases"
    httpd, thread = start_background(
        "127.0.0.1", 0, store, cluster=EXAMPLE, mysql=boom, http=boom
    )
    host, port = httpd.server_address[:2]
    url = f"http://{host}:{port}"
    try:
        _post(url + "/inspect", {})
        html = _get(url + "/")
        assert "level: L0" in html
        assert "CHANGE_ME" in html
        assert "Alive true=" not in html
        assert "探活（只读）" in html
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
