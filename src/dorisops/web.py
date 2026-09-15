from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import re
import sys
import threading

from dorisops import __version__
from dorisops.case import Case, CaseStoreError
from dorisops.engine import show_banner
from dorisops.playbook import PlaybookError
from dorisops.service import (
    cases_for_index,
    open_from_alert,
    refuse_from_reason,
    reply_from_text,
    show_from_id,
)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_BODY = 512 * 1024


def parse_bind(spec: str) -> tuple[str, int]:
    raw = spec.strip()
    if raw.startswith("["):
        raise ValueError("use 127.0.0.1:8787 (IPv6 bind is not enabled in S4)")
    if raw.count(":") != 1:
        raise ValueError("bind must look like 127.0.0.1:8787")
    host, port_s = raw.split(":", 1)
    if host not in LOOPBACK_HOSTS:
        raise ValueError("web bind must be loopback (127.0.0.1 or localhost); public bind is not allowed")
    try:
        port = int(port_s)
    except ValueError as exc:
        raise ValueError("bind port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("bind port out of range")
    return host, port


def serve(host: str, port: int, store: Path, extra_dirs: list[Path] | None = None) -> None:
    httpd = make_server(host, port, store, extra_dirs)
    bind_host, bind_port = httpd.server_address[:2]
    sys.stderr.write(
        f"dorisops web {__version__}  http://{bind_host}:{bind_port}/  (loopback only, no cluster I/O)\n"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstopping\n")
    finally:
        httpd.server_close()


def make_server(
    host: str,
    port: int,
    store: Path,
    extra_dirs: list[Path] | None = None,
) -> HTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("web bind must be loopback (127.0.0.1 or localhost)")
    handler = _handler_class(store, list(extra_dirs or []))
    return HTTPServer((host, port), handler)


def _handler_class(store: Path, extra_dirs: list[Path]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def do_GET(self) -> None:
            if not self._loopback_host():
                self._html(403, _page("Forbidden", "<p>Host must be loopback.</p>"))
                return
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._html(200, render_index(cases_for_index(store)))
                return
            match = re.fullmatch(r"/cases/([^/]+)", parsed.path)
            if match:
                self._show_case(match.group(1))
                return
            self._html(404, _page("Not found", "<p>Not found.</p>"))

        def do_POST(self) -> None:
            if not self._loopback_host():
                self._html(403, _page("Forbidden", "<p>Host must be loopback.</p>"))
                return
            parsed = urlparse(self.path)
            fields = self._form()
            if fields is None:
                return
            try:
                if parsed.path == "/cases":
                    alert = (fields.get("alert") or [""])[0]
                    mode = (fields.get("mode") or ["integrated"])[0]
                    case, _, _matched = open_from_alert(alert, mode, store, extra_dirs)
                    self._redirect(f"/cases/{case.id}")
                    return
                match = re.fullmatch(r"/cases/([^/]+)/reply", parsed.path)
                if match:
                    text = (fields.get("output") or [""])[0]
                    reply_from_text(store, match.group(1), text, extra_dirs, source="web")
                    self._redirect(f"/cases/{match.group(1)}")
                    return
                match = re.fullmatch(r"/cases/([^/]+)/refuse", parsed.path)
                if match:
                    reason = (fields.get("reason") or [""])[0]
                    refuse_from_reason(store, match.group(1), reason)
                    self._redirect(f"/cases/{match.group(1)}")
                    return
            except CaseStoreError as exc:
                self._html(404, _page("Not found", f"<p>{escape(str(exc))}</p>"))
                return
            except ValueError as exc:
                self._html(400, _page("Bad request", f"<p>{escape(str(exc))}</p><p><a href='/'>Back</a></p>"))
                return
            except PlaybookError as exc:
                self._html(400, _page("Playbook error", f"<p>{escape(str(exc))}</p>"))
                return
            self._html(404, _page("Not found", "<p>Not found.</p>"))

        def _show_case(self, case_id: str) -> None:
            try:
                case = show_from_id(store, case_id)
            except CaseStoreError as exc:
                self._html(404, _page("Not found", f"<p>{escape(str(exc))}</p>"))
                return
            self._html(200, render_case(case))

        def _loopback_host(self) -> bool:
            header = (self.headers.get("Host") or "").split("/")[0]
            host = header.rsplit("]", 1)[0].lstrip("[").split(":")[0]
            return host in LOOPBACK_HOSTS or host == ""

        def _form(self) -> dict[str, list[str]] | None:
            raw_len = self.headers.get("Content-Length") or "0"
            try:
                length = int(raw_len)
            except ValueError:
                self._html(400, _page("Bad request", "<p>Invalid Content-Length.</p>"))
                return None
            if length < 0:
                self._html(400, _page("Bad request", "<p>Invalid Content-Length.</p>"))
                return None
            if length > MAX_BODY:
                self._html(413, _page("Too large", "<p>Body too large.</p>"))
                return None
            raw = self.rfile.read(length) if length else b""
            try:
                decoded = raw.decode("utf-8")
            except UnicodeDecodeError:
                self._html(400, _page("Bad request", "<p>Body must be UTF-8.</p>"))
                return None
            return parse_qs(decoded, keep_blank_values=True)

        def _html(self, code: int, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def render_index(cases: list[Case]) -> str:
    rows = []
    for case in cases:
        rows.append(
            "<tr>"
            f"<td><a href='/cases/{escape(case.id)}'>{escape(case.id)}</a></td>"
            f"<td>{escape(case.mode)}</td>"
            f"<td>{escape(show_banner(case))}</td>"
            f"<td>{escape(case.playbook_id or '—')}</td>"
            f"<td>{escape(_clip(case.alert, 80))}</td>"
            "</tr>"
        )
    table = (
        "<p>还没有诊断单。</p>"
        if not rows
        else (
            "<table><thead><tr><th>Case</th><th>模式</th><th>状态</th><th>剧本</th><th>告警</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    )
    body = f"""
<section>
  <h1>开一张 L0 单</h1>
  <p>不连接集群。命令由你在本机执行后再回贴。</p>
  <form method="post" action="/cases">
    <label>集群模式
      <select name="mode">
        <option value="integrated">integrated（一体 / shared-nothing）</option>
        <option value="cloud">cloud（存算分离）</option>
      </select>
    </label>
    <label>告警原文
      <textarea name="alert" rows="10" required placeholder="be node down on host X"></textarea>
    </label>
    <button type="submit">开单</button>
  </form>
</section>
<section>
  <h2>Cases</h2>
  {table}
</section>
<p class="foot">L1 只读凭据尚未开通。没有去查集群、没有写操作按钮。</p>
"""
    return _page("DorisOps", body)


def render_case(case: Case) -> str:
    cmds = []
    for index, command in enumerate(case.commands, start=1):
        body = command.get("body") or ""
        cid = f"cmd-{index}"
        restart = "重启前必采" if command.get("before_restart") else "可后补"
        cmds.append(
            f"<article class='cmd'>"
            f"<h3>{index}. <code>{escape(str(command.get('id', '')))}</code> · {escape(restart)}</h3>"
            f"<p>执行位置：{escape(str(command.get('where', '')))}</p>"
            f"<p>看什么：{escape(str(command.get('look_for', '')))}</p>"
            f"<pre id='{cid}'>{escape(body)}</pre>"
            f"<button type='button' class='copy' data-target='{cid}'>复制</button>"
            f"</article>"
        )
    if not cmds:
        if case.mode_mismatch:
            cmd_block = "<p>当前模式无命令包。请改模式后重新开单，不要在一体集群上做 clone / disk rebalance。</p>"
        else:
            cmd_block = "<p>无命令。补充告警原文后再开单。</p>"
    else:
        cmd_block = "".join(cmds)
    waiting = not case.evidence and case.status != "in_progress"
    wait_note = (
        "<p><strong>待人执行。</strong>未回贴之前不要把告警标题当成已核实的集群结论，也不能写 Alive=false。</p>"
        if waiting
        else "<p>下面若出现数字，只来自你回贴的文本，不是程序查询集群得到的。</p>"
    )
    refusals = "".join(
        f"<li>{escape(str(item.get('at', '')))}: {escape(str(item.get('reason', '')))}</li>"
        for item in case.refusals
    )
    evidence = ""
    for item in case.evidence:
        evidence += (
            f"<h4>{escape(str(item.get('source', '')))} · 匹配={escape(str(item.get('matched_advance') or '未前进'))}</h4>"
            f"<pre>{escape(_clip(str(item.get('text', '')), 4000))}</pre>"
        )
    body = f"""
<p><a href="/">← 全部 cases</a></p>
<h1>{escape(case.id)}</h1>
<ul>
  <li>档位：{escape(case.lane)}（不开集群连接）</li>
  <li>模式：{escape(case.mode)}</li>
  <li>状态：{escape(case.status)} / {escape(show_banner(case))}</li>
  <li>节点：{escape(case.node_id or "（无判定树）")}</li>
  <li>剧本：{escape(case.playbook_id or "（未匹配）")}
    {escape(' / ' + case.playbook_title) if case.playbook_title else ''}
    {' · 模式不匹配' if case.mode_mismatch else ''}</li>
</ul>
{wait_note}
<h2>待证</h2>
<p>{escape(case.pending_note)}</p>
<h2>30 秒卡片</h2>
<ul>
  <li>本质：{escape(case.essence)}</li>
  <li>影响面：{escape(case.impact)}</li>
  <li>立即做：{escape(case.do_now)}</li>
  <li>止损红线：{escape(case.stop_line)}</li>
  <li>千万别：{escape(case.never_do)}</li>
</ul>
<h2>本轮命令（程序不会执行）</h2>
{cmd_block}
<h2>回贴 stdout</h2>
<form method="post" action="/cases/{escape(case.id)}/reply">
  <textarea name="output" rows="12" required placeholder="把 SHOW BACKENDS 或其他采集输出贴在这里"></textarea>
  <button type="submit">回贴并进入下一节点</button>
</form>
<h2>拒绝执行</h2>
<form method="post" action="/cases/{escape(case.id)}/refuse">
  <input name="reason" required placeholder="例如：无跳板机权限" />
  <button type="submit">拒绝（单仍打开）</button>
</form>
<h2>拒绝记录</h2>
{"<ul>" + refusals + "</ul>" if refusals else "<p>无</p>"}
<h2>已回贴</h2>
{evidence or "<p>无</p>"}
<h2>告警原文</h2>
<pre>{escape(case.alert)}</pre>
<p class="foot">没有「去查集群」按钮，也没有写操作。L1 只读凭据尚未开通。</p>
<script>
document.querySelectorAll("button.copy").forEach(function (btn) {{
  btn.addEventListener("click", function () {{
    var el = document.getElementById(btn.getAttribute("data-target"));
    if (!el) return;
    navigator.clipboard.writeText(el.textContent || "");
    btn.textContent = "已复制";
    setTimeout(function () {{ btn.textContent = "复制"; }}, 1200);
  }});
}});
</script>
"""
    return _page(case.id, body)


def _clip(text: str, limit: int) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)} · DorisOps</title>
  <style>
    :root {{ font-family: ui-sans-serif, system-ui, sans-serif; color: #102a2a; background: #f4f1ea; }}
    body {{ max-width: 860px; margin: 24px auto; padding: 0 16px 48px; line-height: 1.45; }}
    textarea, input, select {{ width: 100%; box-sizing: border-box; margin: 6px 0 12px; padding: 8px; }}
    textarea {{ font-family: ui-monospace, monospace; }}
    button {{ padding: 8px 14px; cursor: pointer; }}
    pre {{ background: #111c1c; color: #e8f0e8; padding: 12px; overflow: auto; white-space: pre-wrap; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ border-bottom: 1px solid #cfc8bc; text-align: left; padding: 6px 4px; vertical-align: top; }}
    .foot {{ color: #5c6565; font-size: 0.9rem; }}
    a {{ color: #0b5c4c; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def start_background(
    host: str,
    port: int,
    store: Path,
    extra_dirs: list[Path] | None = None,
) -> tuple[HTTPServer, threading.Thread]:
    httpd = make_server(host, port, store, extra_dirs)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread
