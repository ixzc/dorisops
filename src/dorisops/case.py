from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import secrets

from dorisops.playbook import Command, Playbook, commands_for_mode


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

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"


def new_case_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"CASE-{stamp}-{secrets.token_hex(4)}"


def open_case(alert: str, mode: str, book: Playbook | None) -> Case:
    cmds: list[Command] = commands_for_mode(book, mode) if book else []
    pending = (
        book.pending_note
        if book
        else "未命中内置 playbook。不要把告警标题当成已核实的集群状态。"
    )
    return Case(
        id=new_case_id(),
        created_at=datetime.now(timezone.utc).isoformat(),
        lane="L0",
        mode=mode,
        alert=alert,
        status="awaiting_evidence",
        playbook_id=book.id if book else None,
        playbook_title=book.title if book else None,
        pending_note=pending,
        essence=book.essence if book else "告警文本未能匹配内置剧本。",
        impact=book.impact if book else "未知。在采集之前不要假设业务已中断。",
        do_now=book.do_now if book else "核对告警原文、集群模式（一体/云），或改用 --playbook-dir。",
        stop_line=book.stop_line if book else "无。未匹配剧本时不要重启、不要改配置。",
        never_do=book.never_do if book else "不要编造 Alive、内存水位或 query 结论。",
        commands=[
            {
                "id": item.id,
                "where": item.where,
                "language": item.language,
                "before_restart": item.before_restart,
                "body": item.body,
                "look_for": item.look_for,
            }
            for item in cmds
        ],
        conclusion=None,
    )


def save_case(case: Case, store: Path) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        path = store / f"{case.id}.json"
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(case.to_json())
            return path
        except FileExistsError:
            case.id = new_case_id()
    raise RuntimeError(f"could not allocate a unique case id in {store}")
