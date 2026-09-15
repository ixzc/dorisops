"""P0 golden eval (E1–E6). Default CI must not talk to a real Doris cluster."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from dorisops.cli import main
from dorisops.web import start_background

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "show_backends_alive_false.txt"
_OPENER = build_opener(ProxyHandler({}))


def _post(url: str, data: dict[str, str]) -> str:
    body = urlencode(data).encode("utf-8")
    req = Request(url, data=body, method="POST")
    with _OPENER.open(req, timeout=5) as resp:
        return resp.read().decode("utf-8")


def test_e1_be_node_down_no_cluster_facts(tmp_path: Path, capsys) -> None:
    store = tmp_path / "cases"
    code = main(
        [
            "case",
            "open",
            "--alert",
            "be node down on host X",
            "--mode",
            "integrated",
            "--store",
            str(store),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "SHOW BACKENDS" in out
    assert "be-node-down" in out or "剧本: be-node-down" in out
    assert "已查询集群" not in out
    assert "Alive true=" not in out
    assert "待人执行" in out
    assert "awaiting_evidence" in out
    payload = json.loads(next(store.glob("CASE-*.json")).read_text(encoding="utf-8"))
    assert payload["lane"] == "L0"
    assert payload["playbook_id"] == "be-node-down"
    assert payload["status"] == "awaiting_evidence"
    assert payload["evidence"] == []
    assert payload["conclusion"] is None


def test_e2_memory_used_not_mem_tracker(tmp_path: Path, capsys) -> None:
    store = tmp_path / "cases"
    code = main(
        [
            "case",
            "open",
            "--alert",
            "MemoryUsed 大于 95%",
            "--mode",
            "cloud",
            "--store",
            str(store),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "/profile" in out
    assert "http://<be_host>:8040/mem_tracker" not in out
    payload = json.loads(next(store.glob("CASE-*.json")).read_text(encoding="utf-8"))
    assert payload["playbook_id"] == "memory-pressure"
    bodies = "\n".join(item["body"] for item in payload["commands"])
    assert "/mem_tracker" not in bodies
    assert "/profile" in bodies


def test_e3_metaservice_integrated_mismatch(tmp_path: Path, capsys) -> None:
    store = tmp_path / "cases"
    code = main(
        [
            "case",
            "open",
            "--alert",
            "metaservice node down",
            "--mode",
            "integrated",
            "--store",
            str(store),
        ]
    )
    assert code == 2
    out = capsys.readouterr().out
    assert "模式不匹配" in out
    assert "`ms-status`" not in out
    assert "SHOW PROC '/cluster_health/tablet_health'" not in out
    payload = json.loads(next(store.glob("CASE-*.json")).read_text(encoding="utf-8"))
    assert payload["mode_mismatch"] is True
    assert payload["commands"] == []


def test_e4_show_without_reply_stays_pending(tmp_path: Path, capsys) -> None:
    store = tmp_path / "cases"
    opened = main(
        [
            "case",
            "open",
            "--alert",
            "be node down on host X",
            "--mode",
            "integrated",
            "--store",
            str(store),
        ]
    )
    assert opened == 0
    case_id = next(store.glob("CASE-*.json")).stem
    capsys.readouterr()
    code = main(["case", "show", case_id, "--store", str(store)])
    assert code == 0
    out = capsys.readouterr().out
    assert "待人执行" in out
    assert "awaiting_evidence" in out
    assert "已查询集群" not in out
    payload = json.loads((store / f"{case_id}.json").read_text(encoding="utf-8"))
    assert payload["evidence"] == []
    assert payload["conclusion"] is None


def test_e5_too_many_versions_not_a_query_issue(tmp_path: Path, capsys) -> None:
    store = tmp_path / "cases"
    code = main(
        [
            "case",
            "open",
            "--alert",
            "too many versions tablet -235",
            "--mode",
            "integrated",
            "--store",
            str(store),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "too-many-versions" in out
    assert "compaction" in out.lower() or "tablet_version" in out
    assert "query-timeout" not in out
    assert "已查询集群" not in out
    payload = json.loads(next(store.glob("CASE-*.json")).read_text(encoding="utf-8"))
    assert payload["playbook_id"] == "too-many-versions"
    assert payload["lane"] == "L0"
    assert payload["playbook_id"] != "query-timeout"


def test_e6_web_open_reply_same_state_as_cli(tmp_path: Path, capsys) -> None:
    store = tmp_path / "cases"
    httpd, thread = start_background("127.0.0.1", 0, store)
    host, port = httpd.server_address[:2]
    url = f"http://{host}:{port}"
    try:
        opened = _post(url + "/cases", {"alert": "be node down on host X", "mode": "integrated"})
        case_id = opened.split("<h1>")[1].split("</h1>")[0]
        replied = _post(
            f"{url}/cases/{case_id}/reply",
            {"output": FIXTURE.read_text(encoding="utf-8")},
        )
        assert "be-logs-heartbeat" in replied
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)

    capsys.readouterr()
    code = main(["case", "show", case_id, "--store", str(store)])
    assert code == 0
    out = capsys.readouterr().out
    assert "in_progress" in out
    assert "fe-marked-dead" in out
    payload = json.loads((store / f"{case_id}.json").read_text(encoding="utf-8"))
    assert payload["status"] == "in_progress"
    assert payload["node_id"] == "fe-marked-dead"
    assert [item["id"] for item in payload["commands"]] == [
        "be-logs-heartbeat",
        "probe-heartbeat-port",
    ]
    assert payload["conclusion"] is None
    assert payload["lane"] == "L0"
