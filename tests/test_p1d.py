from __future__ import annotations

from pathlib import Path

import pytest

from dorisops.cli import main
from dorisops.playbook import PlaybookError, load_all, match
from dorisops.render import render
from dorisops.service import open_from_alert

SOP2 = Path(__file__).resolve().parent / "fixtures" / "sop2"


def test_sop2_gap_fills_unknown_alert(tmp_path: Path, capsys) -> None:
    store = tmp_path / "cases"
    code = main(
        [
            "case",
            "open",
            "--alert",
            "fe metrics down on 10.0.0.1",
            "--mode",
            "integrated",
            "--sop-dir",
            str(SOP2),
            "--store",
            str(store),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "SHOW FRONTENDS" in out
    assert "/metrics" in out
    assert "监控侧抓不到" in out
    assert "CIR-REDACTED" in out
    assert "CIR-20826" not in out
    assert "20269" not in out
    assert "CIR-21912" not in out
    assert "不要在这里写" not in out
    assert "已查询集群" not in out
    assert "Alive true=" not in out


def test_sop2_does_not_override_builtin_tree() -> None:
    books = load_all(sop_dirs=[SOP2])
    book = match("be node down on host X", "integrated", books)
    assert book is not None
    assert book.id == "be-node-down"
    assert book.title == "BE node down"
    assert "SOP2 OVERRIDE" not in book.essence
    assert "TOML IN SOP DIR" not in book.title
    assert book.nodes
    assert "sop2-1" not in {cmd.id for cmd in book.commands}


def test_sop2_skips_shared_facts_and_missing_dir(tmp_path: Path) -> None:
    books = load_all(sop_dirs=[SOP2])
    ids = {book.id for book in books}
    assert "shared-facts" not in ids
    assert "fe-metrics-down" in ids
    assert "leftover draft" not in ids and "00-draft" not in ids and "draft" not in ids
    with pytest.raises(PlaybookError, match="sop dir not found"):
        load_all(sop_dirs=[tmp_path / "missing-sop"])


def test_sop2_env_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("DORISOPS_SOP", str(SOP2))
    code = main(
        [
            "case",
            "open",
            "--alert",
            "fe metrics down",
            "--mode",
            "cloud",
            "--store",
            str(tmp_path / "cases"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "SHOW FRONTENDS" in out
    case, _path, matched = open_from_alert(
        "fe metrics down", "integrated", tmp_path / "cases2", sop_dirs=[SOP2]
    )
    assert matched is True
    text = render(case)
    assert "CIR-20826" not in text
    assert "CIR-21912" not in text
    assert "历史 CIR" in text


def test_sop2_ascii_word_boundary() -> None:
    books = load_all(sop_dirs=[SOP2])
    assert match("maybe metrics down", "integrated", books) is None
    assert match("fe metrics down", "integrated", books) is not None
    book = match("fdb_client_thread_busyness_percent 大于 80%", "cloud", books)
    assert book is not None
    assert book.id == "fdb-thread"
    assert "SOP 2.0" not in book.title


def test_missing_sop_env_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("DORISOPS_SOP", str(tmp_path / "no-such-sop"))
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
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "ignoring" in captured.err
    assert "SHOW BACKENDS" in captured.out
    assert "SOP2 OVERRIDE" not in captured.out
