from __future__ import annotations

import json
from pathlib import Path

from dorisops.cli import main


def test_open_be_node_down_no_cluster(tmp_path: Path, capsys) -> None:
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
    assert "/api/health" in out
    assert "heartbeat" in out.lower() or "9050" in out
    assert "已查询集群" not in out
    assert "不要" in out and "Alive=false" in out
    assert "awaiting_evidence" in out
    files = list(store.glob("CASE-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["lane"] == "L0"
    assert payload["conclusion"] is None
    assert payload["status"] == "awaiting_evidence"


def test_open_memory_uses_profile_not_mem_tracker(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "case",
            "open",
            "--alert",
            "MemoryUsed 大于 95%",
            "--mode",
            "cloud",
            "--store",
            str(tmp_path / "cases"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "/profile" in out
    assert "http://<be_host>:8040/mem_tracker" not in out
    assert "file_cache" in out


def test_missing_playbook_dir_exits_2(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "case",
            "open",
            "--alert",
            "be node down on host X",
            "--mode",
            "integrated",
            "--store",
            str(tmp_path / "cases"),
            "--playbook-dir",
            str(tmp_path / "missing-pack"),
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "playbook dir not found" in err


def test_unmatched_exits_2(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "case",
            "open",
            "--alert",
            "something-unrelated-zzz",
            "--mode",
            "integrated",
            "--store",
            str(tmp_path / "cases"),
        ]
    )
    assert code == 2
    out = capsys.readouterr().out
    assert "未匹配" in out or "未命中" in out
    assert "已查询集群" not in out
