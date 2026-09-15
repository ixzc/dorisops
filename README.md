# DorisOps

Read-only ops workbench for [Apache Doris](https://doris.apache.org/).

It is **not** an APM, **not** Grafana, and **not** a pager (PagerDuty / Flashduty).
It turns an alert into a diagnosis case with commands you run yourself.

Supports **integrated** (shared-nothing) and **cloud** (storage-compute separation) clusters.

## Status

Pre-alpha. Stage **S4**: local L0 web UI on loopback. No cluster credentials.

MCP is not in this commit. L1 inspect is not in this commit.

## Two lanes

| Lane | What you grant | What you get |
|------|----------------|--------------|
| **L0 diagnosis case** | Nothing (no FE/BE account) | Paste an alert → get a command pack. You run commands. |
| **L1 inspect** | Read-only FE MySQL + FE/BE HTTP | Not shipped yet. Missing credentials will downgrade to L0. |

**P0–P1 are read-only.** The case may describe a stop-the-bleeding line. It will not `SET`, `ALTER`, repair replicas, kill queries, or SSH. It will not invent `Alive=false`.

## Install

```bash
git clone git@github.com:ixzc/dorisops.git
cd dorisops
python3 -m pip install -e ".[dev]"   # 3.9+; 3.9/3.10 会自动装 tomli
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

## Cluster config

See [`examples/cluster.example.yaml`](examples/cluster.example.yaml) for the upcoming L1 inspect file. Copy to a gitignored `cluster.yaml` when that stage lands.

## License

Apache License 2.0. See [LICENSE](LICENSE).
