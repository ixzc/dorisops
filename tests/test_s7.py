from __future__ import annotations

from pathlib import Path

from dorisops.mcp_api import L0_NO_INVENT, McpSession, TOOL_NAMES

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "cluster.example.yaml"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "show_backends_alive_false.txt"


def test_tool_names_match_plan() -> None:
    assert TOOL_NAMES == (
        "case_open",
        "case_show",
        "case_reply",
        "case_refuse",
        "case_export",
        "inspect_cluster",
    )


def test_case_open_be_node_down(tmp_path: Path) -> None:
    session = McpSession(store=tmp_path / "cases")
    out = session.case_open("be node down on host X", "integrated")
    assert out.startswith("# CASE-")
    assert "SHOW BACKENDS" in out
    assert "已查询集群" not in out
    assert "Alive=false" in out  # warning not to invent it
    assert "awaiting_evidence" in out


def test_inspect_without_cluster_does_not_invent_alive(tmp_path: Path) -> None:
    session = McpSession(store=tmp_path / "cases")
    out = session.inspect_cluster()
    assert "level: L0" in out
    assert L0_NO_INVENT.split(".")[0] in out
    assert "Alive true=" not in out
    assert "[OK] SHOW FRONTENDS" not in out
    assert "case_open" in out.lower() or "case open" in out


def test_inspect_placeholders_stay_l0(tmp_path: Path) -> None:
    session = McpSession(store=tmp_path / "cases")
    out = session.inspect_cluster(cluster_path=str(EXAMPLE))
    assert "level: L0" in out
    assert "CHANGE_ME" in out
    assert L0_NO_INVENT.split(".")[0] in out
    assert "[OK] SHOW FRONTENDS" not in out


def test_case_show_waiting_and_reply(tmp_path: Path) -> None:
    session = McpSession(store=tmp_path / "cases")
    opened = session.case_open("be node down on host X", "integrated")
    case_id = opened.splitlines()[0].lstrip("# ").strip()
    shown = session.case_show(case_id)
    assert "待人执行" in shown or "awaiting_evidence" in shown
    assert "已查询集群" not in shown
    replied = session.case_reply(case_id, output=FIXTURE.read_text(encoding="utf-8"))
    assert "Alive" in replied
    assert "be-logs-heartbeat" in replied or "in_progress" in replied


def test_case_refuse(tmp_path: Path) -> None:
    session = McpSession(store=tmp_path / "cases")
    opened = session.case_open("be node down on host X", "integrated")
    case_id = opened.splitlines()[0].lstrip("# ").strip()
    out = session.case_refuse(case_id, "no jumphost")
    assert "no jumphost" in out
    assert "blocked" in out


def test_mcp_cli_without_sdk(tmp_path: Path, capsys, monkeypatch) -> None:
    import dorisops.mcp_server as server
    from dorisops.cli import main

    def _boom(_session):
        raise ImportError("the mcp package is required for `dorisops mcp`")

    monkeypatch.setattr(server, "serve_stdio", _boom)
    code = main(["mcp", "--store", str(tmp_path / "cases")])
    assert code == 2
    err = capsys.readouterr().err
    assert "dorisops[mcp]" in err
