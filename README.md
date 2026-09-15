# DorisOps

Read-only ops workbench for [Apache Doris](https://doris.apache.org/).

It is **not** an APM, **not** Grafana, and **not** a pager (PagerDuty / Flashduty).
It turns an alert into a diagnosis case with commands you run yourself.

Supports **integrated** (shared-nothing) and **cloud** (storage-compute separation) clusters.

## Status

Pre-alpha. Stage **S6**: cloud-only MetaService `/status` and BE `file_cache` metrics. Integrated mode refuses those probes.

MCP is not in this commit.

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
```

## Open a case (no cluster)

```bash
dorisops case open --alert "be node down on host X" --mode integrated
dorisops case open --alert "MemoryUsed 大于 95%" --mode cloud
dorisops case open --alert "metaservice node down" --mode cloud
# --mode integrated on a cloud-only alert prints a hint; it will not emit clone/rebalance commands
```

JSON is stored under `$DORISOPS_HOME/cases` or `~/.dorisops/cases`.

```bash
dorisops case show   CASE-xxxx
dorisops case reply  CASE-xxxx --output-file show-backends.txt
dorisops case refuse CASE-xxxx --reason "no jumphost"
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
```

Open http://127.0.0.1:8787/ — paste an alert, copy commands, paste stdout back. The process never talks to Doris. Binding `0.0.0.0` is rejected.

## Cluster config / L1 inspect

Copy [`examples/cluster.example.yaml`](examples/cluster.example.yaml) (integrated) or [`examples/cluster.cloud.example.yaml`](examples/cluster.cloud.example.yaml) (cloud) to a gitignored `cluster.yaml`. Leave `CHANGE_ME` in place and the command stays on L0 — it will not open a MySQL or HTTP connection.

```bash
dorisops inspect                          # no yaml → L0, tells you how to open a case
dorisops inspect --cluster ./cluster.yaml # placeholders → L0; real read-only user → SHOW + HTTP
```

Whitelist: `SHOW FRONTENDS` / `SHOW BACKENDS` / `SHOW COMPUTE GROUPS` (cloud), HTTP `/api/health`, `/metrics`, `/api/profile` (with `--query-id`), and MetaService `/status` (cloud only). `mode: integrated` refuses MS HTTP and `file_cache` metrics even if `meta_service` is in the file. Cloud yaml without `meta_service.http_url` prints **待人执行**, not a fake OK. No `SET`, `ALTER`, SSH, FDB cli, or Recycler writes.

## License

Apache License 2.0. See [LICENSE](LICENSE).
