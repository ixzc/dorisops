from __future__ import annotations

from pathlib import Path

from dorisops.cli import main
from dorisops.playbook import commands_for_mode, load_all, match, match_alert


def test_metaservice_wrong_mode_hints_cloud(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "case",
            "open",
            "--alert",
            "metaservice node down",
            "--mode",
            "integrated",
            "--store",
            str(tmp_path / "cases"),
        ]
    )
    assert code == 2
    out = capsys.readouterr().out
    assert "云模式" in out or "存算分离" in out
    assert "--mode cloud" in out
    assert "clone" in out.lower() or "disk rebalance" in out
    assert "`ms-status`" not in out
    assert "当前模式无命令包" in out
    assert "模式不匹配" in out


def test_metaservice_cloud_has_status_not_clone(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "case",
            "open",
            "--alert",
            "metaservice node down",
            "--mode",
            "cloud",
            "--store",
            str(tmp_path / "cases"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "/status" in out
    assert "selectdb_cloud" in out or "doris_cloud" in out
    assert "SHOW PROC '/cluster_health/tablet_health'" not in out
    assert "ADMIN REBALANCE" not in out
    assert "`cluster-health-local`" not in out


def test_too_many_versions_forks_by_mode() -> None:
    books = load_all()
    book = match("too many versions tablet -235", "integrated", books)
    assert book is not None
    assert book.id == "too-many-versions"
    integrated = [item.id for item in commands_for_mode(book, "integrated")]
    cloud = [item.id for item in commands_for_mode(book, "cloud")]
    assert "cluster-health-local" in integrated
    assert "cluster-health-local" not in cloud
    assert "cloud-compaction-path" in cloud
    assert "cloud-compaction-path" not in integrated


def test_fe_and_query_timeout_match_both_modes() -> None:
    books = load_all()
    assert match("fe node down on follower", "integrated", books).id == "fe-node-down"
    assert match("fe node down on follower", "cloud", books).id == "fe-node-down"
    assert match("query timeout query_id=abc", "integrated", books).id == "query-timeout"
    assert match("query timeout query_id=abc", "cloud", books).id == "query-timeout"


def test_match_alert_mismatch_object() -> None:
    books = load_all()
    hit = match_alert("ms node down", "integrated", books)
    assert hit.book is None
    assert hit.mismatch is not None
    assert hit.mismatch.id == "metaservice-down"
    cloud = match_alert("ms node down", "cloud", books)
    assert cloud.book is not None
    assert cloud.book.id == "metaservice-down"
    assert cloud.mismatch is None


def test_mismatch_json_and_reply_stay_empty(tmp_path: Path) -> None:
    import json

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
    files = list(store.glob("CASE-*.json"))
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["mode_mismatch"] is True
    assert payload["commands"] == []
    junk = tmp_path / "out.txt"
    junk.write_text("Alive: false\n", encoding="utf-8")
    reply = main(
        [
            "case",
            "reply",
            files[0].stem,
            "--output-file",
            str(junk),
            "--store",
            str(store),
        ]
    )
    assert reply == 0
    after = json.loads(files[0].read_text(encoding="utf-8"))
    assert after["commands"] == []
    assert after["mode_mismatch"] is True
