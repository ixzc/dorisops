from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import secrets

from dorisops.playbook import Command, Playbook, commands_for_node, mode_mismatch_note


STATUS_AWAITING = "awaiting_evidence"
STATUS_IN_PROGRESS = "in_progress"
STATUS_BLOCKED = "blocked"


def default_store() -> Path:
    override = os.environ.get("DORISOPS_HOME")
    root = Path(override) if override else Path.home() / ".dorisops"
    return root / "cases"


@dataclass
class Case:
    id: str
    created_at: str
    lane: str
    mode: str
    alert: str
    status: str
    playbook_id: str | None
    playbook_title: str | None
    pending_note: str
    essence: str
    impact: str
    do_now: str
    stop_line: str
    never_do: str
    commands: list[dict]
    conclusion: str | None = None
    node_id: str | None = None
    updated_at: str | None = None
    evidence: list[dict] = field(default_factory=list)
    refusals: list[dict] = field(default_factory=list)
    mode_mismatch: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_dict(cls, data: dict) -> Case:
        known = {key.name for key in cls.__dataclass_fields__.values()}
        payload = {key: value for key, value in data.items() if key in known}
        payload.setdefault("evidence", [])
        payload.setdefault("refusals", [])
        payload.setdefault("node_id", None)
        payload.setdefault("updated_at", None)
        payload.setdefault("conclusion", None)
        payload.setdefault("mode_mismatch", False)
        return cls(**payload)


def new_case_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"CASE-{stamp}-{secrets.token_hex(4)}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def command_dicts(cmds: list[Command]) -> list[dict]:
    return [
        {
            "id": item.id,
            "where": item.where,
            "language": item.language,
            "before_restart": item.before_restart,
            "body": item.body,
            "look_for": item.look_for,
        }
        for item in cmds
    ]


def open_case(
    alert: str,
    mode: str,
    book: Playbook | None,
    mismatch: Playbook | None = None,
) -> Case:
    created = utc_now()
    if book is None and mismatch is not None:
        return Case(
            id=new_case_id(),
            created_at=created,
            lane="L0",
            mode=mode,
            alert=alert,
            status=STATUS_AWAITING,
            playbook_id=mismatch.id,
            playbook_title=mismatch.title,
            pending_note=mode_mismatch_note(mismatch, mode),
            essence=mismatch.essence,
            impact=mismatch.impact,
            do_now=f"改用 --mode {' / '.join(mismatch.modes)} 后重新开单。当前模式没有可执行命令包。",
            stop_line=mismatch.stop_line,
            never_do=mismatch.never_do,
            commands=[],
            conclusion=None,
            node_id=None,
            updated_at=created,
            evidence=[],
            refusals=[],
            mode_mismatch=True,
        )
    node_id = book.initial_node_id() if book else None
    cmds: list[Command] = commands_for_node(book, node_id, mode) if book else []
    pending = (
        book.pending_note
        if book
        else "未命中内置 playbook。不要把告警标题当成已核实的集群状态。"
    )
    if book and node_id:
        node = book.node_map().get(node_id)
        if node and node.pending_note:
            pending = node.pending_note
    return Case(
        id=new_case_id(),
        created_at=created,
        lane="L0",
        mode=mode,
        alert=alert,
        status=STATUS_AWAITING,
        playbook_id=book.id if book else None,
        playbook_title=book.title if book else None,
        pending_note=pending,
        essence=book.essence if book else "告警文本未能匹配内置剧本。",
        impact=book.impact if book else "未知。在采集之前不要假设业务已中断。",
        do_now=book.do_now if book else "核对告警原文、集群模式（一体/云），或改用 --playbook-dir。",
        stop_line=book.stop_line if book else "无。未匹配剧本时不要重启、不要改配置。",
        never_do=book.never_do if book else "不要编造 Alive、内存水位或 query 结论。",
        commands=command_dicts(cmds),
        conclusion=None,
        node_id=node_id,
        updated_at=created,
        evidence=[],
        refusals=[],
        mode_mismatch=False,
    )


class CaseStoreError(ValueError):
    """Missing or ambiguous case id."""


def find_case_path(store: Path, case_id: str) -> Path:
    token = case_id.strip()
    if not token or any(ch in token for ch in "/\\:*?[]"):
        raise CaseStoreError("invalid case id")
    if ".." in token:
        raise CaseStoreError("invalid case id")
    exact = store / f"{token}.json"
    if exact.is_file():
        return exact
    matches = sorted(path for path in store.glob("CASE-*.json") if path.stem.startswith(token))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise CaseStoreError(f"case not found: {token}")
    names = ", ".join(path.stem for path in matches)
    raise CaseStoreError(f"ambiguous case id {token!r}: {names}")


def load_case(store: Path, case_id: str) -> Case:
    path = find_case_path(store, case_id)
    try:
        return Case.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise CaseStoreError(f"invalid case file {path.name}: {exc}") from exc


def save_case(case: Case, store: Path, *, replace: bool = False) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    if replace:
        path = store / f"{case.id}.json"
        path.write_text(case.to_json(), encoding="utf-8")
        return path
    for _ in range(8):
        path = store / f"{case.id}.json"
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(case.to_json())
            return path
        except FileExistsError:
            case.id = new_case_id()
    raise RuntimeError(f"could not allocate a unique case id in {store}")
