from __future__ import annotations

from pathlib import Path

from dorisops.playbook import load_all, match


def test_be_node_down_matches() -> None:
    books = load_all()
    book = match("CRITICAL be node down on host X", "integrated", books)
    assert book is not None
    assert book.id == "be-node-down"


def test_memory_used_matches() -> None:
    books = load_all()
    book = match("MemoryUsed 大于 95%", "cloud", books)
    assert book is not None
    assert book.id == "memory-pressure"


def test_unknown_alert_does_not_match() -> None:
    books = load_all()
    assert match("disk write time 大于 1000ms", "integrated", books) is None


def test_backend_not_alive_matches() -> None:
    books = load_all()
    book = match("backend not alive on host X", "integrated", books)
    assert book is not None
    assert book.id == "be-node-down"


def test_be_offline_substring_false_positives() -> None:
    books = load_all()
    assert match("The HTTP probe is offline", "integrated", books) is None
    assert match("number of tablets offline", "integrated", books) is None
    assert match("maybe the node is offline", "integrated", books) is None


def test_cloud_extra_command_hidden_in_integrated() -> None:
    from dorisops.playbook import commands_for_mode

    books = load_all()
    book = match("be node down", "integrated", books)
    assert book is not None
    shown = [item.id for item in commands_for_mode(book, "integrated")]
    assert "show-backends" in shown
    assert "show-compute-groups" not in shown
    cloud = [item.id for item in commands_for_mode(book, "cloud")]
    assert "show-compute-groups" in cloud


def test_extra_playbook_dir_overrides(tmp_path: Path) -> None:
    extra = tmp_path / "pack"
    extra.mkdir()
    (extra / "be-node-down.toml").write_text(
        """
id = "be-node-down"
title = "override"
modes = ["integrated"]
essence = "x"
impact = "x"
do_now = "x"
stop_line = "x"
never_do = "x"
pending_note = "x"

[[matchers]]
pattern = "be\\\\s+node\\\\s+down"
""",
        encoding="utf-8",
    )
    books = load_all([extra])
    book = match("be node down on host X", "integrated", books)
    assert book is not None
    assert book.title == "override"
