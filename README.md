# DorisOps

Read-only ops workbench for [Apache Doris](https://doris.apache.org/).

It is **not** an APM, **not** Grafana, and **not** a pager (PagerDuty / Flashduty).
It turns an alert into a diagnosis case with commands you run yourself.

Supports **integrated** (shared-nothing) and **cloud** (storage-compute separation) clusters.

## Status

Pre-alpha. **P1c**: L1 inspect `--watch` snapshots + optional loopback probe block. P0 golden eval remains `pytest -q tests/test_golden.py`.

## Two lanes

| Lane | What you grant | What you get |
|------|----------------|--------------|
| **L0 diagnosis case** | Nothing (no FE/BE account) | Paste an alert → get a command pack. You run commands. |
| **L1 inspect** | Read-only FE MySQL + FE/BE HTTP | `dorisops inspect --cluster ./cluster.yaml`. Placeholder passwords never connect. |

**P0–P1 are read-only.** The case may describe a stop-the-bleeding line. It will not `SET`, `ALTER`, repair replicas, kill queries, or SSH. It will not invent `Alive=false`.

## Install

```bash
git clone git@github.com:ixzc/dorisops.git
cd dorisops
python3 -m pip install -e ".[dev]"   # 3.9+; 3.9/3.10 会自动装 tomli
# optional L1 inspect extras:
python3 -m pip install -e ".[inspect]"
# optional Cursor MCP:
python3 -m pip install -e ".[mcp]"
```

## Open a case (no cluster)

```bash
dorisops case open --alert "be node down on host X" --mode integrated
dorisops case open --alert "MemoryUsed 大于 95%" --mode cloud
dorisops case open --alert "metaservice node down" --mode cloud
# --mode integrated on a cloud-only alert prints a hint; it will not emit clone/rebalance commands
```

JSON is stored under `$DORISOPS_HOME/cases` or `~/.dorisops/cases` (SQLite `cases.sqlite` plus JSON sidecars).

```bash
dorisops case show   CASE-xxxx
dorisops case reply  CASE-xxxx --output-file show-backends.txt
dorisops case refuse CASE-xxxx --reason "no jumphost"
dorisops case export CASE-xxxx            # Markdown 转发稿，不是实时快照
```

`show` before any reply only says the case is waiting. It will not invent `Alive=false`.
`reply` matches keywords (for example `Alive false` in `SHOW BACKENDS` text) and prints the next command pack.
`refuse` keeps the case open and records the reason.

`--mode integrated` hides cloud-only commands (for example `SHOW COMPUTE GROUPS`).
`--mode cloud` keeps them.

Private playbooks: `--playbook-dir /path/to/pack` (do not commit customer CIR).

## Local web (loopback)

```bash
dorisops web --bind 127.0.0.1:8787
# optional: accept alerts from a local forwarder (still loopback, still L0)
dorisops web --bind 127.0.0.1:8787 --webhook-token "$TOKEN" --webhook-mode integrated
# optional L1 probe block on the same page (still loopback, still read-only)
dorisops web --bind 127.0.0.1:8787 --cluster ./cluster.yaml
```

Open http://127.0.0.1:8787/ — paste an alert, copy commands, paste stdout back. Without `--cluster` the process never talks to Doris. Binding `0.0.0.0` is rejected. With `--cluster`, the index shows a **探活（只读）** button that runs the same SHOW/HTTP whitelist as `inspect`; placeholders stay on L0. `--watch` writes `inspect-latest.json` next to cases (a snapshot, not Grafana).

Webhook is off unless `--webhook-token` or `$DORISOPS_WEBHOOK_TOKEN` is set:

```bash
curl -sS -X POST http://127.0.0.1:8787/hooks/alert \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"alert":"be node down on host X","mode":"integrated"}'
```

Generic `{alert,mode}` and Alertmanager `alerts[]` both work. Auth is `Authorization: Bearer` or `X-DorisOps-Token` (query-string tokens are rejected so they never hit access logs). The hook only opens an L0 case; it does not query the cluster or invent `Alive`. `resolved` alerts are ignored.

## Cluster config / L1 inspect

Copy [`examples/cluster.example.yaml`](examples/cluster.example.yaml) (integrated) or [`examples/cluster.cloud.example.yaml`](examples/cluster.cloud.example.yaml) (cloud) to a gitignored `cluster.yaml`. Leave `CHANGE_ME` in place and the command stays on L0 — it will not open a MySQL or HTTP connection.

```bash
dorisops inspect                          # no yaml → L0, tells you how to open a case
dorisops inspect --cluster ./cluster.yaml # placeholders → L0; real read-only user → SHOW + HTTP
dorisops inspect --cluster ./cluster.yaml --watch --interval 60
```

Whitelist: `SHOW FRONTENDS` / `SHOW BACKENDS` / `SHOW COMPUTE GROUPS` (cloud), HTTP `/api/health`, `/metrics`, `/api/profile` (with `--query-id`), and MetaService `/status` (cloud only). `mode: integrated` refuses MS HTTP and `file_cache` metrics even if `meta_service` is in the file. Cloud yaml without `meta_service.http_url` prints **待人执行**, not a fake OK. No `SET`, `ALTER`, SSH, FDB cli, or Recycler writes.

## Cursor MCP

```bash
python3 -m pip install -e ".[mcp]"
dorisops mcp
```

Point Cursor at stdio (see [`examples/cursor-mcp.json`](examples/cursor-mcp.json)):

```json
{
  "mcpServers": {
    "dorisops": {
      "command": "python3",
      "args": ["-m", "dorisops", "mcp"]
    }
  }
}
```

Optional env: `DORISOPS_HOME` (case store), `DORISOPS_CLUSTER` (default `cluster.yaml` for inspect). Tools: `case_open`, `case_show`, `case_reply`, `case_refuse`, `case_export`, `inspect_cluster`. They are read-only. Without credentials `inspect_cluster` returns L0 and must not be treated as a health check.

## Tests

```bash
python3 -m pytest -q                 # no live cluster; E1–E6 plus the rest
python3 -m pytest -q tests/test_golden.py   # P0 gate only
# optional L1 smoke (not in GitHub Actions):
DORISOPS_LIVE_CLUSTER=./cluster.yaml python3 -m pytest -q -m live
```

E1–E6: `be node down` with no invented facts; memory pressure without `/mem_tracker`; MetaService + integrated mismatch; show-before-reply stays pending; `-235` is versions not a query; Web open+reply shares the CLI case state machine.

## License

Apache License 2.0. See [LICENSE](LICENSE).
