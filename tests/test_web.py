from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from dorisops.cli import main
from dorisops.web import parse_bind, start_background

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "show_backends_alive_false.txt"
_OPENER = build_opener(ProxyHandler({}))


def _get(url: str) -> str:
    with _OPENER.open(url, timeout=5) as resp:
        return resp.read().decode("utf-8")


def _post(url: str, data: dict[str, str]) -> str:
    body = urlencode(data).encode("utf-8")
    req = Request(url, data=body, method="POST")
    with _OPENER.open(req, timeout=5) as resp:
        return resp.read().decode("utf-8")


def _case_id(html: str) -> str:
    return html.split("<h1>")[1].split("</h1>")[0]


@pytest.fixture
def web_url(tmp_path: Path):
    httpd, thread = start_background("127.0.0.1", 0, tmp_path / "cases")
    host, port = httpd.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_parse_bind_rejects_public() -> None:
    with pytest.raises(ValueError, match="loopback"):
        parse_bind("0.0.0.0:8787")
    host, port = parse_bind("127.0.0.1:8787")
    assert host == "127.0.0.1"
    assert port == 8787
    assert main(["web", "--bind", "0.0.0.0:9"]) == 2


def test_web_open_be_node_down_copy_commands(web_url: str) -> None:
    html = _post(
        f"{web_url}/cases",
        {"alert": "be node down on host X", "mode": "integrated"},
    )
    assert "SHOW BACKENDS" in html
    assert "/api/health" in html
    assert 'class="copy"' in html or "class='copy'" in html
    assert "待人执行" in html
    assert "已查询集群" not in html
    assert "没有「去查集群」按钮" in html


def test_web_reply_advances_tree(web_url: str) -> None:
    opened = _post(
        f"{web_url}/cases",
        {"alert": "be node down on host X", "mode": "integrated"},
    )
    case_id = _case_id(opened)
    html = _post(
        f"{web_url}/cases/{case_id}/reply",
        {"output": FIXTURE.read_text(encoding="utf-8")},
    )
    assert "be-logs-heartbeat" in html
    assert "probe-heartbeat-port" in html
    assert "<code>show-backends</code>" not in html


def test_web_metaservice_integrated_hint(web_url: str) -> None:
    html = _post(
        f"{web_url}/cases",
        {"alert": "metaservice node down", "mode": "integrated"},
    )
    assert "云模式" in html or "存算分离" in html
    assert "ms-status" not in html
    assert "SHOW PROC '/cluster_health/tablet_health'" not in html
    assert "ADMIN REBALANCE" not in html
    index = _get(f"{web_url}/")
    assert "CASE-" in index
    assert "模式不匹配" in index


def test_web_refuse(web_url: str) -> None:
    opened = _post(
        f"{web_url}/cases",
        {"alert": "be node down on host X", "mode": "integrated"},
    )
    html = _post(
        f"{web_url}/cases/{_case_id(opened)}/refuse",
        {"reason": "无跳板机权限"},
    )
    assert "无跳板机权限" in html
    assert "已拒绝" in html


def test_web_missing_case_is_404(web_url: str) -> None:
    with pytest.raises(HTTPError) as err:
        _post(f"{web_url}/cases/CASE-does-not-exist/reply", {"output": "x"})
    assert err.value.code == 404


def test_web_index_skips_bad_json(tmp_path: Path) -> None:
    store = tmp_path / "cases"
    store.mkdir()
    (store / "CASE-null.json").write_text("null\n", encoding="utf-8")
    httpd, thread = start_background("127.0.0.1", 0, store)
    host, port = httpd.server_address[:2]
    try:
        html = _get(f"http://{host}:{port}/")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
    assert "开一张 L0 单" in html
