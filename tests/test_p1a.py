from __future__ import annotations

import json
from pathlib import Path

from dorisops.case import db_path, list_cases, load_case
from dorisops.cli import main
from dorisops.mcp_api import McpSession
from dorisops.web import start_background

from test_web import _get, _post, _case_id


def test_sqlite_created_and_roundtrip(tmp_path: Path, capsys) -> None:
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
    capsys.readouterr()
    assert db_path(store).is_file()
    cases = list_cases(store)
    assert len(cases) == 1
    loaded = load_case(store, cases[0].id)
    assert loaded.playbook_id == "be-node-down"
    assert loaded.lane == "L0"


def test_migrates_json_only_store(tmp_path: Path) -> None:
    store = tmp_path / "cases"
    store.mkdir()
    payload = {
        "id": "CASE-legacy-abcd",
        "created_at": "2026-01-01T00:00:00+00:00",
        "lane": "L0",
        "mode": "integrated",
        "alert": "be node down",
        "status": "awaiting_evidence",
        "playbook_id": "be-node-down",
        "playbook_title": "BE node down",
        "pending_note": "waiting",
        "essence": "x",
        "impact": "x",
        "do_now": "x",
        "stop_line": "x",
        "never_do": "x",
        "commands": [],
    }
    (store / "CASE-legacy-abcd.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    loaded = load_case(store, "CASE-legacy-abcd")
    assert loaded.alert == "be node down"
    listed = list_cases(store)
    assert [item.id for item in listed] == ["CASE-legacy-abcd"]
    assert db_path(store).is_file()


def test_export_markdown_is_forwardable_not_live(tmp_path: Path, capsys) -> None:
    store = tmp_path / "cases"
    main(
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
    case_id = list_cases(store)[0].id
    capsys.readouterr()
    code = main(["case", "export", case_id, "--store", str(store)])
    assert code == 0
    out = capsys.readouterr().out
    assert "转发稿" in out
    assert "不是实时集群快照" in out
    assert "SHOW BACKENDS" in out
    assert "已查询集群" not in out
    json_code = main(["case", "export", case_id, "--format", "json", "--store", str(store)])
    assert json_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == case_id
    assert payload["lane"] == "L0"
    assert "不是实时集群快照" in payload["dorisops_notice"]


def test_web_export_md(tmp_path: Path) -> None:
    store = tmp_path / "cases"
    httpd, thread = start_background("127.0.0.1", 0, store)
    host, port = httpd.server_address[:2]
    url = f"http://{host}:{port}"
    try:
        opened = _post(url + "/cases", {"alert": "be node down on host X", "mode": "integrated"})
        case_id = _case_id(opened)
        assert "export.md" in opened
        text = _get(f"{url}/cases/{case_id}/export.md")
        assert "转发稿" in text
        assert "SHOW BACKENDS" in text
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_mcp_export(tmp_path: Path) -> None:
    session = McpSession(store=tmp_path / "cases")
    opened = session.case_open("be node down on host X", "integrated")
    case_id = opened.splitlines()[0].lstrip("# ").strip()
    text = session.case_export(case_id)
    assert "转发稿" in text
    assert "SHOW BACKENDS" in text
