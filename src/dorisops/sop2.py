from __future__ import annotations

from pathlib import Path
import re
import sys

from dorisops.playbook import Command, Playbook, PlaybookError

SKIP_NAMES = {
    "template.md",
    "shared-facts.md",
    "agent-brief.md",
    "batch-protocol.md",
    "pilot-report.md",
    "verification-guide.md",
    "readme.md",
}

CARD_KEYS = {
    "本质": "essence",
    "影响面": "impact",
    "立即做": "do_now",
    "止损红线": "stop_line",
    "千万别": "never_do",
}

CLOUD_MARKERS = (
    "metaservice",
    "meta-service",
    "fdb",
    "recycler",
    "file-cache",
    "file_cache",
    "txn_kv",
    "compute-group",
)

FENCE = re.compile(r"```(\w+)\n(.*?)```", re.DOTALL)
TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
CARD_MARK = re.compile(r"30\s*秒卡片")
BULLET = re.compile(
    r"^-\s*\*\*(?P<key>本质|影响面|立即做|止损红线|千万别)\*\*[^：:]*[：:](?P<body>.*?)(?=\n-\s*\*\*|\n## |\Z)",
    re.MULTILINE | re.DOTALL,
)
CIR_RE = re.compile(
    r"CIR(?:[-_–—\s]+)?\d+(?:\s*[/_–—,-]\s*\d+)*",
    re.IGNORECASE,
)
CMD_LANGS = {"bash", "sh", "sql"}
TITLE_DECORATION = re.compile(
    r"（SOP\s*2\.0）|\(SOP\s*2\.0\)|\[(?:FE|BE|MS)\]|仅告警一次",
    re.IGNORECASE,
)
CUT_AFTER = re.compile(r"^#{2,}\s*.*(判定树|历史案例|断言核查)", re.MULTILINE)


def playbook_id_from_path(path: Path) -> str:
    stem = redact(path.stem.strip().lower())
    stem = re.sub(r"^\d+-", "", stem)
    stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-")
    return stem or "sop2-gap"


def redact(text: str) -> str:
    return CIR_RE.sub("CIR-REDACTED", text)


def load_sop2_dir(directory: Path) -> list[Playbook]:
    paths = sorted(directory.glob("*.md"))
    references = directory / "references"
    if references.is_dir():
        paths.extend(sorted(references.glob("*.md")))
    books: list[Playbook] = []
    seen: set[str] = set()
    for path in paths:
        if path.name.lower() in SKIP_NAMES:
            continue
        try:
            book = load_sop2_markdown(path)
        except PlaybookError as exc:
            sys.stderr.write(f"skip SOP 2.0 {path}: {exc}\n")
            continue
        if book is None:
            continue
        if book.id in seen:
            continue
        seen.add(book.id)
        books.append(book)
    return books


def load_sop2_markdown(path: Path) -> Playbook | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlaybookError(f"cannot read SOP 2.0 {path}: {exc}") from exc
    if not CARD_MARK.search(raw):
        return None
    try:
        return _parse_sop2(path, raw)
    except PlaybookError:
        raise
    except (KeyError, TypeError, ValueError, re.error) as exc:
        raise PlaybookError(f"invalid SOP 2.0 {path}: {exc}") from exc


def _parse_sop2(path: Path, raw: str) -> Playbook:
    raw = redact(raw)
    title_m = TITLE.search(raw)
    title = _clean_title(title_m.group(1).strip() if title_m else "")
    book_id = playbook_id_from_path(path)
    if not title:
        title = book_id.replace("-", " ")
    usable = raw
    cut = CUT_AFTER.search(raw)
    if cut:
        usable = raw[: cut.start()]
    fields = {value: "" for value in CARD_KEYS.values()}
    for match in BULLET.finditer(usable):
        key = CARD_KEYS[match.group("key")]
        fields[key] = match.group("body").strip()
    if not fields["essence"]:
        raise PlaybookError(f"SOP 2.0 {path} missing 本质")
    commands = _commands(usable)
    blob = f"{book_id} {title}".lower()
    modes: tuple[str, ...] = (
        ("cloud",) if any(marker in blob for marker in CLOUD_MARKERS) else ("integrated", "cloud")
    )
    return Playbook(
        id=book_id,
        title=title,
        modes=modes,
        matchers=(_matcher_from_title(title, book_id),),
        essence=fields["essence"],
        impact=fields["impact"] or "核对告警原文与集群模式，不要编造集群状态。",
        do_now=fields["do_now"] or "按命令块采集，回贴后再下结论。",
        stop_line=fields["stop_line"] or "业务已大面积受损时按紧急事件处理，先同步业务方。",
        never_do=fields["never_do"] or "不要无证据重启、不要编造 Alive。本工具不会连集群。",
        commands=tuple(commands),
        pending_note=(
            "本单来自本地 SOP 2.0 缺口补篇，尚未收到采集回贴。"
            "不要把告警标题当成已核实的集群状态，也不要写入历史 CIR。"
        ),
        priority=80,
    )


def _clean_title(title: str) -> str:
    cleaned = TITLE_DECORATION.sub(" ", title)
    cleaned = cleaned.replace("%", " ").replace("％", " ")
    return re.sub(r"\s+", " ", cleaned).strip(" -—|/")


def _matcher_from_title(title: str, book_id: str) -> re.Pattern[str]:
    parts = [part for part in _clean_title(title).split() if part] or [
        part for part in book_id.replace("-", " ").split() if part
    ]
    tokens: list[str] = []
    for part in parts:
        escaped = re.escape(part)
        if part.isascii() and re.fullmatch(r"[A-Za-z0-9_]+", part):
            escaped = rf"(?<![\w]){escaped}(?![\w])"
        tokens.append(escaped)
    if not tokens:
        tokens = [re.escape(book_id)]
    return re.compile(r"\s+".join(tokens), re.IGNORECASE)


def _commands(text: str) -> list[Command]:
    out: list[Command] = []
    seen: set[str] = set()
    for index, match in enumerate(FENCE.finditer(text), start=1):
        language = (match.group(1) or "").strip().lower()
        if language not in CMD_LANGS:
            continue
        block = match.group(2).strip("\n")
        if not block.strip():
            continue
        header = block.splitlines()[0] if block.splitlines() else ""
        cmd_id = _command_id(index, header)
        if cmd_id in seen:
            cmd_id = f"{cmd_id}-{index}"
        seen.add(cmd_id)
        where_m = re.search(r"执行位置[：:]\s*(.+)", block)
        where = (where_m.group(1).strip() if where_m else "本机（SOP 2.0 未标注执行位置）")
        where = where.split("）")[0].strip(" （")
        look_m = re.search(r"看什么[：:]\s*(.*)", block, re.DOTALL)
        look_for = " ".join((look_m.group(1) if look_m else "").split())
        if not look_for:
            look_for = "回贴输出后再下结论，不要编造集群状态。"
        if len(look_for) > 400:
            look_for = look_for[:397] + "…"
        lang = "sql" if language == "sql" else "bash"
        out.append(
            Command(
                id=cmd_id,
                where=where,
                look_for=look_for,
                body=block.strip("\n"),
                language=lang,
                before_restart="重启前" in header,
            )
        )
    return out


def _command_id(index: int, header: str) -> str:
    numbered = re.search(r"^\s*(?:#|--)\s*(\d+)\.", header)
    if numbered:
        return f"sop2-{numbered.group(1)}"
    return f"sop2-cmd-{index}"
