from __future__ import annotations

import json
from pathlib import Path

from dorisops.cli import main

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "show_backends_alive_false.txt"


def _open(tmp_path: Path) -> str:
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
    files = list(store.glob("CASE-*.json"))
    assert len(files) == 1
    return files[0].stem


def test_show_after_open_is_waiting(tmp_path: Path, capsys) -> None:
    case_id = _open(tmp_path)
    capsys.readouterr()
    code = main(["case", "show", case_id, "--store", str(tmp_path / "cases")])
    assert code == 0
    out = capsys.readouterr().out
    assert "待人执行" in out
    assert "awaiting_evidence" in out
    assert "已查询集群" not in out
    assert "be-logs-heartbeat" not in out
    payload = json.loads((tmp_path / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))
    assert payload["conclusion"] is None
    assert payload["evidence"] == []


def test_refuse_keeps_case_open(tmp_path: Path, capsys) -> None:
    case_id = _open(tmp_path)
    capsys.readouterr()
    code = main(
        [
            "case",
            "refuse",
            case_id,
            "--reason",
            "无跳板机权限",
            "--store",
            str(tmp_path / "cases"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "无跳板机权限" in out
    assert "打开（已拒绝执行）" in out
    assert "blocked" in out
    payload = json.loads((tmp_path / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["conclusion"] is None
    assert payload["refusals"][0]["reason"] == "无跳板机权限"
    show = main(["case", "show", case_id, "--store", str(tmp_path / "cases")])
    assert show == 0
    shown = capsys.readouterr().out
    assert "无跳板机权限" in shown
    assert "已查询集群" not in shown


def test_reply_show_backends_advances_tree(tmp_path: Path, capsys) -> None:
    case_id = _open(tmp_path)
    capsys.readouterr()
    code = main(
        [
            "case",
            "reply",
            case_id,
            "--output-file",
            str(FIXTURE),
            "--store",
            str(tmp_path / "cases"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "`be-logs-heartbeat`" in out
    assert "`probe-heartbeat-port`" in out
    assert "`show-backends`" not in out
    assert "fe-marked-dead" in out
    assert "已查询集群" not in out
    payload = json.loads((tmp_path / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))
    assert payload["status"] == "in_progress"
    assert payload["node_id"] == "fe-marked-dead"
    assert payload["conclusion"] is None
    assert [item["id"] for item in payload["commands"]] == [
        "be-logs-heartbeat",
        "probe-heartbeat-port",
    ]


def test_reply_unmatched_keeps_round(tmp_path: Path, capsys) -> None:
    case_id = _open(tmp_path)
    capsys.readouterr()
    junk = tmp_path / "noise.txt"
    junk.write_text("disk usage 12%\n", encoding="utf-8")
    code = main(
        [
            "case",
            "reply",
            case_id,
            "--output-file",
            str(junk),
            "--store",
            str(tmp_path / "cases"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "SHOW BACKENDS" in out
    assert "be-logs-heartbeat" not in out
    assert "未命中" in out
