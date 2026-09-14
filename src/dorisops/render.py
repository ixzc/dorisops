from __future__ import annotations

from dorisops.case import Case
from dorisops.engine import show_banner


def render(case: Case) -> str:
    waiting = not case.evidence and case.status != "in_progress"
    lines = [
        f"# {case.id}",
        "",
        f"- 档位: {case.lane}（不开集群连接，命令需你本地执行）",
        f"- 模式: {case.mode}",
        f"- 状态: {case.status} / {show_banner(case)}",
        f"- 节点: {case.node_id or '（无判定树）'}",
        f"- 剧本: {case.playbook_id or '（未匹配）'}"
        + (f" / {case.playbook_title}" if case.playbook_title else "")
        + (" · 模式不匹配，无命令包" if case.mode_mismatch else ""),
        "",
        "## 待证",
        case.pending_note,
        "",
    ]
    if waiting:
        lines.append("未回贴采集结果之前，禁止把告警标题当成已核实的集群结论。")
        lines.append("show 只能写「待人执行」，不能写集群数字。")
        lines.append("")
    else:
        lines.append("下面的数字只来自你回贴的文本，不是程序查询集群得到的。")
        lines.append("")
    lines.extend(
        [
            "## 30 秒卡片",
            f"- 本质: {case.essence}",
            f"- 影响面: {case.impact}",
            f"- 立即做: {case.do_now}",
            f"- 止损红线: {case.stop_line}",
            f"- 千万别: {case.never_do}",
            "",
            "## 本轮命令（程序不会执行）",
        ]
    )
    if not case.commands:
        if case.mode_mismatch:
            lines.append("（当前模式无命令包。请按上面的提示改 --mode 后重新开单，不要补 playbook-dir 硬跑。）")
        else:
            lines.append("（无命令。补充告警原文或 playbook 目录后再开单。）")
    for index, command in enumerate(case.commands, start=1):
        restart = "重启前必采" if command["before_restart"] else "可后补"
        lines.extend(
            [
                "",
                f"### {index}. `{command['id']}` · {restart}",
                f"- 执行位置: {command['where']}",
                f"- 看什么: {command['look_for']}",
                "",
                f"```{command['language']}",
                command["body"],
                "```",
            ]
        )
    if case.refusals:
        lines.extend(["", "## 拒绝执行"])
        for item in case.refusals:
            lines.append(f"- {item.get('at', '')}: {item.get('reason', '')}")
    if case.evidence:
        lines.extend(["", "## 已回贴（原文摘录）"])
        for item in case.evidence:
            matched = item.get("matched_advance") or "未前进"
            lines.extend(
                [
                    "",
                    f"### {item.get('source', '')} · 匹配={matched}",
                    "```",
                    _clip(item.get("text", "")),
                    "```",
                ]
            )
    lines.extend(
        [
            "",
            "## 告警原文",
            "```",
            case.alert.strip(),
            "```",
            "",
        ]
    )
    if case.conclusion:
        lines.extend(["## 结论", case.conclusion, ""])
    return "\n".join(lines)


def _clip(text: str, limit: int = 4000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（截断）"
