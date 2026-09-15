from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


PLACEHOLDERS = {
    "",
    "CHANGE_ME",
    "changeme",
    "READONLY_USER",
    "password",
    "******",
}


class ClusterError(ValueError):
    """Invalid cluster.yaml."""


@dataclass(frozen=True)
class ClusterConfig:
    name: str
    mode: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str = field(repr=False)
    fe_http_url: str
    backend_http_urls: tuple[str, ...] = ()
    ms_http_url: str = ""
    path: Path | None = None

    def credentials_ready(self) -> bool:
        if self.mysql_password.strip() in PLACEHOLDERS:
            return False
        if self.mysql_user.strip() in PLACEHOLDERS:
            return False
        if not self.mysql_host.strip() or not self.mysql_user.strip():
            return False
        return True


def load_cluster_yaml(path: Path) -> ClusterConfig:
    if not path.is_file():
        raise ClusterError(f"cluster file not found: {path}")
    data = _parse_simple_yaml(path.read_text(encoding="utf-8"))
    fe = data.get("fe")
    if not isinstance(fe, dict):
        raise ClusterError("cluster.yaml missing fe: mapping")
    mode = str(data.get("mode", "integrated")).strip()
    if mode not in {"integrated", "cloud"}:
        raise ClusterError("mode must be integrated or cloud")
    backends = data.get("backends") or []
    urls: list[str] = []
    if isinstance(backends, list):
        for item in backends:
            if isinstance(item, dict):
                url = _as_str(item.get("http_url"))
                if url:
                    urls.append(url)
    try:
        port = int(fe.get("mysql_port", 9030))
    except (TypeError, ValueError) as exc:
        raise ClusterError("fe.mysql_port must be an integer") from exc
    return ClusterConfig(
        name=_as_str(data.get("name", path.stem)) or path.stem,
        mode=mode,
        mysql_host=_as_str(fe.get("mysql_host")),
        mysql_port=port,
        mysql_user=_as_str(fe.get("mysql_user")),
        mysql_password=str(fe.get("mysql_password") or ""),
        fe_http_url=_as_str(fe.get("http_url")),
        backend_http_urls=tuple(urls),
        ms_http_url=_ms_http_url(data.get("meta_service")),
        path=path,
    )


def _ms_http_url(meta: object) -> str:
    if not isinstance(meta, dict):
        return ""
    return _as_str(meta.get("http_url"))


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_simple_yaml(text: str) -> dict:
    """Parse cluster.yaml. Uses PyYAML when installed; otherwise a tiny subset."""
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise ClusterError("cluster.yaml must be a mapping")
        return loaded
    return _parse_without_pyyaml(text)


def _parse_without_pyyaml(text: str) -> dict:
    """Scalars, one-level maps, and lists of maps — enough for cluster.yaml."""
    root: dict = {}
    section: str | None = None
    section_map: dict | None = None
    section_list: list | None = None
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0 and stripped.endswith(":") and " " not in stripped[:-1]:
            section = stripped[:-1]
            section_map = {}
            section_list = []
            root[section] = section_map
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            root[key.strip()] = _scalar(value)
            section = None
            section_map = None
            section_list = None
            continue
        if section is None:
            raise ClusterError(f"unexpected line: {stripped}")
        if stripped.startswith("- "):
            if section_list is None:
                section_list = []
            item: dict = {}
            rest = stripped[2:]
            if ":" in rest:
                key, value = rest.split(":", 1)
                if value.strip() == "":
                    pass
                else:
                    item[key.strip()] = _scalar(value)
            section_list.append(item)
            root[section] = section_list
            section_map = item
            continue
        if ":" in stripped and section_map is not None:
            key, value = stripped.split(":", 1)
            section_map[key.strip()] = _scalar(value)
            continue
        raise ClusterError(f"unexpected line: {stripped}")
    return root


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    out: list[str] = []
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out)


def _scalar(value: str) -> object:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text
