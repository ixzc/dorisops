from __future__ import annotations

from dorisops.mcp_api import McpSession, TOOL_NAMES

INSTRUCTIONS = (
    "Read-only Apache Doris ops workbench. P0–P1 never SET, ALTER, SSH, or kill queries. "
    "case_open / case_show / case_reply / case_refuse never connect to the cluster. "
    "inspect_cluster without real credentials returns L0; do not invent Alive=false or topology."
)


def load_fastmcp():
    try:
        from mcp.server.fastmcp import FastMCP
        return FastMCP
    except ImportError as exc:
        raise ImportError(
            "the mcp package is required for `dorisops mcp`"
        ) from exc


def build_server(session: McpSession):
    FastMCP = load_fastmcp()
    try:
        mcp = FastMCP("dorisops", instructions=INSTRUCTIONS)
    except TypeError:
        mcp = FastMCP("dorisops")

    @mcp.tool()
    def case_open(alert: str, mode: str) -> str:
        """Open an L0 diagnosis case from raw alert text. Does not connect to Doris. mode must be integrated or cloud."""
        return session.case_open(alert, mode)

    @mcp.tool()
    def case_show(case_id: str) -> str:
        """Show a diagnosis case. Does not query the cluster. Before any reply it only says the case is waiting."""
        return session.case_show(case_id)

    @mcp.tool()
    def case_reply(case_id: str, output: str) -> str:
        """Paste command stdout to advance the decision tree. The server never runs the command and never reads local files."""
        return session.case_reply(case_id, output)

    @mcp.tool()
    def case_refuse(case_id: str, reason: str) -> str:
        """Record why a command pack cannot be run. Keeps the case open. Read-only; no cluster writes."""
        return session.case_refuse(case_id, reason)

    @mcp.tool()
    def inspect_cluster(cluster_path: str = "", query_id: str = "") -> str:
        """Read-only L1 probe (SHOW/HTTP whitelist). Empty cluster_path stays on L0. Never invent Alive or topology."""
        return session.inspect_cluster(cluster_path=cluster_path, query_id=query_id)

    _ = TOOL_NAMES
    return mcp


def serve_stdio(session: McpSession) -> None:
    mcp = build_server(session)
    try:
        mcp.run(transport="stdio")
    except TypeError:
        mcp.run()
