from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]


class PlaybookError(ValueError):
    """Invalid playbook file or extra directory."""


@dataclass(frozen=True)
class Command:
    id: str
    where: str
    look_for: str
    body: str
    language: str = "bash"
    before_restart: bool = False
    modes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Advance:
    pattern: re.Pattern[str]
    next_id: str
    note: str


@dataclass(frozen=True)
class Node:
    id: str
    title: str
    command_ids: tuple[str, ...]
    pending_note: str
    advances: tuple[Advance, ...] = ()


@dataclass(frozen=True)
class Playbook:
    id: str
    title: str
    modes: tuple[str, ...]
    matchers: tuple[re.Pattern[str], ...]
    essence: str
    impact: str
    do_now: str
    stop_line: str
    never_do: str
    commands: tuple[Command, ...]
    pending_note: str
    priority: int = 100
    start_node: str = ""
    nodes: tuple[Node, ...] = ()

    def score(self, alert: str) -> int:
        if any(pat.search(alert) for pat in self.matchers):
            return self.priority
        return 0

    def command_map(self) -> dict[str, Command]:
        return {item.id: item for item in self.commands}

    def node_map(self) -> dict[str, Node]:
        return {item.id: item for item in self.nodes}

    def initial_node_id(self) -> str | None:
        if not self.nodes:
            return None
        if self.start_node:
            return self.start_node
        return self.nodes[0].id


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise TypeError(f"expected string or list, got {type(value).__name__}")


def _load_nodes(data: dict) -> tuple[str, tuple[Node, ...]]:
    raw_nodes = data.get("nodes") or []
    nodes: list[Node] = []
    for item in raw_nodes:
        advances = tuple(
            Advance(
                pattern=re.compile(row["pattern"], re.IGNORECASE | re.DOTALL),
                next_id=str(row["next"]),
                note=str(row.get("note", "")).strip(),
            )
            for row in item.get("advances") or []
        )
        nodes.append(
            Node(
                id=str(item["id"]),
                title=str(item.get("title", item["id"])).strip(),
                command_ids=_as_tuple(item.get("commands")),
                pending_note=str(item.get("pending_note", "")).strip(),
                advances=advances,
            )
        )
    ids = [item.id for item in nodes]
    if len(ids) != len(set(ids)):
        raise PlaybookError("duplicate node id")
    known = set(ids)
    start = str(data.get("start_node", "")).strip()
    if start and start not in known:
        raise PlaybookError(f"start_node {start!r} is not a node id")
    catalog = {str(item.get("id", "")) for item in data.get("commands") or []}
    for node in nodes:
        for command_id in node.command_ids:
            if command_id not in catalog:
                raise PlaybookError(f"node {node.id!r} unknown command {command_id!r}")
        for advance in node.advances:
            if advance.next_id not in known:
                raise PlaybookError(
                    f"node {node.id!r} advances to unknown {advance.next_id!r}"
                )
    return start, tuple(nodes)


def load_playbook(path: Path) -> Playbook:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        matchers = tuple(
            re.compile(item["pattern"], re.IGNORECASE)
            for item in data.get("matchers", [])
        )
        commands = []
        for item in data.get("commands", []):
            modes = _as_tuple(item.get("modes"))
            commands.append(
                Command(
                    id=str(item["id"]),
                    where=str(item["where"]),
                    look_for=str(item["look_for"]),
                    body=str(item["body"]).strip("\n"),
                    language=str(item.get("language", "bash")),
                    before_restart=bool(item.get("before_restart", False)),
                    modes=modes,
                )
            )
        try:
            start_node, nodes = _load_nodes(data)
        except PlaybookError as exc:
            raise PlaybookError(f"invalid playbook {path}: {exc}") from exc
        return Playbook(
            id=str(data["id"]),
            title=str(data["title"]),
            modes=_as_tuple(data.get("modes")) or ("integrated", "cloud"),
            matchers=matchers,
            essence=str(data["essence"]).strip(),
            impact=str(data["impact"]).strip(),
            do_now=str(data["do_now"]).strip(),
            stop_line=str(data["stop_line"]).strip(),
            never_do=str(data["never_do"]).strip(),
            commands=tuple(commands),
            pending_note=str(data["pending_note"]).strip(),
            priority=int(data.get("priority", 100)),
            start_node=start_node,
            nodes=nodes,
        )
    except PlaybookError:
        raise
    except (tomllib.TOMLDecodeError, KeyError, re.error, TypeError, ValueError) as exc:
        raise PlaybookError(f"invalid playbook {path}: {exc}") from exc


def builtin_dir() -> Path:
    return Path(__file__).resolve().parent / "playbooks"


def load_all(extra_dirs: list[Path] | None = None) -> list[Playbook]:
    books: list[Playbook] = []
    seen: set[str] = set()
    extra = extra_dirs or []
    for directory in extra:
        if not directory.is_dir():
            raise PlaybookError(f"playbook dir not found: {directory}")
    for directory in [builtin_dir(), *extra]:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.toml")):
            book = load_playbook(path)
            if book.id in seen:
                books = [item for item in books if item.id != book.id]
            seen.add(book.id)
            books.append(book)
    return books


def match(alert: str, mode: str, books: list[Playbook]) -> Playbook | None:
    ranked: list[tuple[int, Playbook]] = []
    for book in books:
        if mode not in book.modes:
            continue
        score = book.score(alert)
        if score > 0:
            ranked.append((score, book))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return ranked[0][1]


def commands_for_mode(book: Playbook, mode: str) -> list[Command]:
    out = []
    for command in book.commands:
        if command.modes and mode not in command.modes:
            continue
        out.append(command)
    return out


def commands_for_node(book: Playbook, node_id: str | None, mode: str) -> list[Command]:
    catalog = book.command_map()
    if not book.nodes or not node_id:
        return commands_for_mode(book, mode)
    node = book.node_map().get(node_id)
    if node is None:
        return []
    out: list[Command] = []
    for command_id in node.command_ids:
        command = catalog.get(command_id)
        if command is None:
            continue
        if command.modes and mode not in command.modes:
            continue
        out.append(command)
    return out


def next_node(book: Playbook, node_id: str | None, text: str) -> tuple[str | None, Advance | None]:
    if not book.nodes:
        return node_id, None
    current_id = node_id or book.initial_node_id()
    node = book.node_map().get(current_id or "")
    if node is None:
        return current_id, None
    for advance in node.advances:
        if advance.pattern.search(text):
            return advance.next_id, advance
    return current_id, None
