from __future__ import annotations

from dorisops.case import Case


def render(case: Case) -> str:
    lines = [
        f"# {case.id}",
        "",
        f"- 档位: {case.lane}（不开集群连接，命令需你本地执行）",
        f"- 模式: {case.mode}",
        f"- 状态: {case.status}",
        f"- 剧本: {case.playbook_id or '（未匹配）'}"
        + (f" / {case.playbook_title}" if case.playbook_title else ""),
        "",
        "## 待证",
        case.pending_note,
        "",
        "未回贴采集结果之前，禁止把告警标题当成已核实的集群结论。",
        "",
        "## 30 秒卡片",
        f"- 本质: {case.essence}",
        f"- 影响面: {case.impact}",
        f"- 立即做: {case.do_now}",
        f"- 止损红线: {case.stop_line}",
        f"- 千万别: {case.never_do}",
        "",
        "## 本轮命令（程序不会执行）",
    ]
    if not case.commands:
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
    return "\n".join(lines)
