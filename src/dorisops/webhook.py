from __future__ import annotations

from urllib.parse import parse_qs
import hmac
import json


def extract_alert(payload: object, default_mode: str) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("webhook JSON must be an object")
    mode = str(payload.get("mode") or default_mode).strip()
    if mode not in {"integrated", "cloud"}:
        raise ValueError("mode must be integrated or cloud")
    for key in ("alert", "message", "text", "summary"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), mode
    alerts = payload.get("alerts")
    common_anns = payload.get("commonAnnotations") if isinstance(payload.get("commonAnnotations"), dict) else {}
    common_labels = payload.get("commonLabels") if isinstance(payload.get("commonLabels"), dict) else {}
    if isinstance(alerts, list):
        parts: list[str] = []
        had_alert = False
        had_firing = False
        for item in alerts:
            if not isinstance(item, dict):
                continue
            had_alert = True
            status = str(item.get("status") or "").strip().lower()
            if status == "resolved":
                continue
            had_firing = True
            labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
            anns = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}
            name = str(labels.get("alertname") or common_labels.get("alertname") or "").strip()
            desc = str(
                anns.get("description")
                or anns.get("summary")
                or common_anns.get("description")
                or common_anns.get("summary")
                or ""
            ).strip()
            instance = str(labels.get("instance") or common_labels.get("instance") or "").strip()
            job = str(labels.get("job") or "").strip()
            line = " ".join(part for part in (name, desc, instance, job) if part)
            if line:
                parts.append(line)
        if parts:
            return "\n".join(parts), mode
        if had_alert and not had_firing:
            raise ValueError("no firing alerts in webhook payload")
    title = payload.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip(), mode
    raise ValueError("no alert text found in webhook payload")


def payload_from_body(raw: str, content_type: str) -> dict:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    looks_json = raw.lstrip().startswith("{") or raw.lstrip().startswith("[")
    if ctype in {"application/json", "text/json"} or (not ctype and looks_json):
        loaded = json.loads(raw) if raw.strip() else {}
        if not isinstance(loaded, dict):
            raise ValueError("webhook JSON must be an object")
        return loaded
    fields = parse_qs(raw, keep_blank_values=True)
    return {key: (values[0] if values else "") for key, values in fields.items()}


def provided_token(header_auth: str, header_token: str) -> str:
    auth = (header_auth or "").strip()
    if auth.lower().startswith("bearer "):
        bearer = auth[7:].strip()
        if bearer:
            return bearer
    return (header_token or "").strip()


def token_matches(provided: str, expected: str) -> bool:
    if not expected:
        return False
    key = b"dorisops-webhook-token"
    left = hmac.digest(key, provided.encode("utf-8"), "sha256")
    right = hmac.digest(key, expected.encode("utf-8"), "sha256")
    return hmac.compare_digest(left, right)


def resolve_token(cli_token: str | None, env_token: str | None) -> str:
    if cli_token is not None:
        return cli_token.strip()
    return (env_token or "").strip()
