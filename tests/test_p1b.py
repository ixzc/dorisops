from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

import pytest

from dorisops.case import list_cases, load_case
from dorisops.web import MAX_BODY, start_background
from dorisops.webhook import (
    extract_alert,
    payload_from_body,
    provided_token,
    resolve_token,
    token_matches,
)

from test_web import _OPENER, _get


TOKEN = "p1b-secret"


def _post_hook(url: str, body, headers: dict[str, str] | None = None, token: str | None = TOKEN):
    if isinstance(body, (dict, list)):
        payload = json.dumps(body).encode("utf-8")
        ctype = "application/json"
    else:
        payload = body if isinstance(body, bytes) else str(body).encode("utf-8")
        ctype = "application/x-www-form-urlencoded"
    hdrs = {"Content-Type": ctype}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hdrs.update(headers or {})
    req = Request(url, data=payload, method="POST", headers=hdrs)
    try:
        with _OPENER.open(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as err:
        raw = err.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"error": raw}
        return err.code, parsed


@pytest.fixture
def hook(tmp_path: Path):
    store = tmp_path / "cases"
    httpd, thread = start_background(
        "127.0.0.1", 0, store, webhook_token=TOKEN, webhook_mode="integrated"
    )
    host, port = httpd.server_address[:2]
    try:
        yield f"http://{host}:{port}", store
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_extract_alert_generic_and_alertmanager() -> None:
    text, mode = extract_alert({"alert": "be node down on host X", "mode": "cloud"}, "integrated")
    assert text == "be node down on host X"
    assert mode == "cloud"
    text, mode = extract_alert(
        {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "BENodeDown"},
                    "annotations": {"description": "be node down on host X"},
                }
            ]
        },
        "integrated",
    )
    assert "BENodeDown" in text
    assert "be node down on host X" in text
    assert mode == "integrated"
    with pytest.raises(ValueError, match="no alert text"):
        extract_alert({"mode": "integrated"}, "integrated")
    with pytest.raises(ValueError, match="mode"):
        extract_alert({"alert": "x", "mode": "hybrid"}, "integrated")
    with pytest.raises(ValueError, match="no firing alerts"):
        extract_alert(
            {"alerts": [{"status": "resolved", "labels": {"alertname": "BENodeDown"}}]},
            "integrated",
        )
    text, mode = extract_alert(
        {
            "alerts": [
                {
                    "status": "resolved",
                    "labels": {"alertname": "OldAlert"},
                    "annotations": {"description": "old"},
                },
                {
                    "status": "firing",
                    "labels": {"alertname": "BENodeDown", "instance": "10.0.0.1:9050"},
                    "annotations": {"summary": "be node down"},
                },
            ]
        },
        "cloud",
    )
    assert mode == "cloud"
    assert "OldAlert" not in text
    assert "10.0.0.1:9050" in text
    assert "be node down" in text


def test_payload_and_token_helpers() -> None:
    assert payload_from_body('{"alert":"x"}', "application/json") == {"alert": "x"}
    assert payload_from_body('{"alert":"x"}', "") == {"alert": "x"}
    form = payload_from_body("alert=be+down&mode=cloud", "application/x-www-form-urlencoded")
    assert form["alert"] == "be down"
    assert form["mode"] == "cloud"
    assert token_matches(TOKEN, TOKEN)
    assert not token_matches("nope", TOKEN)
    assert not token_matches(TOKEN, "")
    assert resolve_token(" cli ", "env") == "cli"
    assert resolve_token(None, " env ") == "env"
    assert resolve_token(None, None) == ""
    assert provided_token("Bearer ", TOKEN) == TOKEN
    assert provided_token("Bearer real", "ignored") == "real"
    assert provided_token("", TOKEN) == TOKEN


def test_webhook_disabled_is_403(tmp_path: Path) -> None:
    httpd, thread = start_background("127.0.0.1", 0, tmp_path / "cases")
    host, port = httpd.server_address[:2]
    try:
        code, body = _post_hook(
            f"http://{host}:{port}/hooks/alert",
            {"alert": "be node down on host X"},
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
    assert code == 403
    assert "disabled" in body["error"]


def test_webhook_wrong_token_is_401(hook) -> None:
    url, store = hook
    code, body = _post_hook(f"{url}/hooks/alert", {"alert": "be node down"}, token="wrong")
    assert code == 401
    assert body["error"] == "unauthorized"
    assert list_cases(store) == []


def test_webhook_opens_l0_case_without_cluster_io(hook) -> None:
    url, store = hook
    code, body = _post_hook(
        f"{url}/hooks/alert",
        {"alert": "be node down on host X", "mode": "integrated"},
    )
    assert code == 201
    assert body["lane"] == "L0"
    assert body["matched"] is True
    assert body["playbook_id"] == "be-node-down"
    assert body["mode"] == "integrated"
    assert "Do not invent Alive" in body["note"]
    assert "No cluster was queried" in body["note"]
    case = load_case(store, body["case_id"])
    html = _get(f"{url}/cases/{case.id}")
    assert "SHOW BACKENDS" in html
    assert "待人执行" in html
    assert "已查询集群" not in html
    assert "Alive true=" not in html
    assert "不要" in html and "Alive=false" in html


def test_webhook_alertmanager_and_header_token(hook) -> None:
    url, store = hook
    code, body = _post_hook(
        f"{url}/hooks/alert",
        {
            "alerts": [
                {
                    "labels": {"alertname": "BENodeDown"},
                    "annotations": {"description": "be node down on host X"},
                }
            ]
        },
        headers={"Authorization": "Bearer ", "X-DorisOps-Token": TOKEN},
        token=None,
    )
    assert code == 201
    assert body["playbook_id"] == "be-node-down"
    assert list_cases(store)[0].id == body["case_id"]


def test_webhook_form_body_uses_header_not_query(tmp_path: Path) -> None:
    store = tmp_path / "cases"
    httpd, thread = start_background(
        "127.0.0.1", 0, store, webhook_token=TOKEN, webhook_mode="cloud"
    )
    host, port = httpd.server_address[:2]
    url = f"http://{host}:{port}"
    try:
        payload = urlencode({"alert": "metaservice node down"}).encode("utf-8")
        req = Request(
            f"{url}/hooks/alert",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Bearer {TOKEN}",
            },
        )
        with _OPENER.open(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 201
        assert body["mode"] == "cloud"
        assert body["playbook_id"] == "metaservice-down"
        empty_code, empty_body = _post_hook(f"{url}/hooks/alert", {"mode": "cloud"})
        assert empty_code == 400
        assert "no alert text" in empty_body["error"]
        query_code, query_body = _post_hook(
            f"{url}/hooks/alert?token={TOKEN}",
            {"alert": "be node down on host X"},
            token=None,
        )
        assert query_code == 401
        assert query_body["error"] == "unauthorized"
        bad_json, bad_body = _post_hook(
            f"{url}/hooks/alert",
            b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert bad_json == 400
        assert "invalid JSON" in bad_body["error"]
        huge_code, huge_body = _post_hook(
            f"{url}/hooks/alert",
            b"x" * (MAX_BODY + 1),
            headers={"Content-Type": "application/json"},
        )
        assert huge_code == 413
        assert "too large" in huge_body["error"].lower()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
