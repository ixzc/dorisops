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

    def score(self, alert: str) -> int:
        if any(pat.search(alert) for pat in self.matchers):
            return self.priority
        return 0


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise TypeError(f"expected string or list, got {type(value).__name__}")


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
        )
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
