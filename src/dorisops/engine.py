from __future__ import annotations

from dorisops.case import (
    STATUS_AWAITING,
    STATUS_BLOCKED,
    STATUS_IN_PROGRESS,
    Case,
    command_dicts,
    utc_now,
)
from dorisops.playbook import Playbook, commands_for_node, next_node


def reply_case(case: Case, text: str, source: str, book: Playbook | None) -> Case:
    snippet = text.strip()
    if not snippet:
        raise ValueError("reply text is empty")
    matched = None
    next_id = case.node_id
    if book is not None and not book.nodes:
        case.pending_note = (
            "已记录回贴。该剧本没有判定树，命令清单不变。"
            "不要把回贴内容当成程序已经查过集群。"
        )
    elif book is not None:
        next_id, matched = next_node(book, case.node_id, snippet)
        if next_id != case.node_id:
            case.node_id = next_id
            case.commands = command_dicts(commands_for_node(book, next_id, case.mode))
            node = book.node_map().get(next_id or "")
            if matched and matched.note:
                case.pending_note = matched.note
            elif node and node.pending_note:
                case.pending_note = node.pending_note
            else:
                case.pending_note = "判定树已前进。下一轮命令需你本地执行，程序没有查询集群。"
        else:
            case.pending_note = (
                "已回贴，但未命中当前节点的判定关键字。命令仍是本轮清单；"
                "不要把未匹配的输出解读成已核实的集群结论。"
            )
    else:
        case.pending_note = (
            "已回贴，但当前没有可用 playbook，无法推进判定树。"
            "不要把回贴内容当成程序已经查过集群。"
        )
    case.evidence.append(
        {
            "at": utc_now(),
            "source": source,
            "node_id": case.node_id,
            "matched_advance": matched.next_id if matched else None,
            "text": snippet,
        }
    )
    case.status = STATUS_IN_PROGRESS
    case.updated_at = utc_now()
    case.conclusion = None
    return case


def refuse_case(case: Case, reason: str) -> Case:
    cleaned = reason.strip()
    if not cleaned:
        raise ValueError("refuse reason is empty")
    case.refusals.append({"at": utc_now(), "reason": cleaned})
    case.status = STATUS_BLOCKED
    case.updated_at = utc_now()
    case.pending_note = (
        f"已拒绝执行：{cleaned}。单仍打开，没有采集回贴，不要编造 Alive、内存或 query 结论。"
    )
    case.conclusion = None
    return case


def show_banner(case: Case) -> str:
    if case.refusals and case.status == STATUS_BLOCKED:
        return "打开（已拒绝执行）"
    if case.status == STATUS_AWAITING and not case.evidence:
        return "待人执行"
    if case.status == STATUS_IN_PROGRESS:
        return "已有回贴，待下一轮"
    return case.status
